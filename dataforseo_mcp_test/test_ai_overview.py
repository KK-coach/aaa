"""TEST 3 - AI Overview citations. Costs ~$0.003 (live SERP advanced).

NOTE on tooling: the official DataForSEO MCP has NO dedicated Google
"AI Overview" tool. The AI_OPTIMIZATION module is about LLM (ChatGPT etc.)
mention tracking, not Google's AI Overview. Google's AI Overview is delivered
as an `ai_overview` element inside serp_organic_live_advanced. So this test
issues one SERP advanced call and extracts both the AI Overview and the
organic top-10 from the same response (self-contained, no Test 2 state).

Run from project root:  python -m dataforseo_mcp_test.test_ai_overview
"""

import asyncio
import sys
from urllib.parse import urlparse

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


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def _collect_ai_overview(payload: dict) -> tuple[list[str], list[str]]:
    """Return (text_snippets, citation_urls) from any ai_overview element."""
    texts: list[str] = []
    urls: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("text", "markdown", "snippet"):
                val = node.get(key)
                if isinstance(val, str) and val.strip():
                    texts.append(val.strip())
            for key in ("url", "link"):
                val = node.get(key)
                if isinstance(val, str) and val.startswith("http"):
                    urls.append(val)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for item in iter_result_items(payload):
        if item.get("type") in ("ai_overview", "ai_overview_reference"):
            walk(item)
    return texts, urls


def _organic_top10(payload: dict) -> list[str]:
    urls = []
    for item in iter_result_items(payload):
        if item.get("type") == "organic" and item.get("url"):
            urls.append(item["url"])
        if len(urls) >= 10:
            break
    return urls


async def main() -> int:
    print("=" * 70)
    print("TEST 3 - AI Overview citations  (cost ~$0.003)")
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
        cost = find_cost(payload)
        texts, cite_urls = _collect_ai_overview(payload)
        organic = _organic_top10(payload)

        cite_urls = list(dict.fromkeys(cite_urls))  # dedupe, keep order
        cite_domains = list(dict.fromkeys(d for d in map(_domain, cite_urls) if d))
        organic_domains = {d for d in map(_domain, organic) if d}

        if not texts and not cite_urls:
            print("No AI Overview was returned for this query.")
        else:
            print("--- AI Overview generated text ---")
            print((" ".join(texts))[:1200] or "(no text field)")
            print()
            print(f"--- Citation URLs ({len(cite_urls)}) ---")
            for u in cite_urls:
                print(f"  - {u}")
            print()
            print(f"--- Cited domains ({len(cite_domains)}) ---")
            print("  " + (", ".join(cite_domains) or "(none)"))
            print()
            overlap = [d for d in cite_domains if d in organic_domains]
            print(
                f"Overlap with organic top-10: {len(overlap)}/"
                f"{len(cite_domains)} cited domains also rank organically"
            )
            if overlap:
                print("  " + ", ".join(overlap))

        print()
        if cost is None:
            print("DataForSEO reported cost: not in MCP response (trimmed; "
                  "set DATAFORSEO_FULL_RESPONSE=true). AI Overview via SERP "
                  "Advanced list price ~= $0.002-0.003")
        else:
            print(f"DataForSEO reported cost: ${cost:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
