"""Tool 1: target-keyword extraction (what this page wants to rank for)."""

from __future__ import annotations

from page_analysis._gemini import generate_json, select_body

_VALID_INTENT = {
    "informational", "commercial", "transactional", "navigational",
}
_VALID_DIFFICULTY = {"low", "medium", "high"}
_VALID_GAP = {"high", "medium", "low", "none"}


def _norm(s) -> str:
    """lowercase, drop non-alphanumerics for brand-substring comparison."""
    import re

    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

_PROMPT = """\
You are analyzing a specific webpage to determine its SEO target keywords.

SITE CONTEXT:
- **Language: {language}**  (the site's natural language — ALL emitted
  category/topic phrases MUST be in this language; see rule below)
- Brand: {brand}
- Industry: {industry}
- Target country: {location}
- Audience: {audience}

PAGE SIGNALS:
- URL: {url}
- Title: {title}
- Meta description: {meta_description}
- H1: {h1_list}
- H2 headers: {h2_list}
- H3 headers: {h3_list}
- Schema types: {schema_types}

MAIN CONTENT (first 2500 chars){thin_note}:
{main_content}

Based on these signals, determine the keywords this page is targeting.

Return ONLY valid JSON in this exact format:
{{
    "primary_keyword": "...",
    "secondary_keywords": ["...", "...", "..."],
    "long_tail_keywords": ["...", "...", "..."],
    "topic_cluster": "...",
    "intent": "informational" | "commercial" | "transactional" | "navigational",
    "estimated_difficulty": "low" | "medium" | "high",
    "category_keyword": "...",
    "is_branded_primary": true | false,
    "keyword_gap_severity": "high" | "medium" | "low" | "none",
    "gap_interpretation": "...",
    "category_competitors_likely": ["...", "...", "..."],
    "reasoning": "Brief explanation of your decisions."
}}

Important:
- Primary keyword should be 1-4 words, what you'd target in title/H1
- Long-tail keywords are 4-7 words, more specific
- Do NOT bias toward generic examples - infer from THIS page's actual content

In addition to the primary keyword and other fields, also determine:

1. CATEGORY_KEYWORD: The general product/service category this page belongs
   to, where it competes with alternatives. The category should be
   DESCRIPTIVE, not branded. Format examples (placeholders only - do NOT
   match these to the page):
   * "Acme Cloud Hosting" -> category: "cloud hosting platform"
   * "Bobby's Bicycle Shop" -> category: "bicycle retailer"
   * "Express VPN" -> category: "VPN service"
2. IS_BRANDED_PRIMARY: Boolean. True if primary_keyword contains the brand
   name from site context, or the page is heavily centered on the brand.
   * primary "Vercel Platform" + brand "Vercel" -> true
   * primary "deployment platform" + brand "Vercel" -> false
3. KEYWORD_GAP_SEVERITY:
   * "high": primary is branded, category is generic and distinct.
   * "medium": primary partially branded, category similar but distinct.
   * "low": primary is descriptive and similar to category (some overlap).
   * "none": primary and category are essentially the same.
4. GAP_INTERPRETATION: 1-2 sentence actionable explanation of the gap for a
   website owner.
5. CATEGORY_COMPETITORS_LIKELY: 2-3 known competitors in the category (from
   general industry knowledge), to validate SERP results downstream.

LANGUAGE BINDING (AAA-110 — anti-English-drift on category/topic fields):
For `category_keyword` and `topic_cluster`:
- These fields MUST be emitted in the site's language ({language}).
- The {language} value is provided in the site-context block; honor it
  strictly.
- It should be the descriptive category phrase a native-{language}-speaker
  user would actually type in their local Google search.
- The English illustrative examples shown above for format guidance are
  FORMAT placeholders. DO NOT translate the page's vocabulary to English;
  use the site's natural-language equivalent.
- Examples for English sites: "cloud hosting platform", "bicycle retailer".
- Examples for Hungarian sites: "felhő hosting szolgáltató",
  "kerékpár webáruház".
- For other languages, follow the same pattern: natural local phrasing.

ANTI-ANCHOR INSTRUCTION: Every example above (Acme Cloud Hosting, Bobby's
Bicycle Shop, Express VPN, the Vercel illustrations, and the
English/Hungarian category samples in the LANGUAGE BINDING block) is a
fictional FORMAT placeholder. They are NOT hints about this page. Do not
bias toward them - infer category, branding, and competitors strictly from
THIS page's actual content and the site context.
"""


def _normalize_intent(value, schema_types: list, has_transact: bool) -> str:
    """Coerce Gemini's intent to the 4-value enum.

    If Gemini returns an off-enum value we fall back deterministically from
    structural cues rather than trusting free text:
      - Product/Offer schema or cart signals -> transactional
      - Service/Organization marketing copy  -> commercial
      - otherwise                            -> informational
    """
    if isinstance(value, str) and value.strip().lower() in _VALID_INTENT:
        return value.strip().lower()
    types_l = {str(t).lower() for t in (schema_types or [])}
    if has_transact or {"product", "offer", "aggregateoffer"} & types_l:
        return "transactional"
    if {"service", "organization", "softwareapplication"} & types_l:
        return "commercial"
    return "informational"


async def extract_target_keywords(crawl_result: dict, site_profile: dict) -> dict:
    """Extract the keywords/topics this page is TARGETING."""
    if crawl_result.get("error"):
        return _empty(f"crawl failed: {crawl_result.get('error')}")

    meta = crawl_result.get("meta") or {}
    headings = crawl_result.get("headings") or {}
    schema_types = (crawl_result.get("schema_markup") or {}).get(
        "schema_types_detected", []
    )
    body = select_body(crawl_result, 2500)
    sp = site_profile or {}

    thin_note = (
        f" [WARNING: only ~{body['word_count']} words available - page is "
        f"likely JS-rendered; treat keyword inference as low-confidence]"
        if body["thin"]
        else ""
    )

    prompt = _PROMPT.format(
        brand=sp.get("brand", "unknown"),
        industry=sp.get("industry", "unknown"),
        location=sp.get("location", "unknown"),
        language=sp.get("language", "unknown"),
        audience=sp.get("audience", "unknown"),
        url=crawl_result.get("url", ""),
        title=meta.get("title", {}).get("text", ""),
        meta_description=meta.get("description", {}).get("text", "") or "[none]",
        h1_list=headings.get("h1", []) or "[none]",
        h2_list=headings.get("h2", [])[:10] or "[none]",
        h3_list=headings.get("h3", [])[:5] or "[none]",
        schema_types=schema_types or "[none]",
        thin_note=thin_note,
        main_content=body["text"] or "[none]",
    )

    data = await generate_json(prompt)
    if "_error" in data:
        return _empty(f"Gemini unavailable: {data['_error']}")

    data["intent"] = _normalize_intent(
        data.get("intent"), schema_types, has_transact=False
    )
    if data.get("estimated_difficulty") not in _VALID_DIFFICULTY:
        data["estimated_difficulty"] = "medium"

    # Deterministic brand-substring cross-check: if the site brand appears
    # inside the primary keyword it IS branded, regardless of Gemini's call.
    primary = data.get("primary_keyword") or ""
    brand = sp.get("brand") or ""
    brand_n = _norm(brand)
    gemini_branded = bool(data.get("is_branded_primary"))
    deterministic_branded = bool(brand_n) and brand_n in _norm(primary)
    is_branded = gemini_branded or deterministic_branded

    gap = data.get("keyword_gap_severity")
    if gap not in _VALID_GAP:
        gap = "medium"

    out = {
        "primary_keyword": data.get("primary_keyword"),
        "secondary_keywords": data.get("secondary_keywords", []) or [],
        "long_tail_keywords": data.get("long_tail_keywords", []) or [],
        "topic_cluster": data.get("topic_cluster"),
        "intent": data["intent"],
        "estimated_difficulty": data["estimated_difficulty"],
        "category_keyword": data.get("category_keyword"),
        "is_branded_primary": is_branded,
        "keyword_gap_severity": gap,
        "gap_interpretation": data.get("gap_interpretation", ""),
        "category_competitors_likely": (
            data.get("category_competitors_likely", []) or []
        ),
        "reasoning": data.get("reasoning", ""),
        "_model_version": data.get("_model_version"),
    }
    if deterministic_branded and not gemini_branded:
        out["gap_interpretation"] = (
            f"[brand '{brand}' detected inside primary keyword by "
            f"deterministic check] " + (out["gap_interpretation"] or "")
        )
    if body["thin"]:
        out["reasoning"] = (
            f"[CONTENT LIMITED: ~{body['word_count']} words from "
            f"{body['source']}; recommend Playwright re-crawl for "
            f"reliable keywords] " + out["reasoning"]
        )
    return out


def _empty(reason: str) -> dict:
    return {
        "primary_keyword": None,
        "secondary_keywords": [],
        "long_tail_keywords": [],
        "topic_cluster": None,
        "intent": None,
        "estimated_difficulty": None,
        "category_keyword": None,
        "is_branded_primary": None,
        "keyword_gap_severity": None,
        "gap_interpretation": "",
        "category_competitors_likely": [],
        "reasoning": reason,
        "_model_version": None,
    }
