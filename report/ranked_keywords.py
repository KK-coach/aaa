"""AAA-206 — ranked-keywords §2 comparison fetcher.

For the target + its (up to 3) selected competitors, fetch the WHOLE-DOMAIN
ranked keywords from DataForSEO Labs and derive two MEASURED facts per
keyword (S0/Gate-0 verified derivable from this endpoint):
  - organic rank   -> ranked_serp_element.serp_item.rank_absolute
  - AIO present     -> ranked_serp_element.serp_item_types contains "ai_overview"

AIO-citation membership is intentionally NOT included: Gate-0 (S1) proved the
endpoint carries no citation field, and per Krisztián's S2 decision the
requirement is AIO-PRESENCE per keyword only, never citation. So there is no
cited column anywhere.

S2 form decision: WHOLE-DOMAIN (no relative_url filter), ordered by search
volume desc so the top-100-by-volume are returned. This reliably returns
deep-page competitors (e.g. tax.thomsonreuters.com) that homepage-only "/"
would skip.

Cost: one ranked_keywords/live call per entity (~$0.013–0.02, scales with
returned rows, capped at limit=100). 4 entities ≈ $0.08 (~7.9% of mean audit
cost). Per-entity skip-finding: on genuine call failure/empty -> that entity
is omitted, cost 0 for that call, the rest continue.
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
    """One whole-domain ranked_keywords call for a bare domain, ordered so the
    top-100-by-volume are returned. Returns (rows, cost). Raises on transport
    error (caller skip-finds)."""
    login, password = _credentials()
    if not login or not password:
        raise RuntimeError("DataForSEO creds missing")

    body = [{
        "target": domain,
        "location_name": _LOCATION_NAME,
        "language_name": _LANGUAGE_NAME,
        "limit": _LIMIT,
        "load_rank_absolute": True,
        # S2: WHOLE-DOMAIN (no relative_url filter) so deep-page competitors
        # return. Order by search volume desc → the limit-100 are the top-100
        # by volume, which is exactly what the top-N display cap then shows.
        "order_by": ["keyword_data.keyword_info.search_volume,desc"],
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


def _rows_from_items(items: list[dict]) -> list[dict]:
    """Map raw DataForSEO items -> per-keyword fact rows (rank + AIO-present)."""
    out = []
    for it in items or []:
        kd = it.get("keyword_data") or {}
        rse = it.get("ranked_serp_element") or {}
        si = rse.get("serp_item") or {}
        types = rse.get("serp_item_types") or []
        out.append({
            "keyword": kd.get("keyword"),
            "rank_absolute": si.get("rank_absolute"),
            "search_volume": ((kd.get("keyword_info") or {}).get("search_volume")),
            "type": si.get("type"),
            "aio_present": "ai_overview" in types,
        })
    out.sort(key=lambda r: (r["search_volume"] is None, -(r["search_volume"] or 0)))
    return out


def summarize_entity(rows: list[dict]) -> dict:
    """Per-entity summary: keyword count + AIO-present %."""
    n = len(rows)
    aio_present = sum(1 for r in rows if r.get("aio_present"))
    return {
        "keyword_count": n,
        "aio_present_count": aio_present,
        "aio_present_pct": round(100 * aio_present / n) if n else None,
    }


async def build_ranked_keywords_comparison(ao: dict) -> dict:
    """Top-level builder. Returns ranked_keywords_comparison:
      {entities: [{role, domain, url, rows, summary}], cost_usd, _error?}

    Per-entity skip-finding: a failed entity is omitted (cost 0 for it); the
    builder never raises. Whole-domain form for all entities; no cited data.
    """
    target_url = ao.get("url") or ""
    comp_ids = ((ao.get("re_findings") or {}).get("competitor_audit_ids") or {})
    competitor_urls = list(comp_ids.keys()) if isinstance(comp_ids, dict) else []

    entities_spec = [("target", target_url)] + [
        ("competitor", u) for u in competitor_urls[:3]
    ]

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
        rows = _rows_from_items(items)
        if not rows:
            continue  # genuine empty → omit, audit continues
        out_entities.append({
            "role": role,
            "domain": domain,
            "url": url,
            "rows": rows,
            "summary": summarize_entity(rows),
        })

    return {"entities": out_entities, "cost_usd": round(total_cost, 6)}
