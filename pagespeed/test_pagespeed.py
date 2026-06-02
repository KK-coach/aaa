"""Manual test harness for the PageSpeed client.

Runs 3 URLs x 2 strategies = 6 analyses (free API).

Run from project root:  python -m pagespeed.test_pagespeed
"""

import asyncio
import time

from pagespeed.client import get_pagespeed_score

TEST_URLS = [
    "https://en.wikipedia.org",   # well-optimized large site
    "https://web.dev",            # Google's own site
    "https://www.bbc.com",        # heavy news site
]
STRATEGIES = ("mobile", "desktop")


def _fmt_cwv(cwv: dict) -> str:
    parts = []
    for key in ("lcp", "inp", "fid", "cls", "fcp", "ttfb"):
        m = cwv.get(key, {})
        val = m.get("value_ms", m.get("value"))
        rating = m.get("rating")
        if val is None:
            parts.append(f"{key.upper()}=n/a")
        else:
            unit = "" if key == "cls" else "ms"
            parts.append(f"{key.upper()}={val}{unit}({rating})")
    return "  ".join(parts)


def _print_result(url: str, strategy: str, r: dict) -> None:
    print(f"--- {url}  [{strategy}] ---")
    if r.get("error"):
        print(f"  ERROR [{r.get('error_type')}]: {r['error']}")
        return
    s = r["scores"]
    print(
        f"  scores: perf={s['performance']} a11y={s['accessibility']} "
        f"bp={s['best_practices']} seo={s['seo']}  "
        f"({r['fetch_time_ms']} ms)"
    )
    print(
        f"  data: field={r['field_data_available']} "
        f"lab={r['lab_data_available']}"
    )
    print(f"  CWV: {_fmt_cwv(r['core_web_vitals'])}")
    if r["opportunities"]:
        top = r["opportunities"][0]
        print(
            f"  top opportunity: {top['title']} "
            f"(saves {top['savings_ms']} ms)"
        )


async def main() -> None:
    overall_start = time.perf_counter()
    timed_out: list[str] = []
    field_summary: list[tuple[str, bool]] = []

    for url in TEST_URLS:
        for strategy in STRATEGIES:
            r = await get_pagespeed_score(url, strategy)
            _print_result(url, strategy, r)
            if r.get("error_type") == "timeout":
                timed_out.append(f"{url} [{strategy}]")
            if not r.get("error"):
                field_summary.append(
                    (f"{url} [{strategy}]", r["field_data_available"])
                )
            print()

    total_s = time.perf_counter() - overall_start
    print("=" * 64)
    print(f"Total time for 6 analyses: {total_s:.1f} s")
    print(f"Timed out: {timed_out or 'none'}")
    print("Field data (real-user CrUX) availability:")
    for name, has_field in field_summary:
        print(f"  {'YES' if has_field else 'no '}  {name}")


if __name__ == "__main__":
    asyncio.run(main())
