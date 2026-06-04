"""AAA-96 Phase 2 Sub-step 1 — Content Quality eval (production callable).

The ONE place Gemini scores in the Readiness model. Reproduces the rubric that
PASSED the Phase-0 discrimination re-sweep (AAA-96 13151/13218): page_type-
RELATIVE 6-criteria judgment, gemini-3-flash-preview @ global, temp=0,
thinking_level="LOW", structured JSON. Groundedness guard: judge ONLY from the
provided main_content; thin/missing content drives the verdicts (do NOT invent).

sub_score = Σ(yes=1.0, partial=0.5, no=0.0)/6 -> 0-1. Bands: Strong >=0.75 /
Adequate 0.4-0.75 / Weak <0.4.

Skip-finding: any failure -> {_error, sub_score_0_1=None, cost_usd=0.0}.
"""
from __future__ import annotations

import json
import logging

from site_profile.gemini_analyzer import _resolve_project, MODEL, compute_call_cost_usd

logger = logging.getLogger(__name__)

LOCATION = "global"
RUBRIC_VERSION = "cq_v1"
CRITERIA = ["comprehensiveness", "intent_match", "clarity", "value_add",
            "eeat_substance", "freshness"]
_PTS = {"yes": 1.0, "partial": 0.5, "no": 0.0}
_MAX_CONTENT_CHARS = 8000  # token control; the rubric is page_type-relative


def _band(s: float) -> str:
    return "Strong" if s >= 0.75 else ("Adequate" if s >= 0.4 else "Weak")


def _schema() -> dict:
    crit = {"type": "OBJECT", "properties": {
        "verdict": {"type": "STRING", "enum": ["yes", "partial", "no"]},
        "reason": {"type": "STRING"}}, "required": ["verdict", "reason"]}
    return {"type": "OBJECT",
            "properties": {c: crit for c in CRITERIA}, "required": CRITERIA}


def _prompt(page_type, bm, topic_domain, audience, intent, char_count, text) -> str:
    return f"""You are grading the CONTENT QUALITY of one webpage on 6 criteria. For each, return
verdict yes/partial/no + a 1-line reason that MUST reference the actual content below.

PAGE CONTEXT: page_type={page_type} | business_model={bm} | topic_domain={topic_domain} | \
audience={audience} | search_intent={intent} | main_content_length={char_count} chars

KEY RULE — judge RELATIVE TO page_type expectations: does this page cover what a page of THIS page_type
should? A homepage is NOT expected to be a deep article (don't penalize brevity if it does its job); a
thin news_article or a generic/empty homepage IS a problem. Char-count is context interpreted relative
to page_type, not an absolute floor.

CRITERIA:
1. comprehensiveness — covers what THIS page_type should (relative, not absolute depth)?
2. intent_match — content matches the page's likely search/user intent ({intent})?
3. clarity — clear, well-organized, readable?
4. value_add — original value vs generic/commodity/thin/keyword-stuffed boilerplate?
5. eeat_substance — does the TEXT show experience/expertise/authority/trust appropriate to THIS page_type?
6. freshness — specific/current vs vague/dated, page_type-relative (an evergreen homepage is NOT dinged
   for "not fresh")?

GROUNDEDNESS: judge ONLY from the MAIN CONTENT below. If content is missing or thin, that itself drives
the verdicts — do NOT invent content that is not present.

MAIN CONTENT (may be truncated):
---
{text}
---
Return ONLY structured JSON (all 6 criteria). Ground every reason in the content above."""


_client = None


def _get_client():
    global _client
    if _client is None:
        from site_profile.gemini_analyzer import make_genai_client  # AAA-155
        _client = make_genai_client(location=LOCATION)
    return _client


def _main_content(ao: dict) -> str:
    mc = (ao.get("crawl") or {}).get("main_content") or {}
    return mc.get("text") or mc.get("content") or ""


def evaluate_content_quality(ao: dict) -> dict:
    """Run the validated CQ rubric on one audit_output. Returns
    {sub_score_0_1, band, criteria[], rubric_version, cost_usd, _error,
    main_content_chars}. Skip-finding: failure -> _error + sub_score None."""
    from google.genai import types

    text = _main_content(ao)
    cc = len(text)
    base = {"rubric_version": RUBRIC_VERSION, "main_content_chars": cc}
    if not text.strip():
        return {**base, "sub_score_0_1": None, "band": None, "criteria": [],
                "cost_usd": 0.0,
                "_error": "no main_content (CQ would be unfair — skipped)"}
    intent = (ao.get("target_keywords") or {}).get("intent")
    prompt = _prompt(ao.get("page_type"), ao.get("business_model"),
                     ao.get("topic_domain"),
                     ao.get("audience_relationship_primary"), intent,
                     cc, text[:_MAX_CONTENT_CHARS])
    try:
        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0, response_mime_type="application/json",
                response_schema=_schema(),
                thinking_config=types.ThinkingConfig(thinking_level="LOW")))
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = ((getattr(um, "candidates_token_count", 0) or 0)
                   + (getattr(um, "thoughts_token_count", 0) or 0))
        cost = round(compute_call_cost_usd(MODEL, in_tok, out_tok), 8)
        parsed = json.loads(resp.text)
        crits, total = [], 0.0
        for c in CRITERIA:
            v = (parsed.get(c) or {}).get("verdict")
            r = (parsed.get(c) or {}).get("reason")
            if v not in _PTS:
                raise ValueError(f"out-of-enum verdict for {c}: {v!r}")
            total += _PTS[v]
            crits.append({"name": c, "verdict": v, "reason": r})
        sub = round(total / len(CRITERIA), 4)
        return {**base, "sub_score_0_1": sub, "band": _band(sub),
                "criteria": crits, "cost_usd": cost, "_error": None}
    except Exception as e:  # noqa: BLE001 — skip-finding
        logger.warning("evaluate_content_quality failed: %s: %s",
                       type(e).__name__, e)
        return {**base, "sub_score_0_1": None, "band": None, "criteria": [],
                "cost_usd": 0.0, "_error": f"{type(e).__name__}: {e}"}
