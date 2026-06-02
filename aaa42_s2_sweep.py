"""AAA-42 Sub-step 2 — 5x5 stability sweep + ship gate orchestration."""

import asyncio
import json
import time

from discovery_agent.test_agent import audit

URLS = [
    "https://www.agrobook.hu",
    "https://kk.coach",
    "https://www.aboutyou.hu",
    "https://www.taxually.com",
    "https://www.arukereso.hu",
]
RUNS = 5
OUT = r"C:\Users\donm6\ai-advisor-app\aaa42_s2_results.json"


async def main() -> None:
    results = []
    n_done = n_fail = 0
    t0 = time.perf_counter()
    for url in URLS:
        for run in range(1, RUNS + 1):
            try:
                d = await audit(url)
                rec = {
                    "url": url, "run": run,
                    "audit_id": d.get("audit_id"),
                    "render_method_used": d.get("render_method_used"),
                    "agent_friendly": d.get("agent_friendly_measurements") or {},
                    "duration_s": (d.get("audit_metadata") or {}).get(
                        "duration_seconds"),
                }
                results.append(rec)
                n_done += 1
                afm = rec["agent_friendly"]
                print(f"  [{n_done}] {url} run{run} method={rec['render_method_used']} "
                      f"h1={afm.get('heading',{}).get('h1_count')} "
                      f"land={afm.get('landmarks',{}).get('count')} "
                      f"aria={afm.get('aria',{}).get('with_aria_count')}/"
                      f"{afm.get('aria',{}).get('interactive_count')} "
                      f"actions={afm.get('schema_actions')}",
                      flush=True)
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
