"""AAA-64 Sub-step 1 — active memory retrieval for the RE agent.

Turns the AAA-61 passive embedding store into an active context source:
the RE agent calls memory_read_similar_cases FIRST and reasons WITH the
top-K similar prior audits (tool-result pattern, NOT deterministic
injection).

Live-probe findings (verified against the real corpus, not SDK hints):
  - Response: resp.contexts.contexts[] with .score .source_display_name
    .source_uri .text .chunk
  - source_display_name == audit_id (set at AAA-61 upload) — reliable key
  - Native metadata_filter does NOT exclude by audit_id (no indexed
    metadata; AAA-61 deviation #2). Self-match exclusion is CLIENT-SIDE:
    request top_k+1, drop self, truncate to top_k.
  - The SDK default applies a restrictive vector-distance cutoff that
    silently returns <top_k (AAA-61 S4 Q2 returned 1). A permissive
    Filter(vector_distance_threshold=0.7) defeats that so top_k is
    actually honoured. This is plumbing to make top_k mean top_k — it is
    NOT a score-based quality gate (none added, per scope guardrail).

Firestore is the source of truth: the embedded text is a snapshot, so for
every retrieved audit_id we re-fetch the live archive doc for fresh
metadata + the full EN summary.

Cost: AAA-53 separation — audit_memory_retrieval_calls/_cost_usd are
SEPARATE fields, never folded into audit_cost_usd. Free quota -> 0.0.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# AAA-75 Sub-step 3 — cross-role self-exclusion identity.
# Multi-tenant HOST suffixes: many distinct businesses share one registrable
# domain, so a registrable-domain match is NOT "same business" -> suppress
# domain-exclusion (fall back to exact audit_id) when either side is here.
_PLATFORM_HOST_SUFFIXES = (
    "myshopify.com", "wixsite.com", "github.io", "webflow.io", "wordpress.com",
    "blogspot.com", "squarespace.com", "weebly.com", "netlify.app",
    "vercel.app", "pages.dev", "sites.google.com",
)
# Marketplace / multi-tenant registrable domains where businesses live under
# PATHS (registrable domain alone is not identity) — same suppression.
_MULTITENANT_DOMAINS = (
    "emag.ro", "amazon.com", "etsy.com", "ebay.com", "jofogas.hu",
    "facebook.com", "marktplaats.nl", "allegro.pl",
)


def _registrable(url: str | None) -> str | None:
    """Last-two-labels registrable domain (membership/identity key). Deliberately
    NOT the customer-render canonical collapse (different purpose)."""
    if not url:
        return None
    n = urlparse(url if "://" in url else "https://" + url).netloc.lower().split(":")[0]
    if n.startswith("www."):
        n = n[4:]
    parts = [p for p in n.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else (n or None)


def _is_multitenant(url: str | None) -> bool:
    if not url:
        return False
    n = urlparse(url if "://" in url else "https://" + url).netloc.lower().split(":")[0]
    if any(n == s or n.endswith("." + s) for s in _PLATFORM_HOST_SUFFIXES):
        return True
    return _registrable(url) in _MULTITENANT_DOMAINS

CORPUS = (
    "projects/664356368213/locations/europe-west3/"
    "ragCorpora/3995818769384472576"
)
# Permissive: defeats the SDK's restrictive default so top_k is honoured.
# NOT a quality gate (n=5 Phase 1 returns all top-K regardless).
_DISTANCE_THRESHOLD = 0.7


def _audit_id_of(ctx) -> str | None:
    aid = getattr(ctx, "source_display_name", None)
    if aid:
        return aid
    txt = getattr(ctx, "text", "") or ""
    if txt.startswith("[audit_id="):
        return txt[len("[audit_id="):].split(" ", 1)[0].split("]", 1)[0].strip()
    return None


async def memory_read_similar_cases(
    query_summary: str,
    current_audit_id: str | None = None,
    top_k: int = 3,
    current_url: str | None = None,
) -> dict:
    """Return top-K similar prior audits from the memory layer.

    Empty (no similar audits) -> results=[], _error=None.
    API failure              -> results=[], _error="<reason>".
    Self-match excluded client-side when current_audit_id is given.

    AAA-75 Sub-step 3 cross-role exclusion: when current_url is given, a
    candidate is ALSO dropped if its registrable domain equals current_url's
    (a site once archived as a competitor, later audited as a client, has a
    different audit_id but the same business). Suppressed for multi-tenant
    hosts (shared registrable domain != same business) -> falls back to the
    exact audit_id match there.
    """
    base = {
        "results": [],
        "memory_call_count": 1,
        "memory_cost_usd": 0.0,  # free quota
        "_error": None,
    }
    if not (query_summary or "").strip():
        base["_error"] = "empty query_summary"
        return base

    cur_reg = _registrable(current_url) if current_url else None
    domain_excl = bool(cur_reg) and not _is_multitenant(current_url)
    # over-fetch: +5 when domain exclusion is active (multiple same-domain
    # entries may drop), +1 for the audit_id self-match only.
    if domain_excl:
        fetch_k = top_k + 5
    elif current_audit_id:
        fetch_k = top_k + 1
    else:
        fetch_k = top_k

    try:
        from memory.embedding_layer import _vertexai

        rag = _vertexai()

        def _q():
            cfg = rag.RagRetrievalConfig(
                top_k=fetch_k,
                filter=rag.Filter(
                    vector_distance_threshold=_DISTANCE_THRESHOLD
                ),
            )
            resp = rag.retrieval_query(
                text=query_summary,
                rag_resources=[rag.RagResource(rag_corpus=CORPUS)],
                rag_retrieval_config=cfg,
            )
            return list(getattr(resp.contexts, "contexts", []) or [])

        ctxs = await asyncio.to_thread(_q)
    except Exception as e:  # noqa: BLE001
        logger.warning("memory retrieval API failure: %s", e)
        base["_error"] = f"{type(e).__name__}: {e}"
        return base

    from memory.firestore_archive import read_audit

    results: list[dict] = []
    missing: list[str] = []
    for ctx in ctxs:
        aid = _audit_id_of(ctx)
        if not aid:
            continue
        if current_audit_id and aid == current_audit_id:
            continue  # client-side self-match exclusion (exact audit_id)
        doc = await read_audit(aid)
        if doc is None:  # memory <-> archive inconsistency
            missing.append(aid)
            continue
        if domain_excl:
            cand_url = doc.get("audit_url")
            # cross-role drop: same business (registrable domain), unless the
            # candidate itself is multi-tenant-hosted (distinct businesses).
            if not _is_multitenant(cand_url) and _registrable(cand_url) == cur_reg:
                continue
        ao = doc.get("audit_output") or {}
        md = doc.get("metadata") or {}
        results.append({
            "audit_id": aid,
            "similarity_score": getattr(ctx, "score", None),
            "audit_summary": (
                (ao.get("summary_translations") or {}).get("en")
                or ao.get("summary_markdown") or ""
            ),
            "industry_llm": md.get("industry_llm"),
            "page_type": md.get("page_type") or ao.get("page_type"),
            "brand": md.get("brand"),
            "audit_date": doc.get("audit_date"),
            "audit_url": doc.get("audit_url"),
        })
        if len(results) >= top_k:
            break

    base["results"] = results
    if missing:
        base["_error"] = (
            f"archive miss for retrieved ids: {missing} "
            "(memory<->archive inconsistency)"
        )
    return base
