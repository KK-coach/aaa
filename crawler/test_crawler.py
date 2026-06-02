"""Manual test harness for the crawler.

Run from the project root:

    python -m crawler.test_crawler
"""

import asyncio
import json

from crawler.crawler import crawl_html

TEST_URLS = [
    # Server-side rendered, schema-rich content page.
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
    # Client-side rendered SPA (React / Next.js style).
    "https://react.dev",
    # Clear article structure — good main-content extraction test.
    "https://blog.cloudflare.com",
    # Error case — should return an http_error result.
    "https://httpbin.org/status/404",
]


def _print_main_content(result: dict) -> None:
    mc = result.get("main_content")
    bp = result.get("boilerplate_detected")
    if mc is None and bp is None:
        return

    if mc is not None:
        preview = mc["text"][:300]
        if len(mc["text"]) > 300:
            preview += " …"
        print("-" * 80)
        print("MAIN CONTENT")
        print(f"  method     : {mc['extraction_method']}")
        print(f"  element    : {mc['html_element_tag']}")
        print(f"  confidence : {mc['confidence']}")
        print(f"  chars/words: {mc['chars']} / {mc['words']}")
        print(f"  preview    : {preview}")

    if bp is not None:
        print("-" * 80)
        print("BOILERPLATE DETECTED")
        for key, val in bp.items():
            print(f"  {key:24}: {val}")
    print("-" * 80)


async def main() -> None:
    for url in TEST_URLS:
        print("=" * 80)
        print(f"CRAWLING: {url}")
        print("=" * 80)
        result = await crawl_html(url)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print()
        _print_main_content(result)
        print()


if __name__ == "__main__":
    asyncio.run(main())
