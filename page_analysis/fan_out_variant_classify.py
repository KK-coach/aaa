"""AAA-95 Sub-step 1 — query fan-out variant_type classifier.

Classifies each fan-out query (from AAA-80 Google-grounded fan-out and
AAA-86 ChatGPT fan-out) into one of the 8 transformation types defined by
Google patent US11663201B2. Prompt + enum schema are verbatim from the
AAA-95 Sub-step 0.5 probe (93.8% accuracy / 100% determinism on n=16).

Model: gemini-3.5-flash @ location=global (matches AAA-80/AAA-86). One
Gemini call per query (Sub-step 0.5 measured this form). Cost is SEPARATE
(audit_fan_out_enrichment_cost_usd, AAA-53 separation) — never folded into
audit_cost_usd.

Skip-finding contract: a per-query exception does NOT abort the batch —
that entry gets variant_type=None, _meta.error set, cost 0; the remaining
queries are still classified.

FORWARD-COMPAT (AAA-94): the enriched entry schema is designed so a future
`variant_types: list[str]` (multi-label) field can sit beside the current
single `variant_type: str`. Phase 1 writes ONLY `variant_type` (single).
Downstream readers MUST tolerate the absence of `variant_types`.
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

VARIANT_TYPES = (
    "equivalent", "follow_up", "generalization", "canonicalization",
    "language_translation", "entailment", "specification", "clarification",
)
_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "variant_type": {"type": "STRING", "enum": list(VARIANT_TYPES)}
    },
    "required": ["variant_type"],
}

# Verbatim Sub-step 0.5 prompt.
_PROMPT_TEMPLATE = """\
You are classifying a search query variant according to Google patent
US11663201B2, which defines 8 transformation types that a query fan-out
system can apply.

Original query: {original_keyword}
Fan-out variant: {fan_out_query}

Classify the variant into EXACTLY ONE of these types:

1. equivalent — same meaning, different wording (paraphrase, synonym substitution)
2. follow_up — a logical next question that builds on the original
3. generalization — broader scope (less specific than original)
4. canonicalization — standardized form (diacritic normalization, lemmatization,
   capitalization, orthographic variants of the same underlying query)
5. language_translation — same meaning in a different language
6. entailment — a logical consequence or implication of the original
7. specification — narrower scope (adds qualifier, time, location, superlative)
8. clarification — asks for disambiguation or refinement

Examples:
- "climate change" → "climate change effects on coastal cities 2025" = specification
- "best Italian restaurants in Manhattan" → "best restaurants in New York City"
  = generalization
- "did leonardo da vinci paint mona lisa"
  → "who commissioned leonardo da vinci to paint the mona lisa" = follow_up
- "marketing ügynökség Budapest" → "marketing ugynokseg Budapest" = canonicalization
- "marketing ugynokseg Budapest"
  → "legjobb marketing ugynokseg Budapest 2025 2026" = specification

If the variant could fit multiple types, pick the DOMINANT transformation.
Return ONLY the type name.
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


def _classify_one(target_keyword: str, query: str, source: str) -> dict:
    """One Gemini call. Skip-finding: exception -> variant_type=None +
    _meta.error; cost 0 for this entry."""
    from google.genai import types

    prompt = _PROMPT_TEMPLATE.format(
        original_keyword=target_keyword, fan_out_query=query
    )
    t0 = time.perf_counter()
    try:
        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
            ),
        )
        latency = round(time.perf_counter() - t0, 3)
        vt = json.loads(resp.text).get("variant_type")
        if vt not in VARIANT_TYPES:
            raise ValueError(f"out-of-enum variant_type: {vt!r}")
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = getattr(um, "candidates_token_count", 0) or 0
        cost = round(compute_call_cost_usd(MODEL, in_tok, out_tok), 8)
        return {
            "query": query, "source": source, "variant_type": vt,
            "_meta": {
                "input_tokens": in_tok, "output_tokens": out_tok,
                "latency_s": latency, "cost_usd": cost,
                "model_id": MODEL, "error": None,
            },
        }
    except Exception as e:  # noqa: BLE001 — per-query skip-finding
        logger.warning(
            "classify_fan_out_variants: %r failed: %s: %s",
            query, type(e).__name__, e,
        )
        return {
            "query": query, "source": source, "variant_type": None,
            "_meta": {
                "input_tokens": 0, "output_tokens": 0,
                "latency_s": round(time.perf_counter() - t0, 3),
                "cost_usd": 0.0, "model_id": MODEL,
                "error": f"{type(e).__name__}: {e}",
            },
        }


async def classify_fan_out_variants(
    target_keyword: str,
    fan_out_queries: list[dict],
) -> tuple[list[dict], float]:
    """Classify each fan-out query's variant_type. Returns
    (enriched_list, total_cost_usd). fan_out_queries items are
    {"query": str, "source": str}. Per-query skip-finding contract.
    """
    if not (target_keyword or "").strip() or not fan_out_queries:
        return [], 0.0

    enriched: list[dict] = []
    for item in fan_out_queries:
        q = (item or {}).get("query")
        src = (item or {}).get("source") or "unknown"
        if not q or not str(q).strip():
            continue
        entry = await asyncio.to_thread(
            _classify_one, target_keyword, str(q), src
        )
        enriched.append(entry)

    total_cost = round(
        sum(e["_meta"]["cost_usd"] for e in enriched), 8
    )
    return enriched, total_cost
