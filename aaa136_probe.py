import asyncio
from reverse_engineering_agent.tools import _run_serp
from discovery_agent.tools import _normalize_url_for_match as N
async def main():
    for q in ["site:https://agrobook.hu", "site:agrobook.hu", "site:agrobook.hu/"]:
        s=await _run_serp(q, "Hungary", "hu", depth=10)
        urls=[r.get("url") for r in (s.get("organic_results") or [])]
        print(f"\nQUERY {q!r}  cost=${s.get('cost_usd')}  n_organic={len(urls)} err={s.get('error')}")
        for u in urls[:10]: print(f"   {u}   (norm={N(u)})")
        print(f"   homepage 'agrobook.hu' in normalized set? {'agrobook.hu' in {N(u) for u in urls}}")
asyncio.run(main())
