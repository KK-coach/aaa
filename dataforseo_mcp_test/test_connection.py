"""TEST 1 - Connection check. FREE (no DataForSEO API cost).

Starts the DataForSEO MCP server over stdio, lists every tool it exposes,
groups them by module, and verifies our ENABLED_MODULES restriction took
effect (no backlinks_*/on_page_*/labs_*/etc.).

Run from project root:  python -m dataforseo_mcp_test.test_connection
"""

import asyncio
import sys

from dataforseo_mcp_test.mcp_client import open_session, print_credential_banner
from dataforseo_mcp_test.preflight import preflight_gate

# Prefixes we EXPECT (the 3 enabled modules) vs prefixes that must be ABSENT.
EXPECTED_PREFIXES = ("serp", "ai_optimization", "keywords_data", "keywords")
FORBIDDEN_PREFIXES = (
    "backlinks",
    "on_page",
    "onpage",
    "dataforseo_labs",
    "labs",
    "business_data",
    "domain_analytics",
    "content_analysis",
)


def _module_of(tool_name: str) -> str:
    name = tool_name.lower()
    for pref in ("ai_optimization", "keywords_data", "serp", "keywords"):
        if name.startswith(pref):
            return pref
    return name.split("_")[0]


async def main() -> int:
    print("=" * 70)
    print("TEST 1 - DataForSEO MCP connection check (free)")
    print("=" * 70)
    print_credential_banner()
    print()

    async with open_session() as session:
        if not await preflight_gate(session):
            return 1
        tools_resp = await session.list_tools()
        tools = tools_resp.tools
        print(f"Connected. Server exposes {len(tools)} tools.\n")

        grouped: dict[str, list[str]] = {}
        for t in tools:
            grouped.setdefault(_module_of(t.name), []).append(t.name)

        for module in sorted(grouped):
            print(f"[{module}]  ({len(grouped[module])} tools)")
            for name in sorted(grouped[module]):
                print(f"    - {name}")
            print()

        # Verify restriction.
        forbidden_found = [
            t.name
            for t in tools
            if t.name.lower().startswith(FORBIDDEN_PREFIXES)
        ]
        expected_found = [
            t.name
            for t in tools
            if t.name.lower().startswith(EXPECTED_PREFIXES)
        ]

        print("-" * 70)
        print(f"Tools from enabled modules : {len(expected_found)}")
        print(f"Tools from disabled modules: {len(forbidden_found)}")
        if forbidden_found:
            print("  RESTRICTION FAILED - leaked tools:")
            for n in forbidden_found:
                print(f"    ! {n}")
            return 1
        if not expected_found:
            print("  WARNING: no tools from expected modules - check naming.")
            return 1
        print("RESTRICTION OK - only SERP / AI_OPTIMIZATION / KEYWORDS_DATA "
              "tools present.")
        print("MCP plumbing is OPERATIONAL.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
