# -*- coding: utf-8 -*-
"""AAA-31 Sub-step 1 — Cloud Tasks enqueue for the audit worker.

Creates an HTTP POST task (OIDC-authenticated) on the `audit-jobs` queue,
targeting the Sub-step 2 worker (env WORKER_URL — placeholder for now).

google-cloud-tasks is NOT a current dependency (deploy-time add). The client is
lazy-imported and dependency-injectable so the smoke can run with a mock and so
importing this module never hard-fails in dev. Retry is a QUEUE property — set
once at queue creation (ensure_queue); the per-task create just enqueues.
"""

from __future__ import annotations

import json
import os

from site_profile.gemini_analyzer import _resolve_project

QUEUE_NAME = "audit-jobs"
HTTP_POST = 1  # tasks_v2.HttpMethod.POST == 1 (use the int so mocks/no-dep work)

# Test seam: smoke injects a mock; production leaves None -> real client.
_INJECTED_CLIENT = None


def cloud_tasks_location() -> str:
    """Queue region. Default europe-west1 — near Firestore eur3 / RAG
    europe-west3 (FLAGGED: final region follows the worker's Cloud Run region)."""
    return os.environ.get("CLOUD_TASKS_LOCATION", "europe-west1")


def worker_url() -> str:
    return os.environ.get("WORKER_URL", "https://WORKER_URL_PLACEHOLDER.run.app/run")


def worker_invoker_sa() -> str:
    return os.environ.get("WORKER_INVOKER_SA", "")  # OIDC SA email (placeholder)


def _client():
    if _INJECTED_CLIENT is not None:
        return _INJECTED_CLIENT
    from google.cloud import tasks_v2  # lazy — deploy-time dependency
    return tasks_v2.CloudTasksClient()


def _build_task(url: str, payload: dict, sa_email: str) -> dict:
    """The Cloud Tasks HTTP-task dict (OIDC). http_method as int (POST=1) so the
    proto accepts it and mocks need no enum import."""
    return {
        "http_request": {
            "http_method": HTTP_POST,
            "url": url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode("utf-8"),
            "oidc_token": {
                "service_account_email": sa_email,
                "audience": url,
            },
        }
    }


def ensure_queue(client=None, project: str | None = None) -> str:
    """Idempotently create the audit-jobs queue WITH retry config. Returns the
    queue path. (Deploy-time; not exercised by the dev smoke.)"""
    from google.cloud import tasks_v2
    cl = client or _client()
    project = project or _resolve_project()
    parent = f"projects/{project}/locations/{cloud_tasks_location()}"
    queue_path = cl.queue_path(project, cloud_tasks_location(), QUEUE_NAME)
    queue = {
        "name": queue_path,
        "retry_config": {
            "max_attempts": 5,
            "min_backoff": {"seconds": 30},
            "max_backoff": {"seconds": 600},
            "max_doublings": 3,
        },
    }
    try:
        cl.create_queue(parent=parent, queue=queue)
    except Exception:  # noqa: BLE001 — AlreadyExists is fine (idempotent)
        pass
    return queue_path


def enqueue_audit_task(audit_id: str, url: str, locale: str, email: str | None,
                       *, client=None, project: str | None = None) -> dict:
    """Create the worker HTTP task. Returns {name, queue_path, payload, worker_url}.
    Delivery is NOT required (worker doesn't exist yet)."""
    cl = client or _client()
    project = project or _resolve_project()
    queue_path = cl.queue_path(project, cloud_tasks_location(), QUEUE_NAME)
    payload = {"audit_id": audit_id, "url": url, "locale": locale, "email": email}
    task = _build_task(worker_url(), payload, worker_invoker_sa())
    resp = cl.create_task(parent=queue_path, task=task)
    return {
        "name": getattr(resp, "name", None),
        "queue_path": queue_path,
        "worker_url": worker_url(),
        "payload": payload,
    }
