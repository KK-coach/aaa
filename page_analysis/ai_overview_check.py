"""AAA-85 / AAA-137 — AI Overview detection + cited-source capture.

One DataForSEO serp/google/organic/live/advanced call per audit checks Google's
AI Overview for the PRIMARY keyword. AAA-85 captured only the trigger boolean;
AAA-137 also extracts, from the SAME live response (no new call), the AIO
`markdown`, its `references[]` -> cited_sources [{title,url}], whether the
client domain is among them (client_cited, subdomain/path tolerant per AAA-86),
and the asynchronous flag.

AAA-137 finding (supersedes the old AAA-85 docstring): the live call returns a
SYNCHRONOUS AI Overview with full markdown + references for triggering keywords
(asynchronous_ai_overview=False) — the citations were available-but-discarded,
so capture is a cheap parse, NOT a new/async call. Async fallback retained: if
asynchronous_ai_overview=True OR references are empty, present=True with
cited_sources=[] and note="async, citations unavailable" (skip-finding, no retry).

Direct REST (NOT the project MCP — AAA-76 finding: MCP trims `cost`).
Skip-finding contract: any error -> (None, 0.0) + WARN. None (not measured) vs
present=False (measured, no AIO) is meaningful.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _credentials() -> tuple[str, str]:
    """AAA-201 — .env first (local dev), os.environ fallback (the worker has the
    creds as Cloud Run env vars and no .env file). Same fix as keywords_volume;
    without it the worker's AIO check failed creds-missing → top-level
    ai_overview null on every worker-launched audit."""
    import os as _os

    from dotenv import dotenv_values

    v = dotenv_values(_ENV_PATH)
    login = v.get("DATAFORSEO_LOGIN") or _os.environ.get("DATAFORSEO_LOGIN") or ""
    password = (v.get("DATAFORSEO_PASSWORD")
                or _os.environ.get("DATAFORSEO_PASSWORD") or "")
    return login, password


def _registrable(url: str) -> str | None:
    """Registrable domain (last two labels), scheme/www/path-stripped,
    lowercased. e.g. https://www.taxually.com/x -> taxually.com. Sufficient for
    Phase-1 locales (.com/.hu); .co.uk-style not special-cased (flagged)."""
    if not url:
        return None
    netloc = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    netloc = netloc.split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    labels = [l for l in netloc.split(".") if l]
    return ".".join(labels[-2:]) if len(labels) >= 2 else (netloc or None)


def _domain_match(client_url: str, ref_url: str) -> bool:
    """Subdomain/path-tolerant domain match (AAA-86 behavior): the reference
    URL is the client iff its registrable domain equals the client's."""
    c, r = _registrable(client_url), _registrable(ref_url)
    return bool(c and r and c == r)


def check_ai_overview(
    keyword: str,
    language_code: str,
    location_code: int,
    client_url: str | None = None,
) -> "tuple[dict | None, float]":
    """Synchronous worker — returns (ai_overview_obj | None, cost_usd).

    obj = {present, markdown, cited_sources:[{title,url}], client_cited,
           asynchronous, note?}. None on skip-finding (no keyword / no creds /
           API error). Run via asyncio.to_thread by the async entry points."""
    kw = (keyword or "").strip()
    if not kw:
        return None, 0.0
    login, password = _credentials()
    if not login or not password:
        logger.warning("check_ai_overview: DataForSEO creds missing")
        return None, 0.0

    body = [{
        "keyword": kw, "language_code": language_code,
        "location_code": location_code, "depth": 10,
        # AAA-168: recover async AI Overviews. Without this DataForSEO returns
        # asynchronous_ai_overview=True with empty references; with it, the
        # server waits for the async AIO and returns markdown + references
        # (+~3.5s, +~$0.002 on this same call). Probe: 0 → 7 refs recovered.
        "load_async_ai_overview": True,
    }]
    try:
        import requests
        from requests.auth import HTTPBasicAuth

        resp = requests.post(
            _ENDPOINT, auth=HTTPBasicAuth(login, password),
            json=body, timeout=120,
        )
        resp.raise_for_status()
        j = resp.json()
    except Exception as e:  # noqa: BLE001 — skip-finding
        logger.warning("check_ai_overview(%r) failed: %s: %s — (None, 0.0)",
                       kw, type(e).__name__, e)
        return None, 0.0

    cost = round(float(j.get("cost") or 0.0), 6)
    items = (((j.get("tasks") or [{}])[0].get("result") or [{}])[0]
             or {}).get("items") or []
    aio_item = next(
        (it for it in items
         if it.get("type") in ("ai_overview", "ai_overview_reference")), None)
    async_any = any(it.get("asynchronous_ai_overview") for it in items)
    present = bool(aio_item) or async_any

    # AAA-168: aio_citation_status is the explicit provenance emitted at
    # measurement time (never inferred later from a bare client_cited=None):
    #   absent   — no AIO on this SERP (present=False)
    #   measured — AIO present AND references obtained (sync or async-recovered)
    #   deferred — AIO present, but even load_async returned no references
    if not present:
        return {"present": False, "markdown": None, "cited_sources": [],
                "client_cited": None, "asynchronous": False,
                "aio_citation_status": "absent"}, cost

    aio = aio_item or {}
    is_async = bool(aio.get("asynchronous_ai_overview")) or (
        async_any and aio_item is None)
    markdown = aio.get("markdown")
    refs = aio.get("references") or []
    cited = [{"title": r.get("title"), "url": r.get("url")}
             for r in refs if r.get("url")]

    # Gate on REFERENCES-PRESENT, not the asynchronous flag — that flag stays
    # True even when load_async recovered the refs (the original bug was gating
    # on it). No refs (rare residual, even after load_async) -> deferred, with
    # client_cited=None now explicitly explained by the status.
    if not cited:
        return {"present": True, "markdown": markdown, "cited_sources": [],
                "client_cited": None, "asynchronous": is_async,
                "note": "async, citations unavailable",
                "aio_citation_status": "deferred"}, cost

    client_cited = None
    if client_url:
        client_cited = any(_domain_match(client_url, c["url"]) for c in cited)
    return {"present": True, "markdown": markdown, "cited_sources": cited,
            "client_cited": client_cited, "asynchronous": is_async,
            "aio_citation_status": "measured"}, cost


async def check_ai_overview_async(
    keyword: str, language_code: str, location_code: int,
    client_url: str | None = None,
) -> "tuple[dict | None, float]":
    """Async entry point (AAA-137): returns (ai_overview_obj | None, cost)."""
    return await asyncio.to_thread(
        check_ai_overview, keyword, language_code, location_code, client_url)


async def check_ai_overview_trigger(
    keyword: str, language_code: str, location_code: int,
) -> "tuple[bool | None, float]":
    """Back-compat (AAA-85): returns (triggered_bool | None, cost). Derives the
    boolean from the AAA-137 object's `present`."""
    obj, cost = await check_ai_overview_async(keyword, language_code, location_code)
    return (obj.get("present") if obj else None), cost
