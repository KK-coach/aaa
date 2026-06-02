"""AAA-77 v2 + AAA-81 v3 + AAA-113 — multi-dimensional Discovery classifier.

Single multi-field Gemini call (AAA-84 precedens) emitting 7 classification
fields together for forensic peer-group matching, competitor filtering, and
report segmentation. Coordinated ship for all 3 tickets in one Discovery
prompt + schema change.

Fields produced (returned in a dict + a cost meter):
  1. page_type                       — AAA-81 v3, 27-leaf Schema.org-inspired
  2. page_type_parent_intent_group   — derived from page_type leaf (NOT LLM)
  3. business_model                  — AAA-77 v2, 26-value flat enum
  4. topic_domain                    — AAA-113, IAB Content Taxonomy 3.1 Tier-1
  5. locality                        — AAA-113, 4-value flat (+ unknown)
  6. audience_relationship_primary   — AAA-113, 11-value (B/C/G 3×3 + B2E)
  7. audience_relationship_secondary — opt., same enum as primary, None default
  8. audience_confidence             — 0-100 int, AAA-91 confidence pattern

AAA-53 cost separation: caller stores the returned cost in a SEPARATE
audit_multi_dim_classify_cost_usd field (never folded into audit_cost_usd).

Model: gemini-3-flash-preview (AAA-62 hard-set, NOT bumped per AAA-83 guard).
thinking_level=LOW kept ON — judgment-laden classification (AAA-84 finding:
thinking_budget=0 collapses intent-quality).
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel

from site_profile.gemini_analyzer import _parse, get_usage, vertex_generate

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Locked enums (per Jira tickets + AAA-113 Scope-lock 2026-05-25)
# ----------------------------------------------------------------------------

# AAA-81 v3 — 27 leaves
PageType = Literal[
    "homepage", "category_page", "product_page", "service_page",
    "landing_page", "blog_article", "news_article", "guide_or_resource",
    "glossary_or_wiki_page", "documentation", "paywalled_or_gated_content",
    "pricing_page", "comparison_page", "case_study_page",
    "testimonial_or_review_page", "search_results_page", "contact_page",
    "location_page", "form_page", "checkout_or_booking",
    "account_or_dashboard", "legal_page", "media_page", "event_page",
    "job_listing_page", "error_or_redirect_page", "other_or_unknown",
]

# AAA-81 v3 — derived 4-value parent intent group (None for the (skip) leaves)
_PARENT_INTENT_GROUP: dict[str, Optional[str]] = {
    "homepage": "navigation",
    "category_page": "comparison_discovery",
    "product_page": "conversion",
    "service_page": "conversion",
    "landing_page": "conversion",
    "blog_article": "informational",
    "news_article": "informational",
    "guide_or_resource": "informational",
    "glossary_or_wiki_page": "informational",
    "documentation": "informational",
    "paywalled_or_gated_content": "informational",
    "pricing_page": "conversion",
    "comparison_page": "comparison_discovery",
    "case_study_page": "comparison_discovery",
    "testimonial_or_review_page": "comparison_discovery",
    "search_results_page": "navigation",
    "contact_page": "navigation",
    "location_page": "navigation",
    "form_page": "conversion",
    "checkout_or_booking": "conversion",
    "account_or_dashboard": "navigation",
    "legal_page": "navigation",
    "media_page": "informational",
    "event_page": "conversion",
    "job_listing_page": "navigation",
    "error_or_redirect_page": None,
    "other_or_unknown": None,
}

# AAA-77 v2 — 26 values (incl. unknown)
BusinessModel = Literal[
    "ecommerce", "b2b_saas", "b2b_service", "local_business",
    "publisher_or_media", "blog_or_personal_brand", "marketplace",
    "directory", "documentation_or_developer_site", "education",
    "government_or_public_sector", "nonprofit", "community_or_forum",
    "web_app_or_dashboard", "lead_generation_site", "portfolio",
    "social_media", "affiliate_or_review_site", "news_or_press_agency",
    "event_or_ticketing", "coupon_or_deals_site", "healthcare_provider",
    "financial_services", "real_estate", "travel_or_hospitality",
    "unknown",
]

# AAA-113 — IAB Content Taxonomy 3.1 Tier-1 (30 values + unknown fallback)
TopicDomain = Literal[
    "Automotive", "Books and Literature", "Business and Finance", "Careers",
    "Education", "Events and Attractions", "Family and Relationships",
    "Fine Art", "Food & Drink", "Healthy Living", "Hobbies & Interests",
    "Home & Garden", "Medical Health", "Movies", "Music and Audio",
    "News and Politics", "Personal Finance", "Pets", "Pop Culture",
    "Real Estate", "Religion & Spirituality", "Science", "Shopping",
    "Sports", "Style & Fashion", "Technology & Computing", "Television",
    "Travel", "Video Gaming", "Sensitive Topics",
    "unknown",
]

# AAA-113 — 4 values + unknown safety
Locality = Literal["local", "regional", "national", "global", "unknown"]

# AAA-113 — 10 nevesített + unknown = 11
AudienceRelationship = Literal[
    "B2B", "B2C", "B2G", "C2B", "C2C", "C2G", "G2B", "G2C", "G2G", "B2E",
    "unknown",
]


class MultiDimClassification(BaseModel):
    """Structured-output schema for the single multi-field call."""
    page_type: PageType
    business_model: BusinessModel
    topic_domain: TopicDomain
    locality: Locality
    audience_relationship_primary: AudienceRelationship
    audience_relationship_secondary: Optional[AudienceRelationship] = None
    audience_confidence: int  # 0–100


# ----------------------------------------------------------------------------
# Prompt
# ----------------------------------------------------------------------------
_PROMPT = """\
You are classifying ONE webpage along 7 orthogonal dimensions for an SEO
audit. Emit a single JSON object — no prose, no other commentary.

Dimensions:

1. PAGE_TYPE — the functional form of THIS page (27-leaf Schema.org-inspired
   taxonomy). Classify by STRUCTURE, not by brand reputation. Use the URL
   path, title, H1, and Schema.org markup as primary signals.
   Allowed values: homepage | category_page | product_page | service_page |
   landing_page | blog_article | news_article | guide_or_resource |
   glossary_or_wiki_page | documentation | paywalled_or_gated_content |
   pricing_page | comparison_page | case_study_page |
   testimonial_or_review_page | search_results_page | contact_page |
   location_page | form_page | checkout_or_booking | account_or_dashboard |
   legal_page | media_page | event_page | job_listing_page |
   error_or_redirect_page | other_or_unknown

2. BUSINESS_MODEL — the SITE's organizational/monetization model (orthogonal
   to industry). Examples: a webshop = ecommerce; an SEO consultancy =
   b2b_service; an SaaS subscription dashboard = b2b_saas / web_app_or_dashboard.
   Allowed values: ecommerce | b2b_saas | b2b_service | local_business |
   publisher_or_media | blog_or_personal_brand | marketplace | directory |
   documentation_or_developer_site | education | government_or_public_sector |
   nonprofit | community_or_forum | web_app_or_dashboard |
   lead_generation_site | portfolio | social_media | affiliate_or_review_site |
   news_or_press_agency | event_or_ticketing | coupon_or_deals_site |
   healthcare_provider | financial_services | real_estate |
   travel_or_hospitality | unknown

3. TOPIC_DOMAIN — IAB Content Taxonomy 3.1 Tier-1. Pick the SINGLE best-fit
   Tier-1 for the site's primary subject matter.
   Allowed values: Automotive | Books and Literature | Business and Finance |
   Careers | Education | Events and Attractions | Family and Relationships |
   Fine Art | Food & Drink | Healthy Living | Hobbies & Interests |
   Home & Garden | Medical Health | Movies | Music and Audio |
   News and Politics | Personal Finance | Pets | Pop Culture | Real Estate |
   Religion & Spirituality | Science | Shopping | Sports | Style & Fashion |
   Technology & Computing | Television | Travel | Video Gaming |
   Sensitive Topics | unknown

4. LOCALITY — geographic reach (NOT language; a HU-language site can be
   global). Signals: physical address, schema:LocalBusiness, opening hours,
   currency, hreflang, content scope.
   Allowed values: local (single-city/area) | regional (sub-national region) |
   national (one country only) | global (multi-country) | unknown

5. AUDIENCE_RELATIONSHIP_PRIMARY — sender × receiver. The site's PRIMARY
   audience-relationship. (B=business, C=consumer/citizen, G=government,
   E=employee.) Examples: Slack marketing site = B2B; Amazon.com = B2C;
   NAV ügyfél-portál = G2C; Jofogás classifieds = C2C; corporate intranet
   = B2E; freelance seller showcase = C2B; government supplier vendor =
   B2G; regulator portal = G2B; magyarorszag.hu (citizen-facing
   e-government) = G2C.
   Allowed values: B2B | B2C | B2G | C2B | C2C | C2G | G2B | G2C | G2G |
   B2E | unknown

6. AUDIENCE_RELATIONSHIP_SECONDARY — optional. Same 11-value enum or null.
   Only fill IF the site CLEARLY serves a second distinct audience (e.g. a
   tax authority portal serving both citizens (G2C) and businesses (G2B)).
   Default: null. Do NOT force-fill — prefer null over a weak second guess.

7. AUDIENCE_CONFIDENCE — integer 0–100, your confidence in the PRIMARY
   audience classification. Use the full range. Single-signal page (e.g. a
   homepage with a clear B2B SaaS feature list) → 85–95. Ambiguous mixed
   audience (e.g. a marketplace serving both consumers and SMBs) → 50–70.
   Vague / thin content → 30–50.

PAGE / SITE DATA:
URL          : {url}
Title        : {title}
H1           : {h1}
Meta desc    : {meta_description}
Schema types : {schema_types}
Brand        : {brand}
Site lang    : {language}
Site location: {location}

AUDIT SUMMARY (page+site context, use as ground truth):
{summary}

MAIN CONTENT EXCERPT (first ~500 words):
{excerpt}

Return ONLY JSON matching the schema (no prose).
"""


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
async def classify_multi_dim(
    crawl: dict,
    site_profile: dict,
    summary_text: str,
) -> tuple[dict, float]:
    """Run the multi-field classification call.

    Returns (result_dict, cost_usd) where result_dict has the 8 emitted keys
    (7 LLM + 1 derived parent_intent_group) plus `_model_version`. Skip-
    finding: on parse / API failure, returns dict of None values + cost 0.0
    (the wrapper records the failure via `_error` key) so the audit pipeline
    keeps running.
    """
    meta = (crawl or {}).get("meta") or {}
    headings = (crawl or {}).get("headings") or {}
    schema_types = (
        (crawl or {}).get("schema_markup") or {}
    ).get("schema_types_detected", []) or []
    mc = (crawl or {}).get("main_content") or {}
    body = mc.get("text") or ""
    excerpt = " ".join(body.split()[:500]) or "[none]"

    prompt = _PROMPT.format(
        url=(crawl or {}).get("url", "") or "",
        title=((meta.get("title") or {}).get("text") or "")[:300],
        h1=(headings.get("h1") or ["[none]"])[0] if headings.get("h1") else "[none]",
        meta_description=(
            (meta.get("description") or {}).get("text") or "[none]"
        )[:300],
        schema_types=", ".join(map(str, schema_types[:10])) or "[none]",
        brand=(site_profile or {}).get("brand") or "[unknown]",
        language=(site_profile or {}).get("language") or "[unknown]",
        location=(site_profile or {}).get("location") or "[unknown]",
        summary=(summary_text or "")[:2500] or "[none]",
        excerpt=excerpt,
    )

    cost_before = get_usage().get("cost", 0.0)
    text, model_version, err = await vertex_generate(
        prompt,
        temperature=0.0,
        thinking_level="LOW",
        response_schema=MultiDimClassification,
    )
    cost_delta = round(get_usage().get("cost", 0.0) - cost_before, 6)

    empty = {
        "page_type": None,
        "page_type_parent_intent_group": None,
        "business_model": None,
        "topic_domain": None,
        "locality": None,
        "audience_relationship_primary": None,
        "audience_relationship_secondary": None,
        "audience_confidence": None,
        "_model_version": model_version,
        "_error": None,
    }

    if err or not text:
        logger.warning("multi_dim_classify Gemini call failed: %s", err)
        empty["_error"] = err or "no response text"
        return empty, cost_delta

    try:
        data = _parse(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("multi_dim_classify parse failed: %s", e)
        empty["_error"] = f"parse: {type(e).__name__}: {e}"
        return empty, cost_delta

    # Validate via Pydantic — guarantees enum membership + 0–100 int.
    try:
        validated = MultiDimClassification.model_validate(data)
    except Exception as e:  # noqa: BLE001
        logger.warning("multi_dim_classify validation failed: %s", e)
        empty["_error"] = f"validate: {type(e).__name__}: {e}"
        return empty, cost_delta

    # Clamp confidence to 0–100 defensively (Pydantic doesn't constrain int).
    conf = max(0, min(100, int(validated.audience_confidence)))

    pt = validated.page_type
    return {
        "page_type": pt,
        "page_type_parent_intent_group": _PARENT_INTENT_GROUP.get(pt),
        "business_model": validated.business_model,
        "topic_domain": validated.topic_domain,
        "locality": validated.locality,
        "audience_relationship_primary": validated.audience_relationship_primary,
        "audience_relationship_secondary": validated.audience_relationship_secondary,
        "audience_confidence": conf,
        "_model_version": model_version,
        "_error": None,
    }, cost_delta
