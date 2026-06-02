"""Single Gemini (Vertex AI) call for the parts heuristics can't do:
brand, industry, audience, entities, and a content-based country read.

Degrades gracefully: if Vertex/credentials are unavailable the function
returns {"available": False, "error": ...} so fusion can fall back to
heuristics-only with reduced confidence instead of crashing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import dotenv_values

# AAA-83 S1 — single production-core MODEL constant. Every core call-site
# (vertex_generate + both ADK agents) reads THIS, never a local literal.
MODEL = "gemini-3-flash-preview"   # single source of truth - Gemini 3 only
LOCATION = "global"                # gemini-3-flash-preview: global endpoint

# AAA-83 S1 — central model-aware pricing table (single source of truth).
# Official Vertex AI rates, USD per 1M tokens (input, output). Thinking tokens
# bill at the OUTPUT rate. Unknown model -> hard fail in compute_call_cost_usd
# (defense-in-depth; we never silently default to a wrong rate).
#   https://cloud.google.com/vertex-ai/generative-ai/pricing
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-3-flash-preview": (0.50, 3.00),   # production-core (this MODEL)
    "gemini-3.5-flash":       (1.50, 9.00),   # fan-out (AAA-80/95) + AAA-124
}
# Flat surcharge per GoogleSearch-grounded call (AAA-80 Sub-step 0.5 estimate).
GROUNDING_SURCHARGE_USD = 0.035


def compute_call_cost_usd(
    model: str, in_tok: int, out_tok: int, grounded: bool = False
) -> float:
    """Model-aware USD cost of a single Gemini call.

    `out_tok` MUST already include thinking tokens (candidates + thoughts) —
    thinking bills at the output rate. Unknown model -> ValueError (hard fail:
    we never silently fall back to a default rate, which is what produced the
    AAA-124 3x mis-pricing this S1 fixes).
    """
    if model not in MODEL_PRICING:
        raise ValueError(
            f"compute_call_cost_usd: unknown model {model!r} — add it to "
            f"MODEL_PRICING (no silent default)."
        )
    rate_in, rate_out = MODEL_PRICING[model]
    cost = in_tok * rate_in / 1_000_000 + out_tok * rate_out / 1_000_000
    if grounded:
        cost += GROUNDING_SURCHARGE_USD
    return cost


def compute_usage_cost_usd(usage_metadata, model: str = MODEL) -> float:
    """USD cost from a Gemini response's usage_metadata (defaults to the
    production-core MODEL). Returns 0.0 if usage_metadata is missing/malformed.

    Gemini 3 exposes `thoughts_token_count` separately (verified live:
    total = prompt + candidates + thoughts); thinking bills at OUTPUT rate, so
    output = candidates + thoughts. Delegates to compute_call_cost_usd."""
    if not usage_metadata:
        return 0.0
    input_tokens = getattr(usage_metadata, "prompt_token_count", 0) or 0
    candidates = getattr(usage_metadata, "candidates_token_count", 0) or 0
    thoughts = getattr(usage_metadata, "thoughts_token_count", 0) or 0
    return compute_call_cost_usd(model, input_tokens, candidates + thoughts)


# Backward-compat aliases (test_agent.py imports these as _IN_PM/_OUT_PM for
# the core audit-cost rollup). Now DERIVED from the central table — same
# values, single source. Expressed as USD-per-1M (callers divide by 1e6).
_GEMINI_3_FLASH_INPUT_USD_PER_1M = MODEL_PRICING[MODEL][0]
_GEMINI_3_FLASH_OUTPUT_USD_PER_1M = MODEL_PRICING[MODEL][1]


# Process-wide token+cost accumulator. Counts only vertex_generate() calls
# (site_profile / keywords / entities / comparison). The ADK Agent model
# turns are counted separately by the runner from event.usage_metadata and
# priced with the same compute_call_cost_usd() helper.
_USAGE = {"prompt": 0, "candidates": 0, "thoughts": 0, "total": 0,
          "calls": 0, "cost": 0.0}


def reset_usage() -> None:
    for k in _USAGE:
        _USAGE[k] = 0 if k != "cost" else 0.0


def get_usage() -> dict:
    return dict(_USAGE)


async def vertex_generate(
    prompt: str,
    temperature: float = 0.0,
    thinking_level: str = "LOW",
    response_mime_type: str = "application/json",
    thinking_budget: int | None = None,
    response_schema=None,
) -> tuple[str | None, str | None, str | None]:
    """Low-level Vertex Gen-AI JSON call shared by every Gemini call site.

    Single model, NO fallback: gemini-3-flash-preview on the GLOBAL endpoint
    with thinking_level (temperature alone is not deterministic for Gemini 3
    due to the internal reasoning step). On HTTP 503 (preview flakiness)
    retries the SAME model up to 3x with exponential backoff; if all retries
    fail the error is returned to the caller (which decides whether to skip
    the URL, log, or surface it). We deliberately do NOT degrade to 2.5 -
    that would contaminate stability metrics and add a second config path.

    Returns (text, model_version, error).
    """
    import asyncio

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        return None, None, f"google-genai not installed: {exc}"

    project = _resolve_project()
    if not project:
        return None, None, "no Vertex project (run gcloud ADC login)"

    location = os.environ.get("GOOGLE_CLOUD_LOCATION") or LOCATION
    try:
        client = genai.Client(
            vertexai=True, project=project, location=location
        )
    except Exception as exc:  # noqa: BLE001
        return None, None, f"client init ({MODEL}@{location}): {exc}"

    # thinking_budget=0 fully disables reasoning (used by translation —
    # CoT adds no value there and was ~66% of the cost). When None, behaviour
    # is unchanged for every existing caller (thinking_level path).
    _think = (
        types.ThinkingConfig(thinking_budget=thinking_budget)
        if thinking_budget is not None
        else types.ThinkingConfig(thinking_level=thinking_level)
    )
    # response_schema (optional): a Pydantic model / type for Gemini
    # structured output. None -> unchanged for every existing caller.
    _cfg_kw = dict(
        temperature=temperature,
        response_mime_type=response_mime_type,
        thinking_config=_think,
    )
    if response_schema is not None:
        _cfg_kw["response_schema"] = response_schema
    cfg = types.GenerateContentConfig(**_cfg_kw)
    delay = 2.0
    last_err = "unknown error"
    for attempt in range(3):
        try:
            resp = await client.aio.models.generate_content(
                model=MODEL, contents=prompt, config=cfg
            )
            um = getattr(resp, "usage_metadata", None)
            if um is not None:
                _USAGE["prompt"] += getattr(um, "prompt_token_count", 0) or 0
                _USAGE["candidates"] += (
                    getattr(um, "candidates_token_count", 0) or 0
                )
                _USAGE["thoughts"] += (
                    getattr(um, "thoughts_token_count", 0) or 0
                )
                _USAGE["total"] += getattr(um, "total_token_count", 0) or 0
                _USAGE["calls"] += 1
                _USAGE["cost"] += compute_usage_cost_usd(um)
            return resp.text, getattr(resp, "model_version", MODEL), None
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            last_err = f"{type(exc).__name__}@{MODEL}: {msg[:200]}"
            if "503" in msg and attempt < 2:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            break  # non-retryable, or retries exhausted -> bubble up
    return None, None, last_err


_PROMPT = """\
CRITICAL - DO NOT FABRICATE NAMES:
- If a person's name is explicitly present in the provided content \
(main_content, brand_context.json_ld_entities, brand_context.meta_author, \
brand_context.footer_text), use that exact name.
- If no person's name is explicitly present, state the owner/author as \
"unnamed" or "not specified on page".
- NEVER expand initials (e.g. "KK", "JD") into a full name. NEVER infer a \
name from a domain (e.g. "kk.coach" -> "Kevin Kwok"). NEVER invent a \
plausible-sounding name.
- Same rule for company names, dates and statistics: if not in the source, \
mark as "unknown" rather than guess.

CRITICAL - PROVENANCE CONSTRAINT:
Every named entity (product, technology, framework, brand, person, place, \
organization) you mention in your output MUST appear verbatim in the provided \
source content above - which includes the main article content, brand \
metadata (JSON-LD entities, meta tags, Twitter/OG tags, footer, address), \
schema types, and the site profile fields.

If a named entity does not appear in any of these sources, do one of the \
following:
1. Omit it entirely, OR
2. Refer to it generically (e.g., "their deployment platform" instead of \
"Next.js", "the founder" instead of an invented name).

Do not pattern-match from domain names, brand initials, or general industry \
knowledge. If you cannot identify something specifically from the provided \
sources, that absence is itself useful information for the audit - surface it \
as "not identifiable from public-facing content" rather than guessing.

You are analyzing a website to determine its profile.

=== PRIMARY SIGNALS (these usually state the business most clearly - weigh \
them heavily) ===
Page title: {title}
Meta description: {meta_description}

=== BRAND CONTEXT (identity signals - authoritative for brand/owner name) ===
{brand_context}

=== SITE METADATA ===
URL: {final_url}
TLD: {tld}
Hreflang values: {hreflang_list}
Schema.org types detected: {schema_types}
Phone prefixes found in HTML: {phone_prefixes}
Currencies found: {currencies}
Heuristic candidates for target country: {heuristic_candidates}

=== MAIN PAGE CONTENT ({content_source}, first 3000 chars) ===
{main_content_text}

Based on this information, determine:

1. PRIMARY LANGUAGE of this website (ISO 639-1 code, e.g., "en", "de", "hu")
2. PRIMARY TARGET COUNTRY (one country from this list): Hungary, Germany, \
Austria, Switzerland, United Kingdom, United States, Canada, Australia, \
Ireland, Italy, France, Spain, Netherlands, Belgium, Czech Republic, Poland, \
Romania, Croatia, or "AMBIGUOUS" if you cannot determine.
3. BRAND/ORGANIZATION NAME (the company name behind this site)
4. INDUSTRY (one short phrase describing the vertical and business model; \
neutral format examples only: "professional services consultancy", "online \
retail marketplace", "enterprise software vendor", "industrial \
manufacturing" - do NOT bias toward these, infer the actual industry from \
the content above)
5. TARGET AUDIENCE: "B2B" or "B2C" or "Both"
6. MAIN ENTITIES mentioned at site level (companies, products lines, \
locations, key people - max 5)

Return ONLY valid JSON in this exact format:
{{
  "language": "...",
  "location": "...",
  "brand": "...",
  "industry": "...",
  "audience": "...",
  "main_entities": ["...", "..."],
  "confidence_self_assessment": 0.0,
  "reasoning": "Brief explanation of your decisions, especially anything \
uncertain"
}}
"""

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_project() -> str | None:
    """Project from env, else .env, else the ADC quota project."""
    env = dotenv_values(PROJECT_ROOT / ".env")
    proj = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or env.get("GOOGLE_CLOUD_PROJECT")
    )
    if proj:
        return proj
    adc = Path(os.path.expanduser(
        "~/AppData/Roaming/gcloud/application_default_credentials.json"
    ))
    if not adc.exists():  # POSIX fallback
        adc = Path(os.path.expanduser(
            "~/.config/gcloud/application_default_credentials.json"
        ))
    if adc.exists():
        try:
            return json.loads(adc.read_text()).get("quota_project_id")
        except (ValueError, OSError):
            return None
    return None


def _select_content(crawl_result: dict) -> tuple[str, str]:
    """Pick the cleanest body text to send to Gemini.

    Default: main_content.text (article/section only - nav/menus/footer
    stripped, far better for industry classification than full visible text).

    Fallback: if main_content extraction confidence < 0.5 the extractor used
    a weak strategy (e.g. fallback_full_body on a JS shell) and its text may
    be unreliable/empty - in that case use content.visible_text instead.
    Returns (text, source_label) where the label is shown in the prompt.
    """
    mc = crawl_result.get("main_content") or {}
    conf = mc.get("confidence")
    mc_text = mc.get("text") or ""
    if isinstance(conf, (int, float)) and conf < 0.5:
        visible = (crawl_result.get("content") or {}).get("visible_text") or ""
        chosen = visible or mc_text
        return chosen[:3000], (
            f"full visible text; main_content confidence "
            f"{conf} < 0.5 so extraction was unreliable"
        )
    return mc_text[:3000], "extracted main article/body content"


def _format_brand_context(bc: dict) -> str:
    if not bc:
        return "(no brand context extracted)"
    ents = bc.get("json_ld_entities") or []
    lines = []
    if ents:
        lines.append("json_ld_entities:")
        for e in ents:
            extra = " ".join(
                f"{k}={e[k]}" for k in ("url", "sameAs", "founder", "author")
                if e.get(k)
            )
            lines.append(
                f'  - type={e.get("type")} name="{e.get("name")}"'
                + (f" {extra}" if extra else "")
            )
    else:
        lines.append("json_ld_entities: [none]")
    lines.append(f'meta_author: {bc.get("meta_author") or "[none]"}')
    lines.append(f'og_site_name: {bc.get("og_site_name") or "[none]"}')
    lines.append(f'og_title: {bc.get("og_title") or "[none]"}')
    lines.append(f'twitter_creator: {bc.get("twitter_creator") or "[none]"}')
    lines.append(f'footer_text: {bc.get("footer_text") or "[none]"}')
    lines.append(f'address_text: {bc.get("address_text") or "[none]"}')
    return "\n".join(lines)


def _build_prompt(crawl_result: dict, heur: dict) -> str:
    meta = crawl_result.get("meta") or {}
    loc = heur["location_hints"]
    main_content_text, content_source = _select_content(crawl_result)
    brand_context_str = _format_brand_context(
        crawl_result.get("brand_context") or {}
    )
    cand = [
        c
        for c in (
            loc["tld_country"],
            *loc["hreflang_countries"],
            loc["path_prefix_country"],
            *[p["country"] for p in loc["phone_prefixes"]],
            loc["schema_address_country"],
        )
        if c
    ]
    return _PROMPT.format(
        final_url=crawl_result.get("url", ""),
        tld=loc["tld"],
        title=meta.get("title", {}).get("text", ""),
        meta_description=meta.get("description", {}).get("text", "") or "[none]",
        main_content_text=main_content_text or "[none]",
        content_source=content_source,
        brand_context=brand_context_str,
        hreflang_list=[
            e.get("hreflang") for e in (crawl_result.get("i18n") or {}).get(
                "hreflang", []
            )
        ]
        or "[none]",
        schema_types=(crawl_result.get("schema_markup") or {}).get(
            "schema_types_detected", []
        ),
        phone_prefixes=[p["prefix"] for p in loc["phone_prefixes"]] or "[none]",
        currencies=loc["currencies_found"] or "[none]",
        heuristic_candidates=list(dict.fromkeys(cand)) or "[none]",
    )


def _parse(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1:
        text = text[s : e + 1]
    return json.loads(text)


async def gemini_site_analysis(crawl_result: dict, heuristic_signals: dict) -> dict:
    # Site-profile is simple classification -> thinking_level LOW, temp 0.
    text, model_version, err = await vertex_generate(
        _build_prompt(crawl_result, heuristic_signals),
        temperature=0.0,
        thinking_level="LOW",
    )
    if err or text is None:
        return {"available": False, "error": err or "empty response"}
    try:
        data = _parse(text)
    except Exception as exc:  # noqa: BLE001 - parse failure
        return {"available": False,
                "error": f"parse failed: {type(exc).__name__}: {exc}"}

    data["available"] = True
    data["_model_version"] = model_version
    return data
