"""AAA-95 Sub-step 2.2 — coverage 5x5 stability sweep (production pipeline)."""

import asyncio
import json
import time

from discovery_agent.test_agent import audit

URLS = [
    "https://kk.coach",
    "https://www.aboutyou.hu",
    "https://www.taxually.com",
    "https://www.agrobook.hu",
    "https://vercel.com/products/vercel-platform",
]
RUNS = 5
OUT = r"C:\Users\donm6\ai-advisor-app\aaa95_s22_sweep_results.json"


async def main() -> None:
    results = []
    n_done = n_fail = 0
    t0 = time.perf_counter()
    for url in URLS:
        for run in range(1, RUNS + 1):
            try:
                d = await audit(url)
                fe = d.get("fan_out_enriched") or []
                rec = {
                    "url": url, "run": run,
                    "audit_id": d.get("audit_id"),
                    "cov_cost": d.get("audit_fan_out_coverage_cost_usd"),
                    "enrich_cost": d.get("audit_fan_out_enrichment_cost_usd"),
                    "audit_cost": d.get("audit_cost_usd"),
                    "eeat": "E-E-A-T Validation" in (
                        d.get("summary_markdown") or ""),
                    "tk_keys": len((d.get("target_keywords") or {}).keys()),
                    "duration_s": (d.get("audit_metadata") or {}).get(
                        "duration_seconds"),
                    "enriched": [
                        {"query": e.get("query"),
                         "source": e.get("source"),
                         "variant_type": e.get("variant_type"),
                         "coverage": e.get("coverage"),
                         "cov_error": (e.get("_meta") or {}).get(
                             "coverage_error")}
                        for e in fe
                    ],
                }
                results.append(rec)
                n_done += 1
                cov_err = sum(1 for e in rec["enriched"]
                              if e["cov_error"])
                print(f"  [{n_done}] {url} run{run}: entries={len(fe)} "
                      f"cov_err={cov_err} cov_cost={rec['cov_cost']} "
                      f"eeat={rec['eeat']}", flush=True)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                results.append({"url": url, "run": run,
                                "_error": f"{type(e).__name__}: {e}"})
                print(f"  FAIL {url} run{run}: {e}", flush=True)
            json.dump({"results": results, "n_done": n_done,
                       "n_fail": n_fail,
                       "wall_s": round(time.perf_counter() - t0, 1)},
                      open(OUT, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    print(f"SWEEP DONE: {n_done} ok / {n_fail} fail / "
          f"{time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
