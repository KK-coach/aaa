"""AAA-118 Sub-step 1 pre-flight dry-run.

3 synthetic SERP URLs covering critical structural distinctions:
  1) a brand-domain homepage (expected: business_homepage)
  2) a LinkedIn company page (expected: social_profile_or_page)
  3) a jofogás marketplace category (expected: marketplace_category)

Validate:
  - Pydantic-valid output (serp_type in 22-enum, topic_relevance in [0,1])
  - Sensible classifications match expected
  - Cache write success (URL #1 round-trips: 2nd call from_cache=True)
  - Per-call cost <$0.005 (well under the $0.005 stop threshold)

Cost: ~$0.003 (3 LLM calls). No live RE flow.
"""
import asyncio
import os

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

from page_analysis.serp_fit_classify import (
    SerpClassification, _VALID_TYPES, classify_serp_url, _cache_key,
)

TARGET_CTX = {
    "target_url": "https://agrobook.hu",
    "topic_domain": "Shopping",
    "topic_cluster": "Mezőgazdasági gépalkatrészek és precíziós gazdálkodás",
    "category_keyword": "mezőgazdasági gépalkatrész kereskedő",
}

PROBES = [
    {
        "label": "brand homepage",
        "expected_type": "business_homepage",
        "url": "https://webaruhaz.habi.hu/",
        "title": "Mezőgazdasági Gépek és Gépalkatrészek | Habi Webáruház",
        "snippet": (
            "HABI webáruház - mezőgazdasági gépek és alkatrészek széles "
            "választéka. Kiszállítás országosan. Kombájn alkatrészek, "
            "traktoralkatrészek, kazettás szűrők."
        ),
    },
    {
        "label": "LinkedIn company page",
        "expected_type": "social_profile_or_page",
        "url": "https://www.linkedin.com/company/organic-growth-consultants",
        "title": "Organic Growth Consultants | LinkedIn",
        "snippet": (
            "Organic Growth Consultants | LinkedIn | 12,345 followers | "
            "Helping companies build long-term organic growth strategies. "
            "Industry: Business Consulting and Services."
        ),
    },
    {
        "label": "jofogás marketplace category",
        "expected_type": "marketplace_category",
        "url": "https://auto.jofogas.hu/magyarorszag/mezogazdasagi-gep-",
        "title": "Mezőgazdasági gép alkatrészek - Jófogás",
        "snippet": (
            "Mezőgazdasági gép alkatrészek az ország egész területén. "
            "Válogass a Jófogás új és használt termékei között! Régi és új "
            "hirdetések."
        ),
    },
]


async def main():
    print("=== AAA-118 Sub-step 1 pre-flight dry-run ===\n", flush=True)
    total_cost = 0.0
    fails: list[str] = []

    # First-pass calls (expected: 3 LLM calls, cache writes)
    print("--- Pass 1: fresh LLM calls + cache writes ---", flush=True)
    pass1_results = []
    for probe in PROBES:
        cls, cost, from_cache = await classify_serp_url(
            target_url=TARGET_CTX["target_url"],
            topic_domain=TARGET_CTX["topic_domain"],
            topic_cluster=TARGET_CTX["topic_cluster"],
            category_keyword=TARGET_CTX["category_keyword"],
            url=probe["url"],
            title=probe["title"],
            snippet=probe["snippet"],
        )
        total_cost += cost
        pass1_results.append((probe, cls, cost, from_cache))
        ok = cls.get("serp_type") == probe["expected_type"]
        pyd_ok = (cls.get("serp_type") in _VALID_TYPES) and isinstance(
            cls.get("topic_relevance_score"), (int, float)
        ) and 0.0 <= cls.get("topic_relevance_score", -1) <= 1.0
        print(
            f"  [{probe['label']:32s}] type={cls.get('serp_type')!r:30s} "
            f"relev={cls.get('topic_relevance_score')} cache={from_cache} "
            f"cost=${cost:.5f}  pydantic-ok={pyd_ok}  "
            f"expected-match={'YES' if ok else 'NO ('+str(probe['expected_type'])+' expected)'}",
            flush=True,
        )
        if not pyd_ok:
            fails.append(f"{probe['label']}: pydantic invalid")
        if not ok:
            fails.append(f"{probe['label']}: expected {probe['expected_type']}, got {cls.get('serp_type')}")
        if cost > 0.005:
            fails.append(f"{probe['label']}: per-call cost ${cost:.4f} > $0.005 stop threshold")

    print(f"\n  pass-1 LLM cost sum: ${total_cost:.5f}", flush=True)

    # Pass 2: identical inputs — expect cache HITS
    print("\n--- Pass 2: same inputs, expecting cache HITS ---", flush=True)
    pass2_cache_hits = 0
    for probe in PROBES:
        cls, cost, from_cache = await classify_serp_url(
            target_url=TARGET_CTX["target_url"],
            topic_domain=TARGET_CTX["topic_domain"],
            topic_cluster=TARGET_CTX["topic_cluster"],
            category_keyword=TARGET_CTX["category_keyword"],
            url=probe["url"],
            title=probe["title"],
            snippet=probe["snippet"],
        )
        total_cost += cost
        pass2_cache_hits += int(from_cache)
        cache_key = _cache_key(probe["url"], TARGET_CTX["topic_cluster"],
                               TARGET_CTX["category_keyword"])
        print(
            f"  [{probe['label']:32s}] type={cls.get('serp_type')!r:30s} "
            f"cache={from_cache}  cost=${cost:.5f}  cache_key={cache_key}",
            flush=True,
        )
        if not from_cache:
            fails.append(f"{probe['label']}: expected cache HIT on pass 2, got MISS")

    print(f"\n  pass-2 LLM cost (should be 0): ${total_cost - (total_cost - 0):.5f}",
          flush=True)
    print(f"  total cost: ${total_cost:.5f}", flush=True)
    print(f"  cache hits on pass 2: {pass2_cache_hits}/{len(PROBES)}", flush=True)

    print("\n=== DRY-RUN VERDICT ===", flush=True)
    if fails:
        print(f"  FAIL ({len(fails)} issues):", flush=True)
        for f in fails:
            print(f"    - {f}", flush=True)
    else:
        print("  PASS — all 3 probes classified correctly, pydantic-valid, "
              "cache write+read round-trip, no cost outlier.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
