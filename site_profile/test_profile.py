"""Test site_profile on 5 demo URLs.

Run from project root:  python -m site_profile.test_profile
"""

import asyncio

from crawler import crawl_html
from site_profile import analyze_site_profile

URLS = [
    "https://www.agrobook.hu",
    "https://kk.coach",
    "https://www.aboutyou.hu",
    "https://www.taxually.com",
    "https://vercel.com/products/vercel-platform",
]


def _print(url: str, p: dict) -> None:
    print("=" * 78)
    print(url)
    print("-" * 78)
    if p.get("error"):
        print(f"  ERROR [{p.get('error_type')}]: {p['error']}")
        return
    print(
        f"  language : {p['language']} (conf {p['language_confidence']})"
    )
    print(
        f"  location : {p['location']} (conf {p['location_confidence']})  "
        f"needs_confirmation={p['needs_user_confirmation']}"
    )
    print(
        f"  >>> SERP STRATEGY: {p.get('serp_strategy')}  "
        f"(og:locale={p.get('detected_signals', {}).get('og_locale')})"
    )
    sc = p.get("signal_consistency") or {}
    if not sc.get("is_consistent", True):
        for c in sc.get("conflicts", []):
            print(
                f"  !!! SIGNAL CONFLICT [{c['severity']}] {c['field']}="
                f"{c['declared']}"
            )
            print(f"        evidence_against: {c['evidence_against']}")
            print(f"        fix: {c['recommendation'][:140]}...")
    print(f"  brand    : {p['brand']}")
    print(f"  industry : {p['industry']}")
    print(f"  audience : {p['audience']}")
    print(f"  entities : {p['main_entities']}")
    print(f"  signals  : {p['detected_signals']}")
    print(f"  candidates: {p['candidates']}")
    print(f"  reasoning: {p['reasoning']}")


async def main() -> None:
    confirm = []
    for url in URLS:
        crawl = await crawl_html(url)
        profile = await analyze_site_profile(crawl)
        _print(url, profile)
        if not profile.get("error") and profile.get("needs_user_confirmation"):
            confirm.append(
                f"{url} (location={profile['location']} "
                f"@ {profile['location_confidence']})"
            )

    print("\n" + "=" * 78)
    print("URLs that would TRIGGER user confirmation (location_conf < 0.85):")
    for c in confirm or ["  (none)"]:
        print(f"  - {c}")


if __name__ == "__main__":
    asyncio.run(main())
