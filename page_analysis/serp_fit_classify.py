"""AAA-118 Sub-step 1 — Stage 1 SERP-fit classifier.

Production module. Stage 1 of the two-stage SERP-analysis frame
(Stage 2 = AAA-114 competitor selection). Classifies each SERP top-10
URL by `serp_type` (22-value taxonomy) + `topic_relevance_score`
(0.0-1.0) from title + snippet ONLY (no crawl, no site_profile).

Sub-step 0 empirical baseline (2026-05-26, 49 URLs across 3 audits):
  - 95.5% hit-rate on clear a-priori cases
  - 0/49 off-enum or other_or_unknown emissions
  - 9/9 critical structural URLs (LinkedIn / jofogás / Reddit / Facebook /
    Investopedia / Upwork / orszagosszaknevsor / firmy.cz / Facebook post)
    correctly classified
  - Per-URL cost ~$0.0008 mean, p99 outlier $0.00378
  - topic_relevance_score validated as Stage 2 formula-C-v2 topic-fit
    proxy (Opció X locked over Opció Y)

Sub-step 0.5 lockdown:
  - prompt includes site-business-context > single-page-content-overlap
    instruction (Q1 INCLUDE)
  - topic_relevance_score >= 0.7 default threshold for Stage 2 (Q2 LOCKED)
  - snippet-text variance (~2% rate) accepted as known limitation (Q3)
  - p99 cost outlier accepted, no investigation (Q4)

Cost is SEPARATE (AAA-53 pattern) — caller stores in
`audit_serp_fit_cost_usd`, never folded into `audit_cost_usd`.

24h Firestore cache (`serp_fit_cache/`) keyed by SHA256 hash of
(url, target_topic_cluster, target_category_keyword). Lazy expiry on read.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from pydantic import BaseModel, Field

from site_profile.gemini_analyzer import _parse, get_usage, vertex_generate

logger = logging.getLogger(__name__)

# AAA-118 S0 locked taxonomy (22 values)
SerpType = Literal[
    "business_homepage", "business_category", "business_product",
    "business_service", "business_pricing", "business_documentation",
    "business_blog_or_article", "business_case_study_or_resource",
    "business_contact_or_form", "business_legal",
    "news_or_publisher_article", "marketplace_listing",
    "marketplace_category", "directory_listing",
    "social_profile_or_page", "social_post", "forum_or_qa_thread",
    "video_or_audio_listing", "wiki_or_reference",
    "gov_or_education", "aggregator_or_personal_blog",
    "other_or_unknown",
]

# 22-tuple for the schema's allow-list checks at the validation layer
_VALID_TYPES = SerpType.__args__  # type: ignore[attr-defined]


class SerpClassification(BaseModel):
    serp_type: SerpType
    topic_relevance_score: float = Field(ge=0.0, le=1.0)
    # AAA-114 Sub-step 2 (Option X-extend, 2026-05-26): per-candidate
    # topic_cluster + category_keyword extraction from SERP-snippet+URL,
    # in the SAME LANGUAGE as the target's values. Optional[str] — None
    # is a legitimate signal that the snippet is too sparse to confidently
    # infer (e.g., social-media host pages, photo URLs). NEVER defaults
    # to target values; per-candidate independence required by Stage 2
    # binary match comparison.
    candidate_topic_cluster: str | None = None
    candidate_category_keyword: str | None = None


# ---------------------------------------------------------------------------
# Firestore cache
# ---------------------------------------------------------------------------
_CACHE_COLLECTION = "serp_fit_cache"
_CACHE_TTL = timedelta(hours=24)

# AAA-118 Sub-step 2.1 — tracking-param strip list for cache-key normalization.
# These query params are per-session/per-impression IDs that Google and other
# platforms append to URLs; the same logical page appears with different
# values across fetches. Stripping them lets the cache hit on the underlying
# URL identity rather than on session metadata. Smoke 2 (Sub-step 1) showed
# 30% cache miss rate dominated by srsltid variance — this list closes that
# gap.
_TRACKING_PARAMS_EXACT = frozenset({
    "srsltid",          # Google SERP session-tracking
    "gclid",            # Google Ads click ID
    "fbclid",           # Facebook click ID
    "mc_eid", "mc_cid", # Mailchimp email/campaign
    "msclkid",          # Microsoft Ads click ID
    "dclid",            # DoubleClick click ID
    "igshid",           # Instagram share ID
    "twclid",           # Twitter click ID
    "vero_id", "vero_conv",  # Vero email
    "hsCtaTracking",    # HubSpot CTA tracking
    "_hsenc", "_hsmi",  # HubSpot email/marketing IDs
    "ref", "ref_source",  # referrer chains
})
_TRACKING_PARAMS_PREFIX = ("utm_",)  # all utm_* parameters


def _normalize_url_for_cache(url: str) -> str:
    """Normalize a URL for cache-key hashing only.

    Rules (per AAA-118 S2.1 design lockdown):
      - Lowercase the host (RFC: host is case-insensitive)
      - Preserve path case (RFC: paths are case-sensitive on most servers)
      - Strip the fragment (#...) entirely (never reaches the server)
      - Strip exact-match tracking params (srsltid, gclid, fbclid, ...)
      - Strip any param starting with `utm_`
      - Preserve order of remaining params
      - Preserve trailing slash (don't normalize /path vs /path/)
      - Preserve all non-tracking query params verbatim

    The returned string is ONLY used in cache-key hashing. The original URL
    is preserved everywhere else (traceability requirement).

    Edge cases: malformed URLs fall back to the original string (the cache
    key stays deterministic; the LLM call will still happen).
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:  # noqa: BLE001 — malformed URL → use original as-is
        return url
    netloc = (parts.netloc or "").lower()
    # parse_qsl preserves duplicates AND order (as a list of tuples).
    try:
        qs_pairs = parse_qsl(parts.query, keep_blank_values=True)
    except Exception:  # noqa: BLE001 — malformed query → use original
        return url
    kept = [
        (k, v) for k, v in qs_pairs
        if k not in _TRACKING_PARAMS_EXACT
        and not any(k.startswith(p) for p in _TRACKING_PARAMS_PREFIX)
    ]
    new_query = urlencode(kept) if kept else ""
    # Fragment dropped (5th tuple element = "").
    return urlunsplit((parts.scheme, netloc, parts.path, new_query, ""))


def _cache_key(url: str, topic_cluster: str, category_keyword: str) -> str:
    """Deterministic content-addressable SHA256 hash of the cache-key tuple.

    AAA-118 S2.1: URL is run through _normalize_url_for_cache() before
    hashing so tracking-param variance (srsltid, utm_*, etc.) doesn't
    fragment the cache.

    Truncated to 24 hex chars (still 96 bits of collision resistance,
    fits comfortably in a Firestore doc id; shorter than the full 64-char
    SHA256 for readability)."""
    normalized = _normalize_url_for_cache(url)
    raw = f"{normalized}|{topic_cluster or ''}|{category_keyword or ''}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _cache_read(key: str) -> dict | None:
    """Read a cached classification. Returns None on miss / expired / error.
    Never raises — cache is a performance optimization, not source of truth."""
    try:
        from memory.firestore_archive import _db
        ref = _db().collection(_CACHE_COLLECTION).document(key)
        snap = await asyncio.to_thread(ref.get)
        if not snap.exists:
            return None
        doc = snap.to_dict() or {}
        emitted_at_str = doc.get("emitted_at")
        if not emitted_at_str:
            return None
        try:
            emitted_at = datetime.fromisoformat(emitted_at_str)
        except (ValueError, TypeError):
            return None
        if _now_utc() - emitted_at > _CACHE_TTL:
            return None  # stale; lazy cleanup (caller may delete; we don't)
        return doc
    except Exception as e:  # noqa: BLE001 — cache failures are non-critical
        logger.warning("serp_fit_cache read failed (key=%s): %s", key, e)
        return None


async def _cache_write(key: str, classification: dict,
                       cache_key_tuple: tuple[str, str, str]) -> None:
    """Best-effort cache write. Failures are logged, never raise."""
    try:
        from memory.firestore_archive import _db
        ref = _db().collection(_CACHE_COLLECTION).document(key)
        doc = {
            "classification": classification,
            "emitted_at": _now_utc().isoformat(),
            "cache_key_tuple": {
                "url": cache_key_tuple[0],
                "topic_cluster": cache_key_tuple[1],
                "category_keyword": cache_key_tuple[2],
            },
        }
        await asyncio.to_thread(ref.set, doc)
    except Exception as e:  # noqa: BLE001
        logger.warning("serp_fit_cache write failed (key=%s): %s", key, e)


# ---------------------------------------------------------------------------
# Classifier — single-call prompt + LLM-side schema validation
# ---------------------------------------------------------------------------
_PROMPT = """\
You classify ONE SERP top-10 result for an SEO audit. The classification
is based on TITLE + SNIPPET + URL only (no page crawl). You ALSO score
how relevant this result is to the AUDIT TARGET's topic context.

TASK A — serp_type (one of 22 enum values):

Business-owned content (a company/brand's own site):
  business_homepage             — front page of a company's site
  business_category             — category/listing page within a webshop or site
  business_product              — single-product or single-SKU page
  business_service              — service description / "what we do" page
  business_pricing              — plans, tiers, fee schedule
  business_documentation        — developer docs / technical reference
  business_blog_or_article      — company-owned blog post or editorial article
  business_case_study_or_resource — case study, white paper, downloadable resource
  business_contact_or_form      — contact, lead form, quote request
  business_legal                — TOS, privacy, GDPR pages

Editorial / third-party:
  news_or_publisher_article     — news outlet article (telex, NYT, Reuters)

Marketplace + classifieds:
  marketplace_listing           — individual listing on a marketplace (an item)
  marketplace_category          — marketplace's category root (e.g. jofogás/cars)

Directories:
  directory_listing             — yellow-pages-style aggregator entry

Social:
  social_profile_or_page        — LinkedIn company page, FB business page,
                                  Twitter profile, Instagram page
  social_post                   — single tweet, FB post, IG post, TikTok video

Community Q&A / forums:
  forum_or_qa_thread            — reddit, stack overflow, quora thread

Media:
  video_or_audio_listing        — YouTube channel/video, podcast episode page

Reference / encyclopedia:
  wiki_or_reference             — wikipedia, mediawiki, glossary entry

Government / education:
  gov_or_education              — .gov/.edu pages, school/uni sites, official

Other:
  aggregator_or_personal_blog   — personal blog, hobbyist site, mixed-content
                                  aggregator
  other_or_unknown              — none of the above fits cleanly

CLASSIFICATION RULES:
- HOST PLATFORM WINS over single-page content. A consultancy described on
  its OWN site = business_service. The SAME consultancy's LinkedIn company
  page = social_profile_or_page (host = LinkedIn). A Reddit discussion
  ABOUT the consultancy = forum_or_qa_thread. Host platform identity always
  beats page-content topic alignment.
- Marketplace vs business_category: if URL is a section/category of a
  marketplace (jofogás/agro), pick marketplace_category. If URL is one
  specific item, pick marketplace_listing.
- "Listing" pages on a brand's OWN webshop (e.g. webshop.example.com/cars)
  are business_category (the host is a business webshop, not a marketplace).
- If genuinely none of the 21 specific values fit, pick other_or_unknown.
  Don't force-fit.

TASK B — topic_relevance_score (float 0.0–1.0):

SITE-BUSINESS-CONTEXT > SINGLE-PAGE-CONTENT-OVERLAP (AAA-118 S0.5 Q1):
Score how relevant the RESULT'S SITE-LEVEL BUSINESS is to the TARGET's
topic context — NOT just how much the result's single-page CONTENT touches
the target's topic. A virtual-office provider that writes a blog post
mentioning "growth strategies" is NOT directly topic-relevant to a growth
consultancy target — its site-level business is virtual offices, not
growth consulting. Score that case ~0.3-0.5, not 1.0.

Score scale:
  1.0 = direct topic-match competitor (same category, same audience)
  0.7 = adjacent / partially overlapping topic at the site level
  0.4 = same broad industry but different sub-topic
  0.2 = tangentially related (single page mentions the topic but site
        business is different)
  0.0 = unrelated (different industry entirely)

AUDIT TARGET CONTEXT:
  Target URL: {target_url}
  Target topic_domain (IAB Tier-1): {topic_domain}
  Target topic_cluster: {topic_cluster}
  Target category_keyword: {category_keyword}

SERP RESULT TO CLASSIFY:
  URL: {url}
  Title: {title}
  Snippet: {snippet}

TASK C — per-candidate extraction (AAA-114 Sub-step 2):
For each SERP result, ALSO extract two per-candidate fields used by the
downstream Stage 2 competitor filter:

  candidate_topic_cluster:
    A SHORT phrase describing the topical cluster THIS SPECIFIC candidate's
    content belongs to. Inferred ONLY from this candidate's title + snippet
    (NOT from the target's values). Emit null when the snippet is too
    sparse / generic to confidently infer (e.g., social media host pages,
    photo URLs, malformed snippets).

  candidate_category_keyword:
    A SHORT phrase describing the business category or service this
    candidate represents. Same inference + null rules as above.

LANGUAGE BINDING (CRITICAL — site-business-context applies to candidate
extraction too):
- Emit candidate_topic_cluster and candidate_category_keyword in the SAME
  LANGUAGE as the target's topic_cluster ({topic_cluster}) and
  category_keyword ({category_keyword}) above. This enables direct
  string-equality matching in Stage 2.
- If the target context is in Hungarian, emit Hungarian. If English, emit
  English. Match the target's natural-language phrasing form.

INDEPENDENCE: each candidate's fields are inferred from THAT candidate's
title + snippet ONLY. DO NOT default to the target's values — that would
defeat the downstream match comparison.

NULL POLICY: prefer null over a forced guess. A "best effort" wrong value
hurts the downstream match more than a clean null.

Examples (FORMAT only; do NOT match these to the current page):
  - HU agricultural webshop ('Habi Webáruház | Mezőgazdasági gépek') →
    candidate_topic_cluster: 'Mezőgazdasági gépalkatrészek és precíziós
    gazdálkodás'
    candidate_category_keyword: 'mezőgazdasági gépalkatrész kereskedő'
  - EN organic growth consultancy blog post →
    candidate_topic_cluster: 'Organic Growth Strategy and Optimization'
    candidate_category_keyword: 'organic growth consultancy'
  - facebook.com/.../photos/123 (host-platform, no business context) →
    candidate_topic_cluster: null
    candidate_category_keyword: null
  - reddit.com/r/SaaS thread → both null (host-platform Q&A)

ANTI-ANCHOR: examples above are FORMAT placeholders. Infer from THIS
candidate's actual title + snippet content. Do NOT bias toward the
example wordings.

Return ONLY JSON matching the schema (no prose).
"""


async def classify_serp_url(
    target_url: str,
    topic_domain: str | None,
    topic_cluster: str | None,
    category_keyword: str | None,
    url: str,
    title: str,
    snippet: str,
) -> tuple[dict, float, bool]:
    """Classify ONE SERP URL. Returns (classification_dict, cost_usd, from_cache).

    classification_dict has keys:
      - serp_type: str (one of 22 enum, or None on error)
      - topic_relevance_score: float (0.0-1.0, or None on error)
      - _model_version: str | None
      - _error: str | None

    Cache: SHA256(url|topic_cluster|category_keyword) → 24h TTL Firestore.
    Cost: from_cache=True implies cost=0.0 (no LLM call).
    """
    key = _cache_key(url, topic_cluster or "", category_keyword or "")
    cached = await _cache_read(key)
    if cached:
        cls = cached.get("classification") or {}
        # AAA-114 Sub-step 2 cache-stale handling: pre-Sub-step-2 cache
        # entries don't have candidate_topic_cluster / _category_keyword
        # KEYS at all. None is legitimate (sparse-snippet null); the
        # check uses `in` (key presence) rather than `.get()` (value)
        # so old entries lacking the keys force a cache miss + fresh
        # LLM call + re-write under the extended shape.
        has_new_fields = (
            "candidate_topic_cluster" in cls
            and "candidate_category_keyword" in cls
        )
        if (cls.get("serp_type") in _VALID_TYPES and isinstance(
                cls.get("topic_relevance_score"), (int, float)
            ) and has_new_fields):
            return {
                "serp_type": cls["serp_type"],
                "topic_relevance_score": float(cls["topic_relevance_score"]),
                "candidate_topic_cluster": cls.get("candidate_topic_cluster"),
                "candidate_category_keyword": cls.get("candidate_category_keyword"),
                "_model_version": cls.get("_model_version"),
                "_error": None,
            }, 0.0, True

    prompt = _PROMPT.format(
        target_url=target_url or "[unknown]",
        topic_domain=topic_domain or "[unknown]",
        topic_cluster=topic_cluster or "[unknown]",
        category_keyword=category_keyword or "[unknown]",
        url=url,
        title=(title or "")[:300],
        snippet=(snippet or "")[:500],
    )
    cost_before = get_usage().get("cost", 0.0)
    text, model_version, err = await vertex_generate(
        prompt, temperature=0.0, thinking_level="LOW",
        response_schema=SerpClassification,
    )
    cost = round(get_usage().get("cost", 0.0) - cost_before, 6)

    if err or not text:
        logger.warning("serp_fit_classify: vertex error for %s: %s", url, err)
        return {
            "serp_type": None, "topic_relevance_score": None,
            "candidate_topic_cluster": None,
            "candidate_category_keyword": None,
            "_model_version": model_version,
            "_error": err or "no response text",
        }, cost, False

    try:
        data = _parse(text)
        validated = SerpClassification.model_validate(data)
    except Exception as e:  # noqa: BLE001
        logger.warning("serp_fit_classify: validation failed for %s: %s",
                       url, e)
        return {
            "serp_type": None, "topic_relevance_score": None,
            "candidate_topic_cluster": None,
            "candidate_category_keyword": None,
            "_model_version": model_version,
            "_error": f"validate: {type(e).__name__}: {e}",
        }, cost, False

    # Normalize optional fields (empty string → None for consistent
    # downstream match logic; LLMs occasionally emit "" instead of null).
    cand_tc = validated.candidate_topic_cluster
    cand_ck = validated.candidate_category_keyword
    if isinstance(cand_tc, str) and not cand_tc.strip():
        cand_tc = None
    if isinstance(cand_ck, str) and not cand_ck.strip():
        cand_ck = None

    result = {
        "serp_type": validated.serp_type,
        "topic_relevance_score": round(validated.topic_relevance_score, 3),
        "candidate_topic_cluster": cand_tc,
        "candidate_category_keyword": cand_ck,
        "_model_version": model_version,
        "_error": None,
    }
    # Best-effort cache write — doesn't gate the return.
    await _cache_write(key, result, (url, topic_cluster or "",
                                      category_keyword or ""))
    return result, cost, False


# ---------------------------------------------------------------------------
# AAA-118 Sub-step 2.2 — target_type mapping + verdict + alternative kws
# ---------------------------------------------------------------------------
# Deterministic AAA-81 v3 page_type (27 leaves) → AAA-118 SERP type (22-leaf).
# Lookup-table, NOT LLM judgment (validated principle #1). business_model
# reserved for future disambiguation if a single page_type maps differently
# across business models (e.g., ecommerce vs b2b_saas homepage); currently
# page_type is dominant. Fall-through to other_or_unknown for safety
# (methodological pattern #18).
PAGE_TYPE_TO_SERP_TYPE: dict[str, str] = {
    # Direct mappings
    "homepage":                     "business_homepage",
    "category_page":                "business_category",
    "product_page":                 "business_product",
    "service_page":                 "business_service",
    "pricing_page":                 "business_pricing",
    "documentation":                "business_documentation",
    "blog_article":                 "business_blog_or_article",
    "news_article":                 "news_or_publisher_article",
    "guide_or_resource":            "business_case_study_or_resource",
    "case_study_page":              "business_case_study_or_resource",
    "contact_page":                 "business_contact_or_form",
    "form_page":                    "business_contact_or_form",
    "legal_page":                   "business_legal",
    # Landing pages: usually conversion-shaped close to homepage
    "landing_page":                 "business_homepage",
    # Comparison content: article-shaped
    "comparison_page":              "business_blog_or_article",
    # Testimonial/review: social-proof case-study shape
    "testimonial_or_review_page":   "business_case_study_or_resource",
    # Paywalled: same article shape, irrelevant access status
    "paywalled_or_gated_content":   "business_blog_or_article",
    # OWN glossary/wiki is brand content (NOT wiki_or_reference, which is
    # for wikipedia-host platforms)
    "glossary_or_wiki_page":        "business_blog_or_article",
    # Media gallery / video page
    "media_page":                   "video_or_audio_listing",
    # Event landing = brand landing
    "event_page":                   "business_homepage",
    # Single-location brand landing
    "location_page":                "business_homepage",
    # Booking/checkout = conversion form shape
    "checkout_or_booking":          "business_contact_or_form",
    # OWN jobs page (NOT third-party directory like LinkedIn Jobs)
    "job_listing_page":             "business_contact_or_form",
    # Non-SERP-relevant page types — never rank top-10
    "search_results_page":          "other_or_unknown",
    "account_or_dashboard":         "other_or_unknown",
    "error_or_redirect_page":       "other_or_unknown",
    # Passthrough
    "other_or_unknown":             "other_or_unknown",
}


# AAA-118.1 Sub-step 1 — joint (business_model, page_type) signature lookup,
# consulted BEFORE the page_type-only fallback. Narrow first iteration
# (one entry only) per AAA-118 comment 11967 Q1 lock; expansion is
# evidence-driven, not speculative.
#
# Trigger case: AAA-118 Sub-step 3 multi-audit canary (deviation flag #1,
# 2026-05-26) showed kormany.hu's `homepage` page_type + `government_or_
# public_sector` business_model was flattening to `business_homepage`,
# producing a semantically-lossy verdict in Stage 2 against gov-dominated
# SERPs. The joint lookup restores correct `gov_or_education` semantics.
#
# Tuple key order: (business_model, page_type) — alphabetical-by-name to
# keep the joint-dict shape consistent with future additions.
PAGE_TYPE_AND_BUSINESS_MODEL_TO_SERP_TYPE: dict[tuple[str | None, str | None], str] = {
    ("government_or_public_sector", "homepage"): "gov_or_education",
}


def map_target_type(page_type: str | None,
                    business_model: str | None = None) -> str:
    """Map (page_type, business_model) → AAA-118 SERP type.

    Lookup order (AAA-118.1 Sub-step 1):
      1) Joint (business_model, page_type) signature — `gov_or_education`
         for government_or_public_sector homepages (and future joint
         signatures as empirical evidence justifies them).
      2) Fall-back: page_type-only `PAGE_TYPE_TO_SERP_TYPE` (preserves
         all pre-AAA-118.1 behavior on non-government audits).
      3) Defense-in-depth fall-through: `other_or_unknown` (methodological
         pattern #18) for unknown page_type or unmapped key tuple.

    Backward-compatible: the additive joint dict is consulted FIRST but
    only fires on its narrow allow-list; every other (business_model,
    page_type) pair falls through to the existing page_type-only path
    byte-identical to AAA-118 Sub-step 2.2 behavior.
    """
    # STEP 1 — Joint (business_model, page_type) lookup
    joint_key = (business_model, page_type)
    if joint_key in PAGE_TYPE_AND_BUSINESS_MODEL_TO_SERP_TYPE:
        return PAGE_TYPE_AND_BUSINESS_MODEL_TO_SERP_TYPE[joint_key]
    # STEP 2 — Fall-back to page_type-only lookup (pre-AAA-118.1 behavior)
    if not page_type:
        return "other_or_unknown"
    return PAGE_TYPE_TO_SERP_TYPE.get(page_type, "other_or_unknown")


def compute_target_type_fit(
    target_type: str,
    classifications: list[dict],
    relevance_threshold: float = 0.7,
) -> tuple[str, list[str], dict[str, int]]:
    """Per-keyword verdict per Sub-step 2.2 bands.

    Filter: only URLs with topic_relevance_score >= threshold (Sub-step 0.5
    Q2 lock at 0.7) count toward the distribution.

    Bands:
      - "high"    = target_type ∈ top-3 dominant AND top-3 cover ≥ 60%
      - "partial" = target_type appears in filtered distribution (count ≥ 1)
                    but NOT a clear "high" fit (either NOT in top-3 OR
                    top-3 coverage < 60%)
      - "low"     = target_type does NOT appear (count = 0), OR filtered
                    distribution is empty

    Edge case (spec gap): if target_type IS in top-3 but coverage < 60%,
    falls to "partial" — SERP too fragmented for "high", target still
    among the dominant set so not "low". Pragmatic interpretation.

    Returns (verdict, top3_dominant_types, filtered_distribution).
    """
    from collections import Counter
    filtered = [
        c for c in (classifications or [])
        if (c.get("topic_relevance_score") or 0) >= relevance_threshold
        and c.get("serp_type")
    ]
    if not filtered:
        return "low", [], {}
    dist = Counter(c["serp_type"] for c in filtered)
    total = sum(dist.values())
    top3 = [t for t, _ in dist.most_common(3)]
    top3_count = sum(dist[t] for t in top3)
    top3_coverage = top3_count / total if total else 0.0
    target_count = dist.get(target_type, 0)

    # Low band (AAA-118 S2.2 baseline + AAA-118.1 S2 off-by-one capture):
    # - target_type count == 0  → low (target absent from SERP entirely)
    # - target_type count <= 1 AND NOT in top-3 → low (off-by-one fluke,
    #   AAA-118 S3 kk.coach pattern: 1 stray homepage in a SERP otherwise
    #   dominated by other types is too weak a signal to call "partial")
    if target_count == 0:
        return "low", top3, dict(dist)
    if target_count <= 1 and target_type not in top3:
        return "low", top3, dict(dist)
    # High band (unchanged from Sub-step 2.2)
    if target_type in top3 and top3_coverage >= 0.6:
        return "high", top3, dict(dist)
    # Partial band (unchanged: everything else NEM low)
    return "partial", top3, dict(dist)


# --- Alternative keyword suggestions (conditional LLM call) ----------------
class AlternativeKeywordSuggestions(BaseModel):
    """Pydantic schema for the alternative-keyword LLM output.

    3-5 keywords in the target's audit language. Reasoning is a 1-2-sentence
    string explaining why these specific keywords would plausibly be a
    better SERP-type fit for the target site.
    """
    suggestions: list[str] = Field(min_length=3, max_length=5)
    reasoning: str


_ALT_KW_PROMPT = """\
You suggest alternative SEO keywords for a website whose CURRENT
target_type does NOT match the dominant SERP type for a given keyword.

TARGET SITE CONTEXT:
- topic_domain (IAB Tier-1): {topic_domain}
- topic_cluster: {topic_cluster}
- category_keyword: {category_keyword}
- target_type (the target's mapped SERP type): {target_type}
- audit_language (output MUST be in this language): {audit_language}

CURRENT LOW-FIT KEYWORD: "{low_fit_keyword}"

The SERP top-10 for that keyword is dominated by these SERP types
(not by the target_type "{target_type}"):
{top3_with_counts}

Sample titles from the dominant URLs (for grounding):
{sample_titles}

TASK: Suggest 3-5 ALTERNATIVE keywords in {audit_language} where this
target site's type ("{target_type}") would plausibly rank in the SERP
top-3. Ground in the target's actual topic_cluster + category_keyword —
do NOT invent generic alternatives unrelated to the target's industry.

The alternatives should:
  - Stay topically aligned with the target's category (so the target site
    is genuinely a relevant result)
  - Be search queries where Google would likely surface
    "{target_type}"-shaped results in the top-3 (e.g., if target_type is
    "business_homepage", the alternative keywords should be ones where
    branded/transactional homepage results dominate the SERP)
  - Be in {audit_language}

Return ONLY JSON matching the schema (no prose).
"""


async def suggest_alternative_keywords(
    *,
    target_topic_domain: str | None,
    target_topic_cluster: str | None,
    target_category_keyword: str | None,
    target_type: str,
    audit_language: str,
    low_fit_keyword: str,
    top3_dominant_types: list[str],
    distribution: dict[str, int],
    dominant_titles: list[str],
) -> tuple[dict, float]:
    """Conditional Gemini LLM call. Fires ONLY when verdict == 'low'.

    Cost target <$0.005 per call. Returns
    ({"suggestions": list[str], "reasoning": str, "_error": str|None},
     cost_usd).
    """
    top3_lines = "\n".join(
        f"  - {t}: {distribution.get(t, 0)}" for t in top3_dominant_types
    ) or "  (no dominant types — distribution is sparse)"
    title_lines = "\n".join(
        f"  - {t!r}" for t in (dominant_titles or [])
    ) or "  (no titles available)"
    prompt = _ALT_KW_PROMPT.format(
        topic_domain=target_topic_domain or "[unknown]",
        topic_cluster=target_topic_cluster or "[unknown]",
        category_keyword=target_category_keyword or "[unknown]",
        target_type=target_type,
        audit_language=audit_language or "[unknown]",
        low_fit_keyword=low_fit_keyword,
        top3_with_counts=top3_lines,
        sample_titles=title_lines,
    )
    cost_before = get_usage().get("cost", 0.0)
    text, model_version, err = await vertex_generate(
        prompt, temperature=0.0, thinking_level="LOW",
        response_schema=AlternativeKeywordSuggestions,
    )
    cost = round(get_usage().get("cost", 0.0) - cost_before, 6)
    if err or not text:
        return {"suggestions": [], "reasoning": None,
                "_model_version": model_version,
                "_error": err or "no response text"}, cost
    try:
        data = _parse(text)
        validated = AlternativeKeywordSuggestions.model_validate(data)
    except Exception as e:  # noqa: BLE001
        return {"suggestions": [], "reasoning": None,
                "_model_version": model_version,
                "_error": f"validate: {type(e).__name__}: {e}"}, cost
    return {
        "suggestions": list(validated.suggestions),
        "reasoning": validated.reasoning,
        "_model_version": model_version,
        "_error": None,
    }, cost


async def enrich_with_verdicts(
    serp_fit_analysis: list[dict],
    *,
    target_type: str,
    target_topic_domain: str | None,
    target_topic_cluster: str | None,
    target_category_keyword: str | None,
    audit_language: str,
) -> tuple[list[dict], float]:
    """Sub-step 2.2 enrichment: per-keyword target_type + verdict +
    conditional alternative_keyword_suggestions LLM call.

    LLM call fires ONLY when target_type_fit == "low" (cost-bounded by the
    proportion of low-fit keywords; verdict==high|partial cases incur $0
    additional cost).

    Returns (enriched_list, additional_cost_usd). The enriched list mutates
    each entry in-place (adds target_type, target_type_fit,
    keyword_recommendation_trigger, alternative_keyword_suggestions,
    alternative_keyword_reasoning). _error entries are passed through
    without verdict computation.
    """
    extra_cost = 0.0
    for entry in serp_fit_analysis:
        if entry.get("_error"):
            entry["target_type"] = target_type
            entry["target_type_fit"] = None
            entry["keyword_recommendation_trigger"] = False
            entry["alternative_keyword_suggestions"] = []
            entry["alternative_keyword_reasoning"] = None
            continue
        classifications = entry.get("serp_top10_classifications") or []
        verdict, top3, _dist = compute_target_type_fit(
            target_type, classifications,
        )
        entry["target_type"] = target_type
        entry["target_type_fit"] = verdict
        entry["keyword_recommendation_trigger"] = (verdict == "low")
        if verdict == "low":
            # Sample 1 title per dominant SERP type (grounding for LLM)
            sample_titles: list[str] = []
            for t in top3:
                for c in classifications:
                    if c.get("serp_type") == t and (c.get("title") or "").strip():
                        sample_titles.append(c["title"])
                        break  # one per type
            alt, alt_cost = await suggest_alternative_keywords(
                target_topic_domain=target_topic_domain,
                target_topic_cluster=target_topic_cluster,
                target_category_keyword=target_category_keyword,
                target_type=target_type,
                audit_language=audit_language,
                low_fit_keyword=entry.get("keyword") or "",
                top3_dominant_types=top3,
                distribution=_dist,
                dominant_titles=sample_titles[:3],
            )
            extra_cost += alt_cost
            entry["alternative_keyword_suggestions"] = alt.get("suggestions") or []
            entry["alternative_keyword_reasoning"] = alt.get("reasoning")
            if alt.get("_error"):
                entry["_alternative_keyword_error"] = alt["_error"]
        else:
            entry["alternative_keyword_suggestions"] = []
            entry["alternative_keyword_reasoning"] = None
    return serp_fit_analysis, round(extra_cost, 6)


# ---------------------------------------------------------------------------
# Batch orchestrator: 1 or more keywords × top-10 SERP each
# ---------------------------------------------------------------------------
async def classify_all_serps(
    target_url: str,
    topic_domain: str | None,
    topic_cluster: str | None,
    category_keyword: str | None,
    keyword_serps: list[dict],
) -> tuple[list[dict], float, int, int]:
    """Stage 1 batch entry point.

    keyword_serps: list of dicts shaped:
      [
        {"keyword": str, "keyword_role": "primary"|"secondary",
         "organic_results": [{"url", "title", "snippet", "position"}, ...],
         "_error": str | None  (optional; skip-finding if present)}
      , ...]

    AAA-118 S0 cost projection (~$0.0008/URL × 50 URLs/audit = ~$0.04/audit
    on first run; 24h cache drops re-audit cost dramatically).

    Returns:
      (serp_fit_analysis, total_cost_usd, call_count_non_cached, cache_hits)

    serp_fit_analysis matches the new audit_output schema shape:
      list[{ keyword, keyword_role, serp_top10_classifications:[...],
             serp_type_distribution:{type:count}, _error: str|None }]
    """
    serp_fit_analysis: list[dict] = []
    total_cost = 0.0
    call_count = 0
    cache_hits = 0

    for entry in keyword_serps:
        kw = entry.get("keyword") or ""
        kw_role = entry.get("keyword_role") or "secondary"
        if entry.get("_error"):
            serp_fit_analysis.append({
                "keyword": kw,
                "keyword_role": kw_role,
                "_error": entry["_error"],
                "serp_top10_classifications": [],
                "serp_type_distribution": {},
            })
            continue

        organic = entry.get("organic_results") or []
        classifications: list[dict] = []
        distribution: dict[str, int] = {}

        for r in organic:
            url = r.get("url") or ""
            if not url:
                continue
            cls, cost, from_cache = await classify_serp_url(
                target_url=target_url,
                topic_domain=topic_domain,
                topic_cluster=topic_cluster,
                category_keyword=category_keyword,
                url=url,
                title=r.get("title") or "",
                snippet=r.get("snippet") or "",
            )
            total_cost += cost
            if from_cache:
                cache_hits += 1
            else:
                call_count += 1
            classifications.append({
                "url": url,
                "position": r.get("position"),
                "title": r.get("title") or "",
                "snippet": r.get("snippet") or "",
                "serp_type": cls.get("serp_type"),
                "topic_relevance_score": cls.get("topic_relevance_score"),
                # AAA-114 Sub-step 2: per-candidate fields propagated to
                # the persisted serp_top10_classifications shape so Stage 2
                # soft-filter can compute topic_cluster_match +
                # category_keyword_match.
                "candidate_topic_cluster": cls.get("candidate_topic_cluster"),
                "candidate_category_keyword": cls.get("candidate_category_keyword"),
                "from_cache": from_cache,
                "_error": cls.get("_error"),
            })
            t = cls.get("serp_type")
            if t:
                distribution[t] = distribution.get(t, 0) + 1

        serp_fit_analysis.append({
            "keyword": kw,
            "keyword_role": kw_role,
            "serp_top10_classifications": classifications,
            "serp_type_distribution": distribution,
            "_error": None,
        })

    return serp_fit_analysis, round(total_cost, 6), call_count, cache_hits
