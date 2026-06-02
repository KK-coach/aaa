"""AAA-95 Sub-step 2.1 — fan-out query coverage classifier.

For each AAA-95 Sub-step 1 variant-tagged fan-out query, judges whether the
landing page COVERS that query (covered / partial / missing / off_topic /
n_a) and, for missing/partial, emits a concrete actionable suggestion.
Prompt is verbatim from Sub-step 2.0.1 (strict-match 92%, missing-tier
2/2, 100% determinism on the n=12 probe).

Model gemini-3.5-flash @ global; one call per query (per-query mode —
batched HALT-ed in Phase E for 67% determinism). Per-query skip-finding:
an exception yields coverage=None + _meta.coverage_error, batch continues.
Cost is SEPARATE (audit_fan_out_coverage_cost_usd, AAA-53).

Schema-additive: each input entry's query/source/variant_type and its
original _meta are preserved verbatim; only `coverage`, `suggestion`, and
`_meta.coverage_*` keys are ADDED.

FORWARD-COMPAT:
  - AAA-98: if an entry arrives with variant_type=None AND
    _meta.reason=="identity_skip" (identity-query skip, AAA-98 — Low-prio
    To Do at time of writing), coverage classification is skipped too:
    coverage=None, _meta.coverage_skip_reason="identity_query_skipped".
  - AAA-94: `coverage` is a single str now; a future multi-section
    coverage may make it list[str] — downstream readers should tolerate
    both (e.g. read coverage[0] with a str fallback).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from site_profile.gemini_analyzer import _resolve_project, compute_call_cost_usd

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"
LOCATION = "global"
# AAA-83 S1: pricing sourced from central MODEL_PRICING via
# compute_call_cost_usd(MODEL, ...). Local _RATE_IN/_RATE_OUT removed
# (were 3-flash-preview rates, under-pricing 3.5-flash calls 3x).
_COVERAGE_ENUM = ["covered", "partial", "missing", "off_topic", "n_a"]
_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "coverage": {"type": "STRING", "enum": _COVERAGE_ENUM},
        "suggestion": {"type": "STRING", "nullable": True},
    },
    "required": ["coverage", "suggestion"],
}

# Verbatim Sub-step 2.0.1 prompt.
_PROMPT = """\
You are analyzing whether a landing page's content covers a specific search query
that an AI search engine (Google AI Overview or ChatGPT) generated as a follow-up
or variant of the user's target keyword.

Target keyword (what the landing page is optimized for): {target_keyword}
Search query to evaluate: {fan_out_query}
Query variant type: {variant_type}

Landing page summary (LLM-generated overview):
---
{landing_page_summary}
---

Landing page main content (raw extracted text):
---
{landing_page_body}
---

Classify the coverage of this query by the landing page into EXACTLY ONE of:

- covered — the landing page explicitly and directly answers this query;
  a reader would find the information without searching elsewhere
- partial — the landing page touches the topic with substantive but incomplete
  information; a reader could partially deduce or partially act on it
- missing — the page does not address the query topic. Mere mention of related
  concepts does NOT constitute coverage. A services page that LISTS a topic as
  one of its services (e.g., "AI Overview optimization" as a service offering)
  does NOT cover a query asking ABOUT that topic (e.g., "current trends in
  AI Overview"). Coverage means the page provides the actual information the
  query seeks, not just acknowledges the topic exists.
- off_topic — the query topic is outside the landing page's domain/purpose;
  this query belongs on a different page of the website, not this one
- n_a — you cannot determine coverage with confidence (genuine ambiguity,
  conflicting signals, or insufficient information to decide)

If coverage is "missing" or "partial", provide a concrete, actionable suggestion
in the SAME LANGUAGE as the landing page (Hungarian or English) describing what
to add or expand. Be specific: name the information type, the suggested location
on the page, and the rationale.

If coverage is "covered", "off_topic", or "n_a", suggestion MUST be null.

Examples:
- target: "VAT compliance software", query: "VAT compliance software pricing",
  page has no pricing section → coverage=missing,
  suggestion="Add a pricing section with indicative monthly subscription tiers
  and a 'Request a quote' CTA — pricing transparency is a key purchase signal
  for B2B SaaS evaluation queries."
- target: "marketing ügynökség Budapest", query: "marketing ügynökség Pécs",
  page is Budapest-only → coverage=off_topic, suggestion=null
- target: "organic growth consultant", query: "organic growth consulting trends",
  page is services-oriented and mentions "AI Overview emergence" only as a
  service area → coverage=missing (the page lists the topic as a service,
  but does NOT provide trend content),
  suggestion="Add a 'Current trends in organic growth' insights or blog section
  with industry-trend articles, separate from the services offering — the
  services page acknowledges these topics exist as offerings, but provides no
  trend content."

Return ONLY structured JSON.
"""

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(
            vertexai=True, project=_resolve_project(), location=LOCATION
        )
    return _client


def _classify_one(target_keyword: str, entry: dict, summary: str,
                  body: str) -> dict:
    """Classify one entry's coverage. Returns the entry with coverage +
    suggestion + _meta.coverage_* added. Per-query skip-finding."""
    from google.genai import types

    out = dict(entry)
    meta = dict(entry.get("_meta") or {})

    # AAA-98 forward-compat: identity-skipped queries skip coverage too.
    if (entry.get("variant_type") is None
            and meta.get("reason") == "identity_skip"):
        out["coverage"] = None
        out["suggestion"] = None
        meta["coverage_skip_reason"] = "identity_query_skipped"
        out["_meta"] = meta
        return out

    prompt = _PROMPT.format(
        target_keyword=target_keyword,
        fan_out_query=entry.get("query") or "",
        variant_type=entry.get("variant_type"),
        landing_page_summary=summary or "",
        landing_page_body=body or "",
    )
    t0 = time.perf_counter()
    try:
        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=_SCHEMA,
            ),
        )
        latency = round(time.perf_counter() - t0, 3)
        parsed = json.loads(resp.text)
        cov = parsed.get("coverage")
        if cov not in _COVERAGE_ENUM:
            raise ValueError(f"out-of-enum coverage: {cov!r}")
        sug = parsed.get("suggestion")
        if cov not in ("missing", "partial"):
            sug = None  # contract: suggestion only for missing/partial
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = getattr(um, "candidates_token_count", 0) or 0
        cost = round(compute_call_cost_usd(MODEL, in_tok, out_tok), 8)
        out["coverage"] = cov
        out["suggestion"] = sug
        meta.update({
            "coverage_input_tokens": in_tok,
            "coverage_output_tokens": out_tok,
            "coverage_latency_s": latency,
            "coverage_cost_usd": cost,
            "coverage_model_id": MODEL,
            "coverage_error": None,
        })
        out["_meta"] = meta
        return out
    except Exception as e:  # noqa: BLE001 — per-query skip-finding
        logger.warning(
            "analyze_fan_out_coverage: %r failed: %s: %s",
            entry.get("query"), type(e).__name__, e,
        )
        out["coverage"] = None
        out["suggestion"] = None
        meta.update({
            "coverage_input_tokens": 0, "coverage_output_tokens": 0,
            "coverage_latency_s": round(time.perf_counter() - t0, 3),
            "coverage_cost_usd": 0.0, "coverage_model_id": MODEL,
            "coverage_error": f"{type(e).__name__}: {e}",
        })
        out["_meta"] = meta
        return out


async def analyze_fan_out_coverage(
    target_keyword: str,
    fan_out_enriched: list[dict],
    landing_page_summary: str,
    landing_page_body: str,
) -> tuple[list[dict], float]:
    """Add coverage + suggestion to each fan-out entry. Returns
    (enriched_with_coverage, total_cost_usd). Schema-additive; per-query
    skip-finding contract."""
    if not (target_keyword or "").strip() or not fan_out_enriched:
        return list(fan_out_enriched or []), 0.0

    enriched: list[dict] = []
    for entry in fan_out_enriched:
        result = await asyncio.to_thread(
            _classify_one, target_keyword, entry,
            landing_page_summary, landing_page_body,
        )
        enriched.append(result)

    total_cost = round(
        sum((e.get("_meta") or {}).get("coverage_cost_usd", 0.0)
            for e in enriched), 8
    )
    return enriched, total_cost
