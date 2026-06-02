"""Compare httpx (raw HTML) vs Playwright (JS-rendered) word counts.

Run from the project root:

    python -m playwright_poc.compare_render
"""

import asyncio

from crawler import crawl_html
from playwright_poc.render import render_url

TEST_URLS = [
    "https://en.wikipedia.org/wiki/Python_(programming_language)",  # true SSR
    "https://react.dev",                                            # Next.js
    "https://vuejs.org",                                            # Vue SPA
]


def _interpret(diff_percent: float) -> str:
    if diff_percent < -2:
        return "Anomaly — investigate"
    if diff_percent < 5:
        return "No JS dependency — fully server-rendered"
    if diff_percent < 30:
        return "Some hydration / lazy content"
    return "Heavy JS dependency — Playwright critical"


async def _measure(url: str) -> dict:
    httpx_result = await crawl_html(url)
    pw_result = await render_url(url)

    httpx_err = httpx_result.get("error")
    pw_err = pw_result.get("error")

    httpx_words = (
        httpx_result.get("content", {}).get("visible_text_words", 0)
        if not httpx_err
        else 0
    )
    # PRIMARY (apples-to-apples): both are "all DOM text, script/style stripped".
    pw_dom_words = pw_result.get("dom_text_words", 0) if not pw_err else 0
    # SECONDARY: what a real user actually sees (CSS-visible inner_text).
    pw_visible_words = pw_result.get("visible_text_words", 0) if not pw_err else 0

    diff_words = pw_dom_words - httpx_words
    diff_percent = (diff_words / max(httpx_words, 1)) * 100

    return {
        "url": url,
        "httpx_words": httpx_words,
        "pw_dom_words": pw_dom_words,
        "pw_visible_words": pw_visible_words,
        "diff_words": diff_words,
        "diff_percent": diff_percent,
        "httpx_ms": httpx_result.get("fetch_time_ms", 0) if not httpx_err else -1,
        "playwright_ms": pw_result.get("render_time_ms", 0) if not pw_err else -1,
        "httpx_err": httpx_err,
        "pw_err": pw_err,
    }


def _short_url(url: str) -> str:
    return url[:42] + "..." if len(url) > 45 else url


def _print_table(rows: list[dict]) -> None:
    header = (
        f"{'URL / layer':<45} {'httpx_words':>12} {'pw_words':>10} "
        f"{'diff%':>9} {'httpx_ms':>9} {'pw_ms':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        url = _short_url(r["url"])
        # Row 1 — DOM level: the real apples-to-apples JS-dependency signal.
        print(
            f"{url:<45} {r['httpx_words']:>12,} {r['pw_dom_words']:>10,} "
            f"{r['diff_percent']:>8.1f}% {r['httpx_ms']:>9,} "
            f"{r['playwright_ms']:>8,}"
        )
        # Row 2 — user-visible: httpx can't render CSS, so no comparable value.
        print(
            f"{'  └─ user-visible (CSS-rendered)':<45} {'N/A':>12} "
            f"{r['pw_visible_words']:>10,} {'—':>9} {'—':>9} {'—':>8}"
        )


async def main() -> None:
    rows = []
    for url in TEST_URLS:
        print(f"Processing {url} ...")
        rows.append(await _measure(url))

    print()
    _print_table(rows)

    print()
    print("Interpretation")
    print("-" * 60)
    for r in rows:
        if r["httpx_err"] or r["pw_err"]:
            note = f"ERROR (httpx={r['httpx_err']!r}, playwright={r['pw_err']!r})"
        else:
            note = f"{r['diff_percent']:+.1f}% -> {_interpret(r['diff_percent'])}"
        print(f"  {r['url']}")
        print(f"    {note}")


if __name__ == "__main__":
    asyncio.run(main())
