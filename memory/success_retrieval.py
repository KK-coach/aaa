"""AAA-202 Gate 2 — deterministic success-peer retrieval (pipeline step).

Called by the archive step (write_audit, client audits only — NOT an agent tool;
the flywheel S0 showed advisory agent instructions get skipped). Embeds the
audit's EN-canonical summary, queries the Gate-1 Vector Search index with the
success filter (serp_position <= 3 OR ai_cited == true, excluded == false),
self-excludes the client's own domain, URL-dedups, returns the top-3 REFERENCE
list (doc ids + metadata only — Gate 3 fetches fact-bases by doc_id at verdict
time; never copy peer fact-bases onto the audit doc, AAA-103 1MiB).

COSINE_DISTANCE: smaller = closer (Gate-1 lesson) — sort ASCENDING.

Failure contract (AAA-197 lesson — no silent skip): any error returns
{"peers": [], "error": <reason>, ...}; the caller persists the explicit signal.
<3 peers after filters is NOT an error → "note" carries the shortfall.
"""

from __future__ import annotations

import os
import re
import time

REGION = "europe-west3"
EMBED_MODEL = "gemini-embedding-001"
# Gate-1 resources (overridable for fault-injection / future rebuilds).
ENDPOINT_RESOURCE = os.environ.get(
    "AAA_SUCCESS_ENDPOINT",
    "projects/664356368213/locations/europe-west3/"
    "indexEndpoints/594501539091972096",
)
DEPLOYED_INDEX_ID = os.environ.get("AAA_SUCCESS_DEPLOYED_ID", "aaa_success_v1")
TOP_K = 3
_RAW_NEIGHBORS = 15  # per query, pre-dedup
# gemini-embedding-001 ≈ $0.15 / 1M input tokens (chars/4 estimate).
_EMBED_USD_PER_TOKEN = 0.15 / 1e6


def _norm(u: str) -> str:
    if not isinstance(u, str):
        return ""
    u = re.sub(r"^https?://(www\.)?", "", u.strip().lower())
    return u.split("?")[0].split("#")[0].rstrip("/")


def _reg_host(u: str) -> str:
    """Registrable-ish domain (last two labels) of a normalized URL/host —
    self-exclusion key, so matebalazs.hu/page-A never retrieves
    matebalazs.hu/page-B either."""
    host = _norm(u).split("/")[0]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


async def retrieve_success_peers(summary_en: str, client_url: str,
                                 db=None) -> dict:
    """Returns {peers: [...], cost_usd, error, note}. Never raises."""
    out = {"peers": [], "cost_usd": 0.0, "error": None, "note": None}
    text = (summary_en or "").strip()[:9000]
    if not text:
        out["error"] = "no EN summary to embed"
        return out
    try:
        import asyncio

        from google.cloud import aiplatform
        import vertexai
        from vertexai.language_models import TextEmbeddingModel

        from site_profile.gemini_analyzer import _resolve_project
        proj = _resolve_project()

        def _run():
            vertexai.init(project=proj, location=REGION)
            aiplatform.init(project=proj, location=REGION)
            t0 = time.time()
            emb = TextEmbeddingModel.from_pretrained(
                EMBED_MODEL).get_embeddings([text])[0].values
            ep = aiplatform.MatchingEngineIndexEndpoint(ENDPOINT_RESOURCE)
            from google.cloud.aiplatform.matching_engine. \
                matching_engine_index_endpoint import (
                    Namespace, NumericNamespace)

            def q(filters, numeric=None):
                return ep.find_neighbors(
                    deployed_index_id=DEPLOYED_INDEX_ID, queries=[emb],
                    num_neighbors=_RAW_NEIGHBORS, filter=filters,
                    numeric_filter=numeric or [])[0]
            # success = pos<=3 OR ai_cited — two queries, merged (min distance).
            r1 = q([Namespace(name="excluded", allow_tokens=["false"])],
                   [NumericNamespace(name="serp_position", value_int=3,
                                     op="LESS_EQUAL")])
            r2 = q([Namespace(name="excluded", allow_tokens=["false"]),
                    Namespace(name="ai_cited", allow_tokens=["true"])])
            merged: dict[str, float] = {}
            for n in list(r1) + list(r2):
                d = float(n.distance)
                merged[n.id] = min(merged.get(n.id, 9.0), d)
            return emb, merged, time.time() - t0

        emb, merged, _lat = await asyncio.to_thread(_run)
        out["cost_usd"] = round(len(text) / 4 * _EMBED_USD_PER_TOKEN, 8)

        if db is None:
            from google.cloud import firestore
            db = firestore.Client(project=proj, database="ai-advisor-app")
        self_key = _reg_host(client_url)
        seen_urls: set[str] = set()
        peers = []
        # ASCENDING distance — smaller = closer (COSINE_DISTANCE).
        for doc_id, dist in sorted(merged.items(), key=lambda x: x[1]):
            d = db.collection("audits").document(doc_id).get().to_dict() or {}
            u = d.get("success_url_normalized") or ""
            if not u or _reg_host(u) == self_key or u in seen_urls:
                continue
            seen_urls.add(u)
            peers.append({
                "doc_id": doc_id,
                "url": u,
                "distance": round(dist, 4),
                "serp_position": d.get("success_serp_position"),
                "ai_cited": bool(d.get("success_ai_cited")),
                "industry": (d.get("metadata") or {}).get("industry_llm"),
                "page_type": ((d.get("audit_output") or {}).get("page_type")),
            })
            if len(peers) == TOP_K:
                break
        out["peers"] = peers
        if len(peers) < TOP_K:
            out["note"] = "only %d peer(s) after filters" % len(peers)
        return out
    except Exception as e:  # noqa: BLE001 — failure contract: explicit, not silent
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        return out
