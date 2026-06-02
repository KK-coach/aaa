"""Render a URL and return structured DOM data — HTTP seam to the Playwright
microservice (AAA-19 / AAA-31 Sub-step 2b).

``render_url`` is the stable, contract-preserving entry point used by the
crawler escalation path (``discovery_agent.tools.crawl_with_playwright_tool``).
The heavy headless-Chromium logic now lives server-side in
``playwright_service.renderer`` (the only place Chromium is bundled); this
module reaches it over HTTP.

Resolution order (documented contract):
  1. HTTP-first — if ``PLAYWRIGHT_URL`` is set, POST to ``<PLAYWRIGHT_URL>/render``.
     This is the PRODUCTION path: the worker/agent images are lean and never
     launch a browser; all rendering happens in the microservice.
  2. In-process fallback — ONLY when ``PLAYWRIGHT_URL`` is unset AND a local
     Chromium is available. Pure local-dev convenience so a developer without
     the service running can still render. Never used in prod (prod sets
     ``PLAYWRIGHT_URL``).
  3. Skip-finding — otherwise (no service + no local browser, or any
     unreachable / error / timeout from either path) return
     ``{"url", "error", "error_type"}``. Never raise / crash: the escalation
     path treats an error dict as "rendered DOM unavailable" and keeps the
     HTTP crawl, so the audit continues.

The return contract is IDENTICAL to the old in-process renderer:
  success -> {url, status_code, render_time_ms, page_load_strategy,
              rendered_html_bytes, rendered_html, visible_text, ...}
  failure -> {url, error, error_type}  (timeout|render_error|network_error)
"""

from __future__ import annotations

import os

import httpx

# Backward-compat re-exports: callers historically imported these from here.
from playwright_service.renderer import (  # noqa: F401
    TIMEOUT_MS,
    USER_AGENT,
    VALID_WAIT,
    VIEWPORT,
    _dom_text,
    _words,
)

# HTTP client timeout must exceed the server-side render budget (TIMEOUT_MS)
# plus network overhead, else we'd time out a render that is about to succeed.
_HTTP_TIMEOUT_S = (TIMEOUT_MS / 1000.0) + 15.0

# Cache the local-Chromium availability check (import is cheap; the real launch
# is what's expensive, and we only do that in the dev fallback).
_LOCAL_RENDER_DISABLED = os.environ.get("PLAYWRIGHT_DISABLE_LOCAL") == "1"


async def _render_via_http(base_url: str, url: str, wait_for: str) -> dict:
    """POST to the Playwright microservice. Maps transport faults to the
    skip-finding contract (never raises)."""
    endpoint = base_url.rstrip("/") + "/render"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            resp = await client.post(endpoint, json={"url": url, "wait_for": wait_for})
    except httpx.TimeoutException as exc:
        return {"url": url, "error": f"{type(exc).__name__}: {exc}".strip(),
                "error_type": "timeout"}
    except Exception as exc:  # noqa: BLE001 — connect error / DNS / etc.
        return {"url": url, "error": f"{type(exc).__name__}: {exc}".strip(),
                "error_type": "network_error"}
    if resp.status_code != 200:
        return {"url": url,
                "error": f"playwright service returned HTTP {resp.status_code}",
                "error_type": "render_error"}
    try:
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — malformed body
        return {"url": url, "error": f"invalid service response: {exc}",
                "error_type": "render_error"}


async def _render_in_process_fallback(url: str, wait_for: str) -> dict:
    """Local-dev fallback: render with a locally-installed Chromium. If Chromium
    is absent the launch fails and render_in_process returns the error dict
    (skip-finding) — no crash."""
    from playwright_service.renderer import render_in_process
    return await render_in_process(url, wait_for)


async def render_url(url: str, wait_for: str = "networkidle") -> dict:
    """Render ``url`` and return structured DOM data. See module docstring for
    the resolution order and the (unchanged) return contract."""
    if wait_for not in VALID_WAIT:
        wait_for = "networkidle"

    pw_url = os.environ.get("PLAYWRIGHT_URL")
    # 1. HTTP-first (production).
    if pw_url:
        return await _render_via_http(pw_url, url, wait_for)

    # 2. In-process fallback (local dev only).
    if not _LOCAL_RENDER_DISABLED:
        return await _render_in_process_fallback(url, wait_for)

    # 3. Skip-finding.
    return {
        "url": url,
        "error": ("PLAYWRIGHT_URL not set and local in-process rendering is "
                  "disabled (set PLAYWRIGHT_URL or enable local fallback)"),
        "error_type": "render_error",
    }
