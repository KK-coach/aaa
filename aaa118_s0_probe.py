"""AAA-118 Sub-step 0 — SERP type taxonomy lock + cost probe.

Research-only. No production code modification. Archive-bypass: read
persisted re_findings.organic_results (AAA-108) from 3 audits, classify
each URL by title+snippet (no crawl), emit serp_type + topic_relevance.

3 audits:
  1) agrobook.hu (post-AAA-110, latest: f2792df5) — HU agri ecomm,
     Hungarian SERP
  2) kk.coach (latest post-AAA-88: 2a2c335c) — EN consulting, US SERP
  3) agrobook.hu (pre-AAA-110, 1e00f93a) — same industry but pre-fix
     English category keyword produced a DIFFERENT SERP (English
     webshops zupan-agroshop, tvh, kramp etc.) — chosen as a 3rd-shape
     substitute since no taxually/aboutyou/vercel/kormany RE audit
     exists in the archive (constraint documented in report §1).

Cost budget: $0.30 hard ceiling (per-call halt if approaching).
"""
import asyncio
import json
import os
import time
from typing import Literal, Optional

# AAA-62 — gemini-3-flash-preview only in 'global'
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

from pydantic import BaseModel, Field
from memory.firestore_archive import read_audit
from site_profile.gemini_analyzer import _parse, get_usage, vertex_generate


# ---- 22-value taxonomy ------------------------------------------------------
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


class SerpClassification(BaseModel):
    serp_type: SerpType
    topic_relevance_score: float = Field(ge=0.0, le=1.0)


# ---- Prompt ----------------------------------------------------------------
_PROMPT = """\
You classify ONE SERP top-10 result for an SEO audit. The classification is
based on TITLE + SNIPPET only (no page crawl). You also score how relevant
this result is to the AUDIT TARGET's topic context.

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
- Pay attention to the HOST PLATFORM, not just content. A consultancy
  described on its OWN site = business_service; the SAME consultancy's
  LinkedIn company page = social_profile_or_page; a Reddit discussion ABOUT
  it = forum_or_qa_thread. Host platform wins.
- Marketplace vs business_category: if the URL is a section/category of a
  marketplace (jofogás/agro), pick marketplace_category. If the URL is one
  specific item, pick marketplace_listing.
- "Listing" pages on a brand's OWN webshop (e.g. webshop.example.com/cars)
  are business_category (the host is a business webshop, not a marketplace).
- If genuinely none of the 21 specific values fit, pick other_or_unknown.
  Don't force-fit.

TASK B — topic_relevance_score (float 0.0–1.0):
How relevant is this URL to the AUDIT TARGET's topic context (the target
site's industry and category)? Use the full range.
  1.0 = direct topic-match competitor (same category, same audience)
  0.7 = adjacent / partially overlapping topic
  0.4 = same broad industry but different sub-topic
  0.2 = tangentially related (e.g. a generic article that mentions the topic)
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

Return ONLY JSON matching the schema (no prose).
"""


async def classify_serp_url(target_ctx: dict, url: str, title: str,
                            snippet: str) -> tuple[dict, float]:
    """Single-call classification: serp_type + topic_relevance."""
    prompt = _PROMPT.format(
        target_url=target_ctx["target_url"],
        topic_domain=target_ctx["topic_domain"] or "[unknown]",
        topic_cluster=target_ctx["topic_cluster"] or "[unknown]",
        category_keyword=target_ctx["category_keyword"] or "[unknown]",
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
        return {"_error": f"vertex: {err or 'no text'}",
                "serp_type": None, "topic_relevance_score": None,
                "_model_version": model_version}, cost
    try:
        data = _parse(text)
        validated = SerpClassification.model_validate(data)
    except Exception as e:  # noqa: BLE001
        return {"_error": f"validate: {type(e).__name__}: {e}",
                "serp_type": None, "topic_relevance_score": None,
                "_model_version": model_version}, cost
    return {
        "serp_type": validated.serp_type,
        "topic_relevance_score": round(validated.topic_relevance_score, 3),
        "_model_version": model_version, "_error": None,
    }, cost


# ---- Reference audits ------------------------------------------------------
REFERENCES = [
    ("agrobook.hu (post-AAA-110)",
     "f2792df5-3fb1-484e-9d03-84c749637701"),
    ("kk.coach",
     "2a2c335c-33f9-4ec2-97a9-082865acbd2c"),
    ("agrobook.hu (pre-AAA-110, English-keyword SERP)",
     "1e00f93a-c9a7-4609-91a5-cf18b23059d7"),
]
COST_CEILING = 0.30


async def main():
    grid = []
    cost_sum = 0.0
    t0 = time.perf_counter()

    # ---- Pre-flight dry-run on 2 agrobook URLs ----
    print("=== PRE-FLIGHT DRY-RUN ===", flush=True)
    doc0 = await read_audit(REFERENCES[0][1])
    ao0 = doc0.get("audit_output") or {}
    rf0 = ao0.get("re_findings") or {}
    sb0 = (rf0.get("serp_branded") or {}).get("organic_results") or []
    tk0 = ao0.get("target_keywords") or {}
    target_ctx0 = {
        "target_url": doc0.get("audit_url"),
        "topic_domain": ao0.get("topic_domain"),
        "topic_cluster": tk0.get("topic_cluster"),
        "category_keyword": tk0.get("category_keyword"),
    }
    dry_runs = []
    for r in sb0[:2]:
        res, c = await classify_serp_url(target_ctx0, r["url"], r["title"], r["snippet"])
        cost_sum += c
        dry_runs.append({"url": r["url"], "result": res, "cost": c})
        print(f"  dry: {r['url'][:70]:70s}  type={res.get('serp_type')!r}  "
              f"relev={res.get('topic_relevance_score')}  cost=${c:.5f}",
              flush=True)
    # Halt early if dry-run produced errors
    if any(d["result"].get("_error") for d in dry_runs):
        print("!!! DRY-RUN ERROR — halting before full sweep", flush=True)
        return
    print(f"  dry-run cost so far: ${cost_sum:.4f}\n", flush=True)

    # ---- Full sweep ----
    by_url_cache = {}  # serp URL → classification (avoid re-classifying
                       # any URL that appears in multiple audits' SERPs)
    audit_results = []
    for label, aid in REFERENCES:
        if cost_sum > COST_CEILING:
            print(f"!!! Cost ceiling approached ({cost_sum:.4f} > ${COST_CEILING})", flush=True)
            break
        print(f"=== {label} ({aid[:8]}…) ===", flush=True)
        doc = await read_audit(aid)
        ao = doc.get("audit_output") or {}
        rf = ao.get("re_findings") or {}
        tk = ao.get("target_keywords") or {}
        target_ctx = {
            "target_url": doc.get("audit_url"),
            "topic_domain": ao.get("topic_domain"),
            "topic_cluster": tk.get("topic_cluster"),
            "category_keyword": tk.get("category_keyword"),
        }
        sb = (rf.get("serp_branded") or {}).get("organic_results") or []
        sc = (rf.get("serp_category") or {}).get("organic_results") or []
        # Dedupe URLs across branded + category for this audit
        seen = set()
        urls_to_classify = []
        for r in sb + sc:
            u = r.get("url")
            if not u or u in seen:
                continue
            seen.add(u)
            urls_to_classify.append(r)
        print(f"  target_ctx: {target_ctx}", flush=True)
        print(f"  unique URLs: {len(urls_to_classify)}", flush=True)

        classified = []
        for r in urls_to_classify:
            url = r["url"]
            if url in by_url_cache:
                cls = by_url_cache[url]
                cost = 0.0
                from_cache = True
            else:
                cls, cost = await classify_serp_url(
                    target_ctx, url, r.get("title", ""), r.get("snippet", "")
                )
                cost_sum += cost
                by_url_cache[url] = cls
                from_cache = False
            classified.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": r.get("snippet", "")[:200],
                "position": r.get("position"),
                "serp_type": cls.get("serp_type"),
                "topic_relevance_score": cls.get("topic_relevance_score"),
                "cost": cost,
                "_from_cache": from_cache,
                "_error": cls.get("_error"),
            })
            tag = "cache" if from_cache else f"${cost:.5f}"
            print(f"    [{tag}] {url[:65]:65s}  type={cls.get('serp_type')!r:30s}  "
                  f"relev={cls.get('topic_relevance_score')}",
                  flush=True)
            if cost_sum > COST_CEILING:
                print(f"!!! Cost ceiling hit at ${cost_sum:.4f}", flush=True)
                break
        audit_results.append({"label": label, "target_ctx": target_ctx,
                              "classified": classified})

    wall = round(time.perf_counter() - t0, 1)
    print(f"\n=== TOTAL: cost=${cost_sum:.4f}  wall={wall}s  "
          f"unique_urls_classified={len(by_url_cache)} ===",
          flush=True)
    with open("aaa118_s0_probe.json", "w", encoding="utf-8") as f:
        json.dump({
            "audit_results": audit_results,
            "by_url_cache": by_url_cache,
            "dry_runs": dry_runs,
            "cost_sum": cost_sum,
            "wall_s": wall,
        }, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    asyncio.run(main())
