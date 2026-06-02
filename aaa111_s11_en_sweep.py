"""AAA-111 Sub-step 1.1 — full-pipeline EN coverage mini-sweep.

Closes the Sub-step 1 coverage gap: 2 EN URLs × 3 runs = 6 audits,
end-to-end production-flow Discovery. Hard breaker at $1.50.
"""
import asyncio
import json
import time

from discovery_agent.test_agent import audit

URLS = ["https://kk.coach", "https://taxually.com"]
RUNS = 3
COST_BREAKER_USD = 1.50

HU_DIACR = set("őűáéíóúöüÖÜÓÚÉÁŰÍŐ")


def has_hu_diacritic(text: str) -> bool:
    return bool(text) and any(c in HU_DIACR for c in text)


async def main():
    grid = []
    t0 = time.perf_counter()
    cost_sum = 0.0
    breaker_hit = False
    for url in URLS:
        if breaker_hit:
            break
        for run in range(1, RUNS + 1):
            t_start = time.perf_counter()
            try:
                ao = await audit(url)
                tk = ao.get("target_keywords") or {}
                cost_fields = {
                    k: ao.get(k) for k in ao
                    if k.startswith("audit_") and k.endswith("_cost_usd")
                }
                total_cost = sum(
                    v for v in cost_fields.values()
                    if isinstance(v, (int, float))
                )
                cost_sum += total_cost
                row = {
                    "url": url, "run": run,
                    "audit_id": ao.get("audit_id"),
                    "primary_keyword": tk.get("primary_keyword"),
                    "category_keyword": tk.get("category_keyword"),
                    "topic_cluster": tk.get("topic_cluster"),
                    "secondary_keywords": (tk.get("secondary_keywords") or [])[:3],
                    "cost_fields": cost_fields,
                    "total_cost_usd": round(total_cost, 6),
                    "latency_s": round(time.perf_counter() - t_start, 1),
                    "error": None,
                }
                fields = [tk.get("primary_keyword") or "",
                          tk.get("category_keyword") or "",
                          tk.get("topic_cluster") or ""]
                hu_drift = any(has_hu_diacritic(f) for f in fields)
                drift_tag = "DRIFT-TO-HU" if hu_drift else "EN-clean"
                print(
                    f"[{url[8:30]:18s} r{run}] {drift_tag} | "
                    f"primary={tk.get('primary_keyword')!r}  "
                    f"cat={tk.get('category_keyword')!r}  "
                    f"topic={tk.get('topic_cluster')!r}  "
                    f"cost=${total_cost:.4f} sum=${cost_sum:.3f} "
                    f"lat={row['latency_s']}s",
                    flush=True,
                )
            except Exception as e:
                row = {
                    "url": url, "run": run,
                    "error": f"{type(e).__name__}: {e}",
                    "latency_s": round(time.perf_counter() - t_start, 1),
                }
                print(f"[{url}] r{run}: ERROR {row['error']}", flush=True)
            grid.append(row)
            if cost_sum > COST_BREAKER_USD:
                print(
                    f"\n!!! COST BREAKER tripped at ${cost_sum:.4f} "
                    f"(>${COST_BREAKER_USD}). Partial grid saved.",
                    flush=True,
                )
                breaker_hit = True
                break

    total_time = round(time.perf_counter() - t0, 1)
    print(
        f"\n=== TOTAL: {total_time}s wall time, ${cost_sum:.4f} cost sum, "
        f"{len(grid)} audits ===",
        flush=True,
    )
    with open("aaa111_s11_en_sweep.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "grid": grid,
                "wall_time_s": total_time,
                "total_cost_usd": cost_sum,
                "breaker_hit": breaker_hit,
            },
            f, indent=2, ensure_ascii=False, default=str,
        )


if __name__ == "__main__":
    asyncio.run(main())
