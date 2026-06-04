# -*- coding: utf-8 -*-
"""AAA-31 Sub-step 1 — conversational audit front-door dispatcher.

A lightweight ADK Agent (wrapped as an AdkApp for Agent Runtime) that:
  - new request  -> start_audit (create job + enqueue Cloud Task) -> return id
  - status Q     -> get_audit_status
  - finished-report Q -> read_completed_audit (+ flywheel) -> answer ONLY from
    retrieved data; never invent numbers/findings; never expose internal ids/
    fields/tool names.

The heavy ~20-min run_one runs in the Sub-step 2 worker, NOT here. This module
builds the dispatcher; it does NOT deploy.
"""

from __future__ import annotations

import os

# Mirror the RE/Discovery import-time contract: gemini-3-flash-preview is
# 'global'-only. Set BEFORE importing the ADK Agent.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
from site_profile.gemini_analyzer import MODEL, _RETRY, _resolve_project  # noqa: E402

_proj = _resolve_project()
if _proj and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = _proj
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

import asyncio  # noqa: E402

from google.adk.agents import Agent  # noqa: E402
from google.adk.models.google_llm import Gemini  # noqa: E402 (AAA-155 retry)
from google.adk.tools import FunctionTool  # noqa: E402

from deploy_agent.job_state import create_job, get_job
from deploy_agent.tasks_enqueue import enqueue_audit_task
from memory.firestore_archive import read_audit
from memory.retrieval import memory_read_similar_cases


# --------------------------------------------------------------------------
# FunctionTools
# --------------------------------------------------------------------------
async def start_audit(url: str, locale: str = "hu", email: str = "") -> dict:
    """Start a new SEO/AI-visibility audit for a website. Creates the job and
    queues the long-running analysis (delivered later by link/email).

    Args:
        url: The website URL to audit.
        locale: Report language, 'hu' or 'en' (default 'hu').
        email: Optional email to notify when the report is ready.
    Returns: {audit_id, status, message}.
    """
    audit_id = await asyncio.to_thread(create_job, url, locale, (email or None))
    try:
        await asyncio.to_thread(enqueue_audit_task, audit_id, url, locale, (email or None))
        queued = True
    except Exception as e:  # noqa: BLE001 — surface, don't crash the front-door
        queued = False
        await asyncio.to_thread(_mark_enqueue_error, audit_id, e)
    return {
        "audit_id": audit_id,
        "status": "queued" if queued else "queued_enqueue_failed",
        "message": ("Audit started. The report will be delivered by link/email "
                    "when ready."),
    }


def _mark_enqueue_error(audit_id, e):
    from deploy_agent.job_state import transition_job
    try:
        transition_job(audit_id, "error", error="enqueue failed: %s: %s" % (type(e).__name__, e))
    except Exception:  # noqa: BLE001
        pass


async def get_audit_status(audit_id: str) -> dict:
    """Get the current status of an audit job.

    Args:
        audit_id: The audit identifier returned when the audit was started.
    Returns: {found, status, submitted_at, finished_at, report_uri} or {found: False}.
    """
    job = await asyncio.to_thread(get_job, audit_id)
    if not job:
        return {"found": False}
    return {
        "found": True,
        "status": job.get("status"),
        "submitted_at": job.get("submitted_at"),
        "finished_at": job.get("finished_at"),
        "report_uri": job.get("report_uri"),
    }


async def read_completed_audit(audit_id: str, locale: str = "hu") -> dict:
    """Read a FINISHED audit report (bounded subset for grounded Q&A). Returns
    the localized customer summary, the competitor comparison (dimension table +
    patterns), ranking + AI-Overview citation state, and per-aspect findings —
    NOT the full audit blob.

    Args:
        audit_id: The audit identifier.
        locale: 'hu' or 'en' (default 'hu').
    Returns: bounded dict, or {found: False} if not archived.
    """
    doc = await read_audit(audit_id)
    if not doc:
        return {"found": False}
    ao = doc.get("audit_output") or {}
    rf = ao.get("re_findings") or {}
    comp = rf.get("comparison") or {}
    cst = ao.get("customer_summary_translations") or {}
    legacy = ao.get("summary_translations") or {}
    summary = (cst.get(locale) or cst.get("en")
               or legacy.get(locale) or legacy.get("en"))
    aspects = ao.get("aaa124_aspect_evaluations") or {}
    aspect_findings = {
        k: (v or {}).get("structured_finding")
        for k, v in aspects.items()
        if isinstance(v, dict) and not k.startswith("_")
    }
    return {
        "found": True,
        "report_summary": summary,
        "comparison": {
            "dimension_table": comp.get("dimension_table"),
            "patterns": comp.get("patterns"),
        },
        "client_ranking": (rf.get("client_ranking_status") or {}).get("branded"),
        "ai_overview_client_cited": (ao.get("ai_overview") or {}).get("client_cited"),
        "chatgpt_target_cited": (ao.get("chatgpt_query_response") or {}).get("target_site_cited"),
        "no_competitors_reason": rf.get("no_competitors_reason"),
        "aspect_findings": aspect_findings,
    }


async def find_similar_reports(query: str) -> dict:
    """Find similar prior audited sites from the memory corpus (the flywheel).
    Use for context when answering about a finished report.

    Args:
        query: A short description of the site/topic to find neighbours for.
    Returns: the memory_read_similar_cases result (top-K similar prior audits).
    """
    return await memory_read_similar_cases(query_summary=query, top_k=3)


# --------------------------------------------------------------------------
# Agent + AdkApp
# --------------------------------------------------------------------------
_INSTRUCTION = """\
You are a conversational front-door for an SEO / AI-visibility audit service.

ROUTING:
- If the user asks to audit / analyze a NEW website (gives a URL): call start_audit
  with the URL (locale 'hu' unless they ask otherwise; pass email if given). Then
  tell them the audit has started and the report will be delivered by link/email.
  Give them the reference id so they can check status later.
- If the user asks about the STATUS / progress of an audit: call get_audit_status.
- If the user asks a QUESTION about a finished report (they reference a report /
  id): call read_completed_audit. You MAY also call find_similar_reports for
  market context if helpful.

ANSWERING ABOUT A REPORT:
- Answer ONLY from the data returned by read_completed_audit / find_similar_reports.
- NEVER invent numbers, competitors, or findings. If the requested detail is not
  in the retrieved data, say plainly that it is not available in the report.
- Do NOT expose internal identifiers, field names, tool names, or system details.
  Speak in plain business language.
- Match the user's language (Hungarian or English).
"""

dispatcher_agent = Agent(
    name="audit_dispatcher",
    model=Gemini(model=MODEL, retry_options=_RETRY),  # AAA-155 transient retry
    instruction=_INSTRUCTION,
    tools=[
        FunctionTool(start_audit),
        FunctionTool(get_audit_status),
        FunctionTool(read_completed_audit),
        FunctionTool(find_similar_reports),
    ],
)
root_agent = dispatcher_agent


def build_adk_app():
    """Wrap the dispatcher as an AdkApp for Agent Runtime (NOT deployed here)."""
    from vertexai import agent_engines
    return agent_engines.AdkApp(agent=dispatcher_agent)
