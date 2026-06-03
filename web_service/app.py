# -*- coding: utf-8 -*-
"""AAA-97 public serving service — GET /report/{audit_id}?lang=<lang>.

Lean by design: reads Firestore + GCS directly (no audit-pipeline imports), so
the public image stays small and cold-starts fast. Runs as the aaa-web SA
(bucket-scoped storage.objectViewer + datastore.user). The bucket stays
non-public — bytes are fetched by the service SA and streamed to the client.

Endpoints run as sync `def` so FastAPI threadpools the blocking Firestore/GCS
SDK calls (no event-loop blocking).
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from google.cloud import firestore, storage

DATABASE = os.environ.get("FIRESTORE_DATABASE", "ai-advisor-app")
COLLECTION = "audits"

app = FastAPI(title="aaa-web", version="1")

_fs = None
_gcs = None


def _db() -> firestore.Client:
    global _fs
    if _fs is None:
        _fs = firestore.Client(database=DATABASE)
    return _fs


def _storage() -> storage.Client:
    global _gcs
    if _gcs is None:
        _gcs = storage.Client()
    return _gcs


def _page(title: str, message: str, status: int) -> HTMLResponse:
    """Minimal, self-contained friendly page (no stack trace)."""
    html = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s</title><style>"
        "body{font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif;background:#f6f8fc;"
        "color:#222;margin:0;display:flex;min-height:100vh;align-items:center;"
        "justify-content:center}.box{background:#fff;border:1px solid #e3e8f0;"
        "border-radius:12px;padding:36px 40px;max-width:420px;text-align:center;"
        "box-shadow:0 1px 3px rgba(0,0,0,.06)}h1{font-size:20px;margin:0 0 8px}"
        "p{color:#555;margin:0}</style></head><body><div class=\"box\">"
        "<h1>%s</h1><p>%s</p></div></body></html>" % (title, title, message)
    )
    return HTMLResponse(content=html, status_code=status)


@app.get("/health")
def health() -> dict:
    # NOT /healthz (that literal path is swallowed by the GFE on *.run.app).
    return {"status": "ok"}


@app.get("/report/{audit_id}", response_class=HTMLResponse)
def report(audit_id: str, lang: str = "") -> Response:
    # 1. Firestore lookup (blocking; threadpooled by FastAPI).
    try:
        snap = _db().collection(COLLECTION).document(audit_id).get()
    except Exception:  # noqa: BLE001 — never leak a stack trace
        return _page("Something went wrong",
                     "We could not load this report right now. Please try again later.",
                     503)
    if not snap.exists:
        return _page("Report not found",
                     "We couldn't find a report for this link. Please check the URL.", 404)

    ao = (snap.to_dict() or {}).get("audit_output") or {}
    uri = ao.get("customer_report_html_uri")
    # Availability gate: uri present AND not flagged failed.
    if ao.get("_customer_report_html_failed") is not None or not isinstance(uri, dict):
        return _page("Report not available yet",
                     "Your report is still being prepared. Please check back shortly.", 200)

    objects = uri.get("objects") or {}
    chosen = lang if lang in objects else uri.get("default_lang")
    key = objects.get(chosen) if chosen else None
    if not key:
        return _page("Report not available yet",
                     "Your report is still being prepared. Please check back shortly.", 200)

    # 2. Fetch the rendered HTML as the service SA (bucket stays non-public).
    try:
        data = _storage().bucket(uri.get("bucket")).blob(key).download_as_bytes()
    except Exception:  # noqa: BLE001
        return _page("Something went wrong",
                     "We could not load this report right now. Please try again later.", 503)

    return Response(content=data, media_type="text/html; charset=utf-8")


if __name__ == "__main__":  # local dev only
    import uvicorn
    uvicorn.run("web_service.app:app", host="0.0.0.0", port=8080, reload=False)
