"""Free credential / account preflight for DataForSEO.

Runs the FREE `appendix/user_data` endpoint to fail fast BEFORE any paid
API call. Reusable — the three test scripts call `preflight_gate()` once
each instead of duplicating the logic.

NOTE on the `session` argument: the spec asked to call user_data "through
the MCP session", but the official DataForSEO MCP server does NOT expose a
user_data tool under our restricted modules (SERP / AI_OPTIMIZATION /
KEYWORDS_DATA) — user_data is an `appendix` endpoint with no MCP tool. So we
keep the `session` parameter for API symmetry / future-proofing (used only if
a user_data-like tool ever appears) and otherwise call the free REST endpoint
directly with the same credentials. It stays free either way.
"""

from __future__ import annotations

import httpx

from dataforseo_mcp_test.mcp_client import load_credentials

USER_DATA_URL = "https://api.dataforseo.com/v3/appendix/user_data"
BALANCE_WARNING_THRESHOLD = 1.00

# ANSI colours (harmless if the terminal ignores them).
_YELLOW = "\033[33m"
_RESET = "\033[0m"


def mask_email(email: str) -> str:
    """'user@example.com' -> 'u***@example.com' (first char + domain kept)."""
    if "@" not in email:
        return (email[:1] + "***") if email else "***"
    local, _, domain = email.partition("@")
    first = local[:1] or "*"
    return f"{first}***@{domain}"


def _find_user_data_tool(session) -> str | None:
    """Return a user_data MCP tool name if one exists (currently none)."""
    tools = getattr(session, "_cached_tool_names", None)
    if tools is None:
        return None
    for name in tools:
        if "user_data" in name.lower():
            return name
    return None


async def check_credentials(session=None) -> dict:
    """Verify credentials + account state via the free user_data endpoint.

    Returns a dict: valid, balance_usd, balance_warning, rate_limits, error.
    Never raises — all failures come back as ``valid=False`` + ``error``.
    """
    result = {
        "valid": False,
        "balance_usd": None,
        "balance_warning": False,
        "rate_limits": None,
        "error": None,
        "login_masked": None,
    }

    try:
        login, password = load_credentials()
    except (FileNotFoundError, KeyError) as exc:
        result["error"] = f"credential load failed: {exc}"
        return result

    result["login_masked"] = mask_email(login)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(USER_DATA_URL, auth=(login, password))
    except httpx.HTTPError as exc:
        result["error"] = f"network error contacting user_data: {exc!r}"
        return result

    if resp.status_code == 401:
        result["error"] = (
            "HTTP 401 - invalid DataForSEO API credentials "
            "(check DATAFORSEO_PASSWORD is the API password from "
            "app.dataforseo.com/api-access, not the dashboard password)"
        )
        return result
    if resp.status_code != 200:
        result["error"] = f"HTTP {resp.status_code} from user_data endpoint"
        return result

    try:
        payload = resp.json()
        task = (payload.get("tasks") or [{}])[0]
        if task.get("status_code") != 20000:
            result["error"] = (
                f"API status {task.get('status_code')}: "
                f"{task.get('status_message')}"
            )
            return result
        data = (task.get("result") or [{}])[0]
        money = data.get("money") or {}
        balance = money.get("balance")
        result["balance_usd"] = (
            round(float(balance), 5) if balance is not None else None
        )
        result["rate_limits"] = (data.get("rates") or {}).get("limits")
        result["balance_warning"] = (
            result["balance_usd"] is not None
            and result["balance_usd"] < BALANCE_WARNING_THRESHOLD
        )
        result["valid"] = True
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        result["error"] = f"could not parse user_data response: {exc!r}"

    return result


async def preflight_gate(session=None) -> bool:
    """Run the preflight and print a one-line verdict.

    Returns True if it is safe to proceed (credentials valid). Returns False
    if the caller must abort BEFORE any paid call (error already printed).
    A low balance prints a yellow warning but still returns True.
    """
    info = await check_credentials(session)
    who = info.get("login_masked") or "?"

    if not info["valid"]:
        print(f"Preflight FAILED ({who}): {info['error']}")
        return False

    bal = info["balance_usd"]
    print(f"Preflight OK ({who}), balance ${bal:.2f}")
    if info["balance_warning"]:
        print(
            f"{_YELLOW}WARNING: balance ${bal:.2f} is below "
            f"${BALANCE_WARNING_THRESHOLD:.2f} - paid calls may fail soon."
            f"{_RESET}"
        )
    return True
