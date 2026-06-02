"""Sub-step 1 — full 6×5 sweep (30 audits) validating the AAA-77 v2 +
AAA-81 v3 + AAA-113 multi-dimensional classifier.

URL set locked per Krisztián Path A authorization (2026-05-25):
  - agrobook.hu        HU mixed B2C+B2B canary
  - kk.coach           EN B2B service
  - kormany.hu         HU G2C clean reference
  - aboutyou.hu        HU B2C clean ecommerce
  - vercel.com         EN B2B SaaS
  - magyarorszag.hu    HU G2C+G2B mixed canary

Cost breaker at $6.00 cumulative — halts before sweep escalates beyond the
$5.40 upper estimate.
"""
import asyncio
import json
import time

from discovery_agent.test_agent import audit

URLS = [
    "https://agrobook.hu",
    "https://kk.coach",
    "https://kormany.hu",
    "https://aboutyou.hu",
    "https://vercel.com",
    "https://magyarorszag.hu",
]
RUNS = 5
COST_BREAKER_USD = 6.00


async def main():
    grid = []
    t0 = time.perf_counter()
    cost_sum = 0.0
    breaker_hit = False
    for url in URLS:
        if breaker_hit:
            break
        for run in range(1, RUNS + 1):
            t = time.perf_counter()
            try:
                ao = await audit(url)
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
                    "page_type": ao.get("page_type"),
                    "page_type_parent_intent_group": ao.get(
                        "page_type_parent_intent_group"
                    ),
                    "business_model": ao.get("business_model"),
                    "topic_domain": ao.get("topic_domain"),
                    "locality": ao.get("locality"),
                    "audience_relationship_primary": ao.get(
                        "audience_relationship_primary"
                    ),
                    "audience_relationship_secondary": ao.get(
                        "audience_relationship_secondary"
                    ),
                    "audience_confidence": ao.get("audience_confidence"),
                    "audit_multi_dim_classify_cost_usd": ao.get(
                        "audit_multi_dim_classify_cost_usd"
                    ),
                    "total_audit_cost_usd": round(total_cost, 6),
                    "latency_s": round(time.perf_counter() - t, 1),
                    "error": None,
                }
                print(
                    f"[{url[8:30]:24s} r{run}] "
                    f"pt={row['page_type']!r} bm={row['business_model']!r} "
                    f"td={row['topic_domain']!r} loc={row['locality']!r} "
                    f"ar={row['audience_relationship_primary']!r}"
                    f"/{row['audience_relationship_secondary']!r} "
                    f"conf={row['audience_confidence']} "
                    f"md=${row['audit_multi_dim_classify_cost_usd']} "
                    f"sum=${cost_sum:.3f} lat={row['latency_s']}s",
                    flush=True,
                )
            except Exception as e:
                row = {
                    "url": url, "run": run,
                    "error": f"{type(e).__name__}: {e}",
                    "latency_s": round(time.perf_counter() - t, 1),
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

    wall = round(time.perf_counter() - t0, 1)
    print(
        f"\n=== TOTAL: {wall}s wall, ${cost_sum:.4f} cost sum, "
        f"{len(grid)} audits, breaker={breaker_hit} ===",
        flush=True,
    )
    with open("aaa_multidim_sweep.json", "w", encoding="utf-8") as f:
        json.dump({
            "grid": grid, "wall_s": wall, "cost_usd_total": cost_sum,
            "breaker_hit": breaker_hit,
        }, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    asyncio.run(main())
