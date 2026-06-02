"""AAA-123 Sub-step 2 — Track A: multi-run stability sweep.

5 URLs × 5 measurement passes per URL within ONE session.
1× HTTP GET per URL → save body bytes to memory →
5× call run_phase2_measurements on the saved bytes.

Byte-stable input ⇒ expect 0% drift across all 5 runs on every
deterministic key. Surface ANY drift as halt-condition trigger.

URLs:
  3 existing canaries (S1 baselines): agrobook.hu, vercel.com, kk.coach
  2 new (S2 diversity): hvg.hu (HU news/content), docs.python.org/3 (EN docs)
"""
import asyncio
import json
import time

import httpx

from page_analysis.phase2_html import run_phase2_measurements

URLS = [
    ("agrobook.hu",       "https://agrobook.hu",        "hu", "homepage"),
    ("vercel.com",        "https://vercel.com",         "en", "homepage"),
    ("kk.coach",          "https://kk.coach",           "en", "homepage"),
    ("hvg.hu",            "https://hvg.hu",             "hu", "homepage"),
    ("docs.python.org",   "https://docs.python.org/3/", "en", "documentation"),
]

N_RUNS = 5

# Deterministic keys to compare across runs (semantic_structure block)
DETERMINISTIC_SS_KEYS = (
    "heading_tree_count", "list_structure", "table_structure",
    "blockquote_count", "figure_count", "div_table_suspicious",
    "inline_emphasis",
)
# Deterministic keys (google_2mb_cutoff block)
DETERMINISTIC_CUT_KEYS = (
    "raw_html_bytes_uncompressed", "inline_total_bytes",
    "exceeds_2mb_cutoff", "content_after_cutoff_pct",
)
# Deterministic keys (rendering_mode block)
DETERMINISTIC_RM_KEYS = (
    "raw_html_visible_text_chars", "inline_script_bytes",
    "is_csr_likely", "spa_frameworks_detected",
)


def fetch(url: str) -> tuple[str, int, int]:
    """Single HTTP GET, returns (body_text, body_bytes_len, headers_bytes_est)."""
    with httpx.Client(follow_redirects=True, timeout=30,
                      headers={"User-Agent": "AAA-123-S2-stability/0"}) as c:
        r = c.get(url)
    body = r.text
    body_b = len(r.content)
    hdr_b = sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) + 4
                for k, v in r.headers.items())
    return body, body_b, hdr_b


def extract_signature(result: dict) -> dict:
    """Extract deterministic-key snapshot for diff comparison."""
    ss = result.get("semantic_structure", {}) or {}
    cut = result.get("google_2mb_cutoff", {}) or {}
    rm = result.get("rendering_mode", {}) or {}
    sig = {}
    for k in DETERMINISTIC_SS_KEYS:
        sig[f"ss.{k}"] = ss.get(k)
    for k in DETERMINISTIC_CUT_KEYS:
        sig[f"cut.{k}"] = cut.get(k)
    for k in DETERMINISTIC_RM_KEYS:
        sig[f"rm.{k}"] = rm.get(k)
    # schema_pagetype_match
    sig["ss.schema_match"] = (ss.get("schema_pagetype_match") or {}).get("match")
    sig["ss.schema_matched"] = tuple(
        (ss.get("schema_pagetype_match") or {}).get("matched_types") or []
    )
    return sig


def diff(a: dict, b: dict) -> list[str]:
    out = []
    for k in a:
        if a[k] != b.get(k):
            out.append(f"{k}: {a[k]!r} vs {b.get(k)!r}")
    return out


async def main():
    print("=" * 72)
    print("AAA-123 Sub-step 2 — Track A: stability sweep (5 URL × 5 runs)")
    print("=" * 72)

    overall_drift = 0
    overall_runs = 0
    per_url_summary = []
    latency_table = []

    for label, url, lang, page_type in URLS:
        print(f"\n--- {label} ({url}) ---")
        t_fetch = time.perf_counter()
        try:
            body, body_b, hdr_b = fetch(url)
        except Exception as e:
            print(f"  FETCH FAILED: {type(e).__name__}: {e}")
            per_url_summary.append((label, "FETCH_FAIL", 0, 0))
            continue
        fetch_wall = round(time.perf_counter() - t_fetch, 3)
        print(f"  fetch: {fetch_wall}s  body={body_b}B  headers~{hdr_b}B")

        signatures = []
        walls = []
        for i in range(N_RUNS):
            t0 = time.perf_counter()
            res = await run_phase2_measurements(
                {"_raw_html_transient": body,
                 "response_headers_bytes_estimate": hdr_b},
                page_type=page_type, audit_language=lang,
            )
            walls.append(round(time.perf_counter() - t0, 4))
            signatures.append(extract_signature(res))

        # Pairwise diff vs run 0
        drifts = []
        for i in range(1, N_RUNS):
            d = diff(signatures[0], signatures[i])
            if d:
                drifts.append((i, d))

        verdict = "PASS" if not drifts else "FAIL"
        overall_runs += N_RUNS
        overall_drift += sum(len(d) for _, d in drifts)
        print(f"  measurement walls: {walls}  mean={sum(walls)/len(walls):.4f}s")
        if drifts:
            print(f"  DRIFT DETECTED across {len(drifts)} run(s):")
            for i, d in drifts:
                print(f"    run-0 vs run-{i}:")
                for line in d:
                    print(f"      - {line}")
        else:
            print(f"  drift across 5 runs: NONE")
        print(f"  verdict: {verdict}")

        # Print 1 representative signature
        sig0 = signatures[0]
        print(f"  signature (run-0):")
        print(f"    heading_tree_count={sig0['ss.heading_tree_count']}")
        print(f"    raw_html_bytes={sig0['cut.raw_html_bytes_uncompressed']}")
        print(f"    exceeds_2mb={sig0['cut.exceeds_2mb_cutoff']}")
        print(f"    visible_text={sig0['rm.raw_html_visible_text_chars']}")
        print(f"    is_csr_likely={sig0['rm.is_csr_likely']}")
        print(f"    spa_frameworks={sig0['rm.spa_frameworks_detected']}")
        print(f"    schema_match={sig0['ss.schema_match']} matched={sig0['ss.schema_matched']}")

        per_url_summary.append((label, verdict, sum(len(d) for _, d in drifts), N_RUNS))
        latency_table.append((label, walls, body_b))

    # ============================================================
    # Final summary
    # ============================================================
    print("\n" + "=" * 72)
    print("TRACK A SUMMARY")
    print("=" * 72)
    print(f"{'URL':22s} {'verdict':8s} {'drift':>6s} {'runs':>6s}")
    for label, v, dcnt, runs in per_url_summary:
        print(f"{label:22s} {v:8s} {dcnt:6d} {runs:6d}")
    print(f"\nTOTAL runs: {overall_runs}  TOTAL drift entries: {overall_drift}")
    halt_a = overall_drift == 0
    print(f"\nTrack A halt-condition (0% drift on byte-stable input): "
          f"{'PASS' if halt_a else 'FAIL'}")

    # Latency table
    print("\n--- LATENCY (per-URL min/mean/max over 5 runs) ---")
    print(f"{'URL':22s} {'body_B':>10s} {'min':>8s} {'mean':>8s} {'max':>8s}")
    for label, walls, body_b in latency_table:
        print(f"{label:22s} {body_b:10d} "
              f"{min(walls):8.4f} {sum(walls)/len(walls):8.4f} {max(walls):8.4f}")

    # Halt-condition: <1s on every URL <2MB
    over_1s = [(label, max(walls), body_b) for label, walls, body_b in latency_table
               if max(walls) >= 1.0 and body_b < 2*1024*1024]
    print(f"\nLatency halt (<1s on <2MB bodies): "
          f"{'PASS' if not over_1s else 'FAIL'}")
    if over_1s:
        for label, w, b in over_1s:
            print(f"  OVER: {label} max={w}s body={b}B")


if __name__ == "__main__":
    asyncio.run(main())
