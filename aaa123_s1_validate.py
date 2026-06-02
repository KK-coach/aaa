"""AAA-123 Sub-step 1 validation: canaries + synthetic fixture + latency."""
import asyncio
import time

import httpx
from selectolax.parser import HTMLParser

from page_analysis.phase2_html import (
    run_phase2_measurements, measure_2mb_cutoff,
    PAGE_TYPE_TO_SCHEMA_ORG_TYPES, GOOGLE_2MB_BYTES,
)


def fetch(url):
    with httpx.Client(follow_redirects=True, timeout=30,
                       headers={"User-Agent": "AAA-123-S1-validate/0"}) as c:
        r = c.get(url)
    hdr_bytes = sum(len(k) + len(v) + 4 for k, v in r.headers.items())
    return r.text, hdr_bytes


# ============================================================================
# 1. Schema.org mapping coverage check
# ============================================================================
print("=== Schema.org mapping coverage ===")
print(f"  size: {len(PAGE_TYPE_TO_SCHEMA_ORG_TYPES)} entries (expect 27)")
expected_leaves = {
    "homepage", "category_page", "product_page", "service_page", "landing_page",
    "blog_article", "news_article", "guide_or_resource", "glossary_or_wiki_page",
    "documentation", "paywalled_or_gated_content", "pricing_page", "comparison_page",
    "case_study_page", "testimonial_or_review_page", "search_results_page",
    "contact_page", "location_page", "form_page", "checkout_or_booking",
    "account_or_dashboard", "legal_page", "media_page", "event_page",
    "job_listing_page", "error_or_redirect_page", "other_or_unknown",
}
missing = expected_leaves - set(PAGE_TYPE_TO_SCHEMA_ORG_TYPES.keys())
extra = set(PAGE_TYPE_TO_SCHEMA_ORG_TYPES.keys()) - expected_leaves
print(f"  missing leaves: {missing or 'none'}")
print(f"  extra leaves  : {extra or 'none'}")
print(f"  {'PASS' if not missing and not extra else 'FAIL'}")

# ============================================================================
# 2. Canaries
# ============================================================================
canaries = []
S0_BASELINES = {
    "agrobook.hu": dict(heading_tree_count=1, raw_html_bytes=953672,
                        inline_total_bytes=634597, visible_text_chars=5305,
                        is_csr_likely=False, wall_s=1.774),
    "vercel.com":  dict(heading_tree_count=36, div_table_suspicious_S0=17,
                        visible_text_chars=6599, wall_s=0.158,
                        expected_spa="next.js"),
    "kk.coach":    dict(heading_tree_count=45, wall_s=0.362),
}

print("\n=== CANARY: agrobook.hu (HU homepage, expected SSR) ===")
body, hdr_bytes = fetch("https://agrobook.hu")
t0 = time.perf_counter()
ag = asyncio.run(run_phase2_measurements(
    {"_raw_html_transient": body, "response_headers_bytes_estimate": hdr_bytes},
    page_type="homepage", audit_language="hu",
))
ag_wall = round(time.perf_counter() - t0, 3)
canaries.append(("agrobook.hu", ag_wall, S0_BASELINES["agrobook.hu"]["wall_s"]))
print(f"  measurement wall: {ag_wall} s  (S0 baseline: 1.774 s)")
print(f"  heading_tree_count: {ag['semantic_structure']['heading_tree_count']}  (S0: 1)")
print(f"  list_structure.li : {ag['semantic_structure']['list_structure']['li']}")
print(f"  inline_emphasis   : {ag['semantic_structure']['inline_emphasis']}")
print(f"  raw_html_bytes    : {ag['google_2mb_cutoff']['raw_html_bytes_uncompressed']}  (S0: 953,672)")
print(f"  inline_total_bytes: {ag['google_2mb_cutoff']['inline_total_bytes']}  (S0: 634,597)")
print(f"  exceeds_2mb       : {ag['google_2mb_cutoff']['exceeds_2mb_cutoff']}")
print(f"  visible_text      : {ag['rendering_mode']['raw_html_visible_text_chars']}  (S0: 5305)")
print(f"  is_csr_likely     : {ag['rendering_mode']['is_csr_likely']}  (S0: False)")
print(f"  spa_frameworks    : {ag['rendering_mode']['spa_frameworks_detected']}  (S0: none)")
print(f"  schema_pagetype_match.match: {ag['semantic_structure']['schema_pagetype_match']['match']}")
print(f"  schema_pagetype_match.matched_types: {ag['semantic_structure']['schema_pagetype_match']['matched_types']}")

print("\n=== CANARY: vercel.com (EN, Next.js App Router) ===")
body, hdr_bytes = fetch("https://vercel.com")
t0 = time.perf_counter()
vc = asyncio.run(run_phase2_measurements(
    {"_raw_html_transient": body, "response_headers_bytes_estimate": hdr_bytes},
    page_type="homepage", audit_language="en",
))
vc_wall = round(time.perf_counter() - t0, 3)
canaries.append(("vercel.com", vc_wall, S0_BASELINES["vercel.com"]["wall_s"]))
print(f"  measurement wall: {vc_wall} s  (S0 baseline: 0.158 s)")
print(f"  heading_tree_count: {vc['semantic_structure']['heading_tree_count']}  (S0: 36)")
print(f"  div_table_suspicious: {vc['semantic_structure']['div_table_suspicious']}  (S0: 17, expect ~0)")
print(f"  visible_text      : {vc['rendering_mode']['raw_html_visible_text_chars']}  (S0: 6599)")
print(f"  is_csr_likely     : {vc['rendering_mode']['is_csr_likely']}")
print(f"  spa_frameworks    : {vc['rendering_mode']['spa_frameworks_detected']}  (S0: none, expect ['next.js'])")
nx_sigs = [s for s in vc['rendering_mode']['spa_framework_signals']
           if 'next' in s.get('framework', '').lower()]
print(f"  next.js signals   : {nx_sigs}")
print(f"  schema_pagetype_match.match: {vc['semantic_structure']['schema_pagetype_match']['match']}")
print(f"  schema_pagetype_match.matched_types: {vc['semantic_structure']['schema_pagetype_match']['matched_types']}")

print("\n=== CANARY: kk.coach (HU/EN consulting, SSR) ===")
body, hdr_bytes = fetch("https://kk.coach")
t0 = time.perf_counter()
kk = asyncio.run(run_phase2_measurements(
    {"_raw_html_transient": body, "response_headers_bytes_estimate": hdr_bytes},
    page_type="homepage", audit_language="en",
))
kk_wall = round(time.perf_counter() - t0, 3)
canaries.append(("kk.coach", kk_wall, S0_BASELINES["kk.coach"]["wall_s"]))
print(f"  measurement wall: {kk_wall} s  (S0 baseline: 0.362 s)")
print(f"  heading_tree_count: {kk['semantic_structure']['heading_tree_count']}  (S0: 45)")
print(f"  is_csr_likely     : {kk['rendering_mode']['is_csr_likely']}  (S0: False)")
print(f"  schema_pagetype_match.match: {kk['semantic_structure']['schema_pagetype_match']['match']}")
print(f"  schema_pagetype_match.matched_types: {kk['semantic_structure']['schema_pagetype_match']['matched_types']}")

# ============================================================================
# 3. Synthetic >2 MB fixture (cutoff branch)
# ============================================================================
print("\n=== SYNTHETIC >2 MB fixture ===")
hdr_html = '<!DOCTYPE html><html><head><title>fixture</title></head><body>'
ftr_html = '</body></html>'
parts = [
    '<section id="intro"><h1>Intro Section</h1>' + 'A' * 200_000 + '</section>',
    '<section id="early"><h2>Early Body</h2>' + 'B' * 800_000 + '</section>',
    '<section id="mid"><h2>Mid Section</h2>' + 'C' * 700_000 + '</section>',
    '<section id="post-cutoff"><h2>POST-CUTOFF Section (should be lost)</h2>' + 'D' * 700_000 + '</section>',
    '<section id="trailing"><h3>Trailing</h3>' + 'E' * 200_000 + '</section>',
]
fixture = hdr_html + ''.join(parts) + ftr_html
fb = fixture.encode("utf-8")
print(f"  fixture size: {len(fb)} bytes ({len(fb)/1024/1024:.2f} MB)")
cut_fix = measure_2mb_cutoff(fb, 200, HTMLParser(fixture))
print(f"  exceeds_2mb_cutoff: {cut_fix['exceeds_2mb_cutoff']}  (expect True)")
cp = cut_fix.get("cutoff_position") or {}
print(f"  cutoff_position.char_offset: {cp.get('char_offset')}")
print(f"  cutoff_position.nearest_heading: {cp.get('nearest_heading_before_cutoff')!r}")
print(f"  cutoff_position.nearest_section: {cp.get('nearest_section_before_cutoff')!r}")
print(f"  content_after_cutoff_pct: {cut_fix.get('content_after_cutoff_pct')}")
synth_pass = (
    cut_fix["exceeds_2mb_cutoff"] is True
    and cp.get("char_offset") is not None
    and cp.get("nearest_heading_before_cutoff") is not None
    and cut_fix.get("content_after_cutoff_pct") is not None
    and cut_fix["content_after_cutoff_pct"] > 0
)
print(f"  synthetic verdict: {'PASS' if synth_pass else 'FAIL'}")

# ============================================================================
# 4. Determinism check (agrobook re-run, byte-equal verify)
# ============================================================================
print("\n=== Determinism check (agrobook re-run) ===")
body2, hdr_bytes2 = fetch("https://agrobook.hu")
ag2 = asyncio.run(run_phase2_measurements(
    {"_raw_html_transient": body2, "response_headers_bytes_estimate": hdr_bytes2},
    page_type="homepage", audit_language="hu",
))
drift = []
for k in ("heading_tree_count", "list_structure", "table_structure",
          "blockquote_count", "figure_count", "div_table_suspicious",
          "inline_emphasis"):
    if ag['semantic_structure'].get(k) != ag2['semantic_structure'].get(k):
        drift.append(f"{k}: {ag['semantic_structure'].get(k)!r} vs {ag2['semantic_structure'].get(k)!r}")
print(f"  deterministic-key drift: {drift or 'NONE'}")
print(f"  determinism: {'PASS' if not drift else 'FAIL'}")

# ============================================================================
# 5. Latency summary
# ============================================================================
print("\n=== LATENCY TABLE ===")
print(f"  {'URL':18s} {'S0 wall':>10s} {'S1 wall':>10s} {'reduction':>12s}")
for label, s1, s0 in canaries:
    red = round((1 - s1/s0)*100, 1)
    sign = "-" if red >= 0 else "+"
    print(f"  {label:18s} {s0:10.3f}s {s1:10.3f}s   {sign}{abs(red):5.1f}%")
print(f"\n  agrobook.hu < 1 s halt-condition: "
      f"{'PASS' if ag_wall < 1.0 else 'FAIL'}")
