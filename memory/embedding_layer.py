"""AAA-61 Sub-step 4 — Vertex AI RAG embedding layer.

ONE embedding entry per audit, EN canonical only (Phase 1). The archive
(Firestore) is the source of truth; this index is regenerable from it, so
HU / future-language embeddings can be added later without rebuilding the
archive (user's "store everything, regenerate later" principle).

Region europe-west3, RagManagedDb, text-embedding-005 (AAA-60 research).
Raw vertexai.rag API (NOT the ADK VertexAiRagMemoryService wrapper —
AAA-60 found the wrapper has soft display-name tenancy; native API gives
proper corpus/metadata control).

Naming (Sub-step 4 decision, confirmed): embedding tracking uses
audit_embedding_calls / audit_embedding_cost_usd — a clean parallel to the
AAA-56 audit_kg_* fields (Knowledge Graph E-E-A-T validation), NOT a reuse.
Both are free-quota (cost 0.0) but they are distinct services.

Honest deviation (API limitation, flagged): vertexai.rag.upload_file
(local-path) exposes only display_name + description — there is no
arbitrary indexed-metadata kwarg in vertexai 1.153.1 (indexed metadata
filtering requires GCS import_files + sidecar JSON, an AAA-3d concern).
Phase-1 mitigation: metadata is (a) the full source of truth in Firestore,
(b) JSON-encoded into the RagFile description, and (c) embedded as a
header line in the uploaded text so it survives retrieval. The retrieval
probe (semantic only) does not need indexed filters yet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone

from pydantic import BaseModel

from site_profile.gemini_analyzer import _resolve_project

logger = logging.getLogger(__name__)

CORPUS_DISPLAY_NAME = "audit_summaries"
EMBEDDING_MODEL = "text-embedding-005"
RAG_REGION = "europe-west3"  # AAA-60: Spanner allowlist OK here, HU residency
_PUBLISHER_MODEL = f"publishers/google/models/{EMBEDDING_MODEL}"
_BACKOFF_SECONDS = (1.0, 2.0, 4.0)

_inited = False
_corpus_name: str | None = None


def _vertexai():
    """Lazy vertexai.init pinned to the RAG region. Returns the rag module."""
    global _inited
    import vertexai
    import vertexai.rag as rag

    if not _inited:
        project = _resolve_project()
        # GOOGLE_CLOUD_LOCATION may be 'global' (Gemini) — RAG needs the
        # regional endpoint, so we pass location explicitly here.
        vertexai.init(project=project, location=RAG_REGION)
        _inited = True
        logger.info(
            "vertexai.init project=%s location=%s (RAG)", project, RAG_REGION
        )
    return rag


def _is_transient(exc: Exception) -> bool:
    """AAA-60: fresh-corpus first upload can hit gRPC code 13 INTERNAL."""
    s = f"{type(exc).__name__}: {exc}".lower()
    return any(t in s for t in (
        "internal", "code 13", "unavailable", "deadline", "503", "aborted",
    ))


async def ensure_audit_summaries_corpus() -> str:
    """Idempotent: return existing corpus resource name, else create it."""
    global _corpus_name
    if _corpus_name:
        return _corpus_name
    rag = _vertexai()

    def _find_or_create() -> str:
        for c in rag.list_corpora():
            if c.display_name == CORPUS_DISPLAY_NAME:
                return c.name
        # vertexai 1.153.1 has a proto bug (RagManagedDb.CopyFrom) when an
        # explicit backend_config is passed. AAA-60 confirmed the SDK
        # defaults ARE RagManagedDb + text-embedding-005, so we rely on
        # defaults and VERIFY post-creation rather than fight the bug.
        corpus = rag.create_corpus(
            display_name=CORPUS_DISPLAY_NAME,
            description="AAA-61 audit EN-canonical summaries (Phase 1)",
        )
        logger.info("Created RAG corpus: %s", corpus.name)
        return corpus.name

    _corpus_name = await asyncio.to_thread(_find_or_create)
    logger.info("audit_summaries corpus: %s", _corpus_name)
    return _corpus_name


def _as_dict(archive_doc) -> dict:
    if isinstance(archive_doc, BaseModel):
        return archive_doc.model_dump()
    return dict(archive_doc or {})


def _meta_of(doc: dict) -> dict:
    ao = doc.get("audit_output") or {}
    md = doc.get("metadata") or {}
    return {
        "audit_id": doc.get("audit_id"),
        "language": "en",  # Phase 1: EN canonical only
        "industry_llm": md.get("industry_llm"),
        "page_type": md.get("page_type") or ao.get("page_type"),
        "audit_date": doc.get("audit_date"),
    }


async def embed_and_upload_audit(audit_id: str, archive_doc) -> dict:
    """Embed the EN canonical summary + upload it to the corpus.

    Returns {rag_file_id, audit_embedding_calls, audit_embedding_cost_usd,
    _error}. Transient INTERNAL errors retried 3x (1s/2s/4s).
    """
    rag = _vertexai()
    corpus = await ensure_audit_summaries_corpus()
    doc = _as_dict(archive_doc)
    meta = _meta_of(doc)
    ao = doc.get("audit_output") or {}
    en_text = (ao.get("summary_translations") or {}).get("en") or ""
    if not en_text.strip():
        return {
            "rag_file_id": None, "audit_embedding_calls": 0,
            "audit_embedding_cost_usd": 0.0,
            "_error": "no EN canonical summary to embed",
        }

    # Metadata header line so it survives retrieval (no indexed-meta API).
    header = f"[audit_id={meta['audit_id']} | industry={meta['industry_llm']}"\
             f" | page_type={meta['page_type']} | language=en]\n\n"
    body = header + en_text

    def _upload() -> str:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix=f"{audit_id}_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            rf = rag.upload_file(
                corpus_name=corpus,
                path=path,
                display_name=str(audit_id),
                description=json.dumps(meta, ensure_ascii=False),
            )
            return rf.name
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    last: Exception | None = None
    for attempt in range(len(_BACKOFF_SECONDS) + 1):
        try:
            rag_file_id = await asyncio.to_thread(_upload)
            logger.info("Embedded audit %s -> %s", audit_id, rag_file_id)
            return {
                "rag_file_id": rag_file_id,
                "audit_embedding_calls": 1,
                "audit_embedding_cost_usd": 0.0,  # free tier
                "_error": None,
            }
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < len(_BACKOFF_SECONDS) and _is_transient(e):
                d = _BACKOFF_SECONDS[attempt]
                logger.warning(
                    "embed upload transient (attempt %d): %s — retry %.0fs",
                    attempt + 1, type(e).__name__, d,
                )
                time.sleep(d)
                continue
            break
    logger.error("embed_and_upload_audit %s failed: %s", audit_id, last)
    return {
        "rag_file_id": None, "audit_embedding_calls": 0,
        "audit_embedding_cost_usd": 0.0,
        "_error": f"{type(last).__name__}: {last}" if last else "unknown",
    }


def _embedding_metadata(result: dict) -> dict:
    return {
        "rag_file_id": result.get("rag_file_id"),
        "embedded_at": (
            datetime.now(timezone.utc).isoformat()
            if result.get("rag_file_id") else None
        ),
        "embedded_language": "en",
        "embedding_model": EMBEDDING_MODEL,
        "_error": result.get("_error"),
    }


async def backfill_embedding(audit_id: str) -> dict:
    """Embed an EXISTING archived audit + dotted-path update its doc."""
    from memory.firestore_archive import read_audit, _db, _COLLECTION, _now_iso

    doc = await read_audit(audit_id)
    if doc is None:
        raise RuntimeError(f"backfill_embedding: {audit_id} not found")
    result = await embed_and_upload_audit(audit_id, doc)
    emeta = _embedding_metadata(result)
    patch = {
        "audit_output.embedding_metadata": emeta,
        "audit_embedding_calls": result["audit_embedding_calls"],
        "audit_embedding_cost_usd": result["audit_embedding_cost_usd"],
        "updated_at": _now_iso(),
    }
    ref = _db().collection(_COLLECTION).document(audit_id)
    await asyncio.to_thread(ref.update, patch)
    logger.info("Embedding backfilled: %s (file=%s)",
                audit_id, emeta["rag_file_id"])
    return {"audit_id": audit_id, **result, "embedding_metadata": emeta}


async def probe_retrieval(query_text: str, top_k: int = 3) -> list[dict]:
    """Throwaway retrieval test (AAA-3d implements production retrieval).

    Returns [{audit_id, score, snippet}] for the top-K contexts.
    """
    rag = _vertexai()
    corpus = await ensure_audit_summaries_corpus()

    def _q():
        cfg = rag.RagRetrievalConfig(top_k=top_k)
        resp = rag.retrieval_query(
            text=query_text,
            rag_resources=[rag.RagResource(rag_corpus=corpus)],
            rag_retrieval_config=cfg,
        )
        out = []
        for ctx in getattr(resp.contexts, "contexts", []) or []:
            txt = getattr(ctx, "text", "") or ""
            aid = None
            if txt.startswith("[audit_id="):
                aid = txt[len("[audit_id="):].split(" ", 1)[0].strip()
            if not aid:
                aid = getattr(ctx, "source_display_name", None)
            out.append({
                "audit_id": aid,
                "score": getattr(ctx, "score", None),
                "snippet": txt[:160].replace("\n", " "),
            })
        return out

    return await asyncio.to_thread(_q)
