"""Test page_analysis tools on 5 demo URLs.

Run from project root:  python -m page_analysis.test_page_analysis
"""

import asyncio

from crawler import crawl_html
from site_profile import analyze_site_profile
from page_analysis import extract_entities, extract_target_keywords

URLS = [
    "https://www.agrobook.hu",
    "https://kk.coach",
    "https://www.aboutyou.hu",
    "https://www.taxually.com",
    "https://vercel.com/products/vercel-platform",
]


def _top_entities(ent: dict, n: int = 5) -> list[str]:
    flat = []
    for cat in ("products", "organizations", "people", "places",
                "technologies", "concepts"):
        for v in ent.get(cat, []):
            flat.append(f"{v} ({cat[:4]})")
    return flat[:n]


async def main() -> None:
    empty_entities = []
    for url in URLS:
        print("=" * 78)
        print(url)
        print("-" * 78)
        crawl = await crawl_html(url)
        profile = await analyze_site_profile(crawl)

        kw = await extract_target_keywords(crawl, profile)
        ent = await extract_entities(crawl, profile)

        print(
            f"  primary_keyword : {kw['primary_keyword']}  "
            f"[intent={kw['intent']}, difficulty={kw['estimated_difficulty']}]"
        )
        print(f"  topic_cluster   : {kw['topic_cluster']}")
        print(
            f"  category_keyword: {kw.get('category_keyword')}  "
            f"[branded_primary={kw.get('is_branded_primary')}, "
            f"gap={kw.get('keyword_gap_severity')}]"
        )
        print(f"  gap_interpret   : {kw.get('gap_interpretation')}")
        print(f"  cat_competitors : {kw.get('category_competitors_likely')}")
        print(f"  secondary_kw    : {kw['secondary_keywords']}")
        print(f"  long_tail_kw    : {kw['long_tail_keywords']}")
        print(f"  top entities    : {_top_entities(ent)}")
        ent_total = sum(
            len(ent.get(c, []))
            for c in ("products", "organizations", "people", "places",
                      "technologies", "concepts")
        )
        if ent_total <= 2:
            empty_entities.append(f"{url} ({ent_total} entities)")
        print(f"  kw reasoning    : {kw['reasoning'][:240]}")
        print(f"  ent reasoning   : {ent['reasoning'][:200]}")
        print()

    print("=" * 78)
    print("URLs with near-empty entity extraction (<=2 total):")
    for e in empty_entities or ["  (none)"]:
        print(f"  - {e}")


if __name__ == "__main__":
    asyncio.run(main())
