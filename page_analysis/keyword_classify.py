"""AAA-84 / AAA-91 — two-step keyword classifier.

STEP 1 (classify_keywords) — the UNCHANGED AAA-84 classifier: one batched
Gemini call, flat 3-label output (tail_type + search_intent [L1] +
relevance_score). Prompt-instructed JSON, NO response_schema. This module
is byte-preserved as the AAA-84 original — L1 byte-stability is a literal
guarantee (A/B control probe, 2026-05-21: 11/11 vs stored baseline, twice).

STEP 2 (classify_l2) — AAA-91 L2 sub-intent: a SEPARATE batched Gemini
call. L1 is a FIXED INPUT (from Step 1); the call only assigns L2 from the
L1-conditional sublist (Gemini structured-output discriminated union —
plain anyOf union, the explicit Field(discriminator=...) is rejected by
google-genai). L2-only — it never re-classifies L1.

ORCHESTRATOR (classify_keywords_with_l2) — Step 1, then Step 2, merge.

WHY TWO STEPS (AAA-91 Sub-step 1, 2026-05-21): the single-call Variant B
(joint L1+L2 discriminated union) was MEASURED to shift L1 — the A/B
control probe showed unchanged-AAA-84 = 11/11 vs baseline but Variant B =
7/11, a 100% schema-effect (joint L1+L2 reasoning couples the levels).
Two-step is the only form that keeps the Option B-B locked premise
("search_intent / L1 byte-unchanged"). Methodological rule: schema-
altering changes require a measurement-based A/B control before ship.

Cost (AAA-53 separation, never folded into audit_cost_usd): Step 1
~$0.0011-0.012 + Step 2 ~$0.0002-0.001 (run-to-run thinking-token
variance). thinking_level=LOW kept ON — judgment-laden task (AAA-84
Sub-step 1: thinking_budget=0 collapsed intent quality).

EMPIRICAL STABILITY (AAA-84 Sub-step 2): search_intent (L1) ~60% mean
end-to-end byte-stability — BEST-EFFORT tier. search_intent_l2 (L2)
stability is characterized in AAA-91 Sub-step 2; provisionally also
BEST-EFFORT (Sub-step 0.5 cross-variant divergence). Model:
gemini-3-flash-preview.
"""

from __future__ import annotations

import logging
from typing import Literal, Union

from pydantic import BaseModel

from discovery_agent.output_schema import (
    CommercialL2, InformationalL2, L2_BY_L1, NavigationalL2, TransactionalL2,
)
from site_profile.gemini_analyzer import _parse, get_usage, vertex_generate

logger = logging.getLogger(__name__)

_TAIL = ("shorttail", "midtail", "longtail")
_INTENT = ("informational", "commercial", "transactional", "navigational")


# --- Step 2 response-schema: L2-only, L1 is fixed input -------------------
# Plain Union (anyOf) — NOT Annotated[..., Field(discriminator=...)]: the
# explicit discriminator emits a `discriminator` JSON-schema key that the
# google-genai Schema type rejects (AAA-91 Sub-step 1 gate finding). Each
# model echoes search_intent_l1 (the fixed input) so the orchestrator can
# detect any L1 modification, and constrains search_intent_l2 to that L1's
# sublist.
class _L2Informational(BaseModel):
    keyword: str
    search_intent_l1: Literal["informational"]
    search_intent_l2: InformationalL2


class _L2Commercial(BaseModel):
    keyword: str
    search_intent_l1: Literal["commercial"]
    search_intent_l2: CommercialL2


class _L2Transactional(BaseModel):
    keyword: str
    search_intent_l1: Literal["transactional"]
    search_intent_l2: TransactionalL2


class _L2Navigational(BaseModel):
    keyword: str
    search_intent_l1: Literal["navigational"]
    search_intent_l2: NavigationalL2


class _L2Batch(BaseModel):
    items: list[Union[_L2Informational, _L2Commercial,
                      _L2Transactional, _L2Navigational]]


# --- Step 1 prompt: VERBATIM unchanged AAA-84 (flat 3-label) --------------
_PROMPT_L1 = """\
You are classifying SEO keywords for a website audit.

For EACH keyword in the list, determine three labels:
1) tail_type:
   - "shorttail" = 1-2 generic words (broad head terms)
   - "midtail" = 2-4 specific words (clear topic, moderate specificity)
   - "longtail" = 4+ words, or a question/phrase
2) search_intent:
   - "informational" = learning/researching (no purchase signal)
   - "commercial" = purchase research (comparing, evaluating)
   - "transactional" = ready to buy / sign up / take action
   - "navigational" = looking for a specific brand or property
3) relevance_score: float in [0.0, 1.0] - how well the keyword represents
   THIS PAGE'S core topic based on the audit summary below. Use the full
   range; do NOT bunch everything at 0.5.

CLASSIFY BASED ON THE PAGE CONTEXT BELOW, not generic SEO knowledge.

AUDIT SUMMARY (page context, ground truth for relevance):
{summary}

KEYWORDS TO CLASSIFY ({n} total):
{keywords}

Return ONLY JSON of the form:
{{"items": [
  {{"keyword": "<verbatim>", "tail_type": "<one of {tail_set}>",
    "search_intent": "<one of {intent_set}>", "relevance_score": <float>}},
  ...
]}}
"""

# --- Step 2 prompt: L2-only, L1 already fixed -----------------------------
_PROMPT_L2 = """\
You are assigning a level-2 search sub-intent (L2) to SEO keywords.

The level-1 intent (L1) of each keyword is ALREADY DECIDED and given to
you below — DO NOT change it. For each keyword, echo back its given L1 and
pick the single best L2 from THAT L1's sublist:
- L1 "informational": definition | how_to | why | knowledge |
  comparison_info  (comparison_info = "X vs Y" as concept, not commercial)
- L1 "commercial": review | best_of | versus | alternatives |
  pricing_research
- L1 "transactional": purchase | sign_up | download | contact |
  quote_request
- L1 "navigational": branded | direct | section_lookup

AUDIT SUMMARY (page context):
{summary}

KEYWORDS (each with its fixed L1):
{keywords}

Return ONLY JSON: {{"items": [ one object per keyword with fields
keyword, search_intent_l1 (echo the given L1), search_intent_l2 ]}}.
"""


def _collect_keywords(td: dict) -> list[str]:
    """Flatten + dedupe keyword strings from the heterogeneous dict."""
    out: list[str] = []
    p = (td or {}).get("primary_keyword")
    if isinstance(p, str) and p.strip():
        out.append(p.strip())
    for k in ("secondary_keywords", "long_tail_keywords"):
        for kw in ((td or {}).get(k) or []):
            if isinstance(kw, str) and kw.strip():
                out.append(kw.strip())
    seen, uniq = set(), []
    for kw in out:
        if kw not in seen:
            seen.add(kw)
            uniq.append(kw)
    return uniq


def _coerce_l1(items: list, source_keywords: set[str]) -> list[dict]:
    """Coerce Step-1 (flat AAA-84) items; drop anything malformed."""
    out: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        kw = (it.get("keyword") or "").strip()
        if not kw or kw not in source_keywords:  # never fabricate keywords
            continue
        tail = (it.get("tail_type") or "").strip().lower()
        intent = (it.get("search_intent") or "").strip().lower()
        rs = it.get("relevance_score")
        try:
            rs = float(rs) if rs is not None else None
            if rs is not None:
                rs = max(0.0, min(1.0, rs))
        except (TypeError, ValueError):
            rs = None
        out.append({
            "keyword": kw,
            "tail_type": tail if tail in _TAIL else None,
            "search_intent": intent if intent in _INTENT else None,
            "relevance_score": rs,
        })
    return out


async def classify_keywords(
    target_keywords_dict: dict,
    audit_summary: str,
) -> tuple[list[dict], float]:
    """STEP 1 — the UNCHANGED AAA-84 classifier. Returns (classified
    sorted desc by relevance_score, cost). Items have keyword, tail_type,
    search_intent (L1), relevance_score — NO L2. Skip-finding: any failure
    -> ([], 0.0). Single batched call, prompt-instructed JSON (no schema).
    """
    keywords = _collect_keywords(target_keywords_dict)
    if not keywords:
        return [], 0.0

    prompt = _PROMPT_L1.format(
        summary=" ".join((audit_summary or "").split()[:500]) or "[none]",
        n=len(keywords),
        keywords="\n".join(f"- {k}" for k in keywords),
        tail_set="|".join(_TAIL),
        intent_set="|".join(_INTENT),
    )
    cost_before = get_usage().get("cost", 0.0)
    text, _mv, err = await vertex_generate(
        prompt, temperature=0.0, thinking_level="LOW"
    )
    cost = round(get_usage().get("cost", 0.0) - cost_before, 6)

    if err or not text:
        logger.warning(
            "classify_keywords (L1): LLM error (%s) — skip-finding", err
        )
        return [], 0.0
    try:
        data = _parse(text)
        items = data.get("items") if isinstance(data, dict) else None
        if items is None and isinstance(data, list):
            items = data
    except Exception as e:  # noqa: BLE001 — skip-finding contract
        logger.warning("classify_keywords (L1): parse failed (%s: %s)",
                        type(e).__name__, e)
        return [], cost

    coerced = _coerce_l1(items or [], set(keywords))
    coerced.sort(
        key=lambda x: (x.get("relevance_score") is None,
                       -(x.get("relevance_score") or 0.0),
                       x.get("keyword") or ""),
    )
    return coerced, cost


async def classify_l2(
    keywords: list[str],
    l1_map: dict[str, str],
    audit_summary: str,
) -> tuple[dict[str, str | None], float]:
    """STEP 2 — assign L2 given a FIXED L1 per keyword. Returns
    ({keyword: l2_or_None}, cost). One batched call. L2-only — never
    re-classifies L1. Skip-finding: any failure -> ({}, 0.0).

    Keywords whose echoed L1 differs from the given L1, or whose L2 is not
    in the L1 sublist, get None (logged) — Step 2 must not mutate L1.
    """
    pairs = [(k, l1_map.get(k)) for k in keywords
             if l1_map.get(k) in _INTENT]
    if not pairs:
        return {}, 0.0

    prompt = _PROMPT_L2.format(
        summary=" ".join((audit_summary or "").split()[:500]) or "[none]",
        keywords="\n".join(f'- "{k}" (L1={l1})' for k, l1 in pairs),
    )
    cost_before = get_usage().get("cost", 0.0)
    text, _mv, err = await vertex_generate(
        prompt, temperature=0.0, thinking_level="LOW",
        response_schema=_L2Batch,
    )
    cost = round(get_usage().get("cost", 0.0) - cost_before, 6)

    if err or not text:
        logger.warning("classify_l2: LLM error (%s) — skip-finding ({})", err)
        return {}, 0.0
    try:
        data = _parse(text)
        items = data.get("items") if isinstance(data, dict) else data
    except Exception as e:  # noqa: BLE001 — skip-finding contract
        logger.warning("classify_l2: parse failed (%s: %s)",
                        type(e).__name__, e)
        return {}, cost

    given = dict(pairs)
    l2_map: dict[str, str | None] = {}
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        kw = (it.get("keyword") or "").strip()
        if kw not in given:
            continue
        echoed_l1 = (it.get("search_intent_l1") or "").strip().lower()
        l2 = (it.get("search_intent_l2") or "").strip().lower() or None
        if echoed_l1 != given[kw]:  # Step 2 must NOT mutate L1
            logger.warning(
                "classify_l2: L1 mismatch for %r (given=%s echoed=%s) "
                "— dropping L2", kw, given[kw], echoed_l1,
            )
            l2_map[kw] = None
        elif l2 and l2 in L2_BY_L1.get(given[kw], ()):
            l2_map[kw] = l2
        else:
            l2_map[kw] = None
    return l2_map, cost


async def classify_keywords_with_l2(
    target_keywords_dict: dict,
    audit_summary: str,
) -> tuple[list[dict], float]:
    """ORCHESTRATOR — Step 1 (L1) then Step 2 (L2), merged.

    Step 1 failure -> ([], 0.0) full skip-finding.
    Step 2 failure -> Step 1 L1-only result kept (graceful degrade —
    search_intent_l2=None for all; L2 is a BEST-EFFORT tier, its loss is
    not a regression), partial cost.
    """
    classified, c1 = await classify_keywords(target_keywords_dict,
                                             audit_summary)
    if not classified:
        return [], c1  # Step 1 fail -> full skip

    l1_map = {c["keyword"]: c.get("search_intent") for c in classified}
    l2_map, c2 = await classify_l2(
        list(l1_map), l1_map, audit_summary
    )
    for c in classified:
        c["search_intent_l2"] = l2_map.get(c["keyword"])  # None if degraded
    return classified, round(c1 + c2, 6)
