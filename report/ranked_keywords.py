"""AAA-206 — ranked-keywords §2 comparison fetcher.

For the target + its (up to 3) selected competitors, fetch the HOMEPAGE-only
ranked keywords from DataForSEO Labs and derive two MEASURED facts per
keyword (S0/Gate-0 verified derivable from this endpoint):
  - organic rank   -> ranked_serp_element.serp_item.rank_absolute
  - AIO present     -> ranked_serp_element.serp_item_types contains "ai_overview"

A THIRD fact — "target cited in the AI Overview" — is NOT carried by this
endpoint (Gate-0 proved the default call returns 0 ai_overview items even for
heavily-cited domains; there is no citation field). Per Krisztián's S1
decision it is populated for the TARGET ONLY, by reusing the per-SERP AIO
citation data the audit already collected (re_findings.serp_*.ai_overview_*),
matched by keyword — no new API calls. Competitors carry no cited column.
Where no measured citation data exists for a keyword, aio_cited is None
(not_measured) — never a false zero.

Cost: one ranked_keywords/live call per entity (~$0.013–0.02, scales with
returned rows, capped at limit=100). 4 entities ≈ $0.08 (~7.9% of mean audit
cost). Per-entity skip-finding: on exception/empty -> that entity is omitted,
cost 0 for that call, the rest continue.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_ENDPOINT = (
    "https://api.dataforseo.com/v3/dataforseo_labs/google/"
    "ranked_keywords/live"
)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_LIMIT = 100
_LOCATION_NAME = "United States"
_LANGUAGE_NAME = "English"
_ATTEMPTS = 3
_BACKOFF = (1.5, 3.0)


def _credentials() -> tuple[str, str]:
    """AAA-201 — .env first (local dev), os.environ fallback (worker)."""
    import os as _os

    from dotenv import dotenv_values

    v = dotenv_values(_ENV_PATH)
    login = v.get("DATAFORSEO_LOGIN") or _os.environ.get("DATAFORSEO_LOGIN") or ""
    password = (v.get("DATAFORSEO_PASSWORD")
                or _os.environ.get("DATAFORSEO_PASSWORD") or "")
    return login, password


def _bare_domain(url: str) -> str:
    """AAA-127 — strip scheme + leading www + any path → bare registrable host
    for the DataForSEO `target` field. '' if unusable."""
    if not isinstance(url, str) or not url.strip():
        return ""
    h = re.sub(r"^https?://", "", url.strip().lower()).split("/")[0].split("?")[0]
    return h[4:] if h.startswith("www.") else h


async def _fetch_one(domain: str) -> tuple[list[dict], float]:
    """One homepage-only ranked_keywords call for a bare domain.
    Returns (rows, cost). Raises on transport error (caller skip-finds)."""
    login, password = _credentials()
    if not login or not password:
        raise RuntimeError("DataForSEO creds missing")

    body = [{
        "target": domain,
        "location_name": _LOCATION_NAME,
        "language_name": _LANGUAGE_NAME,
        "limit": _LIMIT,
        "load_rank_absolute": True,
        # homepage-only (S0 form decision): restrict to the root path.
        "filters": [["ranked_serp_element.serp_item.relative_url", "=", "/"]],
    }]

    def _call() -> tuple[list[dict], float]:
        import requests
        from requests.auth import HTTPBasicAuth

        resp = requests.post(_ENDPOINT, auth=HTTPBasicAuth(login, password),
                             json=body, timeout=120)
        resp.raise_for_status()
        j = resp.json()
        cost = float(j.get("cost") or 0.0)
        tasks = j.get("tasks") or []
        res = (tasks[0].get("result") or [{}]) if tasks else [{}]
        items = (res[0] or {}).get("items") or []
        return list(items), cost

    last_err = None
    for attempt in range(_ATTEMPTS):
        try:
            items, cost = await asyncio.to_thread(_call)
            return items, cost
        except Exception as e:  # noqa: BLE001 — transient; retry then skip-finding
            last_err = "%s: %s" % (type(e).__name__, e)
            if attempt < _ATTEMPTS - 1:
                await asyncio.sleep(_BACKOFF[attempt])
    raise RuntimeError("ranked_keywords fetch failed: %s" % last_err)


def _rows_from_items(items: list[dict], cited_kw_map: dict | None) -> list[dict]:
    """Map raw DataForSEO items -> per-keyword fact rows.

    cited_kw_map: {normalized_keyword: bool} of MEASURED target AIO-citation
    status from re_findings (target only; None/{} for competitors). A keyword
    absent from the map -> aio_cited=None (not_measured), never a false zero.
    """
    out = []
    for it in items or []:
        kd = it.get("keyword_data") or {}
        rse = it.get("ranked_serp_element") or {}
        si = rse.get("serp_item") or {}
        kw = kd.get("keyword")
        vol = ((kd.get("keyword_info") or {}).get("search_volume"))
        types = rse.get("serp_item_types") or []
        aio_cited = None
        if cited_kw_map:
            aio_cited = cited_kw_map.get((kw or "").strip().lower())
        out.append({
            "keyword": kw,
            "rank_absolute": si.get("rank_absolute"),
            "search_volume": vol,
            "type": si.get("type"),
            "aio_present": "ai_overview" in types,
            "aio_cited": aio_cited,  # bool (target measured) | None (not measured)
        })
    out.sort(key=lambda r: (r["search_volume"] is None, -(r["search_volume"] or 0)))
    return out


def _target_cited_map(ao: dict, target_url: str) -> dict:
    """Build {normalized_keyword: bool} of the target's MEASURED AIO-citation
    status, reusing the per-SERP data the audit already collected. No API call.
    Only the keyword(s) the pipeline ran a full SERP on are present."""
    rf = (ao or {}).get("re_findings") or {}
    target_reg = _bare_domain(target_url)
    cited = {}
    for branch in ("serp_branded", "serp_category"):
        sb = rf.get(branch) or {}
        kw = ((sb.get("query_metadata") or {}).get("keyword")
              or sb.get("keyword") or "").strip().lower()
        if not kw:
            continue
        if not sb.get("ai_overview_present"):
            cited[kw] = False  # AIO checked, not present → target not cited
            continue
        cites = sb.get("ai_overview_citations") or []
        hit = any(_bare_domain(u) == target_reg for u in cites if isinstance(u, str))
        cited[kw] = bool(hit)
    return cited


def summarize_entity(rows: list[dict]) -> dict:
    """Per-entity summary: keyword count, AIO-present %, and (target only)
    a measured AIO-cited fraction. Cited % is over the MEASURED subset only."""
    n = len(rows)
    aio_present = sum(1 for r in rows if r.get("aio_present"))
    cited_measured = [r for r in rows if r.get("aio_cited") is not None]
    cited_yes = sum(1 for r in cited_measured if r.get("aio_cited"))
    return {
        "keyword_count": n,
        "aio_present_count": aio_present,
        "aio_present_pct": round(100 * aio_present / n) if n else None,
        "aio_cited_measured": len(cited_measured),
        "aio_cited_yes": cited_yes,
    }


async def build_ranked_keywords_comparison(ao: dict) -> dict:
    """Top-level builder. Returns ranked_keywords_comparison:
      {entities: [{role, domain, url, rows, summary}], cost_usd, _error?}

    Per-entity skip-finding: a failed entity is omitted (cost 0 for it); the
    builder never raises. AIO-cited is filled for the TARGET only.
    """
    target_url = ao.get("url") or ""
    comp_ids = ((ao.get("re_findings") or {}).get("competitor_audit_ids") or {})
    competitor_urls = list(comp_ids.keys()) if isinstance(comp_ids, dict) else []

    entities_spec = [("target", target_url)] + [
        ("competitor", u) for u in competitor_urls[:3]
    ]
    cited_map = _target_cited_map(ao, target_url)

    out_entities = []
    total_cost = 0.0
    for role, url in entities_spec:
        domain = _bare_domain(url)
        if not domain:
            continue
        try:
            items, cost = await _fetch_one(domain)
        except Exception as e:  # noqa: BLE001 — per-entity skip-finding
            logger.warning("ranked_keywords skip-finding for %s: %s", domain, e)
            continue  # omit entity, cost 0
        total_cost += cost
        rows = _rows_from_items(items, cited_map if role == "target" else None)
        if not rows:
            continue  # empty → omit (homepage ranks for nothing measurable)
        out_entities.append({
            "role": role,
            "domain": domain,
            "url": url,
            "rows": rows,
            "summary": summarize_entity(rows),
        })

    return {"entities": out_entities, "cost_usd": round(total_cost, 6)}
