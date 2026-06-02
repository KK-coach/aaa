"""AAA-123 Sub-step 0 — capability probe (A + B + C measurement dimensions).

Throw-away exploration script. NOT a production module. NO modifications to
agents/, NO commits to page_analysis/. Pure raw-HTTP + selectolax. $0 cost.
"""
import asyncio
import json
import re
import time
from collections import Counter

import httpx
from selectolax.parser import HTMLParser

URLS = [
    ("agrobook.hu",  "https://agrobook.hu",  "MarketplacePage"),
    ("vercel.com",   "https://vercel.com",   "LandingPage"),
    ("kk.coach",     "https://kk.coach",     "ServicePage"),
]

# Google 2026-02 official 2 MB cutoff
GOOGLE_2MB_BYTES = 2 * 1024 * 1024  # 2,097,152

# Generic/low-quality anchor texts (a-priori list, multi-lingual)
GENERIC_ANCHOR_TEXTS = frozenset({
    "click here", "read more", "link", "here", "more", "learn more",
    "tovább", "kattints ide", "olvass tovább", "itt", "kattints",
})

# SPA framework markers
SPA_MARKERS = [
    ("__next_data__", "next.js"),
    ("_nuxt", "nuxt.js"),
    ("_astro", "astro"),
    ("data-reactroot", "react (legacy attr)"),
    ("react-root", "react (id)"),
    ("ng-app", "angular"),
    ("ng-version", "angular"),
    ('data-server-rendered="true"', "vue (ssr-flagged)"),
    ('id="app"', "vue/spa-common (weak)"),
    ("data-vue", "vue"),
    ('id="__nuxt"', "nuxt"),
    ('id="root"', "react/cra-common (weak)"),
    ("svelte-", "svelte"),
    ("data-sveltekit", "sveltekit"),
    ("data-fresh", "fresh (deno)"),
]


def _byte_len(s):
    if s is None:
        return 0
    if isinstance(s, str):
        return len(s.encode("utf-8"))
    if isinstance(s, (bytes, bytearray)):
        return len(s)
    return 0


def fetch(url):
    """Raw HTTP GET — decompressed body bytes + raw response headers."""
    with httpx.Client(follow_redirects=True, timeout=30.0,
                      headers={"User-Agent": "AAA-123-probe/0"}) as cli:
        t0 = time.perf_counter()
        r = cli.get(url)
        wall = time.perf_counter() - t0
    # r.content = decompressed bytes (httpx handles gzip/br transparently)
    return {
        "final_url": str(r.url),
        "status": r.status_code,
        "body_bytes": r.content,            # decompressed
        "body_text": r.text,                 # str, decoded
        "headers_bytes_estimate": sum(
            _byte_len(k) + _byte_len(v) + 4  # `K: V\r\n` per header
            for k, v in r.headers.items()
        ),
        "headers_repr": dict(r.headers),
        "fetch_wall_s": round(wall, 3),
    }


# === A) SEMANTIC STRUCTURE =================================================

ZONE_TAGS = {
    "header": "header", "footer": "footer", "nav": "nav", "aside": "aside",
    "main":   "main",
}


def detect_zone(node):
    """Walk up parent chain; first matching landmark tag wins. else 'other'."""
    cur = node.parent
    while cur is not None:
        if cur.tag in ZONE_TAGS:
            return ZONE_TAGS[cur.tag]
        # role-based landmarks
        role = (cur.attributes.get("role") or "").strip().lower() \
            if cur.attributes else ""
        if role in ("banner", "header"):
            return "header"
        if role in ("contentinfo", "footer"):
            return "footer"
        if role == "navigation":
            return "nav"
        if role == "complementary":
            return "aside"
        if role == "main":
            return "main"
        cur = cur.parent
    return "other"


def measure_a(tree):
    out = {}

    # 1) heading_tree + 2) by_zone
    heading_tree = []
    h_idx = 0
    for h in tree.css("h1, h2, h3, h4, h5, h6"):
        text = (h.text(strip=True) or "")[:300]
        level = int(h.tag[1])
        heading_tree.append({
            "level": level,
            "text": text,
            "position": h_idx,
            "zone": detect_zone(h),
            "char_count": len(text),
        })
        h_idx += 1
    out["heading_tree_count"] = len(heading_tree)
    out["heading_tree_sample_first3"] = heading_tree[:3]
    by_zone = Counter(h["zone"] for h in heading_tree)
    out["headings_by_zone"] = dict(by_zone)
    out["structural_noise_warning"] = (
        by_zone.get("header", 0) > 2 or by_zone.get("footer", 0) > 2 or
        by_zone.get("nav", 0) > 2
    )

    # 3) list_structure + heading_stacking_candidate
    ul = len(tree.css("ul"))
    ol = len(tree.css("ol"))
    li = len(tree.css("li"))
    dl = len(tree.css("dl"))
    out["list_structure"] = {"ul": ul, "ol": ol, "li": li, "dl": dl}
    # heading_stacking: 3+ consecutive Hn (n>=3) with <50 chars between
    deep_h = [h for h in heading_tree if h["level"] >= 3]
    stacking = False
    if len(deep_h) >= 3:
        for i in range(len(deep_h) - 2):
            a, b, c = deep_h[i:i + 3]
            if (b["char_count"] < 50 and c["char_count"] < 50 and
                    a["position"] + 1 == b["position"] and
                    b["position"] + 1 == c["position"]):
                stacking = True
                break
    out["heading_stacking_candidate"] = stacking

    # 4) table_structure + div_table_suspicious
    tables = len(tree.css("table"))
    thead = len(tree.css("thead"))
    tbody = len(tree.css("tbody"))
    tr = len(tree.css("tr"))
    th = len(tree.css("th"))
    out["table_structure"] = {"table": tables, "thead": thead,
                              "tbody": tbody, "tr": tr, "th": th}
    div_table_susp = 0
    for d in tree.css("div[style]"):
        style = (d.attributes.get("style") or "").lower()
        if "display:table" in style or "display: table" in style \
           or "display:grid" in style or "display: grid" in style:
            div_table_susp += 1
    out["div_table_suspicious"] = div_table_susp

    # 5) blockquote
    bq = tree.css("blockquote")
    out["blockquote_count"] = len(bq)
    out["blockquote_with_cite"] = sum(
        1 for q in bq if (q.attributes or {}).get("cite")
    )

    # 6) figure
    figs = tree.css("figure")
    out["figure_count"] = len(figs)
    out["figure_with_figcaption"] = sum(
        1 for f in figs if f.css_first("figcaption") is not None
    )

    # 7) inline_emphasis
    strong = len(tree.css("strong"))
    em = len(tree.css("em"))
    b = len(tree.css("b"))
    i = len(tree.css("i"))
    total = strong + em + b + i
    out["inline_emphasis"] = {"strong": strong, "em": em, "b": b, "i": i}
    out["semantic_to_visual_ratio"] = (
        round((strong + em) / total, 3) if total > 0 else None
    )

    # 8) link_semantic
    anchors = tree.css("a")
    a_total = len(anchors)
    blank_target = 0
    blank_target_unsafe = 0
    generic_count = 0
    for a in anchors:
        attrs = a.attributes or {}
        if (attrs.get("target") or "").lower() == "_blank":
            blank_target += 1
            rel = (attrs.get("rel") or "").lower()
            if "noopener" not in rel and "noreferrer" not in rel:
                blank_target_unsafe += 1
        text = (a.text(strip=True) or "").lower()
        if text in GENERIC_ANCHOR_TEXTS:
            generic_count += 1
    out["link_semantic"] = {
        "anchor_count": a_total,
        "blank_target_count": blank_target,
        "blank_target_unsafe_count": blank_target_unsafe,
        "generic_anchor_text_count": generic_count,
    }

    # 9) form_quality_extended
    forms = tree.css("form")
    inputs = tree.css("input")
    buttons = tree.css("button")
    submit_generic = 0
    submit_total = 0
    for btn in buttons:
        btype = ((btn.attributes or {}).get("type") or "").lower()
        if btype == "submit":
            submit_total += 1
            text = (btn.text(strip=True) or "").lower()
            if text in ("submit", "send", "küldés", "go", "ok"):
                submit_generic += 1
    input_types = Counter(
        ((i.attributes or {}).get("type") or "text").lower()
        for i in inputs
    )
    out["form_quality_extended"] = {
        "form_count": len(forms),
        "input_count": len(inputs),
        "input_type_distribution": dict(input_types),
        "submit_button_count": submit_total,
        "submit_button_generic_count": submit_generic,
    }

    # 10) schema_pagetype_match — extract JSON-LD @type values
    jsonld_types = []
    for s in tree.css('script[type="application/ld+json"]'):
        raw = s.text() or ""
        try:
            parsed = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            if isinstance(t, str):
                jsonld_types.append(t)
            elif isinstance(t, list):
                jsonld_types.extend(x for x in t if isinstance(x, str))
            # @graph case
            for sub in (it.get("@graph") or []):
                if isinstance(sub, dict):
                    tt = sub.get("@type")
                    if isinstance(tt, str):
                        jsonld_types.append(tt)
                    elif isinstance(tt, list):
                        jsonld_types.extend(x for x in tt if isinstance(x, str))
    out["jsonld_types_found"] = jsonld_types

    return out


# === B) 2 MB CUTOFF ========================================================

def measure_b(fetch_result, tree):
    raw_html_bytes = len(fetch_result["body_bytes"])
    headers_bytes = fetch_result["headers_bytes_estimate"]

    # Inline CSS, JS, base64
    inline_css = sum(_byte_len(s.text() or "") for s in tree.css("style"))
    inline_js = sum(
        _byte_len(s.text() or "")
        for s in tree.css("script")
        if not (s.attributes or {}).get("src")
    )
    # base64 image data URIs anywhere in img src / inline style
    base64_bytes = 0
    for img in tree.css("img"):
        src = (img.attributes or {}).get("src") or ""
        if src.startswith("data:image"):
            base64_bytes += _byte_len(src)
    # also in inline style background-image
    for el in tree.css("[style]"):
        style = (el.attributes or {}).get("style") or ""
        if "data:image" in style:
            # crude: count the data: substrings
            for m in re.finditer(r"data:image[^)\"'\s]+", style):
                base64_bytes += _byte_len(m.group(0))

    inline_total = inline_css + inline_js + base64_bytes
    total_counting_toward_2mb = raw_html_bytes + headers_bytes
    exceeds = total_counting_toward_2mb > GOOGLE_2MB_BYTES

    # Cutoff position
    cutoff_info = None
    if exceeds:
        # Available bytes for HTML body = 2MB - headers
        budget = GOOGLE_2MB_BYTES - headers_bytes
        if budget > 0:
            cut_off_at_byte = budget
            # Find the byte offset in the decompressed body
            head_chunk = fetch_result["body_bytes"][:cut_off_at_byte]
            # Estimate the character offset (UTF-8 may have multibyte)
            try:
                head_str = head_chunk.decode("utf-8", errors="ignore")
                char_offset = len(head_str)
            except Exception:
                char_offset = cut_off_at_byte
            # Find nearest heading before the cutoff
            cut_tree = HTMLParser(head_str)
            head_headings = cut_tree.css("h1, h2, h3, h4, h5, h6")
            nearest_heading = head_headings[-1].text(strip=True)[:120] \
                if head_headings else None
            cutoff_info = {
                "char_offset": char_offset,
                "nearest_heading_before_cutoff": nearest_heading,
                "nearest_section_before_cutoff": None,  # TODO if useful
            }

    # content_after_cutoff_pct — only if exceeds
    content_after_pct = None
    if exceeds and cutoff_info:
        full_text = tree.body.text() if tree.body else (fetch_result["body_text"])
        full_chars = len(full_text)
        if full_chars > 0:
            tail_pct = max(
                0.0, 1.0 - (cutoff_info["char_offset"] / full_chars)
            )
            content_after_pct = round(tail_pct * 100, 2)

    return {
        "raw_html_bytes_uncompressed": raw_html_bytes,
        "http_response_headers_bytes": headers_bytes,
        "inline_css_bytes": inline_css,
        "inline_js_bytes": inline_js,
        "inline_base64_image_bytes": base64_bytes,
        "inline_total_bytes": inline_total,
        "total_counting_toward_2mb": total_counting_toward_2mb,
        "google_2mb_threshold": GOOGLE_2MB_BYTES,
        "exceeds_2mb_cutoff": exceeds,
        "cutoff_position": cutoff_info,
        "content_after_cutoff_pct": content_after_pct,
    }


# === C) RENDERING MODE =====================================================

def measure_c(fetch_result, tree):
    body_text = fetch_result["body_text"]

    # 1) visible_text — strip script/style/comments via selectolax
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
    main_node = tree.css_first("main") or tree.body
    main_text = ""
    if main_node is not None:
        # Strip script/style under main too
        clone_text = main_node.text()
        # Subtract header/footer/nav text from body if no <main>
        if tree.css_first("main") is None and tree.body is not None:
            # body minus header/footer/nav
            body_clone_html = tree.body.html or ""
            bc = HTMLParser(body_clone_html)
            for tag in ("header", "footer", "nav", "aside", "script", "style"):
                for n in bc.css(tag):
                    n.decompose()
            main_text = (bc.body.text(strip=True) if bc.body else "") or ""
        else:
            main_text = clone_text or ""
    main_chars = len(main_text.strip())

    # 4) inline_script_total_bytes — sum of <script> with body
    inline_script_bytes = sum(
        _byte_len(s.text() or "")
        for s in tree.css("script")
        if not (s.attributes or {}).get("src")
    )

    # 5) is_csr_likely
    is_csr = (visible_chars < 1000) and (inline_script_bytes > 100 * 1024)

    # 6) spa_framework_signals — search both attributes and inline JS body
    signals = []
    body_lower = body_text  # case-sensitive matching; many markers are exact
    for marker, label in SPA_MARKERS:
        if marker in body_lower:
            signals.append({"marker": marker, "framework": label})

    return {
        "raw_html_visible_text_chars": visible_chars,
        "raw_html_text_to_markup_ratio": ratio,
        "body_main_content_chars": main_chars,
        "inline_script_total_bytes": inline_script_bytes,
        "is_csr_likely": is_csr,
        "ai_crawler_visibility_warning": is_csr,
        "spa_framework_signals": signals,
    }


# === ORCHESTRATOR ==========================================================

def probe_url(label, url, expected_page_type):
    t0 = time.perf_counter()
    fetch_result = fetch(url)
    if fetch_result["status"] >= 400:
        return {"label": label, "url": url,
                "error": f"HTTP {fetch_result['status']}"}
    tree = HTMLParser(fetch_result["body_text"])
    A = measure_a(tree)
    A["expected_page_type_synthetic"] = expected_page_type
    A["schema_pagetype_match"] = expected_page_type in A["jsonld_types_found"]
    B = measure_b(fetch_result, tree)
    C = measure_c(fetch_result, tree)
    measurement_wall = round(time.perf_counter() - t0, 3)
    return {
        "label": label, "url": url, "final_url": fetch_result["final_url"],
        "status": fetch_result["status"],
        "fetch_wall_s": fetch_result["fetch_wall_s"],
        "measurement_wall_s": measurement_wall,
        "A_semantic": A, "B_cutoff": B, "C_rendering": C,
    }


def main():
    results = []
    for label, url, expected_pt in URLS:
        print(f"=== probing {label} ({url}) ===")
        try:
            r = probe_url(label, url, expected_pt)
            results.append(r)
            print(f"  status={r.get('status')} fetch={r.get('fetch_wall_s')}s "
                  f"measure={r.get('measurement_wall_s')}s")
            if r.get("error"):
                print(f"  ERROR: {r['error']}")
                continue
            # quick summary
            A = r["A_semantic"]; B = r["B_cutoff"]; C = r["C_rendering"]
            print(f"  heading_tree_count={A['heading_tree_count']}")
            print(f"  raw_html_bytes={B['raw_html_bytes_uncompressed']} "
                  f"headers_bytes={B['http_response_headers_bytes']} "
                  f"inline_total={B['inline_total_bytes']}")
            print(f"  total_counting_toward_2mb={B['total_counting_toward_2mb']} "
                  f"exceeds_2mb={B['exceeds_2mb_cutoff']}")
            print(f"  visible_text={C['raw_html_visible_text_chars']} chars  "
                  f"inline_script_bytes={C['inline_script_total_bytes']}  "
                  f"is_csr_likely={C['is_csr_likely']}")
            print(f"  spa_signals={[s['framework'] for s in C['spa_framework_signals']][:5]}")
            print(f"  jsonld_types={A['jsonld_types_found']}  "
                  f"schema_pagetype_match={A['schema_pagetype_match']}")
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append({"label": label, "url": url,
                            "error": f"{type(e).__name__}: {e}"})
    with open("aaa123_s0_probe.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote aaa123_s0_probe.json")


if __name__ == "__main__":
    main()
