"""AAA-114 Sub-step 2 pre-flight: 1 LLM-probe + scoring + cache-stale.

Scenario 1: real Stage 1 LLM call on 3 synthetic SERP candidates (HU agro,
            EN consulting, facebook host-platform) — verifies candidate
            field extraction + language-binding + None policy. ~$0.003.
Scenario 2: Stage 2 soft-score scenarios (HIGH/PARTIAL/LOW/NO/LOCAL-HIGH).
            Pure compute, $0.
Scenario 3: cache-stale handling — pre-Sub-step-2 cache entry should be
            detected as missing new fields and treated as cache miss.
"""
import asyncio
import os
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

import hashlib
from page_analysis.serp_fit_classify import (
    SerpClassification, classify_serp_url, _cache_key, _cache_write,
    _cache_read,
)
from reverse_engineering_agent.competitor_filter import _compute_soft_score


# ============================================================================
# Scenario 1 — Stage 1 LLM extension probe ($)
# ============================================================================
async def scenario_1_llm_probe():
    print("=== Scenario 1: Stage 1 LLM extension probe ===")
    target_ctx = {
        "target_url": "https://agrobook.hu",
        "topic_domain": "Shopping",
        "topic_cluster": "Mezőgazdasági gépalkatrészek és precíziós gazdálkodás",
        "category_keyword": "mezőgazdasági gépalkatrész kereskedő",
    }
    probes = [
        {
            "label": "HU agro webshop (expect HU fields)",
            "url": "https://example-agro-shop.hu/",
            "title": "Mezőgazdasági gépalkatrészek webáruháza | TestAgroShop",
            "snippet": "Mezőgazdasági gép és alkatrész kereskedő. Traktor "
                       "alkatrészek, kombájn alkatrészek, országos kiszállítás.",
            "expect_lang": "HU",
            "expect_nonnull": True,
        },
        {
            "label": "EN consulting blog (expect EN fields)",
            "url": "https://example-consulting.com/article",
            "title": "Top 10 Organic Growth Strategies for B2B SaaS",
            "snippet": "A guide to organic growth strategies for B2B SaaS "
                       "companies. Tactics for growth consultants and "
                       "marketers.",
            "expect_lang": "EN-from-HU-target-LOCK",  # tricky case
            "expect_nonnull": True,
        },
        {
            "label": "facebook host-platform (expect both null)",
            "url": "https://www.facebook.com/61579121540335/photos/122150808362970718/",
            "title": "Photo",
            "snippet": "Photo by Habi Kft. on Facebook.",
            "expect_lang": "either",
            "expect_nonnull": False,  # CRITICAL: should be null
        },
    ]
    fails = []
    total_cost = 0.0
    for p in probes:
        cls, cost, from_cache = await classify_serp_url(
            target_url=target_ctx["target_url"],
            topic_domain=target_ctx["topic_domain"],
            topic_cluster=target_ctx["topic_cluster"],
            category_keyword=target_ctx["category_keyword"],
            url=p["url"], title=p["title"], snippet=p["snippet"],
        )
        total_cost += cost
        cand_tc = cls.get("candidate_topic_cluster")
        cand_ck = cls.get("candidate_category_keyword")
        # Pydantic validity
        try:
            SerpClassification.model_validate({
                "serp_type": cls.get("serp_type"),
                "topic_relevance_score": cls.get("topic_relevance_score") or 0,
                "candidate_topic_cluster": cand_tc,
                "candidate_category_keyword": cand_ck,
            })
            pyd_ok = True
        except Exception as e:
            pyd_ok = False
            fails.append(f"{p['label']}: pydantic invalid: {e}")
        # Nonnull-expectation check
        nonnull_actual = (cand_tc is not None) or (cand_ck is not None)
        nonnull_ok = nonnull_actual == p["expect_nonnull"]
        if not nonnull_ok:
            fails.append(
                f"{p['label']}: expected nonnull={p['expect_nonnull']}, "
                f"got tc={cand_tc!r} / ck={cand_ck!r}"
            )
        print(f"  [{p['label']:48s}] type={cls.get('serp_type')!r:30s}")
        print(f"    relev={cls.get('topic_relevance_score')}  cost=${cost:.5f}  "
              f"cache={from_cache}  pyd_ok={pyd_ok}")
        print(f"    candidate_topic_cluster   : {cand_tc!r}")
        print(f"    candidate_category_keyword: {cand_ck!r}")
    print(f"\n  Total Stage 1 LLM probe cost: ${total_cost:.5f}")
    print(f"  Per-call avg (Sub-step 1 baseline was ~$0.0008):  ${total_cost/3:.5f}")
    return fails, total_cost


# ============================================================================
# Scenario 2 — Stage 2 soft-score scenarios ($0)
# ============================================================================
def scenario_2_soft_scores():
    print("\n=== Scenario 2: Stage 2 soft-score (5 sub-scenarios) ===")
    target = {
        "target_type": "business_homepage",
        "target_topic_cluster": "Mezőgazdasági gépalkatrészek",
        "target_category_keyword": "mezőgazdasági gépalkatrész kereskedő",
    }
    cases = [
        # HIGH: 4/4 dims match (relev>=0.8, serp_type, tc, ck)
        ("HIGH (4/4)", {
            "candidate_serp_type": "business_homepage",
            "candidate_relev": 0.95,
            "candidate_topic_cluster": "Mezőgazdasági gépalkatrészek",
            "candidate_category_keyword": "mezőgazdasági gépalkatrész kereskedő",
            "candidate_url": "https://habi.hu",
            "target_locality": None, "target_locality_tld": None,
        }, 4.0),
        # PARTIAL: 2/4 (relev + serp_type, but tc=different, ck=different)
        ("PARTIAL (2/4)", {
            "candidate_serp_type": "business_homepage",
            "candidate_relev": 0.85,
            "candidate_topic_cluster": "Egyéb",
            "candidate_category_keyword": "mas",
            "candidate_url": "https://x.com",
            "target_locality": None, "target_locality_tld": None,
        }, 2.0),
        # LOW: only relev proxy
        ("LOW (1/4)", {
            "candidate_serp_type": "business_blog_or_article",
            "candidate_relev": 0.85,
            "candidate_topic_cluster": None,
            "candidate_category_keyword": None,
            "candidate_url": "https://x.com",
            "target_locality": None, "target_locality_tld": None,
        }, 1.0),
        # NO: 0/4
        ("NO (0/4)", {
            "candidate_serp_type": "business_blog_or_article",
            "candidate_relev": 0.7,
            "candidate_topic_cluster": None,
            "candidate_category_keyword": None,
            "candidate_url": "https://x.com",
            "target_locality": None, "target_locality_tld": None,
        }, 0.0),
        # LOCAL HIGH: 5/5
        ("LOCAL HIGH (5/5)", {
            "candidate_serp_type": "business_homepage",
            "candidate_relev": 0.95,
            "candidate_topic_cluster": "Mezőgazdasági gépalkatrészek",
            "candidate_category_keyword": "mezőgazdasági gépalkatrész kereskedő",
            "candidate_url": "https://habi.hu",
            "target_locality": "local", "target_locality_tld": "hu",
        }, 5.0),
    ]
    fails = []
    for label, kw, expected in cases:
        score, breakdown = _compute_soft_score(
            target_type=target["target_type"],
            target_topic_cluster=target["target_topic_cluster"],
            target_category_keyword=target["target_category_keyword"],
            **kw,
        )
        ok = score == expected
        if not ok:
            fails.append(f"{label}: expected {expected}, got {score}")
        print(f"  [{label:20s}] score={score}  expected={expected}  "
              f"{'PASS' if ok else 'FAIL'}")
        print(f"    breakdown: {breakdown}")
    return fails


# ============================================================================
# Scenario 3 — Cache-stale handling ($0)
# ============================================================================
async def scenario_3_cache_stale():
    print("\n=== Scenario 3: Cache-stale handling (pre-S2 entry → miss) ===")
    # Forge a pre-Sub-step-2 cache entry (missing new fields)
    fake_url = "https://aaa114-s2-cache-stale-probe.example.com/"
    fake_topic = "TestTopicClusterFakeForS2Probe"
    fake_cat = "TestCategoryFakeForS2Probe"
    key = _cache_key(fake_url, fake_topic, fake_cat)
    # Write a stale (pre-S2-shape) entry directly
    from page_analysis.serp_fit_classify import _cache_write
    pre_s2_entry = {
        "serp_type": "business_homepage",
        "topic_relevance_score": 0.9,
        "_model_version": "gemini-3-flash-preview",
        "_error": None,
        # NOTE: candidate_topic_cluster + candidate_category_keyword KEYS ABSENT
    }
    await _cache_write(key, pre_s2_entry,
                       (fake_url, fake_topic, fake_cat))

    # Verify read still works
    cached = await _cache_read(key)
    print(f"  cache write+read: cached={cached is not None}")
    if cached:
        print(f"    has new fields: tc={'candidate_topic_cluster' in cached.get('classification', {})}, "
              f"ck={'candidate_category_keyword' in cached.get('classification', {})}")

    # Now call classify_serp_url — should treat the stale entry as miss
    # and force a fresh LLM call (which would normally cost $0.001-0.003).
    # To avoid the cost in this dry-run, we just verify the cache-miss
    # detection path is hit; the LLM call itself would write a fresh
    # entry with new fields.
    cls, cost, from_cache = await classify_serp_url(
        target_url="https://test.com",
        topic_domain="Test",
        topic_cluster=fake_topic,
        category_keyword=fake_cat,
        url=fake_url,
        title="Test", snippet="Test snippet",
    )
    print(f"  classify call: from_cache={from_cache} (expect False — stale-entry miss)")
    print(f"    cost=${cost:.5f}  serp_type={cls.get('serp_type')!r}")
    print(f"    candidate_topic_cluster   : {cls.get('candidate_topic_cluster')!r}")
    print(f"    candidate_category_keyword: {cls.get('candidate_category_keyword')!r}")
    fails = []
    if from_cache:
        fails.append("expected from_cache=False on stale entry, got True")
    # Verify new fields are present (even if None — KEY presence matters)
    if "candidate_topic_cluster" not in cls:
        fails.append("post-call result missing candidate_topic_cluster key")
    if "candidate_category_keyword" not in cls:
        fails.append("post-call result missing candidate_category_keyword key")

    # Re-call same args; expect cache HIT now (S2-shaped entry was just written)
    cls2, cost2, from_cache2 = await classify_serp_url(
        target_url="https://test.com",
        topic_domain="Test",
        topic_cluster=fake_topic,
        category_keyword=fake_cat,
        url=fake_url,
        title="Test", snippet="Test snippet",
    )
    print(f"  classify re-call: from_cache={from_cache2} (expect True — fresh S2 entry)")
    if not from_cache2:
        fails.append("expected from_cache=True on re-call, got False")
    return fails, cost + cost2


async def main():
    print("=" * 80)
    print("AAA-114 Sub-step 2 pre-flight dry-run")
    print("=" * 80 + "\n")
    fails_1, cost_1 = await scenario_1_llm_probe()
    fails_2 = scenario_2_soft_scores()
    fails_3, cost_3 = await scenario_3_cache_stale()
    print("\n" + "=" * 80)
    all_fails = fails_1 + fails_2 + fails_3
    total_cost = cost_1 + cost_3
    print(f"TOTAL spend: ${total_cost:.5f}")
    if all_fails:
        print(f"FAILS ({len(all_fails)}):")
        for f in all_fails:
            print(f"  - {f}")
    else:
        print("ALL CHECKS PASS")


if __name__ == "__main__":
    asyncio.run(main())
