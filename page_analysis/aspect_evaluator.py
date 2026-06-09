"""AAA-124 Sub-step 1 (Option E narrow scope) — per-aspect page evaluator.

ONE Gemini 3.5 Flash holistic (V3) call per audit, producing 7 per-aspect
evaluations. Each aspect emits a customer-facing finding + confidence +
justification + actionable recommendation. NO aggregate-index scoring, NO
multi-axis weighting rubric (Sub-step 0 (D.1) deferred to a future phase).

Preventive-only hallucination control: the prompt embeds AAA-42
`agent_friendly_measurements` + AAA-123 `phase2_html_measurements` ground-truth
and instructs the model not to contradict them. Sub-step 0 measured 0/264
contradictions with this layer alone, so the detective post-hoc cross-check is
NOT shipped (preventive sufficient).

Cost: ~$0.006-0.007/call (Sub-step 0 measured V3 holistic at $0.005-0.0066).
Latency: ~15-26s (Sub-step 0 measured). $0 network beyond the single Gemini
call; consumes the in-memory audit_output (no re-fetch).

Schema-additive forward-only: the orchestrator writes the result to
`audit_output.aaa124_aspect_evaluations`; legacy + failed audits keep None.

Skip-finding contract: on ANY failure (Gemini error, schema-validation fail,
JSON parse error) the function returns (None, 0.0) — the audit and all other
enrichments continue. The caller stores None on the field.
"""
from __future__ import annotations

import json
import logging
import time

from pydantic import BaseModel, Field, ValidationError

from site_profile.gemini_analyzer import _resolve_project, compute_call_cost_usd
from page_analysis.aspect_edu_templates import EDU_TEMPLATES  # AAA-129 S1 WI-1/7

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"
LOCATION = "global"
# AAA-83 S1: pricing now sourced from the central MODEL_PRICING table via
# compute_call_cost_usd(MODEL, ...). Local _RATE_IN/_RATE_OUT removed (they
# were $0.50/$3.00 — the gemini-3-flash-preview rate — under-pricing this
# module's actual gemini-3.5-flash calls by 3x).

ASPECTS = [
    "macro_structure", "heading_semantics", "above_the_fold",
    "micro_semantics", "inline_link_semantics", "forms_conversion_points",
    "schema_entity",
    # AAA-174: text-level semantics — reads the FULL main_content.text (added to
    # the payload) for the content/meaning layer. Completes the 3-layer
    # "tartalmi felépítés" (macro_structure + micro_semantics + this). SCHEMA is
    # deliberately NOT in this aspect's framing (stays in schema_entity / §4.3).
    "text_level_semantics",
]

_ASPECT_FOCUS = {
    "macro_structure": "the page's macro semantic layout (main/nav/header/footer landmarks, section hierarchy, content-to-chrome ratio)",
    "heading_semantics": "the heading hierarchy (h1 presence/uniqueness, h2-h6 nesting, heading-text quality and topic-coverage)",
    "above_the_fold": "the above-the-fold area (hero content, primary CTA, immediate value proposition for the page_type and audience)",
    "micro_semantics": "the micro semantic richness (inline emphasis em/strong, lists, blockquotes, figures, semantic-vs-presentational markup)",
    "inline_link_semantics": "internal/external link quality (descriptive anchor text, rel attributes, target=_blank safety, internal-link depth)",
    "forms_conversion_points": "conversion-point quality (form fields, CTA placement, lead-gen funnel signals relevant to the business_model)",
    "schema_entity": "structured-data presence and fit (JSON-LD, page_type-specific schema types, entity coverage, KG signals)",
    # AAA-174: text-level / content semantics — analyse the ACTUAL CONTENT TEXT
    # (provided in full below), NOT the markup: core topics & sub-topics covered;
    # the concrete claims made; the target audience + search intent the prose
    # serves; topical depth/coverage (covered well vs thin/missing for the page's
    # apparent purpose); internal contradictions (conflicting facts/numbers,
    # leaked/placeholder/wrong-language text); overall coherence. Do NOT assess
    # schema/structured data here (that is schema_entity).",
    "text_level_semantics": "the CONTENT TEXT meaning (covered topics/sub-topics, concrete claims, target audience + search intent, topical depth/coverage vs the page's purpose, internal contradictions, coherence) — analyse the prose, NOT the markup or schema",
}


# ---------------------------------------------------------------------------
# Pydantic output schema (enforced)
# ---------------------------------------------------------------------------
class AspectEvaluation(BaseModel):
    # AAA-129 S1 WI-4: verbosity locked at the Sub-step 0 probe level (3-6
    # sentence findings, step-numbered recommendations) — maxes raised from the
    # AAA-124 terse limits (500/800/500) to fit that depth without filler.
    structured_finding: str = Field(..., min_length=20, max_length=1500)
    confidence_0_1: float = Field(..., ge=0.0, le=1.0)
    justification: str = Field(..., min_length=20, max_length=2000)
    recommendation: str = Field(..., min_length=20, max_length=1500)
    # AAA-129 S1 WI-2: code-injected educational layer (NOT Gemini-emitted),
    # forward-only OPTIONAL so both Gemini output (4 fields only) and legacy
    # archive entries (no edu fields) validate cleanly.
    educational_context: dict | None = None
    educational_context_template_id: str | None = None


class AAA124AspectEvaluations(BaseModel):
    macro_structure: AspectEvaluation
    heading_semantics: AspectEvaluation
    above_the_fold: AspectEvaluation
    micro_semantics: AspectEvaluation
    inline_link_semantics: AspectEvaluation
    forms_conversion_points: AspectEvaluation
    schema_entity: AspectEvaluation
    text_level_semantics: AspectEvaluation  # AAA-174


# Vertex/Gemini response_schema (mirrors the Pydantic shape; the structured
# JSON contract drives the model, Pydantic re-validates the result).
def _gemini_schema() -> dict:
    aspect = {
        "type": "OBJECT",
        "properties": {
            "structured_finding": {"type": "STRING"},
            "confidence_0_1": {"type": "NUMBER"},
            "justification": {"type": "STRING"},
            "recommendation": {"type": "STRING"},
        },
        "required": ["structured_finding", "confidence_0_1",
                     "justification", "recommendation"],
    }
    return {
        "type": "OBJECT",
        "properties": {asp: aspect for asp in ASPECTS},
        "required": list(ASPECTS),
    }


# ---------------------------------------------------------------------------
# Ground-truth summary (preventive anchor)
# ---------------------------------------------------------------------------
def _ground_truth_block(audit_output: dict) -> str:
    """Tight preventive ground-truth block from AAA-42 + AAA-123 measurements.
    Handles AAA-42's actual schema (singular `heading`, `images`,
    landmarks.present list, schema_actions LIST)."""
    afm = audit_output.get("agent_friendly_measurements") or {}
    p2 = audit_output.get("phase2_html_measurements") or {}
    h = afm.get("heading") or {}
    img = afm.get("images") or {}
    lm = afm.get("landmarks") or {}
    sa = afm.get("schema_actions")
    ss = (p2 or {}).get("semantic_structure") or {}
    cut = (p2 or {}).get("google_2mb_cutoff") or {}
    rm = (p2 or {}).get("rendering_mode") or {}

    alt_cov = None
    ic = img.get("img_count") or 0
    if ic:
        alt_cov = round(100.0 * (img.get("alt_count") or 0) / ic, 1)
    present = lm.get("present") or []
    has_main = ("main" in present) if present is not None else None
    schema_count = (len(sa) if isinstance(sa, list)
                    else (sa.get("count") if isinstance(sa, dict) else None))
    spm = ss.get("schema_pagetype_match") or {}

    lines = [
        "GROUND-TRUTH MEASUREMENTS (programmatically measured; authoritative — do NOT contradict):",
        f"  AAA-42 h1_count={h.get('h1_count')}  total_headings={h.get('total_headings')}  level_skips={h.get('level_skips')}",
        f"  AAA-42 alt_coverage_pct={alt_cov}  ({img.get('alt_count')}/{img.get('img_count')} images with alt)",
        f"  AAA-42 has_main={has_main}  landmarks_present={present}",
        f"  AAA-42 schema_actions_count={schema_count}",
        f"  AAA-42 button_count={(afm.get('semantic_html') or {}).get('button_count')}  aria_interactive={(afm.get('aria') or {}).get('interactive_count')}",
        f"  AAA-123 heading_tree_count={ss.get('heading_tree_count')}  list_structure={ss.get('list_structure')}  inline_emphasis={ss.get('inline_emphasis')}",
        f"  AAA-123 raw_html_bytes={cut.get('raw_html_bytes_uncompressed')}  exceeds_2mb={cut.get('exceeds_2mb_cutoff')}",
        f"  AAA-123 is_csr_likely={rm.get('is_csr_likely')}  spa_frameworks={rm.get('spa_frameworks_detected')}",
        f"  AAA-123 schema_pagetype_match={spm.get('match')}  matched_types={spm.get('matched_types')}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AAA-174: full content text + heading outline blocks (for text_level_semantics)
# ---------------------------------------------------------------------------
_MAIN_TEXT_CHARS = 12000  # ~2.7k-3k tokens; full taxually main_content is ~10.7k


def _content_blocks(audit_output: dict) -> tuple[str, str]:
    """Build the CONTENT (full main_content.text) + HEADING OUTLINE blocks.
    The full text is the grounding source the model must verify quoted figures
    against (AAA-174 grounding guard). Missing text -> an explicit absence note
    so the model lowers confidence on text_level_semantics rather than inventing."""
    cr = audit_output.get("crawl") or {}
    mc = cr.get("main_content") or {}
    text = (mc.get("text") or (cr.get("content") or {}).get("visible_text") or "").strip()
    if not text:
        content = ("PAGE CONTENT (full extracted main text): (not available — no "
                   "main_content.text on this audit; do NOT invent content claims, "
                   "and set text_level_semantics confidence low)")
    else:
        truncated = len(text) > _MAIN_TEXT_CHARS
        body = text[:_MAIN_TEXT_CHARS] + ("...[truncated]" if truncated else "")
        content = ("PAGE CONTENT (full extracted main text — the AUTHORITATIVE source "
                   "for any content/claim/quote; verify every quoted figure against "
                   f"THIS text):\n{body}")
    # heading outline
    ss = (audit_output.get("phase2_html_measurements") or {}).get("semantic_structure") or {}
    tree = ss.get("heading_tree") or []
    if tree:
        lines = "\n".join(
            f"  H{h.get('level')} — {h.get('text')}" for h in tree
            if isinstance(h, dict) and h.get("text")
        )
        heading = f"HEADING OUTLINE (H1–H6, in document order):\n{lines}"
    else:
        heading = "HEADING OUTLINE: (not available)"
    return content, heading


def _build_prompt(audit_output: dict) -> str:
    url = audit_output.get("url") or audit_output.get("client_url") or "(unknown)"
    page_type = audit_output.get("page_type")
    business_model = audit_output.get("business_model")
    locality = audit_output.get("locality")
    audience = audit_output.get("audience_relationship_primary")
    topic_domain = audit_output.get("topic_domain")
    sp = audit_output.get("site_profile") or {}
    brand = sp.get("brand_name") or sp.get("brand")
    summary = audit_output.get("summary") or audit_output.get("audit_summary") or ""
    if summary and len(summary) > 1500:
        summary = summary[:1500] + "...[truncated]"
    gt = _ground_truth_block(audit_output)
    content_block, heading_block = _content_blocks(audit_output)  # AAA-174

    aspect_focus_lines = "\n".join(
        f"  - {asp}: {_ASPECT_FOCUS[asp]}" for asp in ASPECTS
    )

    return f"""\
You are an SEO/AEO (Answer-Engine-Optimization) audit expert evaluating ONE
webpage's per-aspect performance. Produce a factual, customer-facing finding for
each of {len(ASPECTS)} aspects.

PAGE CONTEXT:
  url: {url}
  page_type: {page_type}
  business_model: {business_model}
  locality: {locality}
  audience: {audience}
  topic_domain: {topic_domain}
  brand: {brand}

DISCOVERY NARRATIVE (LLM-generated page overview, truncated):
{summary}

{gt}

{content_block}

{heading_block}

THE {len(ASPECTS)} ASPECTS TO EVALUATE:
{aspect_focus_lines}

For EACH aspect emit:
  - structured_finding: a thorough, customer-facing 3-6 sentence factual
    observation about THIS page's performance on this aspect. Ground every
    claim in the measurements and the page context above. Every sentence must
    add information — no filler, no repetition, no padding.
  - confidence_0_1: your own confidence (0.0-1.0) in the finding given the
    available evidence. Lower it when you lack direct evidence for the aspect.
  - justification: rich reasoning that grounds the finding in the page data and
    the specific measurements above.
  - recommendation: a STEP-BY-STEP, concrete, customer-actionable plan. Number
    the steps (1., 2., 3.). Be specific to THIS page — cite its measured values,
    brand, keywords. NEVER generic ("optimize your headings"); a specific action
    ("Add a single descriptive H1 containing the primary keyword; the page
    currently has {{h1_count}} H1 elements").

RULES:
  - Do NOT contradict the GROUND-TRUTH MEASUREMENTS. They are authoritative.
  - GROUNDEDNESS: confine every finding to the PROVIDED measurements, the PAGE
    CONTENT text, and observable page facts. Do NOT invent or assume performance
    data or advice — e.g. CrUX / LCP / CLS / Core Web Vitals thresholds — nor
    framework-specific tips (Next.js, React, etc.) when no such ground-truth is
    supplied above. Not contradicting the data is NOT the same as being grounded
    in it: if you do not have the measurement, do not make the claim.
  - GROUNDING-VERIFICATION (text claims): for text_level_semantics you MAY cite
    topics, claims, contradictions, and quoted phrases — but ONLY from the PAGE
    CONTENT text provided above. Any specific number, statistic, or quoted figure
    you attribute to the page MUST be literally checkable in that text. If a
    figure is not verifiable there, write it as "unverified" (or omit it) rather
    than asserting it as fact. Prefer quoting a short exact fragment as evidence.
  - text_level_semantics analyses the CONTENT/PROSE meaning only — do NOT discuss
    schema.org / JSON-LD / structured data in that aspect (that is schema_entity).
  - TRANSCRIPTION FIDELITY (AAA-180): when you quote or echo any on-page string
    (brand names, headings, testimonial names, any verbatim site text),
    reproduce it CHARACTER-FOR-CHARACTER, preserving every non-ASCII / accented
    character EXACTLY — Hungarian á é í ó ö ő ú ü ű (and uppercase Á É Í Ó Ö Ő Ú
    Ü Ű) and any other diacritics. NEVER normalize, transliterate, drop an
    accent, or substitute a diacritic with a digit or an ASCII look-alike (e.g.
    write "Hungária" and "Rugalmasság" — NOT "Hung1ria" / "Rugalmass1g", not
    "Hungaria" / "Rugalmassag"). If unsure of a character, copy it verbatim from
    the provided text.
  - Calibrate findings to the page_type / business_model / audience context
    (e.g. a product page's schema expectations differ from a news article's).
  - Do NOT explain in general WHY this aspect matters for SEO/AEO — that
    educational context is added separately by the system. Write ONLY about
    THIS page's specific, measured situation (avoids duplicating the template).

Return ONLY structured JSON matching the required schema (all {len(ASPECTS)} aspects).
"""


_client = None


def _get_client():
    global _client
    if _client is None:
        from site_profile.gemini_analyzer import make_genai_client  # AAA-155
        _client = make_genai_client(location=LOCATION)
    return _client


def evaluate_aspects(audit_output: dict) -> tuple[dict | None, float]:
    """Run the V3 holistic per-aspect evaluation. Returns
    (aspect_evaluations_dict | None, cost_usd). Skip-finding: any failure
    yields (None, 0.0) — never raises to the caller."""
    from google.genai import types

    t0 = time.perf_counter()
    try:
        prompt = _build_prompt(audit_output)
        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=_gemini_schema(),
            ),
        )
        latency = round(time.perf_counter() - t0, 3)
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = getattr(um, "candidates_token_count", 0) or 0
        cost = round(compute_call_cost_usd(MODEL, in_tok, out_tok), 8)

        parsed = json.loads(resp.text)
        # Pydantic enforce — raises ValidationError on bad shape
        validated = AAA124AspectEvaluations(**parsed)
        result = validated.model_dump()

        # AAA-129 S1 WI-7: hybrid rendering — deterministically inject the
        # LOCKED educational layer per aspect (code lookup, NO LLM call). The
        # "rich" per-aspect output = Gemini audit-specific fields + this fixed
        # {hu,en} educational_context + its template_id.
        for asp in ASPECTS:
            tpl = EDU_TEMPLATES[asp]
            result[asp]["educational_context"] = tpl["text"]
            result[asp]["educational_context_template_id"] = tpl["template_id"]

        # Attach non-validated meta (kept out of the Pydantic model so the
        # contract stays clean for downstream readers).
        result["_meta"] = {
            "model_id": MODEL,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "latency_s": latency,
            "cost_usd": cost,
            "error": None,
        }
        logger.info("evaluate_aspects: %d/%d aspects, $%.6f, %.1fs",
                    len(ASPECTS), len(ASPECTS), cost, latency)
        return result, cost
    except (ValidationError, json.JSONDecodeError) as e:
        logger.warning("evaluate_aspects: schema/parse fail: %s: %s",
                       type(e).__name__, e)
        return ({"_meta": {"model_id": MODEL,
                           "latency_s": round(time.perf_counter() - t0, 3),
                           "cost_usd": 0.0,
                           "error": f"{type(e).__name__}: {e}"}}, 0.0)
    except Exception as e:  # noqa: BLE001 — never fail the audit
        logger.warning("evaluate_aspects: call failed: %s: %s",
                       type(e).__name__, e)
        return ({"_meta": {"model_id": MODEL,
                           "latency_s": round(time.perf_counter() - t0, 3),
                           "cost_usd": 0.0,
                           "error": f"{type(e).__name__}: {e}"}}, 0.0)
