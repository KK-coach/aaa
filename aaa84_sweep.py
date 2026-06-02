"""AAA-84 Sub-step 2 Phase A — characterization sweep (5 URL x 5 run).

Sequential fresh end-to-end Discovery audits (no parallel: avoids Firestore
write contention). Each audit() already archives to Firestore. Results
written incrementally to aaa84_sweep_results.json so partial progress
survives an interruption.

One sweep, two purposes: Phase B variance + Phase D ship-gate use the
SAME 25 audits.
"""

import asyncio
import json
import os
import time

os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

from discovery_agent.test_agent import URLS, audit  # noqa: E402

RESULTS = r"C:\Users\donm6\ai-advisor-app\aaa84_sweep_results.json"
RUNS_PER_URL = 5


def _checkpoint(rec: dict) -> dict:
    """Mid-sweep regression-relevant extract."""
    ao = rec  # rec is the audit_output dict
    sm = ao.get("summary_markdown") or ""
    tk = ao.get("target_keywords") or {}
    return {
        "audit_cost_usd": ao.get("audit_cost_usd"),
        "audit_fan_out_cost_usd": ao.get("audit_fan_out_cost_usd"),
        "query_fan_out_n": len(ao.get("query_fan_out") or []),
        "eeat_section": "E-E-A-T Validation" in sm,
        "grounding_confidence": ao.get("grounding_confidence"),
        "tk_dict_keys": sorted(tk.keys()) if isinstance(tk, dict) else None,
        "tk_primary": tk.get("primary_keyword") if isinstance(tk, dict) else None,
    }


async def main() -> None:
    out = {"runs": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    n_done = n_fail = 0
    total_cost = 0.0
    t0 = time.perf_counter()

    for url in URLS:
        for run_idx in range(1, RUNS_PER_URL + 1):
            tag = f"{url} run {run_idx}/{RUNS_PER_URL}"
            print(f"[{n_done + n_fail + 1}/25] {tag} ...", flush=True)
            try:
                data = await audit(url)
            except Exception as e:  # noqa: BLE001
                n_fail += 1
                out["runs"].append({"url": url, "run": run_idx,
                                    "_error": f"{type(e).__name__}: {e}"})
                print(f"   FAILED: {e}", flush=True)
                json.dump(out, open(RESULTS, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
                continue

            n_done += 1
            ac = data.get("audit_cost_usd") or 0.0
            kc = data.get("audit_keyword_classify_cost_usd") or 0.0
            fc = data.get("audit_fan_out_cost_usd") or 0.0
            total_cost += ac + kc + fc
            rec = {
                "url": url, "run": run_idx,
                "audit_id": data.get("audit_id"),
                "target_keywords_classified": data.get(
                    "target_keywords_classified") or [],
                "audit_keyword_classify_cost_usd": kc,
                "audit_cost_usd": ac,
                "audit_fan_out_cost_usd": fc,
                "query_fan_out": data.get("query_fan_out") or [],
                "summary_markdown": (data.get("summary_markdown") or "")[:400],
                "checkpoint": _checkpoint(data),
            }
            out["runs"].append(rec)
            json.dump(out, open(RESULTS, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)

            # mid-sweep checkpoint every 5th audit
            if n_done % 5 == 0:
                cp = rec["checkpoint"]
                print(f"   CHECKPOINT @ {n_done}: cost={ac:.5f} "
                      f"fan_out=${fc:.5f}/n={cp['query_fan_out_n']} "
                      f"eeat={cp['eeat_section']} "
                      f"grounding={cp['grounding_confidence']} "
                      f"tk_keys={len(cp['tk_dict_keys'] or [])}", flush=True)

    out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out["n_done"] = n_done
    out["n_fail"] = n_fail
    out["total_cost_usd"] = round(total_cost, 5)
    out["wall_seconds"] = round(time.perf_counter() - t0, 1)
    json.dump(out, open(RESULTS, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\nSWEEP DONE: {n_done} ok / {n_fail} fail / "
          f"${total_cost:.4f} / {out['wall_seconds']}s")


if __name__ == "__main__":
    asyncio.run(main())
