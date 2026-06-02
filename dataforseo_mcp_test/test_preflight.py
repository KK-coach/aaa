"""Standalone DataForSEO health check (FREE, no paid API cost).

Useful for CI / manual checks: verifies credentials and prints balance +
rate-limit info without touching any paid endpoint.

Run from project root:  python -m dataforseo_mcp_test.test_preflight
"""

import asyncio
import json
import sys

from dataforseo_mcp_test.preflight import check_credentials


async def main() -> int:
    print("=" * 70)
    print("DataForSEO PREFLIGHT - credential & account health check (free)")
    print("=" * 70)

    info = await check_credentials()

    print(f"login        : {info.get('login_masked')}")
    print(f"valid        : {info['valid']}")
    print(f"balance_usd  : {info['balance_usd']}")
    print(f"balance_warn : {info['balance_warning']}")
    if info.get("rate_limits") is not None:
        # Can be large/all-zero on pay-as-you-go accounts; show compactly.
        rl = json.dumps(info["rate_limits"])
        print(f"rate_limits  : {rl[:200]}{' ...' if len(rl) > 200 else ''}")
    else:
        print("rate_limits  : None")
    print(f"error        : {info['error']}")

    if not info["valid"]:
        print("\nRESULT: UNHEALTHY")
        return 1
    print("\nRESULT: HEALTHY")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
