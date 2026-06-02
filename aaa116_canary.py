"""AAA-116 Sub-step 2 — post-removal canary.

5 full Discovery audits to verify schema-fallback behavior post-removal of
legacy AAA-55 classify_page_type. Full Discovery (NOT bypass) because the
removal point is INSIDE the entities tool inside the ADK agent loop — we
need to actually exercise that path to test the change.

Stop conditions per spec:
  - page_type=None → halt
  - off-enum page_type → halt
  - cost approaches $1.50 → halt partial
"""
import asyncio
import json
import time

from discovery_agent.test_agent import audit
from page_analysis.multi_dim_classify import PageType

# Accept the AAA-81 v3 27-leaf enum membership at runtime
_VALID_PT = set(getattr(PageType, "__args__", []))

URLS = [
    "https://agrobook.hu",            # HU ecommerce (canary continuity)
    "https://kk.coach",                # EN B2B service (canary continuity)
    "https://vercel.com/pricing",      # pricing_page
    "https://nextjs.org/docs",         # documentation
    "https://www.aboutyou.hu/c/noi",   # category_page (added diversity)
]
COST_BREAKER = 1.50


async def main():
    grid = []
    t0 = time.perf_counter()
    cost_sum = 0.0
    for url in URLS:
        if cost_sum > COST_BREAKER:
            print(f"\n!!! Cost breaker tripped ({cost_sum:.3f} > ${COST_BREAKER})", flush=True)
            break
        t = time.perf_counter()
        try:
            ao = await audit(url)
        except Exception as e:
            print(f"[{url}] ERROR {type(e).__name__}: {e}", flush=True)
            grid.append({"url": url, "error": str(e)})
            continue
        cost_fields = {
            k: ao.get(k) for k in ao
            if k.startswith("audit_") and k.endswith("_cost_usd")
        }
        total = sum(v for v in cost_fields.values() if isinstance(v, (int, float)))
        cost_sum += total
        pt = ao.get("page_type")
        in_enum = pt in _VALID_PT
        row = {
            "url": url,
            "audit_id": ao.get("audit_id"),
            "page_type": pt,
            "page_type_in_27_leaf_enum": in_enum,
            "page_type_parent_intent_group": ao.get("page_type_parent_intent_group"),
            "page_type_model_version": ao.get("page_type_model_version"),
            "audit_multi_dim_classify_cost_usd": ao.get("audit_multi_dim_classify_cost_usd"),
            "total_audit_cost_usd": round(total, 6),
            "wall_s": round(time.perf_counter() - t, 1),
        }
        grid.append(row)
        print(
            f"[{url[8:30]:25s}] pt={pt!r} in_enum={in_enum} "
            f"parent={row['page_type_parent_intent_group']!r} "
            f"md_cost=${row['audit_multi_dim_classify_cost_usd']} "
            f"total=${total:.4f} sum=${cost_sum:.3f} wall={row['wall_s']}s",
            flush=True,
        )

    wall = round(time.perf_counter() - t0, 1)
    print(f"\n=== TOTAL: wall={wall}s cost=${cost_sum:.4f} audits={len(grid)} ===", flush=True)
    with open("aaa116_canary.json", "w", encoding="utf-8") as f:
        json.dump({"grid": grid, "wall_s": wall, "cost_usd_total": cost_sum},
                  f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    asyncio.run(main())
