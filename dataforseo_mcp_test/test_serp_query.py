"""TEST 2 - Single SERP query. Costs ~$0.002 (live SERP advanced).

Calls serp_organic_live_advanced for "vegan recipes" (US / English, depth 10),
then prints the top-10 organic URLs, whether a Google AI Overview element was
present, and the cost DataForSEO reported.

Run from project root:  python -m dataforseo_mcp_test.test_serp_query
"""

import asyncio
import sys

from dataforseo_mcp_test.mcp_client import (
    find_cost,
    iter_result_items,
    open_session,
    print_credential_banner,
    result_to_json,
)
from dataforseo_mcp_test.preflight import preflight_gate

SERP_TOOL = "serp_organic_live_advanced"
ARGS = {
    "keyword": "vegan recipes",
    "search_engine": "google",
    "location_name": "United States",
    "language_code": "en",
    "depth": 10,
}


def extract_organic_urls(payload: dict, limit: int = 10) -> list[str]:
    urls = []
    for item in iter_result_items(payload):
        if item.get("type") == "organic" and item.get("url"):
            urls.append(item["url"])
        if len(urls) >= limit:
            break
    return urls


def ai_overview_present(payload: dict) -> bool:
    return any(
        item.get("type") in ("ai_overview", "ai_overview_reference")
        for item in iter_result_items(payload)
    )


async def main() -> int:
    print("=" * 70)
    print("TEST 2 - SERP query  (cost ~$0.002)")
    print("=" * 70)
    print_credential_banner()
    print(f"Tool: {SERP_TOOL}  args: {ARGS}\n")

    async with open_session() as session:
        if not await preflight_gate(session):
            return 1
        result = await session.call_tool(SERP_TOOL, arguments=ARGS)
        if getattr(result, "isError", False):
            print("Tool returned an error:")
            for b in result.content or []:
                print(getattr(b, "text", b))
            return 1

        payload = result_to_json(result)
        urls = extract_organic_urls(payload, 10)
        cost = find_cost(payload)

        print(f"Top {len(urls)} organic URLs:")
        for i, u in enumerate(urls, 1):
            print(f"  {i:>2}. {u}")
        print()
        print(f"AI Overview present in SERP : {ai_overview_present(payload)}")
        if cost is None:
            print("DataForSEO reported cost    : not in MCP response "
                  "(trimmed; set DATAFORSEO_FULL_RESPONSE=true to expose). "
                  "SERP Advanced live list price ~= $0.002")
        else:
            print(f"DataForSEO reported cost    : ${cost:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
