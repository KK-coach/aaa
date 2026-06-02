"""AAA-95 Sub-step 1 — 5x5 fan-out variant_type stability sweep."""

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
OUT = r"C:\Users\donm6\ai-advisor-app\aaa95_sweep_results.json"


async def main() -> None:
    results = []
    n_done = n_fail = 0
    t0 = time.perf_counter()
    for url in URLS:
        for run in range(1, RUNS + 1):
            try:
                d = await audit(url)
                enr = d.get("fan_out_enriched") or []
                rec = {
                    "url": url, "run": run,
                    "audit_id": d.get("audit_id"),
                    "enrich_cost": d.get(
                        "audit_fan_out_enrichment_cost_usd"),
                    "eeat": "E-E-A-T Validation" in (
                        d.get("summary_markdown") or ""),
                    "tk_keys": len((d.get("target_keywords") or {}).keys()),
                    "query_fan_out_n": len(d.get("query_fan_out") or []),
                    "enriched": [
                        {"query": e.get("query"),
                         "source": e.get("source"),
                         "variant_type": e.get("variant_type"),
                         "error": (e.get("_meta") or {}).get("error")}
                        for e in enr
                    ],
                }
                results.append(rec)
                n_done += 1
                ne = len(enr)
                nerr = sum(1 for e in enr
                           if (e.get("_meta") or {}).get("error"))
                print(f"  [{n_done}] {url} run{run}: enriched={ne} "
                      f"errors={nerr} cost={rec['enrich_cost']} "
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
