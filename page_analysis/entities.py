"""Tool 2: page-level named-entity extraction."""

from __future__ import annotations

from page_analysis._gemini import generate_json, select_body

_CATEGORIES = (
    "products", "organizations", "people", "places", "technologies", "concepts",
)

_PROMPT = """\
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

You are extracting named entities from a webpage's main content.

SITE CONTEXT:
- Brand: {brand}
- Industry: {industry}

MAIN CONTENT (first 3000 chars){thin_note}:
{main_content}

Extract entities of these types:
- products: specific named products or services mentioned (not generic \
"shoes" but "Nike Air Max 90")
- organizations: companies mentioned (NOT the brand itself - only external \
ones)
- people: named individuals (founders, experts, authors)
- places: geographic locations (cities, countries, regions)
- technologies: specific technologies, frameworks, tools, programming \
languages
- concepts: 3-5 most important concepts central to this page

Return ONLY valid JSON:
{{
    "products": ["...", "..."],
    "organizations": ["...", "..."],
    "people": ["...", "..."],
    "places": ["...", "..."],
    "technologies": ["...", "..."],
    "concepts": ["...", "...", "..."],
    "reasoning": "Brief explanation"
}}

Important:
- Return empty list [] if a category has no entities (don't fabricate)
- Don't include the site's own brand name in organizations
- Don't include the site's address country in places (unless explicitly \
discussed in content)
- Quality over quantity - only entities EXPLICITLY mentioned
"""


def _clean_list(value, drop: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    out, seen = [], set()
    for item in value:
        if not isinstance(item, str):
            continue
        s = item.strip()
        key = s.lower()
        if s and key not in seen and key not in drop:
            seen.add(key)
            out.append(s)
    return out


async def extract_entities(crawl_result: dict, site_profile: dict) -> dict:
    """Extract page-level named entities (products/orgs/people/places/etc.)."""
    if crawl_result.get("error"):
        return _empty(f"crawl failed: {crawl_result.get('error')}")

    sp = site_profile or {}
    brand = sp.get("brand") or ""
    body = select_body(crawl_result, 3000)

    thin_note = (
        f" [WARNING: only ~{body['word_count']} words available - JS-rendered "
        f"page; expect sparse/empty entity lists]"
        if body["thin"]
        else ""
    )

    prompt = _PROMPT.format(
        brand=brand or "unknown",
        industry=sp.get("industry", "unknown"),
        thin_note=thin_note,
        main_content=body["text"] or "[none]",
    )

    data = await generate_json(prompt)
    if "_error" in data:
        return _empty(f"Gemini unavailable: {data['_error']}")

    # Defensively strip the site's own brand from organizations.
    drop = {brand.strip().lower()} if brand else set()
    out = {cat: _clean_list(data.get(cat), drop if cat == "organizations"
                             else set())
           for cat in _CATEGORIES}
    out["concepts"] = out["concepts"][:5]
    out["reasoning"] = data.get("reasoning", "")
    out["_model_version"] = data.get("_model_version")
    if body["thin"]:
        total = sum(len(out[c]) for c in _CATEGORIES)
        out["reasoning"] = (
            f"[CONTENT LIMITED: ~{body['word_count']} words from "
            f"{body['source']}; {total} entities found - recommend Playwright "
            f"re-crawl] " + out["reasoning"]
        )
    return out


def _empty(reason: str) -> dict:
    out = {cat: [] for cat in _CATEGORIES}
    out["reasoning"] = reason
    out["_model_version"] = None
    return out
