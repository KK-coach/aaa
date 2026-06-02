"""AAA-96 Phase 2 Sub-step 3 — full report orchestrator + persist (REAL write).

build_full_report(ao): CQ eval (1 Gemini call) -> deterministic report_model
(CQ included, overall /100) -> narrative (1 Gemini call) -> weave narrative INTO
report_model BY ID -> render-ready report_doc. id-set hardening with ONE retry
then deterministic fallback (never crash). persist_report writes to the separate
`reports/{audit_id}` collection (non-mutating to the audit doc).
"""
from __future__ import annotations

import copy
import logging

from report.cq_eval import evaluate_content_quality
from report.report_model import build_report_model
from report.narrative import generate_narrative

logger = logging.getLogger(__name__)

REPORTS_COLLECTION = "reports"
_DEFAULT_METHODOLOGY = (
    "This score audits the URL against seven readiness pillars, combining "
    "deterministic technical measurements with an AI content-quality assessment.")


def _validate_ids(report_model: dict, narrative: dict) -> bool:
    """True iff narrative's pillar-id set and quick_win-id set EXACTLY match
    report_model's. A narrative that errored (no pillars) fails validation."""
    if not narrative or narrative.get("_meta", {}).get("_error"):
        return False
    rm_pids = {p["id"] for p in report_model.get("pillars", [])}
    nr_pids = {p.get("id") for p in (narrative.get("pillars") or [])}
    rm_qids = {q["code"] for q in report_model.get("quick_wins", [])}
    nr_qids = {q.get("id") for q in (narrative.get("quick_wins") or [])}
    return rm_pids == nr_pids and rm_qids == nr_qids


def _weave(report_model: dict, narrative: dict) -> dict:
    """Weave narrative text INTO a copy of report_model BY ID. Every field
    falls back to the deterministic default if its narrative piece is
    missing/orphaned — so a partial or failed narrative still yields a complete
    render-ready doc."""
    doc = copy.deepcopy(report_model)
    nar = narrative or {}
    o, b = doc.get("overall_score"), doc.get("overall_band")

    # top-level
    doc["hero_verdict"] = nar.get("hero_verdict") or (
        f"Overall readiness is {o}/100 ({b}).")
    doc["exec_summary"] = nar.get("exec_summary") or (
        f"This site scores {o}/100 ({b}) for search & AI readiness. "
        f"See the prioritized fixes below.")
    doc["methodology_note"] = nar.get("methodology_note") or _DEFAULT_METHODOLOGY

    # competitor teaser
    if isinstance(doc.get("competitor"), dict):
        fallback_teaser = ((doc["competitor"].get("teaser") or {})
                           .get("one_line_teaser"))
        doc["competitor"]["teaser_narrative"] = (
            nar.get("competitor_teaser") or fallback_teaser
            or "Unlock to see how you compare to competitors.")

    # priority_fix why
    if isinstance(doc.get("priority_fix"), dict):
        doc["priority_fix"]["narrative_why"] = (
            nar.get("priority_fix_why")
            or doc["priority_fix"].get("default_why_it_matters"))

    # pillars by id
    nar_pmap = {p.get("id"): p for p in (nar.get("pillars") or [])}
    for p in doc.get("pillars", []):
        np = nar_pmap.get(p["id"]) or {}
        p["narrative"] = np.get("narrative") or (
            f"{p['label']} scored {p['sub_score']}/100"
            + (f" ({p['band']})." if p.get("band") else "."))

    # quick_wins by id (rm quick_win key is 'code'; narrative key is 'id')
    nar_qmap = {q.get("id"): q for q in (nar.get("quick_wins") or [])}
    for q in doc.get("quick_wins", []):
        nq = nar_qmap.get(q["code"]) or {}
        q["title"] = nq.get("title") or q.get("default_title")
        q["explanation"] = nq.get("explanation") or q.get("default_recommendation")

    return doc


def build_full_report(ao: dict, generated_at: str | None = None,
                      _narrate=generate_narrative,
                      _eval_cq=evaluate_content_quality) -> dict:
    """Run the full pipeline -> render-ready report_doc. `_narrate`/`_eval_cq`
    are injectable for testing the id-hardening fallback without live calls."""
    cq = _eval_cq(ao)
    rm = build_report_model(ao, cq_result=cq, generated_at=generated_at)

    nar = _narrate(rm, ao)
    nar_cost = (nar.get("_meta") or {}).get("cost_usd") or 0.0
    if _validate_ids(rm, nar):
        narrative_status = "complete"
    else:
        logger.info("narrative id-set mismatch -> retrying once")
        nar2 = _narrate(rm, ao)
        nar_cost += (nar2.get("_meta") or {}).get("cost_usd") or 0.0
        if _validate_ids(rm, nar2):
            nar, narrative_status = nar2, "retry_succeeded"
        else:
            # keep the better of the two (more matching pieces) for weaving;
            # _weave fills the rest from deterministic defaults.
            nar, narrative_status = (nar2 or nar), "partial_fallback"

    doc = _weave(rm, nar)
    doc["meta"] = {
        "audit_id": ao.get("_audit_id"),
        "generated_at": generated_at,
        "rubric_version": rm.get("rubric_version", "v1"),
        "cq_status": (rm.get("meta") or {}).get("cq_status"),
        "narrative_status": narrative_status,
        "report_generation_cost_usd": round(
            (cq.get("cost_usd") or 0.0) + nar_cost, 8),
    }
    return doc


async def persist_report(report_doc: dict, db=None) -> dict:
    """REAL write to reports/{audit_id} (separate collection, non-mutating to
    the audit doc). Returns {path, wrote}."""
    audit_id = (report_doc.get("meta") or {}).get("audit_id")
    if not audit_id:
        return {"path": None, "wrote": False, "error": "no audit_id"}
    own = db is None
    if own:
        from google.cloud import firestore_v1 as firestore
        db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",
                                   database="ai-advisor-app")
    await db.collection(REPORTS_COLLECTION).document(audit_id).set(report_doc)
    return {"path": f"{REPORTS_COLLECTION}/{audit_id}", "wrote": True}
