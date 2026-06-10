"""AAA-202 Gate 1 S1 — success-label backfill over the audit archive.

One pass over `audits`: derives the Gate-0 success labels and stamps them as
TOP-LEVEL DOC FIELDS (not inside audit_output — they're cross-audit derived,
queryable, and re-derivable; the audit_output stays the immutable measurement):

  success_serp_position : int|None  best position of this doc's URL across ALL
                                    audits' serp_{branded,category}.organic_results
                                    + the doc's own client_ranking_status
  success_ai_cited      : bool      URL in any serp_*.ai_overview_citations or
                                    ai_overview.cited_sources
  success_url_normalized: str       scheme/www/query/fragment-stripped URL (dedup)
  success_excluded      : bool      off-type exclusion (gov/public-sector/news
                                    directory pages are not "successful peers")
  success_excluded_reason: str|None
  success_label_version : int       bump on re-derivation

Off-type rule (S1): page_type in {news} OR a gov/public-sector domain
(.gov*, kormany.hu, magyarorszag.hu, *.edu-style public bodies). Reported by the
runner. _en_canonical_failed docs keep their labels but are EXCLUDED from the
vector-index input by the index builder (separate filter).

Idempotent: re-running overwrites the same fields.
"""

from __future__ import annotations

import re

LABEL_VERSION = 1

_GOV_DOMAINS = ("kormany.hu", "magyarorszag.hu")
_GOV_PAT = re.compile(r"\.(gov|gouv)(\.[a-z]{2})?$|\.mil$")
_OFFTYPE_PAGE_TYPES = frozenset({"news"})


def normalize_url(u: str) -> str:
    """scheme/www/query/fragment-stripped, lowercased, no trailing slash."""
    if not isinstance(u, str):
        return ""
    u = u.strip().lower()
    u = re.sub(r"^https?://(www\.)?", "", u)
    u = u.split("?")[0].split("#")[0]
    return u.rstrip("/")


def host_of(norm_url: str) -> str:
    return (norm_url or "").split("/")[0]


def offtype_reason(norm_url: str, page_type: str | None) -> str | None:
    h = host_of(norm_url)
    if any(h == d or h.endswith("." + d) for d in _GOV_DOMAINS):
        return "gov_public_sector_domain"
    if _GOV_PAT.search(h or ""):
        return "gov_public_sector_domain"
    if (page_type or "") in _OFFTYPE_PAGE_TYPES:
        return "news_directory_page_type"
    return None


def derive_labels(all_docs: list[tuple[str, dict]]) -> dict[str, dict]:
    """all_docs: [(doc_id, doc_dict)] -> {doc_id: label_fields}. Pure function
    (no I/O) so the derivation is unit-testable and re-runnable."""
    serp_pos: dict[str, int] = {}
    aio_cited: set[str] = set()

    for _id, doc in all_docs:
        ao = doc.get("audit_output") or {}
        rf = ao.get("re_findings") or {}
        for blk in ("serp_branded", "serp_category"):
            s = rf.get(blk) or {}
            for r in (s.get("organic_results") or []):
                u = normalize_url(r.get("url"))
                p = r.get("position")
                if u and isinstance(p, int):
                    serp_pos[u] = min(serp_pos.get(u, 99), p)
            for c in (s.get("ai_overview_citations") or []):
                cu = c if isinstance(c, str) else (c.get("url") if isinstance(c, dict) else "")
                if cu:
                    aio_cited.add(normalize_url(cu))
        aio = ao.get("ai_overview") or {}
        for c in (aio.get("cited_sources") or []):
            cu = c if isinstance(c, str) else (c.get("url") if isinstance(c, dict) else "")
            if cu:
                aio_cited.add(normalize_url(cu))

    out: dict[str, dict] = {}
    for _id, doc in all_docs:
        ao = doc.get("audit_output") or {}
        url = doc.get("audit_url") or ao.get("url") or ""
        nu = normalize_url(url)
        best = serp_pos.get(nu)
        # the doc's own client ranking also counts (a client CAN be successful)
        crs = (ao.get("re_findings") or {}).get("client_ranking_status") or {}
        for br in ("branded", "category"):
            nd = crs.get(br) or {}
            if nd.get("found_in_top_10") and isinstance(nd.get("position"), int):
                best = min(best if best is not None else 99, nd["position"])
        reason = offtype_reason(nu, ao.get("page_type"))
        out[_id] = {
            "success_serp_position": best,
            "success_ai_cited": nu in aio_cited,
            "success_url_normalized": nu,
            "success_excluded": reason is not None,
            "success_excluded_reason": reason,
            "success_label_version": LABEL_VERSION,
        }
    return out
