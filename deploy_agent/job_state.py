# -*- coding: utf-8 -*-
"""AAA-31 Sub-step 1 — Firestore job-state for the async audit pipeline.

Collection `audit_jobs`, doc id = audit_id. Reuses the existing
memory.firestore_archive._db() singleton (honours FIRESTORE_DATABASE) so the
dispatcher and the archive write to the same Firestore database.

Lifecycle: queued -> running -> (done | error). The dispatcher creates the job
(queued) + enqueues a Cloud Task; the Sub-step 2 worker transitions
running -> done/error and sets report_uri.
"""

from __future__ import annotations

import uuid

from memory.firestore_archive import _db, _now_iso

JOBS_COLLECTION = "audit_jobs"
SCHEMA_VERSION = 1
_VALID_STATUS = {"queued", "running", "done", "error"}


def _jobs():
    return _db().collection(JOBS_COLLECTION)


def create_job(url: str, locale: str = "hu", requester_email: str | None = None,
               audit_id: str | None = None) -> str:
    """Create a queued job. Returns the audit_id (uuid4 unless one is supplied).

    NOTE (flagged for AAA-31): this audit_id is the dispatcher's job-tracking id.
    Whether run_one can adopt it as the ARCHIVE key (write_audit currently mints
    its own uuid4) is an open question — see Findings."""
    aid = audit_id or str(uuid.uuid4())
    now = _now_iso()
    doc = {
        "audit_id": aid,
        "url": url,
        "status": "queued",
        "locale": locale,
        "requester_email": requester_email,
        "report_uri": None,
        "submitted_at": now,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "schema_version": SCHEMA_VERSION,
    }
    _jobs().document(aid).set(doc)
    return aid


def get_job(audit_id: str) -> dict | None:
    snap = _jobs().document(audit_id).get()
    return snap.to_dict() if snap.exists else None


def transition_job(audit_id: str, status: str, *, report_uri: str | None = None,
                   error: str | None = None) -> dict:
    """Status-transition helper. Stamps started_at on 'running', finished_at on
    'done'/'error'. Raises ValueError on an unknown status (no silent corruption)."""
    if status not in _VALID_STATUS:
        raise ValueError("invalid job status %r (valid: %s)" % (status, sorted(_VALID_STATUS)))
    now = _now_iso()
    patch: dict = {"status": status}
    if status == "running":
        patch["started_at"] = now
    if status in ("done", "error"):
        patch["finished_at"] = now
    if report_uri is not None:
        patch["report_uri"] = report_uri
    if error is not None:
        patch["error"] = error
    _jobs().document(audit_id).update(patch)
    return patch
