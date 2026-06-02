# -*- coding: utf-8 -*-
"""AAA-31 Sub-step 2 — audit worker (Cloud Run HTTP service).

A minimal FastAPI service whose single job is to run the EXISTING ~20-min
``run_one`` to completion, triggered by the Sub-step 1 dispatcher's Cloud Tasks
payload. It owns the job-state lifecycle transitions around that run.

Deploy shape (NOT done here — build + local smoke only):
  - Cloud Run, container concurrency = 1 (ONE audit per instance). Because of
    that, the module-level cost counters (_USAGE / _KG_USAGE) and the in-process
    ADK session are safe AS-IS — they are per-process and there is never a second
    concurrent request on the same instance. A future concurrency bump (>1) MUST
    re-open this: move those counters + the forced-client-audit-id seam
    (reverse_engineering_agent.tools._FORCED_CLIENT_AUDIT_ID) to request scope.
  - Request timeout: run_one is ~20-22 min wall-clock. Set the Cloud Run request
    timeout to ~3600s (60 min) with margin; confirm the service's max-timeout
    ceiling covers it. (FLAGGED — exact value set at deploy.)
  - Region: europe-west1 (next to the audit-jobs queue / Firestore eur3 / RAG
    europe-west3). (FLAGGED — locked at deploy.)
  - Chromium is NOT bundled in this image (lean). The JS-render escalation
    degrades to skip-finding when the browser is absent (see render_url's
    catch-all + crawl_with_playwright_tool's error short-circuit). Full
    escalation returns with the Playwright microservice in AAA-19 / Sub-step 2b.

Retry contract: return 200 on ANY handled completion (success OR audit error) so
Cloud Tasks does NOT retry a deterministic audit failure. Return 5xx ONLY for
genuinely retryable infrastructure faults (e.g. Firestore unreachable) so the
queue redelivers. Idempotent per audit_id: a job already 'done' (or in-flight
'running') is not re-run.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from deploy_agent.job_state import create_job, get_job, transition_job
from memory.firestore_archive import _COLLECTION

# run_one is referenced as a module attribute so tests can stub it cleanly
# (monkeypatch deploy_agent.worker.run_one).
from reverse_engineering_agent.test_agent import run_one

logger = logging.getLogger("audit_worker")

app = FastAPI(title="audit-worker", version="1")


def _report_uri(audit_id: str) -> str:
    """Stable pointer to the archived audit (source of truth). The published
    HTML/customer-link delivery lives downstream (AAA-96/143), not in the worker."""
    return "firestore://%s/%s" % (_COLLECTION, audit_id)


@app.get("/health")
async def health() -> dict:
    # NOT /healthz — that literal path is intercepted by the Google Frontend on
    # *.run.app and never reaches the container (same as the Playwright service).
    return {"status": "ok"}


@app.post("/run")
async def run(request: Request) -> JSONResponse:
    """Cloud Tasks target. Body: {audit_id, url, locale, email}."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 — malformed body is a permanent failure
        return JSONResponse(status_code=400, content={"error": "invalid JSON body"})

    audit_id = (payload or {}).get("audit_id")
    url = (payload or {}).get("url")
    locale = (payload or {}).get("locale") or "hu"
    email = (payload or {}).get("email")
    if not audit_id or not url:
        return JSONResponse(status_code=400,
                            content={"error": "audit_id and url are required"})

    # --- job lookup / lifecycle (Firestore). Infra faults here ARE retryable. ---
    try:
        job = get_job(audit_id)
        if job is None:
            # Defensive: the dispatcher normally creates the job (queued) before
            # enqueuing. If it is missing (lost doc / direct call), create it so
            # the run is still tracked. job_id == archive_id is preserved.
            create_job(url=url, locale=locale, requester_email=email, audit_id=audit_id)
            job = get_job(audit_id)

        status = (job or {}).get("status")
        if status == "done":
            # Idempotent: a redelivered task for a finished audit is a no-op.
            return JSONResponse(status_code=200, content={
                "audit_id": audit_id, "status": "done", "idempotent": True,
                "report_uri": (job or {}).get("report_uri"),
            })
        if status == "running":
            # Already in flight (should not happen under concurrency=1, but a
            # redelivery shouldn't double-run). Ack without re-running.
            return JSONResponse(status_code=200, content={
                "audit_id": audit_id, "status": "running", "note": "already in progress",
            })

        transition_job(audit_id, "running")
    except Exception as e:  # noqa: BLE001 — Firestore/infra: let Cloud Tasks retry
        logger.exception("job-state infra error for %s", audit_id)
        return JSONResponse(status_code=503, content={
            "audit_id": audit_id, "error": "job-state unavailable: %s" % type(e).__name__,
        })

    # --- the heavy run. A failure here is the AUDIT's failure (deterministic):
    #     record it and return 200 so Cloud Tasks does NOT retry a bad audit. ---
    try:
        result = await run_one(url, audit_id=audit_id)
    except Exception as e:  # noqa: BLE001 — skip-finding: record, don't fabricate
        reason = ("%s: %s" % (type(e).__name__, e))[:500]
        logger.exception("run_one failed for %s", audit_id)
        try:
            transition_job(audit_id, "error", error=reason)
        except Exception:  # noqa: BLE001 — best-effort; the run already failed
            logger.exception("could not mark error for %s", audit_id)
        return JSONResponse(status_code=200, content={
            "audit_id": audit_id, "status": "error", "error": reason,
        })

    report_uri = _report_uri(audit_id)
    try:
        transition_job(audit_id, "done", report_uri=report_uri)
    except Exception as e:  # noqa: BLE001 — audit succeeded; finalize is retryable
        logger.exception("could not mark done for %s", audit_id)
        return JSONResponse(status_code=503, content={
            "audit_id": audit_id, "error": "finalize failed: %s" % type(e).__name__,
        })

    meta = (result or {}).get("audit_metadata") or {}
    return JSONResponse(status_code=200, content={
        "audit_id": audit_id,
        "status": "done",
        "report_uri": report_uri,
        "duration_seconds": meta.get("duration_seconds"),
        "customer_summary_status": meta.get("customer_summary_status"),
    })


if __name__ == "__main__":  # local dev only
    import uvicorn
    uvicorn.run("deploy_agent.worker:app", host="0.0.0.0", port=8080, reload=False)
