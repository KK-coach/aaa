"""AAA-96 Phase 2 Sub-step 2 — report narrative (ONE structured Gemini call).

Phrases ALL customer-facing text from the COMPLETED report_model. Gemini
PHRASES, never computes/alters a number. EN-only v1. gemini-3-flash-preview @
global, temp=0.3, thinking_level="LOW", structured JSON.

Grounding: scores/bands/findings come ONLY from report_model; a framing context
block (page_type/business_model/topic_domain/audience/brand) is supplied for
relevance/tone, NOT for figures. Skip-finding: failure -> {_error, cost_usd:0}.
"""
from __future__ import annotations

import json
import logging

from site_profile.gemini_analyzer import _resolve_project, MODEL, compute_call_cost_usd

logger = logging.getLogger(__name__)

LOCATION = "global"
NARRATIVE_VERSION = "narrative_v1"


def _qw_schema():
    return {"type": "OBJECT", "properties": {
        "id": {"type": "STRING"}, "title": {"type": "STRING"},
        "explanation": {"type": "STRING"}},
        "required": ["id", "title", "explanation"]}


def _pillar_schema():
    return {"type": "OBJECT", "properties": {
        "id": {"type": "STRING"}, "narrative": {"type": "STRING"}},
        "required": ["id", "narrative"]}


def _schema() -> dict:
    return {"type": "OBJECT", "properties": {
        "hero_verdict": {"type": "STRING"},
        "exec_summary": {"type": "STRING"},
        "priority_fix_why": {"type": "STRING"},
        "quick_wins": {"type": "ARRAY", "items": _qw_schema()},
        "pillars": {"type": "ARRAY", "items": _pillar_schema()},
        "competitor_teaser": {"type": "STRING"},
        "methodology_note": {"type": "STRING"},
    }, "required": ["hero_verdict", "exec_summary", "priority_fix_why",
                    "quick_wins", "pillars", "competitor_teaser",
                    "methodology_note"]}


def _framing(ao: dict) -> dict:
    sp = ao.get("site_profile") or {}
    return {
        "page_type": ao.get("page_type"),
        "business_model": ao.get("business_model"),
        "topic_domain": ao.get("topic_domain"),
        "audience": ao.get("audience_relationship_primary"),
        "brand": sp.get("brand") or sp.get("brand_name"),
        "industry": sp.get("industry"),
    }


def _grounding_view(rm: dict) -> dict:
    """The EXACT figures/findings Gemini may phrase — nothing else."""
    pillars = [{
        "id": p["id"], "label": p["label"], "type": p["type"],
        "sub_score": p["sub_score"], "band": p["band"],
        "findings": [{"code": f["code"], "severity": f["severity"],
                      "title": f["default_title"],
                      "detail": f["default_detail"]} for f in p["findings"]],
    } for p in rm["pillars"]]
    return {
        "overall_score": rm["overall_score"], "overall_band": rm["overall_band"],
        "audited_url": rm["audited_url"], "indexed": rm["indexed"],
        "pillars": pillars,
        "priority_fix": rm["priority_fix"],
        "quick_wins": [{"id": q["code"], "title": q["default_title"],
                        "detail": q["default_detail"], "severity": q["severity"],
                        "effort": q["effort_label"]} for q in rm["quick_wins"]],
        "flags": rm["flags"],
        "competitor_available": (rm.get("competitor") or {}).get("available"),
        "cq_status": (rm.get("meta") or {}).get("cq_status"),
    }


def _prompt(rm: dict, ao: dict) -> str:
    gv = _grounding_view(rm)
    fr = _framing(ao)
    return f"""You are writing the customer-facing narrative for an SEO/AEO Readiness report. You PHRASE the
findings — you NEVER compute, invent, or change a number, score, band, or count.

FRAMING CONTEXT (for relevance/tone ONLY — not a source of figures):
{json.dumps(fr, ensure_ascii=False)}

REPORT DATA (the ONLY source of every score/band/finding you may reference — verbatim):
{json.dumps(gv, ensure_ascii=False)}

Write EN-only JSON with:
- hero_verdict: one punchy executive sentence on what the overall score ({gv['overall_score']},
  band "{gv['overall_band']}") means for this site.
- exec_summary: 2-3 sentences for a NON-technical executive — where they stand, what's at stake, and that
  acting is worth it (motivating, not alarmist).
- priority_fix_why: business-impact "why this is your #1 fix" for the priority_fix in the data.
- quick_wins: EXACTLY one object per quick_win in the data (same id), each {{id, title (phrased),
  explanation (1-2 sentences, what + why, actionable)}}.
- pillars: EXACTLY one object per pillar in the data (same id), each {{id, narrative (1-2 plain-language
  sentences explaining the score)}}. A pillar with NO findings -> positive/affirming narrative; do NOT
  invent problems.
- competitor_teaser: a compelling-but-withheld line for the LOCKED competitor section. competitor_available
  = {gv['competitor_available']}; since it is false, write a GENERIC "unlock to see how you compare to
  competitors" tease — do NOT fabricate competitor names or numbers.
- methodology_note: short plain-language "how we scored this".

RULES:
- Every figure traces VERBATIM to REPORT DATA. Reference ONLY findings present there.
- Be specific to the site using FRAMING (e.g. "As a B2B SaaS homepage…").
- E-E-A-T nuance: the "E-E-A-T" pillar measures author/credential/social MARKUP that machines parse, while
  Content Quality's expertise judgment is about the WRITING. If one is strong and the other weak, narrate
  them so they are NOT contradictory (e.g. "the writing shows expertise, but lacks author/credential markup
  search engines and AI can read").
- Tone: professional, exec-accessible, motivating, concise (mobile-readable), no jargon dumps.

Return ONLY the structured JSON."""


_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=_resolve_project(),
                               location=LOCATION)
    return _client


def generate_narrative(report_model: dict, ao: dict) -> dict:
    """ONE Gemini call -> narrative dict (+ _meta with cost). Skip-finding:
    failure -> {_error, cost_usd:0.0}."""
    from google.genai import types

    try:
        prompt = _prompt(report_model, ao)
        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3, response_mime_type="application/json",
                response_schema=_schema(),
                thinking_config=types.ThinkingConfig(thinking_level="LOW")))
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = ((getattr(um, "candidates_token_count", 0) or 0)
                   + (getattr(um, "thoughts_token_count", 0) or 0))
        cost = round(compute_call_cost_usd(MODEL, in_tok, out_tok), 8)
        parsed = json.loads(resp.text)
        parsed["_meta"] = {"narrative_version": NARRATIVE_VERSION,
                           "model_id": MODEL, "cost_usd": cost, "_error": None}
        return parsed
    except Exception as e:  # noqa: BLE001 — skip-finding
        logger.warning("generate_narrative failed: %s: %s",
                       type(e).__name__, e)
        return {"_meta": {"narrative_version": NARRATIVE_VERSION,
                          "cost_usd": 0.0, "_error": f"{type(e).__name__}: {e}"}}
