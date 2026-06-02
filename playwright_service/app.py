# -*- coding: utf-8 -*-
"""AAA-19 / AAA-31 Sub-step 2b — Playwright microservice HTTP API.

POST /render  {url, wait_for?}  ->  the render_in_process() dict, i.e. either
  success: {url, status_code, render_time_ms, page_load_strategy,
            rendered_html_bytes, rendered_html, visible_text, ...}
  failure: {url, error, error_type}   (error_type: timeout|render_error|network_error)
Always HTTP 200 on a handled render (success OR render failure) — the caller
distinguishes via the body's "error" key, mirroring render_url's old contract.
Only malformed requests return 4xx.

GET /health -> {"status": "ok"}  (NOT /healthz — that literal path is
  intercepted by the Google Frontend on *.run.app and never reaches the app)

Deploy (Sub-step 3, NOT done here):
  - This is the ONLY image that bundles Chromium. See Dockerfile.
  - Cloud Run memory hint: ~2GB (Chromium is memory-heavy) — per the AAA-19 ticket.
  - Recommended conservative container concurrency: 1-2 (each render holds a
    browser context; higher concurrency risks OOM at 2GB). FLAGGED for S3.
  - Region: match the worker / queue (europe-west1). FLAGGED for S3.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from playwright_service.renderer import VALID_WAIT, render_in_process

app = FastAPI(title="playwright-render-service", version="1")


class RenderRequest(BaseModel):
    url: str
    wait_for: str = "networkidle"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/render")
async def render(req: RenderRequest) -> JSONResponse:
    """Render a URL server-side and return the structured dict (see module doc)."""
    if not req.url or not isinstance(req.url, str):
        return JSONResponse(status_code=400, content={"error": "url is required"})
    wait_for = req.wait_for if req.wait_for in VALID_WAIT else "networkidle"
    # render_in_process never raises — it returns an {error, error_type} dict on
    # any failure. Belt-and-suspenders guard keeps the endpoint crash-proof.
    try:
        result = await render_in_process(req.url, wait_for)
    except Exception as e:  # noqa: BLE001
        result = {"url": req.url, "error": "%s: %s" % (type(e).__name__, e),
                  "error_type": "render_error"}
    return JSONResponse(status_code=200, content=result)


if __name__ == "__main__":  # local dev only
    import uvicorn
    uvicorn.run("playwright_service.app:app", host="0.0.0.0", port=8081, reload=False)
