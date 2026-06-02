"""AAA-111 Sub-step 1 — 5×5 sweep validating the AAA-110 prompt-fix
language consistency across the full Discovery pipeline (NOT bypass).

URLs locked per Krisztián 2026-05-24:
  HU regression : agrobook.hu, kormany.hu, aboutyou.hu
  EN control    : kk.coach, taxually.com  (kk.coach is EN-primary bilingual)

Cost circuit breaker at $1.80 cumulative — halts the sweep cleanly before
the 2×$1.50 hard ceiling would be hit on the next audit.
"""

import asyncio
import json
import time

from discovery_agent.test_agent import audit

URLS = [
    "https://agrobook.hu",
    "https://kormany.hu",
    "https://aboutyou.hu",
    "https://kk.coach",
    "https://taxually.com",
]
RUNS = 5
COST_BREAKER_USD = 1.80

HU_DIACRITICS = "őűáéíóúöüÖÜÓÚÉÁŰÍŐ"
HU_MORPH = (
    "alkatrész", "webáruház", "webshop", "szolgáltat", "kereskedő",
    "gép", "gazdaság", "felszerelés", "bolt", "ipari", "kormány",
    "magyar", "rendszer", "ruházat", "ruh", "üzlet", "katalógus",
    "ek ", "ok ", " és ", "ség", "ász", "ász ",
)


def detect_lang(text):
    if not text:
        return "?"
    t = text.lower()
    if any(ch in t for ch in HU_DIACRITICS):
        return "HU"
    if any(h in t for h in HU_MORPH):
        return "HU"
    return "EN"


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
                # Capture every audit_*_cost_usd field for full visibility.
                cost_fields = {
                    k: ao.get(k)
                    for k in ao
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
                p = detect_lang(tk.get("primary_keyword"))
                c = detect_lang(tk.get("category_keyword"))
                t_l = detect_lang(tk.get("topic_cluster"))
                print(
                    f"[{url[8:30]:22s} r{run}] "
                    f"p={p} c={c} t={t_l} | "
                    f"cat={tk.get('category_keyword')!r}  "
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
                print(f"[{url}] run {run}: ERROR {row['error']}", flush=True)
            grid.append(row)

            if cost_sum > COST_BREAKER_USD:
                print(
                    f"\n!!! COST BREAKER tripped at ${cost_sum:.4f} "
                    f"(> ${COST_BREAKER_USD}) — halting sweep early "
                    f"to stay under 2× ceiling. Partial grid saved.",
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
    with open("aaa111_s1_sweep.json", "w", encoding="utf-8") as f:
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
