"""Shared connection helper for the DataForSEO MCP server (stdio transport).

Why a helper module: all three test scripts need identical, careful setup
(credential loading + masking, env var name mapping, npx resolution on
Windows, stderr surfacing). Centralising it keeps the tests readable.

Key facts discovered from the official repo
(github.com/dataforseo/mcp-server-typescript, npm `dataforseo-mcp-server`):

* The server authenticates with ``DATAFORSEO_USERNAME`` / ``DATAFORSEO_PASSWORD``.
  Our project .env uses ``DATAFORSEO_LOGIN`` / ``DATAFORSEO_PASSWORD``, so we
  map LOGIN -> USERNAME when launching the subprocess.
* Module names for ``ENABLED_MODULES`` are UPPERCASE and comma-separated:
  ``SERP``, ``AI_OPTIMIZATION``, ``KEYWORDS_DATA`` (NOT serp/ai_optimization/
  keywords). Full set also includes ONPAGE, DATAFORSEO_LABS, BACKLINKS,
  BUSINESS_DATA, DOMAIN_ANALYTICS, CONTENT_ANALYSIS.
* Running ``npx dataforseo-mcp-server`` with no extra arg = stdio mode
  ("direct MCP communication"); ``... http`` would start an HTTP server.
"""

from __future__ import annotations

import base64
import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

try:  # Python 3.11+ has it builtin; 3.10 uses the anyio-provided backport.
    BaseExceptionGroup  # type: ignore[used-before-def]  # noqa: B018
except NameError:  # pragma: no cover
    from exceptiongroup import BaseExceptionGroup  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# Only the three modules we actually need — cost & blast-radius control.
ENABLED_MODULES = "SERP,AI_OPTIMIZATION,KEYWORDS_DATA"

# AAA-31 S3b-fix: connection mode. 'remote' (default) talks to the DataForSEO
# HOSTED MCP endpoint over streamable-HTTP, so no Node/npx is needed in the
# worker image (prod path). 'stdio' keeps the local `npx dataforseo-mcp-server`
# subprocess (local-dev convenience). Both are env-configurable.
DEFAULT_MCP_URL = "https://mcp.dataforseo.com/mcp"


def _mcp_mode() -> str:
    return (os.environ.get("DATAFORSEO_MCP_MODE") or "remote").strip().lower()


def _mcp_url() -> str:
    return os.environ.get("DATAFORSEO_MCP_URL") or DEFAULT_MCP_URL


def _basic_auth_header() -> str:
    """HTTP Basic header from the DataForSEO creds. Computed from the existing
    env secrets; the token/value is NEVER logged."""
    login, password = load_credentials()
    token = base64.b64encode(("%s:%s" % (login, password)).encode("utf-8")).decode("ascii")
    return "Basic %s" % token


def load_credentials() -> tuple[str, str]:
    """Resolve DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD.

    AAA-31 Sub-step 2: env-first. On Cloud Run these are injected from Secret
    Manager into the process environment; for local dev we fall back to the
    project-root .env (dotenv_values, never auto-exported into os.environ).
    Never hardcoded; never echoed unmasked.
    """
    login = os.environ.get("DATAFORSEO_LOGIN")
    password = os.environ.get("DATAFORSEO_PASSWORD")
    if not login or not password:
        # Local-dev fallback: read .env without polluting os.environ.
        if ENV_PATH.exists():
            values = dotenv_values(ENV_PATH)
            login = login or values.get("DATAFORSEO_LOGIN")
            password = password or values.get("DATAFORSEO_PASSWORD")
    if not login or not password:
        raise KeyError(
            "DATAFORSEO_LOGIN and/or DATAFORSEO_PASSWORD missing from both "
            "the environment and %s" % ENV_PATH
        )
    return login, password


def mask(value: str) -> str:
    """Mask a credential for logging.

    'user@example.com' -> 'user@***.com'; non-emails -> first 2 chars + ***.
    """
    if "@" in value:
        local, _, domain = value.partition("@")
        tld = domain.rsplit(".", 1)[-1] if "." in domain else "***"
        return f"{local}@***.{tld}"
    return f"{value[:2]}***" if len(value) > 2 else "***"


def _resolve_npx() -> str:
    """Resolve the npx executable (Windows ships it as npx.cmd)."""
    for candidate in ("npx", "npx.cmd"):
        found = shutil.which(candidate)
        if found:
            return found
    # Last resort: let the OS PATH resolve it.
    return "npx.cmd" if sys.platform == "win32" else "npx"


def build_server_params() -> StdioServerParameters:
    login, password = load_credentials()
    # Pass the full parent environment (so npx/node resolve) plus the
    # server-specific vars. NOTE the LOGIN -> USERNAME remapping.
    child_env = dict(os.environ)
    child_env.update(
        {
            "DATAFORSEO_USERNAME": login,
            "DATAFORSEO_PASSWORD": password,
            "ENABLED_MODULES": ENABLED_MODULES,
        }
    )
    return StdioServerParameters(
        command=_resolve_npx(),
        args=["-y", "dataforseo-mcp-server"],
        env=child_env,
    )


@contextlib.asynccontextmanager
async def open_session():
    """Yield an initialized MCP ClientSession.

    Dispatches on DATAFORSEO_MCP_MODE: 'remote' (default) uses the hosted
    DataForSEO MCP endpoint over streamable-HTTP (no Node needed); 'stdio' uses
    the local npx subprocess. The SERP tool + downstream parsing are identical
    either way (same ClientSession.call_tool interface).
    """
    if _mcp_mode() == "stdio":
        async with _open_stdio_session() as session:
            yield session
    else:
        async with _open_remote_session() as session:
            yield session


@contextlib.asynccontextmanager
async def _open_remote_session():
    """Initialized ClientSession against the hosted DataForSEO MCP endpoint
    (streamable-HTTP + HTTP Basic auth)."""
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": _basic_auth_header()}
    async with streamablehttp_client(_mcp_url(), headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@contextlib.asynccontextmanager
async def _open_stdio_session():
    """Yield an initialized MCP ClientSession over stdio.

    The MCP server's stderr is captured to a temp file; if startup fails we
    raise with the *actual* server stderr appended, not a wrapped opaque
    exception.
    """
    params = build_server_params()
    # Binary mode: the server emits UTF-8 / non-cp1252 bytes to stderr; a text
    # file with the Windows default codec would crash when we read it back.
    stderr_file = tempfile.NamedTemporaryFile(
        mode="w+b", suffix="_dataforseo_mcp_stderr.log", delete=False
    )

    def _read_stderr() -> str:
        try:
            stderr_file.flush()
            stderr_file.seek(0)
            return stderr_file.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return "(could not read server stderr)"

    def _leaf(exc: BaseException) -> BaseException:
        # stdio_client runs in an anyio task group, so a bug in the caller's
        # body comes back wrapped in an ExceptionGroup. Drill to the real one.
        while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
            exc = exc.exceptions[0]
        return exc

    initialized = False
    try:
        try:
            async with stdio_client(params, errlog=stderr_file) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    initialized = True
                    yield session
        except Exception as exc:
            leaf = _leaf(exc)
            if not initialized:
                # Genuine startup/transport failure — surface server stderr.
                raise RuntimeError(
                    f"MCP server failed to start "
                    f"({type(leaf).__name__}: {leaf}).\n"
                    f"--- dataforseo-mcp-server stderr ---\n"
                    f"{_read_stderr() or '(no stderr captured)'}"
                ) from exc
            # Session was up: this is a bug in the caller's body (or a
            # post-response teardown). Re-raise the real exception, unwrapped.
            raise leaf
    finally:
        stderr_file.close()
        with contextlib.suppress(OSError):
            os.unlink(stderr_file.name)


def result_to_json(call_result) -> dict:
    """Turn an MCP call_tool result into the parsed DataForSEO JSON dict.

    The server returns the API payload as a text content block; we json-load
    the first text block that parses.
    """
    import json

    for block in getattr(call_result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            continue
    return {}


def find_cost(payload: dict):
    """Find a 'cost' value anywhere in the payload.

    The MCP server returns a TRIMMED response (no tasks/cost envelope unless
    DATAFORSEO_FULL_RESPONSE=true), so cost is usually absent here. Returns
    None when not exposed so callers can report that honestly.
    """
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("cost"), (int, float)):
        return float(payload["cost"])
    total = 0.0
    found = False
    for task in payload.get("tasks", []) or []:
        c = task.get("cost") if isinstance(task, dict) else None
        if isinstance(c, (int, float)):
            total += c
            found = True
    return total if found else None


def iter_result_items(payload: dict):
    """Yield every SERP item, tolerant of both response shapes.

    * MCP trimmed shape:  {id, status_code, items: [...]}
    * Raw DataForSEO:     {tasks: [{result: [{items: [...]}]}]}
    Nested element groups (e.g. type 'recipes' / 'ai_overview' with their own
    'items') are also descended into.
    """
    def _walk(items):
        for item in items or []:
            if not isinstance(item, dict):
                # e.g. related_searches has items: ["query", ...] (strings)
                continue
            yield item
            if isinstance(item.get("items"), list):
                yield from _walk(item["items"])

    if isinstance(payload.get("items"), list):
        yield from _walk(payload["items"])
    for task in (payload.get("tasks") or []):
        for res in (task.get("result") or []):
            yield from _walk(res.get("items"))


def print_credential_banner() -> None:
    login, _ = load_credentials()
    print(f"Auth: DATAFORSEO_LOGIN = {mask(login)} (mapped -> DATAFORSEO_USERNAME)")
    print(f"ENABLED_MODULES = {ENABLED_MODULES}")
