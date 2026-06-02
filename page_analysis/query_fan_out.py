"""AAA-80 Sub-step 1 — query fan-out detection via Gemini 3.5 Flash +
GoogleSearch grounding (the actual queries Google's AI Mode fans out for a
target keyword).

Sub-step 0.5/0.6 verified: gemini-3.5-flash on Vertex `global`, the
google-genai SDK pattern `types.Tool(google_search=types.GoogleSearch())`
returns `response.candidates[0].grounding_metadata.web_search_queries`
populated and language-correct, ~8s latency, ~$0.0004 token cost. Note the
Sub-step 0.6 observation that Search applies diacritic normalization
(`ü→u`, `ö→o`) — returned verbatim, no further normalization here.

Skip-finding contract (AAA-56 family): any error -> ([], 0.0) + WARN log;
the audit continues. A successful call with an empty list is preserved
verbatim as ([], cost_paid).

Cost field is SEPARATE (`audit_fan_out_cost_usd`, AAA-53 separation
pattern) — NEVER aggregated into `audit_cost_usd`. The call does NOT route
through `vertex_generate`, so the shared `_USAGE` accumulator is
untouched by design.

Pricing assumption (flagged): exact gemini-3.5-flash Vertex token rates
not looked up here; using gemini-3-flash-preview rates ($0.50/$3.00 per
1M in/out) as a working assumption + a $0.035 flat grounding surcharge
(Sub-step 0.5 estimate). Even if rates differ by 2x, per-call cost stays
well below the $0.10 stop threshold and the spec's order-of-magnitude
expectation.
"""

from __future__ import annotations

import logging
import os

from site_profile.gemini_analyzer import _resolve_project, compute_call_cost_usd

logger = logging.getLogger(__name__)

MODEL = "gemini-3.5-flash"
LOCATION = "global"  # AAA-62; mirrors agent.py hard-set
# AAA-83 S1: pricing + grounding surcharge sourced from central MODEL_PRICING
# via compute_call_cost_usd(MODEL, ..., grounded=True). Local rate constants
# removed (were 3-flash-preview rates, under-pricing 3.5-flash calls 3x; the
# $0.035 grounding surcharge now lives in gemini_analyzer.GROUNDING_SURCHARGE_USD).

# Lazy singleton — vertexai/genai client is process-wide.
_client = None


def _get_client():
    global _client
    if _client is None:
        # Local import keeps module import-light and matches gemini_analyzer.
        from google import genai

        project = _resolve_project()
        # AAA-62 hard-set guarantees global, but be explicit + tolerant.
        location = os.environ.get("GOOGLE_CLOUD_LOCATION") or LOCATION
        _client = genai.Client(vertexai=True, project=project, location=location)
    return _client


async def detect_query_fan_out(target_keyword: str) -> tuple[list[str], float]:
    """Detect Google AI-Mode fan-out queries for one target keyword.

    Returns (fan_out_queries, cost_usd). Skip-finding contract: any error
    -> ([], 0.0) + WARN; never raises.
    """
    kw = (target_keyword or "").strip()
    if not kw:
        return [], 0.0

    try:
        import asyncio

        from google.genai import types

        client = _get_client()
        prompt = (
            f"Search the web for the latest information about: {kw}. "
            "Summarize the 3 most relevant findings in 2-3 sentences total."
        )
        cfg = types.GenerateContentConfig(
            temperature=0.0,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        def _call():
            return client.models.generate_content(
                model=MODEL, contents=prompt, config=cfg
            )

        resp = await asyncio.to_thread(_call)
    except Exception as e:  # noqa: BLE001 — skip-finding contract
        logger.warning(
            "detect_query_fan_out(%r) failed: %s: %s — returning ([], 0.0)",
            kw, type(e).__name__, e,
        )
        return [], 0.0

    try:
        cand = (resp.candidates or [None])[0]
        gm = getattr(cand, "grounding_metadata", None) if cand else None
        queries = list(getattr(gm, "web_search_queries", None) or []) if gm else []
        um = getattr(resp, "usage_metadata", None)
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = getattr(um, "candidates_token_count", 0) or 0
        cost = round(
            compute_call_cost_usd(MODEL, in_tok, out_tok, grounded=True),
            6,
        )
        # Filter empty strings (Sub-step 0.6 observed ''-anomaly on
        # 3-flash-preview; not seen on 3.5 but defensive).
        queries = [q for q in queries if q and q.strip()]
        return queries, cost
    except Exception as e:  # noqa: BLE001 — preserve skip-finding contract
        logger.warning(
            "detect_query_fan_out parse failed: %s: %s", type(e).__name__, e
        )
        return [], 0.0
