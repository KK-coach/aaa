"""Sub-step 1 pilot probe: 1 URL × 2 runs to validate the multi-field
classifier end-to-end before launching the full 5×5 sweep (~$5)."""
import asyncio
import json
import time

from discovery_agent.test_agent import audit

URL = "https://agrobook.hu"  # AAA-110/111/108-S4 canary continuity (HU)
RUNS = 2


async def main():
    out = []
    t0 = time.perf_counter()
    cost_sum = 0.0
    for run in range(1, RUNS + 1):
        t = time.perf_counter()
        try:
            ao = await audit(URL)
        except Exception as e:
            print(f"r{run}: ERROR {type(e).__name__}: {e}", flush=True)
            out.append({"run": run, "error": str(e)})
            continue
        cost_fields = {
            k: ao.get(k) for k in ao
            if k.startswith("audit_") and k.endswith("_cost_usd")
        }
        total_cost = sum(
            v for v in cost_fields.values() if isinstance(v, (int, float))
        )
        cost_sum += total_cost
        row = {
            "run": run,
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
        }
        out.append(row)
        print(
            f"r{run}: pt={row['page_type']!r} bm={row['business_model']!r} "
            f"td={row['topic_domain']!r} loc={row['locality']!r} "
            f"ar={row['audience_relationship_primary']!r} "
            f"ars={row['audience_relationship_secondary']!r} "
            f"conf={row['audience_confidence']} "
            f"md_cost=${row['audit_multi_dim_classify_cost_usd']} "
            f"total=${total_cost:.4f} lat={row['latency_s']}s",
            flush=True,
        )

    wall = round(time.perf_counter() - t0, 1)
    print(f"\nTotal wall: {wall}s  cost sum: ${cost_sum:.4f}", flush=True)
    with open("aaa_multidim_pilot.json", "w", encoding="utf-8") as f:
        json.dump({
            "grid": out, "wall_s": wall, "cost_usd_total": cost_sum,
        }, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    asyncio.run(main())
