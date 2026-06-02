"""AAA-51 Step 1 measurement only. No code changes to the pipeline.

Reproduces the exact content the Gemini synthesis calls received per URL
(crawl -> AAA-18 escalation check -> Playwright if triggered -> _select_content)
and provenance-checks the 3 saved stability summaries against it.
"""

import asyncio
import json
import re
import unicodedata
from pathlib import Path

from crawler import crawl_html
from crawler.crawler import parse_rendered_html
from playwright_poc.render import render_url
from page_analysis._gemini import select_body

STAB = Path("stability")
URLS = {
    "https://www.agrobook.hu": "www-agrobook-hu",
    "https://kk.coach": "kk-coach",
    "https://www.aboutyou.hu": "www-aboutyou-hu",
    "https://www.taxually.com": "www-taxually-com",
    "https://vercel.com/products/vercel-platform":
        "vercel-com_products_vercel-platform",
}

# audit / SEO jargon + generic words that are NOT site entity claims
STOP = {
    "the", "a", "an", "and", "or", "seo", "geo", "ux", "cro", "ai", "audit",
    "summary", "core", "web", "vitals", "page", "speed", "pagespeed",
    "schema", "content", "target", "brand", "primary", "secondary", "https",
    "canonical", "playwright", "javascript", "google", "search", "console",
    "analytics", "overview", "recommendation", "findings", "actionable",
    "technical", "performance", "mobile", "desktop", "structured", "data",
    "keyword", "keywords", "topic", "cluster", "client", "site", "website",
    "url", "html", "json", "ld", "meta", "title", "description", "h1",
    "organic", "growth", "key", "main", "report", "identification",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower())


def _entities(summary: str) -> set[str]:
    """Candidate named entities: TitleCase 1-3-grams + *.js / brandish."""
    ents = set()
    for m in re.findall(r"\b([A-Z][\w.+&-]*(?:\s+[A-Z][\w.+&-]*){0,2})\b",
                        summary):
        t = m.strip()
        words = [w for w in re.split(r"\s+", t) if w]
        if all(_norm(w) in STOP for w in words):
            continue
        if len(t) < 3:
            continue
        ents.add(t)
    for m in re.findall(r"\b[\w.+-]+\.js\b", summary, re.I):
        ents.add(m)
    return ents


def _escalates(crawl: dict) -> bool:
    mc = crawl.get("main_content") or {}
    spa = (crawl.get("javascript_indicators") or {}).get("spa_indicators", [])
    return (
        mc.get("extraction_method") == "fallback_full_body"
        or (mc.get("confidence") or 1.0) < 0.5
        or bool(spa)
    )


async def measure(url: str, slug: str) -> dict:
    crawl = await crawl_html(url)
    render = "httpx"
    active = crawl
    if _escalates(crawl):
        rendered = await render_url(url)
        if not rendered.get("error"):
            parsed = parse_rendered_html(
                url, rendered.get("rendered_html", ""),
                rendered.get("status_code", 200),
            )
            a_old = ((active.get("main_content") or {}).get("confidence") or 0)
            a_new = ((parsed.get("main_content") or {}).get("confidence") or 0)
            o_w = (active.get("main_content") or {}).get("words") or 0
            n_w = (parsed.get("main_content") or {}).get("words") or 0
            if not parsed.get("error") and (
                a_new > a_old or (a_new == a_old and n_w > o_w)
            ):
                active = parsed
                render = "playwright_escalation"
            else:
                render = "playwright_tried_not_promoted"

    body = select_body(active, 3000)  # what the prompt actually receives
    final_text = body["text"]
    final_words = len(final_text.split())
    raw_bytes = (active.get("googlebot_index_limit") or {}).get(
        "raw_html_bytes"
    ) or (active.get("content") or {}).get("raw_html_bytes")
    mc = active.get("main_content") or {}
    vis_words = (active.get("content") or {}).get("visible_text_words")
    schema_types = (active.get("schema_markup") or {}).get(
        "schema_types_detected", []
    )
    headings = active.get("headings") or {}
    para_like = sum(len(headings.get(f"h{i}", [])) for i in range(1, 7))

    norm_final = _norm(final_text)
    leaks: dict[str, list[str]] = {}
    for n in (1, 2, 3):
        f = STAB / slug / f"run-{n}.json"
        if not f.exists():
            continue
        rec = json.loads(f.read_text(encoding="utf-8"))
        sm = rec.get("summary_markdown", "")
        miss = sorted(
            e for e in _entities(sm) if _norm(e) not in norm_final
        )
        leaks[f"run{n}"] = miss

    return {
        "url": url,
        "render": render,
        "raw_bytes": raw_bytes,
        "final_words": final_words,
        "select_source": body["source"],
        "thin_flag_AAA18": body["thin"],
        "mc_method": mc.get("extraction_method"),
        "mc_conf": mc.get("confidence"),
        "mc_words": mc.get("words"),
        "visible_text_words": vis_words,
        "schema_type_count": len(schema_types),
        "heading_count": para_like,
        "html_to_text_ratio": (
            round((raw_bytes or 0) / max(len(final_text), 1), 1)
        ),
        "leaks_per_run": leaks,
    }


async def main() -> None:
    rows = []
    for url, slug in URLS.items():
        print(f"measuring {url} ...", flush=True)
        rows.append(await measure(url, slug))
    Path("_aaa51_step1.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
