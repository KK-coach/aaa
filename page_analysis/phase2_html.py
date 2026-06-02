"""AAA-123 Phase 2 — raw-HTML structural + 2 MB cutoff + rendering-mode
measurements. Pure-Python, no LLM, deterministic. Mirrors AAA-42 shape.

Three measurement groups exposed via three pure functions; an async
orchestrator combines them into a single `phase2_html_measurements` dict
for write_audit. Skip-finding contract per sub-measurement: an exception
inside one group does NOT block the audit nor the other two groups.

Sub-step 0 → Sub-step 1 refinements integrated (6 must-haves):
  1) SPA markers v2 — adds `/_next/`, `/_nuxt/`, `/_astro/` URL paths
     (Next.js App Router stable, no `__NEXT_DATA__` blob anymore)
  2) `div_table_suspicious` narrowed to `display:table` only (drops
     `display:grid` which is a legitimate modern layout)
  3) Schema.org expected-types mapping for the full 27-leaf AAA-81 v3
     `page_type` taxonomy (AAA-113 multi_dim_classify input)
  4) Single-pass DOM traversal (selectolax `tree.iter()`) to consolidate
     N separate CSS queries into ONE walk + Python-side partitioning;
     Sub-step 0 measured agrobook at 1.774s, Sub-step 1 target < 1s
  5) Synthetic >2 MB fixture branch verification (covered by unit-test
     companion `aaa123_s1_validate.py`, NOT this module)
  6) Headers-bytes formula documented:
       headers_bytes ≈ Σ (len(K.encode("utf-8")) + len(V.encode("utf-8")) + 4)
                       over response headers
     where +4 = ": " separator (2 B) + "\r\n" line terminator (2 B).
     Does NOT include HTTP/1.1 status line (~17 B) or trailing CRLF.
     Off-by ~30–100 B per response; negligible at 2 MB scale (<0.005%).

Cost: $0 (no LLM, no network, no Firestore writes). Pure compute on the
crawl_result's raw HTML transient. Latency budget < 1s on 1 MB documents.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter, defaultdict
from typing import Literal
from urllib.parse import urlparse

from selectolax.parser import HTMLParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Locked constants
# ---------------------------------------------------------------------------
GOOGLE_2MB_BYTES = 2 * 1024 * 1024  # 2,097,152 (Google 2026-02 official)
INLINE_SCRIPT_CSR_THRESHOLD_BYTES = 100 * 1024  # 100 KB
VISIBLE_TEXT_CSR_THRESHOLD_CHARS = 1000

# AAA-81 v3 → Schema.org expected-types mapping (27-leaf full coverage,
# AAA-123 Sub-step 1 (A) lockdown). Each entry: page_type → list of
# Schema.org types we expect to find in the page's JSON-LD. The
# `schema_pagetype_match` boolean = any-overlap between found and
# expected. Empty list for error_or_redirect_page (no schema expected);
# fallback singleton ["WebPage"] for other_or_unknown.
PAGE_TYPE_TO_SCHEMA_ORG_TYPES: dict[str, list[str]] = {
    "homepage":                  ["WebSite", "Organization", "WebPage"],
    "category_page":             ["CollectionPage", "ItemList", "WebPage"],
    "product_page":              ["Product", "Offer", "AggregateRating"],
    "service_page":              ["Service", "Organization", "WebPage"],
    "landing_page":              ["WebPage", "Service", "SoftwareApplication"],
    "blog_article":              ["BlogPosting", "Article", "Person"],
    "news_article":              ["NewsArticle", "Article", "Person"],
    "guide_or_resource":         ["Article", "HowTo", "WebPage"],
    "glossary_or_wiki_page":     ["DefinedTerm", "Article", "WebPage"],
    "documentation":             ["TechArticle", "Article", "WebPage"],
    "paywalled_or_gated_content":["Article", "NewsArticle", "BlogPosting"],
    "pricing_page":              ["WebPage", "PriceSpecification", "Offer"],
    "comparison_page":           ["Article", "ItemList", "Product"],
    "case_study_page":           ["Article", "Report", "CreativeWork"],
    "testimonial_or_review_page":["Review", "AggregateRating", "Article"],
    "search_results_page":       ["SearchResultsPage", "WebPage"],
    "contact_page":              ["ContactPage", "ContactPoint", "Organization"],
    "location_page":             ["LocalBusiness", "Place", "Organization"],
    "form_page":                 ["WebPage", "ContactPoint"],
    "checkout_or_booking":       ["Order", "Reservation", "WebPage"],
    "account_or_dashboard":      ["WebPage"],
    "legal_page":                ["WebPage"],
    "media_page":                ["MediaObject", "VideoObject", "ImageObject"],
    "event_page":                ["Event", "Place", "Organization"],
    "job_listing_page":          ["JobPosting", "Organization"],
    "error_or_redirect_page":    [],  # no schema expected on error pages
    "other_or_unknown":          ["WebPage"],  # minimal fallback
}

# Multi-lingual generic anchor text dictionary (Sub-step 1 expansion).
# Indexed by audit_language; fall back to "en" then union of all langs.
GENERIC_ANCHOR_TEXTS_BY_LANG: dict[str, frozenset[str]] = {
    "en": frozenset({
        "click here", "read more", "link", "here", "more", "learn more",
        "find out more", "discover more", "see more", "view more",
    }),
    "hu": frozenset({
        "tovább", "kattints ide", "kattints", "ide kattints",
        "olvass tovább", "olvasd el", "itt", "részletek",
        "tudj meg többet",
    }),
    "de": frozenset({
        "hier klicken", "mehr lesen", "mehr", "weiter", "details",
    }),
    "es": frozenset({
        "haz clic aquí", "leer más", "más", "ver más", "detalles",
    }),
    "fr": frozenset({
        "cliquez ici", "lire la suite", "plus", "voir plus", "détails",
    }),
}

# Multi-lingual generic submit-button text dictionary (Sub-step 1 expansion)
GENERIC_SUBMIT_TEXTS_BY_LANG: dict[str, frozenset[str]] = {
    "en": frozenset({"submit", "send", "go", "ok", "next"}),
    "hu": frozenset({"küldés", "elküld", "ok", "tovább", "rendben"}),
    "de": frozenset({"absenden", "senden", "weiter", "ok"}),
    "es": frozenset({"enviar", "siguiente", "ok"}),
    "fr": frozenset({"envoyer", "soumettre", "valider", "ok"}),
}

# SPA framework markers v2 (Sub-step 0 calibration result).
# URL-path markers are STABLE across framework version changes;
# inline-JSON markers are LEGACY fallback. Order does not matter; we
# scan the body string for each marker substring.
SPA_MARKERS_V2: list[tuple[str, str]] = [
    # URL-path markers (most stable; survive App-Router-style refactors)
    ("/_next/",                  "next.js"),
    ("/_nuxt/",                  "nuxt.js"),
    ("/_astro/",                 "astro"),
    # Inline JSON / attribute markers (legacy or version-specific)
    ("__NEXT_DATA__",            "next.js (legacy pages-router)"),
    ("__NUXT__",                 "nuxt.js"),
    ('id="__next"',              "next.js (app-router root)"),
    ('id="__nuxt"',              "nuxt"),
    ("data-reactroot",           "react (legacy attr)"),
    ("data-react-helmet",        "react-helmet"),
    ("ng-version",               "angular"),
    ("data-server-rendered",     "vue (ssr)"),
    ("data-sveltekit",           "sveltekit"),
    ("data-astro",               "astro"),
    # Build/bundler signatures (loose; SPA-typical)
    ("ReactDOM.hydrate",         "react (hydration)"),
    ("__webpack_require__",      "webpack (spa-typical)"),
]

# `div_table_suspicious` narrowed: only `display:table` patterns count.
# `display:grid` and `display:flex` are legitimate modern layouts, NOT
# anti-patterns. Sub-step 0 vercel.com false-positive 17 hits resolved.
_SUSPICIOUS_STYLE_PATTERNS = ("display:table", "display: table")

# Tag-name set we collect during the single-pass DOM walk. Anything not
# in this set is ignored by the walk (modest perf optimization on huge
# documents). Sub-step 1 (4) single-pass traversal pattern.
_INTERESTED_TAGS = frozenset({
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl",
    "table", "thead", "tbody", "tr", "th",
    "div",  # filtered for style="display:table" later
    "blockquote", "figure", "figcaption",
    "strong", "em", "b", "i",
    "a", "form", "input", "button",
    "main", "header", "footer", "nav", "aside",
    "script", "style",
})

# Landmark zone-tag → zone-name map (used during zone-walk for headings)
_LANDMARK_TAG_TO_ZONE: dict[str, str] = {
    "header": "header", "footer": "footer", "nav": "nav",
    "aside": "aside", "main": "main",
}
_LANDMARK_ROLE_TO_ZONE: dict[str, str] = {
    "banner": "header", "contentinfo": "footer",
    "navigation": "nav", "complementary": "aside", "main": "main",
}


def _byte_len(s: str | bytes | None) -> int:
    """UTF-8 byte length of a str (or len of bytes); 0 on None."""
    if s is None:
        return 0
    if isinstance(s, str):
        return len(s.encode("utf-8"))
    if isinstance(s, (bytes, bytearray)):
        return len(s)
    return 0


def _detect_zone(node) -> str:
    """Walk parent chain until first landmark tag/role hits. Default 'other'.
    Used for heading-zone classification (header/footer/nav/main/aside)."""
    cur = node.parent
    while cur is not None:
        tag = cur.tag
        if tag in _LANDMARK_TAG_TO_ZONE:
            return _LANDMARK_TAG_TO_ZONE[tag]
        attrs = cur.attributes or {}
        role = (attrs.get("role") or "").strip().lower()
        if role in _LANDMARK_ROLE_TO_ZONE:
            return _LANDMARK_ROLE_TO_ZONE[role]
        cur = cur.parent
    return "other"


# ---------------------------------------------------------------------------
# A) SEMANTIC STRUCTURE (10 sub-dimensions)
# ---------------------------------------------------------------------------
def measure_semantic_structure(
    tree: HTMLParser,
    page_type: str | None,
    audit_language: str | None,
) -> dict:
    """AAA-123 (A): semantic-structural HTML measurements.

    Implements a single-pass DOM traversal partitioning interesting tags
    into per-tag collections, then computes the 10 sub-dimensions in
    Python from those collections. ~5-10× faster than the Sub-step 0
    per-selector approach on large documents.
    """
    try:
        # === Single-pass DOM walk via ONE multi-selector CSS query ======
        # selectolax Node.iter() yields direct children only, not
        # descendants — using it for the tag-collection walk produced
        # 0-count regression on Sub-step 1 first validation. Switching to
        # a single CSS multi-selector covers all descendants in ONE call
        # at the parser level (still much faster than N separate
        # tree.css() invocations: ONE selector-compile + ONE document
        # walk vs N separate compile+walk cycles).
        # `tree.css("h1, h2, ...")` returns descendants of the document
        # (which is what we want — includes nested elements).
        all_interested_selector = ",".join(_INTERESTED_TAGS)
        all_nodes = tree.css(all_interested_selector)
        nodes_by_tag: dict[str, list] = defaultdict(list)
        # ----- 1) heading_tree + 2) headings_by_zone (document-order) ---
        heading_levels = {"h1", "h2", "h3", "h4", "h5", "h6"}
        heading_tree: list[dict] = []
        h_idx = 0
        for node in all_nodes:
            t = node.tag
            nodes_by_tag[t].append(node)
            if t in heading_levels:
                text = (node.text(strip=True) or "")[:300]
                heading_tree.append({
                    "level": int(t[1]),
                    "text": text,
                    "position": h_idx,
                    "zone": _detect_zone(node),
                    "char_count": len(text),
                })
                h_idx += 1

        by_zone = Counter(h["zone"] for h in heading_tree)
        structural_noise_warning = (
            by_zone.get("header", 0) > 2
            or by_zone.get("footer", 0) > 2
            or by_zone.get("nav", 0) > 2
        )

        # ----- 3) list_structure + heading_stacking_candidate ----------
        list_structure = {
            "ul": len(nodes_by_tag.get("ul", [])),
            "ol": len(nodes_by_tag.get("ol", [])),
            "li": len(nodes_by_tag.get("li", [])),
            "dl": len(nodes_by_tag.get("dl", [])),
        }
        deep_h = [h for h in heading_tree if h["level"] >= 3]
        heading_stacking_candidate = False
        if len(deep_h) >= 3:
            for i in range(len(deep_h) - 2):
                a, b, c = deep_h[i], deep_h[i + 1], deep_h[i + 2]
                if (
                    b["char_count"] < 50 and c["char_count"] < 50
                    and a["position"] + 1 == b["position"]
                    and b["position"] + 1 == c["position"]
                ):
                    heading_stacking_candidate = True
                    break

        # ----- 4) table_structure + div_table_suspicious ----------------
        table_structure = {
            "table": len(nodes_by_tag.get("table", [])),
            "thead": len(nodes_by_tag.get("thead", [])),
            "tbody": len(nodes_by_tag.get("tbody", [])),
            "tr":    len(nodes_by_tag.get("tr", [])),
            "th":    len(nodes_by_tag.get("th", [])),
        }
        # Narrow: only display:table patterns count (S0 calibration)
        div_table_suspicious = 0
        for d in nodes_by_tag.get("div", []):
            attrs = d.attributes or {}
            style = (attrs.get("style") or "").lower()
            if not style:
                continue
            if any(p in style for p in _SUSPICIOUS_STYLE_PATTERNS):
                div_table_suspicious += 1

        # ----- 5) blockquote --------------------------------------------
        bq_nodes = nodes_by_tag.get("blockquote", [])
        blockquote_count = len(bq_nodes)
        blockquote_with_cite = sum(
            1 for q in bq_nodes if (q.attributes or {}).get("cite")
        )

        # ----- 6) figure + figcaption -----------------------------------
        fig_nodes = nodes_by_tag.get("figure", [])
        figure_count = len(fig_nodes)
        figure_with_figcaption = sum(
            1 for f in fig_nodes if f.css_first("figcaption") is not None
        )

        # ----- 7) inline_emphasis + semantic_to_visual_ratio ------------
        strong_n = len(nodes_by_tag.get("strong", []))
        em_n     = len(nodes_by_tag.get("em", []))
        b_n      = len(nodes_by_tag.get("b", []))
        i_n      = len(nodes_by_tag.get("i", []))
        emph_total = strong_n + em_n + b_n + i_n
        semantic_to_visual_ratio = (
            round((strong_n + em_n) / emph_total, 3)
            if emph_total > 0 else None
        )

        # ----- 8) link_semantic -----------------------------------------
        anchor_nodes = nodes_by_tag.get("a", [])
        lang_key = (audit_language or "en").strip().lower()[:2]
        # Use language-specific list + union of all langs as a fallback
        generic_anchors = GENERIC_ANCHOR_TEXTS_BY_LANG.get(
            lang_key, GENERIC_ANCHOR_TEXTS_BY_LANG["en"]
        )
        blank_target_count = 0
        blank_target_unsafe_count = 0
        generic_anchor_text_count = 0
        for a in anchor_nodes:
            attrs = a.attributes or {}
            if (attrs.get("target") or "").lower() == "_blank":
                blank_target_count += 1
                rel = (attrs.get("rel") or "").lower()
                if "noopener" not in rel and "noreferrer" not in rel:
                    blank_target_unsafe_count += 1
            text = (a.text(strip=True) or "").lower()
            if text in generic_anchors:
                generic_anchor_text_count += 1
        link_semantic = {
            "anchor_count": len(anchor_nodes),
            "blank_target_count": blank_target_count,
            "blank_target_unsafe_count": blank_target_unsafe_count,
            "generic_anchor_text_count": generic_anchor_text_count,
        }

        # ----- 9) form_quality_extended ---------------------------------
        form_nodes = nodes_by_tag.get("form", [])
        input_nodes = nodes_by_tag.get("input", [])
        button_nodes = nodes_by_tag.get("button", [])
        input_type_distribution = Counter(
            ((i.attributes or {}).get("type") or "text").lower()
            for i in input_nodes
        )
        generic_submits = GENERIC_SUBMIT_TEXTS_BY_LANG.get(
            lang_key, GENERIC_SUBMIT_TEXTS_BY_LANG["en"]
        )
        submit_total = 0
        submit_generic = 0
        for btn in button_nodes:
            btn_attrs = btn.attributes or {}
            btype = (btn_attrs.get("type") or "").lower()
            if btype == "submit":
                submit_total += 1
                text = (btn.text(strip=True) or "").lower()
                if text in generic_submits:
                    submit_generic += 1
        form_quality_extended = {
            "form_count": len(form_nodes),
            "input_count": len(input_nodes),
            "input_type_distribution": dict(input_type_distribution),
            "submit_button_count": submit_total,
            "submit_button_generic_count": submit_generic,
        }

        # ----- 10) schema_pagetype_match (JSON-LD vs expected) -----------
        jsonld_types: list[str] = []
        for s in nodes_by_tag.get("script", []):
            attrs = s.attributes or {}
            if (attrs.get("type") or "").lower() != "application/ld+json":
                continue
            raw = s.text() or ""
            try:
                parsed = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                continue
            stack = parsed if isinstance(parsed, list) else [parsed]
            while stack:
                it = stack.pop()
                if not isinstance(it, dict):
                    continue
                t = it.get("@type")
                if isinstance(t, str):
                    jsonld_types.append(t)
                elif isinstance(t, list):
                    jsonld_types.extend(x for x in t if isinstance(x, str))
                graph = it.get("@graph")
                if isinstance(graph, list):
                    stack.extend(g for g in graph if isinstance(g, dict))
        jsonld_types_unique = sorted(set(jsonld_types))
        jsonld_type_counts = dict(Counter(jsonld_types))
        # Schema.org expected-types lookup
        if page_type and page_type in PAGE_TYPE_TO_SCHEMA_ORG_TYPES:
            expected_schemas = PAGE_TYPE_TO_SCHEMA_ORG_TYPES[page_type]
            schema_pagetype_match = {
                "expected_schemas": expected_schemas,
                "found_schemas": jsonld_types_unique,
                "matched_types": sorted(
                    set(expected_schemas) & set(jsonld_types_unique)
                ),
                "match": bool(set(expected_schemas) & set(jsonld_types_unique)),
                "skipped": False,
            }
        else:
            schema_pagetype_match = {
                "expected_schemas": [],
                "found_schemas": jsonld_types_unique,
                "matched_types": [],
                "match": False,
                "skipped": True,
                "_skip_reason": (
                    "page_type not provided" if not page_type
                    else f"page_type {page_type!r} not in mapping"
                ),
            }

        return {
            "heading_tree": heading_tree,
            "heading_tree_count": len(heading_tree),
            "headings_by_zone": dict(by_zone),
            "structural_noise_warning": structural_noise_warning,
            "list_structure": list_structure,
            "heading_stacking_candidate": heading_stacking_candidate,
            "table_structure": table_structure,
            "div_table_suspicious": div_table_suspicious,
            "blockquote_count": blockquote_count,
            "blockquote_with_cite": blockquote_with_cite,
            "figure_count": figure_count,
            "figure_with_figcaption": figure_with_figcaption,
            "inline_emphasis": {
                "strong": strong_n, "em": em_n, "b": b_n, "i": i_n,
            },
            "semantic_to_visual_ratio": semantic_to_visual_ratio,
            "link_semantic": link_semantic,
            "form_quality_extended": form_quality_extended,
            "jsonld_types_found": jsonld_types_unique,
            "jsonld_type_counts": jsonld_type_counts,
            "schema_pagetype_match": schema_pagetype_match,
            "_error": None,
        }
    except Exception as e:  # noqa: BLE001 — skip-finding per sub-measurement
        logger.warning("measure_semantic_structure failed: %s", e)
        return {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# B) GOOGLE 2 MB CUTOFF
# ---------------------------------------------------------------------------
def measure_2mb_cutoff(
    body_bytes: bytes,
    headers_bytes: int,
    tree: HTMLParser,
) -> dict:
    """AAA-123 (B): Google 2026-02 2 MB-cutoff measurement.

    Inline CSS (`<style>`) + inline JS (`<script>` body, NOT `<script src>`)
    + base64 image data URIs counted toward inline_total_bytes (which is
    PART of the raw_html_bytes_uncompressed, NOT additive to it).
    total_counting_toward_2mb = raw_html_bytes + http_response_headers_bytes
    (per Google's 2 MB budget definition).

    If the budget is exceeded, computes cutoff_position (char offset, nearest
    heading before cutoff) and content_after_cutoff_pct via a head-chunk
    re-parse of the doc up to the budget boundary.
    """
    try:
        raw_html_bytes = len(body_bytes)
        # Inline content sub-measurements
        inline_css_bytes = 0
        inline_js_bytes = 0
        for s in tree.css("style"):
            inline_css_bytes += _byte_len(s.text() or "")
        for s in tree.css("script"):
            if not (s.attributes or {}).get("src"):
                inline_js_bytes += _byte_len(s.text() or "")
        base64_bytes = 0
        for img in tree.css("img"):
            src = (img.attributes or {}).get("src") or ""
            if src.startswith("data:image"):
                base64_bytes += _byte_len(src)
        # also inline background-image data URIs in [style] attrs
        for el in tree.css("[style]"):
            style = (el.attributes or {}).get("style") or ""
            if "data:image" in style:
                for m in re.finditer(r"data:image[^)\"'\s]+", style):
                    base64_bytes += _byte_len(m.group(0))

        inline_total = inline_css_bytes + inline_js_bytes + base64_bytes
        total_counting_toward_2mb = raw_html_bytes + headers_bytes
        exceeds = total_counting_toward_2mb > GOOGLE_2MB_BYTES

        cutoff_position = None
        content_after_pct = None
        if exceeds:
            budget = GOOGLE_2MB_BYTES - headers_bytes
            if budget > 0:
                head_chunk = body_bytes[:budget]
                head_str = head_chunk.decode("utf-8", errors="ignore")
                char_offset = len(head_str)
                cut_tree = HTMLParser(head_str)
                head_headings = cut_tree.css("h1, h2, h3, h4, h5, h6")
                nearest_heading = (
                    head_headings[-1].text(strip=True)[:200]
                    if head_headings else None
                )
                # Nearest <section> with id or aria-label as a section name
                head_sections = cut_tree.css("section")
                nearest_section = None
                if head_sections:
                    last_section = head_sections[-1]
                    sa = last_section.attributes or {}
                    nearest_section = (
                        sa.get("id") or sa.get("aria-label") or "(unnamed)"
                    )
                cutoff_position = {
                    "char_offset": char_offset,
                    "nearest_heading_before_cutoff": nearest_heading,
                    "nearest_section_before_cutoff": nearest_section,
                }
            # content_after_cutoff_pct
            full_text = tree.body.text() if tree.body else ""
            if full_text and cutoff_position:
                head_text = HTMLParser(
                    body_bytes[:(GOOGLE_2MB_BYTES - headers_bytes)].decode(
                        "utf-8", errors="ignore"
                    )
                )
                head_body_text = (
                    head_text.body.text() if head_text.body else ""
                )
                full_chars = len(full_text)
                head_chars = len(head_body_text)
                if full_chars > 0:
                    tail_pct = max(0.0, 1.0 - (head_chars / full_chars))
                    content_after_pct = round(tail_pct * 100, 2)

        return {
            "raw_html_bytes_uncompressed": raw_html_bytes,
            "http_response_headers_bytes": headers_bytes,
            "inline_css_bytes": inline_css_bytes,
            "inline_js_bytes": inline_js_bytes,
            "inline_base64_image_bytes": base64_bytes,
            "inline_total_bytes": inline_total,
            "total_counting_toward_2mb": total_counting_toward_2mb,
            "google_2mb_threshold": GOOGLE_2MB_BYTES,
            "exceeds_2mb_cutoff": exceeds,
            "cutoff_position": cutoff_position,
            "content_after_cutoff_pct": content_after_pct,
            "_error": None,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("measure_2mb_cutoff failed: %s", e)
        return {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# C) RENDERING MODE
# ---------------------------------------------------------------------------
def measure_rendering_mode(body_text: str, tree: HTMLParser) -> dict:
    """AAA-123 (C): CSR-likelihood + SPA-framework signals.

    is_csr_likely heuristic: visible_text < 1000 chars AND inline_script >
    100 KB. Sub-step 0 validated 3/3 verdicts on canary URLs.
    SPA signals are informational/descriptive (NOT gate-deciding for the
    is_csr_likely verdict — Sub-step 0.5 decision).
    """
    try:
        # 1) visible_text — strip script/style/noscript, then body.text()
        work = HTMLParser(body_text)
        for tag in ("script", "style", "noscript"):
            for n in work.css(tag):
                n.decompose()
        visible_text = (work.body.text(strip=True) if work.body else "") or ""
        visible_chars = len(visible_text)

        # 2) text_to_markup_ratio
        raw_len = len(body_text)
        ratio = round(visible_chars / raw_len, 4) if raw_len > 0 else 0.0

        # 3) body_main_content_chars — zone-aware
        if tree.css_first("main") is not None:
            main_text = (tree.css_first("main").text() or "")
        elif tree.body is not None:
            # body minus header/footer/nav/aside, scripts, styles
            body_clone_html = tree.body.html or ""
            bc = HTMLParser(body_clone_html)
            for tag in ("header", "footer", "nav", "aside", "script",
                        "style", "noscript"):
                for n in bc.css(tag):
                    n.decompose()
            main_text = (bc.body.text(strip=True) if bc.body else "") or ""
        else:
            main_text = ""
        main_chars = len((main_text or "").strip())

        # 4) inline_script_total_bytes (NOT <script src>)
        inline_script_bytes = 0
        for s in tree.css("script"):
            if not (s.attributes or {}).get("src"):
                inline_script_bytes += _byte_len(s.text() or "")

        # 5) is_csr_likely
        is_csr = (
            visible_chars < VISIBLE_TEXT_CSR_THRESHOLD_CHARS
            and inline_script_bytes > INLINE_SCRIPT_CSR_THRESHOLD_BYTES
        )

        # 6) spa_framework_signals — v2 marker list scan on raw body
        signals: list[dict] = []
        seen_frameworks: set[str] = set()
        for marker, framework in SPA_MARKERS_V2:
            if marker in body_text:
                n = body_text.count(marker)
                signals.append({
                    "marker": marker, "framework": framework, "count": n,
                })
                seen_frameworks.add(framework.split(" ")[0])  # crude root name

        return {
            "raw_html_visible_text_chars": visible_chars,
            "raw_html_text_to_markup_ratio": ratio,
            "body_main_content_chars": main_chars,
            "inline_script_total_bytes": inline_script_bytes,
            "is_csr_likely": is_csr,
            "ai_crawler_visibility_warning": is_csr,
            "spa_framework_signals": signals,
            "spa_frameworks_detected": sorted(seen_frameworks),
            "_error": None,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("measure_rendering_mode failed: %s", e)
        return {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Orchestrator (single entry point for Discovery integration)
# ---------------------------------------------------------------------------
async def run_phase2_measurements(
    crawl_result: dict,
    page_type: str | None = None,
    audit_language: str | None = None,
) -> dict:
    """Combine A + B + C into `audit_output.phase2_html_measurements`.

    crawl_result expected keys:
      - `_raw_html_transient` (preferred) OR `raw_html` (fallback) — full
        raw HTML string from the httpx fetch (AAA-42 same source)
      - `response_headers_bytes_estimate` (optional; defaults to 0 if missing)

    page_type: AAA-81 v3 leaf string (one of 27 enum values). Used for
    Schema.org expected-types mapping in section A's schema_pagetype_match.

    audit_language: ISO-639-1 lowercase (e.g. "en", "hu"). Used for the
    multi-lingual generic-anchor + submit-button dictionaries.

    Returns a dict with keys `semantic_structure`, `google_2mb_cutoff`,
    `rendering_mode`. Each sub-key carries its own `_error` field on
    skip-finding (independent failure isolation).
    """
    raw_html = (
        crawl_result.get("_raw_html_transient")
        or crawl_result.get("raw_html")
        or ""
    )
    if isinstance(raw_html, bytes):
        raw_bytes = raw_html
        body_text = raw_html.decode("utf-8", errors="ignore")
    else:
        body_text = raw_html or ""
        raw_bytes = body_text.encode("utf-8") if body_text else b""

    headers_bytes = int(crawl_result.get("response_headers_bytes_estimate") or 0)

    if not body_text:
        # No raw HTML to measure on — return all-skipped
        skip = {"_error": "no raw_html available in crawl_result"}
        return {
            "semantic_structure": skip,
            "google_2mb_cutoff": skip,
            "rendering_mode": skip,
        }

    tree = HTMLParser(body_text)
    # Run the three measurements; each has its own skip-finding contract,
    # so a failure in one does NOT block the other two.
    semantic = measure_semantic_structure(tree, page_type, audit_language)
    cutoff = measure_2mb_cutoff(raw_bytes, headers_bytes, tree)
    rendering = measure_rendering_mode(body_text, tree)
    return {
        "semantic_structure": semantic,
        "google_2mb_cutoff": cutoff,
        "rendering_mode": rendering,
    }
