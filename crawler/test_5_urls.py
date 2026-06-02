"""Run the crawler on 5 real-world URLs and print a summary report.

Run from project root:  python -m crawler.test_5_urls
"""

import asyncio

from crawler import crawl_html

URLS = [
    "https://www.agrobook.hu",
    "https://kk.coach",
    "https://www.aboutyou.hu",
    "https://www.taxually.com",
    "https://vercel.com/products/vercel-platform",
]


def _clip(text: str, n: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    return (text[: n - 1] + "…") if len(text) > n else text


def summarize(r: dict) -> dict:
    if r.get("error"):
        return {
            "url": r.get("url"),
            "error": f"[{r.get('error_type')}] {r.get('error')}",
        }

    gl = r.get("googlebot_index_limit", {})
    mc = r.get("main_content", {})
    canon = r.get("technical", {}).get("canonical", {})
    desc = r.get("meta", {}).get("description", {}).get("text", "")
    return {
        "url": r["url"],
        "status_code": r.get("status_code"),
        "fetch_time_ms": r.get("fetch_time_ms"),
        "title": _clip(r.get("meta", {}).get("title", {}).get("text", ""), 60),
        "meta_description": _clip(desc, 80) if desc else "[missing]",
        "visible_text_words": r.get("content", {}).get("visible_text_words"),
        "main_content_words": mc.get("words"),
        "extraction_method": mc.get("extraction_method"),
        "confidence": mc.get("confidence"),
        "canonical_present": canon.get("present"),
        "canonical_self_ref": canon.get("self_referencing"),
        "redirect_chain": r.get("technical", {}).get("redirect_chain", []),
        "schema_types": r.get("schema_markup", {}).get(
            "schema_types_detected", []
        ),
        "spa_indicators": r.get("javascript_indicators", {}).get(
            "spa_indicators", []
        ),
        "risk_level": gl.get("risk_level"),
        "uncompressed_html_mb": round(
            gl.get("raw_html_bytes", 0) / 1_048_576, 3
        ),
        "internal_links": r.get("links", {}).get("internal_count"),
        "external_links": r.get("links", {}).get("external_count"),
        "alt_coverage_percent": r.get("images", {}).get(
            "alt_coverage_percent"
        ),
    }


def _print_detail(s: dict) -> None:
    print("=" * 78)
    print(s["url"])
    print("-" * 78)
    if s.get("error"):
        print(f"  ERROR: {s['error']}")
        return
    print(f"  status={s['status_code']}  fetch={s['fetch_time_ms']} ms")
    print(f"  title           : {s['title']}")
    print(f"  meta_description: {s['meta_description']}")
    print(
        f"  words           : visible={s['visible_text_words']}  "
        f"main_content={s['main_content_words']}"
    )
    print(
        f"  main extraction : {s['extraction_method']} "
        f"(confidence {s['confidence']})"
    )
    print(
        f"  canonical       : present={s['canonical_present']} "
        f"self_ref={s['canonical_self_ref']}"
    )
    print(f"  redirect_chain  : {s['redirect_chain']}")
    print(f"  schema_types    : {s['schema_types'] or '[]'}")
    print(f"  spa_indicators  : {s['spa_indicators'] or '[]'}")
    print(
        f"  2MB risk        : {s['risk_level']} "
        f"({s['uncompressed_html_mb']} MB uncompressed)"
    )
    print(
        f"  links           : internal={s['internal_links']} "
        f"external={s['external_links']}"
    )
    print(f"  img alt coverage: {s['alt_coverage_percent']}%")


def _md_table(rows: list[dict]) -> str:
    head = (
        "| URL | Status | Title | Vis/Main words | Extraction (conf) | "
        "Canonical | Schema | SPA | 2MB risk (MB) | Int/Ext links | "
        "Alt % |\n"
    )
    head += "|" + "---|" * 11 + "\n"
    body = ""
    for s in rows:
        short = s["url"].replace("https://", "")
        if s.get("error"):
            body += f"| {short} | ERROR | {s['error']} | | | | | | | | |\n"
            continue
        schema = ", ".join(s["schema_types"][:3]) or "—"
        spa = ", ".join(s["spa_indicators"]) or "—"
        body += (
            f"| {short} | {s['status_code']} | {s['title'][:32]} | "
            f"{s['visible_text_words']}/{s['main_content_words']} | "
            f"{s['extraction_method']} ({s['confidence']}) | "
            f"P={s['canonical_present']},S={s['canonical_self_ref']} | "
            f"{schema} | {spa} | {s['risk_level']} "
            f"({s['uncompressed_html_mb']}) | "
            f"{s['internal_links']}/{s['external_links']} | "
            f"{s['alt_coverage_percent']} |\n"
        )
    return head + body


async def main() -> None:
    rows = []
    for url in URLS:
        r = await crawl_html(url)
        s = summarize(r)
        rows.append(s)
        _print_detail(s)

    print("\n\n## Crawler summary — 5 URLs\n")
    print(_md_table(rows))


if __name__ == "__main__":
    asyncio.run(main())
