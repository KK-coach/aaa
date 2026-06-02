"""AAA-89 Sub-step 2 Phase 1 — standalone PSI sweep (5 URL × 3 run)."""

import asyncio
import json
import statistics
import time

from pagespeed.client import get_pagespeed_score
from page_analysis.crux_field_data import extract_crux_from_psi_response

URLS = [
    "https://agrobook.hu",
    "https://kk.coach",
    "https://aboutyou.hu",
    "https://taxually.com",
    "https://kormany.hu",
]
RUNS = 3


def _drift_pct(values: list) -> float:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return 0.0
    m = statistics.mean(vals)
    if m == 0:
        return 0.0
    return round(100 * (max(vals) - min(vals)) / m, 2)


async def main() -> None:
    grid = {}
    t0 = time.perf_counter()
    for url in URLS:
        grid[url] = []
        for run in range(1, RUNS + 1):
            psi = await get_pagespeed_score(url, "mobile")
            cfd = extract_crux_from_psi_response(psi)
            grid[url].append(cfd)
            ul = cfd["url_level"]
            ol = cfd["origin_level"]
            print(f"  {url:30s} run{run}  "
                  f"url={ul['has_data']}/{ul['overall_category']}  "
                  f"origin={ol['has_data']}/{ol['overall_category']}  "
                  f"err={cfd['_error']}", flush=True)
    elapsed = round(time.perf_counter() - t0, 1)
    print(f"\nelapsed={elapsed}s")

    print("\n=== PHASE 1 RESULTS PER URL ===")
    summary = {}
    for url, runs in grid.items():
        ul_has = [r["url_level"]["has_data"] for r in runs]
        ol_has = [r["origin_level"]["has_data"] for r in runs]
        ul_cat = [r["url_level"]["overall_category"] for r in runs]
        ol_cat = [r["origin_level"]["overall_category"] for r in runs]
        errs = [r["_error"] for r in runs]
        # p75 drift per metric per scope (only on has-data runs)
        drifts = {}
        for scope in ("url_level", "origin_level"):
            scope_drifts = {}
            for metric in ("lcp", "inp", "cls", "fcp", "ttfb"):
                vals = []
                for r in runs:
                    if r[scope]["has_data"]:
                        m = (r[scope]["metrics"] or {}).get(metric) or {}
                        v = m.get("p75_ms") if metric != "cls" else m.get("p75")
                        if v is not None:
                            vals.append(v)
                if len(vals) >= 2:
                    scope_drifts[metric] = _drift_pct(vals)
            drifts[scope] = scope_drifts
        summary[url] = {
            "ul_has": ul_has, "ol_has": ol_has,
            "ul_cat": ul_cat, "ol_cat": ol_cat,
            "errs": errs, "drifts": drifts,
        }
        ul_rate = sum(ul_has) / len(ul_has) * 100
        ol_rate = sum(ol_has) / len(ol_has) * 100
        ul_consist = len(set(ul_cat)) == 1
        ol_consist = len(set(ol_cat)) == 1
        print(f"\n{url}")
        print(f"  url_level: has_data {ul_has} ({ul_rate:.0f}%) "
              f"cat={ul_cat} consistent={ul_consist}")
        print(f"  origin_level: has_data {ol_has} ({ol_rate:.0f}%) "
              f"cat={ol_cat} consistent={ol_consist}")
        if drifts["url_level"]:
            print(f"  url p75 drift: {drifts['url_level']}")
        if drifts["origin_level"]:
            print(f"  origin p75 drift: {drifts['origin_level']}")
        print(f"  _error: {errs}")

    json.dump({"grid": grid, "summary": summary,
               "elapsed_s": elapsed},
              open(r"C:\Users\donm6\ai-advisor-app\aaa89_s2_phase1.json",
                   "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
