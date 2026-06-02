"""Shared Gemini plumbing + body-text selection for page_analysis.

Reuses site_profile.gemini_analyzer's Vertex project resolution and JSON
parsing so there is exactly one place that knows how to reach Vertex.
"""

from __future__ import annotations

from site_profile.gemini_analyzer import _parse, vertex_generate

# Below this word count the page body is too thin for reliable page-level
# analysis (e.g. JS shells like vercel.com served as ~100 words of raw HTML).
THIN_CONTENT_WORDS = 120


def select_body(crawl_result: dict, limit: int) -> dict:
    """Choose the cleanest body text and report whether it's usably thick.

    Default: main_content.text (nav/footer stripped). Fallback: when the
    extractor used a weak strategy (confidence < 0.5) its text is unreliable,
    so use content.visible_text instead. Returns text + provenance + a
    `thin` flag the callers surface to recommend Playwright escalation.
    """
    mc = crawl_result.get("main_content") or {}
    conf = mc.get("confidence")
    method = mc.get("extraction_method")
    mc_text = mc.get("text") or ""
    mc_words = mc.get("words") or len(mc_text.split())

    if (isinstance(conf, (int, float)) and conf < 0.5) or mc_words < 50:
        visible = (crawl_result.get("content") or {}).get("visible_text") or ""
        chosen = visible or mc_text
        source = (
            f"full visible_text (main_content confidence {conf} unreliable)"
        )
    else:
        chosen = mc_text
        source = "extracted main_content"

    words = len(chosen.split())
    # A `fallback_full_body` extraction means no <main>/<article>/role/known
    # container was found - typical of JS shells. Even when visible_text has
    # >120 words it's nav/label soup, not prose, so force thin=True to signal
    # the Discovery agent to escalate to a Playwright re-crawl.
    is_fallback = method == "fallback_full_body"
    return {
        "text": chosen[:limit],
        "source": source,
        "word_count": words,
        "thin": words < THIN_CONTENT_WORDS or is_fallback,
    }


# AAA-51 T2: final-content grounding threshold (read-only over AAA-18 signals).
GROUNDING_MIN_WORDS = 200


def compute_grounding_confidence(crawl: dict) -> str:
    """Compound rule (AAA-22-approved): 'low' if the final content the
    synthesis calls actually received is too thin to ground entity claims,
    else 'high'. Does NOT modify AAA-18 escalation - only reads its signals.

      low  if  final_words < 200
            OR  main_content.extraction_method == 'fallback_full_body'
            OR  main_content.confidence < 0.5
      high otherwise
    """
    if not crawl or crawl.get("error"):
        return "low"
    body = select_body(crawl, 3000)
    mc = crawl.get("main_content") or {}
    conf = mc.get("confidence")
    if (
        body["word_count"] < GROUNDING_MIN_WORDS
        or mc.get("extraction_method") == "fallback_full_body"
        or (isinstance(conf, (int, float)) and conf < 0.5)
    ):
        return "low"
    return "high"


async def generate_json(
    prompt: str,
    temperature: float = 0.0,
    thinking_level: str = "LOW",
) -> dict:
    """Single Vertex Gemini-3 JSON call (shared by keywords/entities/compare).

    thinking_level: "LOW" for classification/extraction (default),
    "MEDIUM" for deeper reasoning (e.g. competitor comparison).
    Never raises: returns {"_error": str} on any failure.
    """
    text, model_version, err = await vertex_generate(
        prompt, temperature=temperature, thinking_level=thinking_level
    )
    if err or text is None:
        return {"_error": err or "empty response"}
    try:
        data = _parse(text)
    except Exception as exc:  # noqa: BLE001 - parse failure
        return {"_error": f"parse failed: {type(exc).__name__}: {exc}"}
    if isinstance(data, dict):
        data["_model_version"] = model_version
    return data
