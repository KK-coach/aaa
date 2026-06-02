"""AAA-91 Sub-step 2 — L2 variance characterization sweep (5 URL x 5 run).

Reuses the AAA-84 Sub-step 2 protocol + URL set. End-to-end fresh audits;
captures per-keyword L1 + L2 for cross-input stability analysis.
"""

import asyncio
import json
import time

from discovery_agent.test_agent import audit

URLS = [
    "https://www.agrobook.hu",
    "https://kk.coach",
    "https://www.aboutyou.hu",
    "https://www.taxually.com",
    "https://vercel.com/products/vercel-platform",
]
RUNS = 5
OUT = r"C:\Users\donm6\ai-advisor-app\aaa91_sweep_results.json"


async def main() -> None:
    results = []
    n_done = n_fail = 0
    total_cost = 0.0
    t0 = time.perf_counter()
    for url in URLS:
        for run in range(1, RUNS + 1):
            try:
                d = await audit(url)
                tkc = d.get("target_keywords_classified") or []
                rec = {
                    "url": url, "run": run,
                    "audit_id": d.get("audit_id"),
                    "kw_classify_cost": d.get(
                        "audit_keyword_classify_cost_usd"),
                    "grounding": d.get("grounding_confidence"),
                    "eeat": "E-E-A-T Validation" in (
                        d.get("summary_markdown") or ""),
                    "tk_keys": len((d.get("target_keywords") or {}).keys()),
                    "classified": [
                        {"keyword": x.get("keyword"),
                         "l1": x.get("search_intent"),
                         "l2": x.get("search_intent_l2")}
                        for x in tkc
                    ],
                }
                results.append(rec)
                total_cost += rec["kw_classify_cost"] or 0.0
                n_done += 1
                print(f"  [{n_done}] {url} run{run}: "
                      f"n_kw={len(tkc)} cost={rec['kw_classify_cost']} "
                      f"eeat={rec['eeat']} tk_keys={rec['tk_keys']}",
                      flush=True)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                results.append({"url": url, "run": run,
                                "_error": f"{type(e).__name__}: {e}"})
                print(f"  FAIL {url} run{run}: {e}", flush=True)
            json.dump({"results": results, "n_done": n_done,
                       "n_fail": n_fail,
                       "total_kw_cost": round(total_cost, 5),
                       "wall_s": round(time.perf_counter() - t0, 1)},
                      open(OUT, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    print(f"SWEEP DONE: {n_done} ok / {n_fail} fail / "
          f"kw_cost ${total_cost:.4f} / {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
