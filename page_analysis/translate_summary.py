"""AAA-61 Sub-step 3 — symmetric HU<->EN translation of the audit summary.

Production-grade: the Validation UI (AAA-3c) renders these to end users in
their browser language, so the bar is publishable quality, not
"good-enough-for-similarity-search". Technical SEO terms stay English in
BOTH directions; markdown structure is byte-preserved; no commentary added.

One vertex_generate call (temperature=0, thinking_level=LOW). Cost is
accrued into the shared _USAGE accumulator; the caller isolates the delta
into a SEPARATE audit_translation_cost_usd (AAA-53 pattern). NOT retried —
a translation failure is non-critical (graceful degradation: the audit
still succeeds, that language entry is skipped).
"""

from __future__ import annotations

import logging

from site_profile.gemini_analyzer import get_usage, vertex_generate

logger = logging.getLogger(__name__)

# Phase 1 supported language pairs (dict shape supports future DE/ES/...).
_LANG_NAME = {"hu": "Hungarian", "en": "English"}
_SUPPORTED = set(_LANG_NAME)

# Verbatim mirror of the preserve list — used by translate AND by the
# smoke's explicit technical-term drift grep.
TECHNICAL_TERMS = (
    "schema markup", "canonical", "meta description", "H1", "H2", "H3",
    "sitemap", "robots.txt", "internal linking", "main content", "alt tags",
    "noscript", "JSON-LD", "Open Graph", "Twitter Cards", "CDN", "TTFB",
    "Core Web Vitals", "indexing", "SERP", "AI Overview",
)

_PROMPT = """\
Translate this SEO audit summary from {src_name} to natural professional \
{tgt_name}.

PRESERVE:
- Markdown structure (headers, bold, lists, code blocks) - byte-equivalent
- Blockquotes: `> text` markers including multi-line blockquotes \
(and `> > nested` if present) - line-by-line preservation
- All proper nouns (URLs, brand names, person names, product names) verbatim
- Technical SEO terms in English: "schema markup", "canonical", "meta \
description", "H1/H2/H3", "sitemap", "robots.txt", "internal linking", \
"main content", "alt tags", "noscript", "JSON-LD", "Open Graph", \
"Twitter Cards", "CDN", "TTFB", "Core Web Vitals", "indexing", "SERP", \
"AI Overview" - these stay English in BOTH directions
- Numbers, percentages, metrics unchanged
- Section dividers (---, ##) intact
- Inline code (`backticks`) unchanged

PROFESSIONAL TONE:
- Match the register of an SEO consultant report
- Avoid touristic phrasing or literal translation
- Use natural professional terminology in the target language

AVOID:
- Adding interpretation or commentary
- Reorganizing the structure or merging sections
- Simplifying or expanding the content
- Translating technical SEO terms (see preserve list above)

INPUT ({src_name}):
{summary}

Return ONLY the {tgt_name} translation. No preamble, no explanation, no \
"Here is the translation:" prefix.
"""


async def translate_summary(
    summary_markdown: str,
    source_language: str,
    target_language: str,
    thinking_level: str | None = None,
) -> tuple[str | None, str | None, float]:
    """Returns (translated_text, _model_version, cost_usd).

    - source == target            -> identity copy, no Gemini call, cost 0.0
    - unsupported language pair    -> (None, None, 0.0)  [Phase 1 scope]
    - Gemini failure               -> (None, model_version, cost)  [non-crit]

    thinking_level (AAA-130 S2): when set (e.g. "LOW"), enables Gemini thinking
    instead of the legacy thinking_budget=0. AAA-83 S0 found budget=0 makes 3.5
    return the EN source verbatim (translation no-op, 33% on long inputs);
    LOW fixes it. None -> legacy budget=0 (unchanged for any other caller).
    """
    src = (source_language or "").lower()
    tgt = (target_language or "").lower()

    if src == tgt:
        return summary_markdown, None, 0.0
    if src not in _SUPPORTED or tgt not in _SUPPORTED:
        return None, None, 0.0
    if not (summary_markdown or "").strip():
        return None, None, 0.0

    prompt = _PROMPT.format(
        src_name=_LANG_NAME[src],
        tgt_name=_LANG_NAME[tgt],
        summary=summary_markdown,
    )
    cost_before = get_usage().get("cost", 0.0)
    if thinking_level:
        # AAA-130 S2: thinking enabled (translate reliability on 3.5).
        text, model_version, err = await vertex_generate(
            prompt, temperature=0.0,
            response_mime_type="text/plain",
            thinking_level=thinking_level,
        )
    else:
        # Legacy (AAA-61 S3 Issue A): CoT adds no value on 3-preview.
        text, model_version, err = await vertex_generate(
            prompt, temperature=0.0,
            response_mime_type="text/plain",
            thinking_budget=0,
        )
    cost = round(get_usage().get("cost", 0.0) - cost_before, 6)

    if err or not text or not text.strip():
        logger.warning(
            "translate_summary %s->%s failed (err=%s) — skipping entry",
            src, tgt, err,
        )
        return None, model_version, cost
    return text.strip(), model_version, cost
