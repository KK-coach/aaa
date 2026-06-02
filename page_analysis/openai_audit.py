"""AAA-86 Sub-step 1 — ChatGPT 5.4 citation + query fan-out extraction.

ONE OpenAI Responses API call (gpt-5.4 + web_search tool) yields BOTH the
target-site citation signal AND the query fan-out — fulfilling AAA-86 and
AAA-80 Sub-step 1c in a single call/module.

AAA-80 Sub-step 1b (2026-05-20) verified the mechanism:
  - client.responses.create(model="gpt-5.4", tools=[{"type":"web_search"}],
    tool_choice="auto", input=...)
  - fan-out: output[i].action.queries where output[i].type=="web_search_call"
    (OpenAI duplicates the canonical query -> dedup required)
  - citations: output[i].content[j].annotations of type "url_citation"
  - cost ~$0.04-0.05/call (token + web_search surcharge; NOT batched)
  - latency 7-16s

Skip-finding contract (AAA-56 family): any error -> (None, 0.0) + WARN;
the audit continues. A successful call with no citations / no fan-out
returns a populated dict with empty lists (NOT None).

Cost is SEPARATE (audit_chatgpt_cost_usd, AAA-53) — never folded into
audit_cost_usd. API key from the OPENAI_API_KEY env var (the openai SDK
reads it natively); .env carries it, never hardcoded / logged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MODEL = "gpt-5.4"
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
# Working-assumption gpt-5.4 token rates (AAA-80 S1b flag); + web_search
# surcharge. Per-call cost is dominated by the surcharge.
_RATE_IN = 1.25 / 1_000_000
_RATE_OUT = 10.0 / 1_000_000
_WEB_SEARCH_SURCHARGE_USD = 0.03


def normalize_domain(url: str) -> str:
    """'https://www.kk.coach/about' -> 'kk.coach'. Exact-netloc match
    after protocol + www strip — conservative (avoids the
    'anotherkk.coach.com' != 'kk.coach' false positive)."""
    if not url:
        return ""
    u = url if url.startswith(("http://", "https://")) else "https://" + url
    parsed = urlparse(u)
    netloc = (parsed.netloc or parsed.path).split("/")[0].lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _client():
    from openai import OpenAI

    if not os.environ.get("OPENAI_API_KEY"):
        from dotenv import dotenv_values

        key = dotenv_values(_ENV_PATH).get("OPENAI_API_KEY")
        if key:
            os.environ["OPENAI_API_KEY"] = key
    return OpenAI()


def _extract(dump: dict, target_domain: str) -> tuple[list[str], list[dict], str]:
    """(fan_out_queries deduped, citations, response_text) from a dump."""
    fan_out: list[str] = []
    citations: list[dict] = []
    response_text = ""
    for item in dump.get("output") or []:
        itype = item.get("type")
        if itype == "web_search_call":
            act = item.get("action") or {}
            q = act.get("query")
            if isinstance(q, str) and q.strip():
                fan_out.append(q.strip())
            for q2 in (act.get("queries") or []):
                if isinstance(q2, str) and q2.strip():
                    fan_out.append(q2.strip())
        for cpart in (item.get("content") or []):
            if cpart.get("type") in ("output_text", "text"):
                response_text += cpart.get("text") or ""
            for ann in (cpart.get("annotations") or []):
                if ann.get("type") != "url_citation":
                    continue
                url = ann.get("url") or ""
                citations.append({
                    "title": ann.get("title") or "",
                    "url": url,
                    "is_target_site": (
                        bool(target_domain)
                        and normalize_domain(url) == target_domain
                    ),
                })
    fan_out = list(dict.fromkeys(fan_out))  # dedup, preserve order
    return fan_out, citations, response_text


async def extract_chatgpt_response(
    target_keyword: str,
    target_url: str,
) -> tuple[dict | None, float]:
    """One gpt-5.4 web-search call. Returns (chatgpt_query_response, cost).

    Skip-finding: any error / empty keyword -> (None, 0.0).
    """
    kw = (target_keyword or "").strip()
    if not kw:
        return None, 0.0

    try:
        import asyncio

        client = _client()
        prompt = (
            f"Search the web for the latest information about: {kw}. "
            "Summarize the 3 most relevant findings in 2-3 sentences total."
        )

        def _call():
            return client.responses.create(
                model=MODEL,
                tools=[{"type": "web_search"}],
                tool_choice="auto",
                input=prompt,
            )

        resp = await asyncio.to_thread(_call)
    except Exception as e:  # noqa: BLE001 — skip-finding contract
        logger.warning(
            "extract_chatgpt_response(%r) failed: %s: %s — (None, 0.0)",
            kw, type(e).__name__, e,
        )
        return None, 0.0

    try:
        dump = resp.model_dump()
        target_domain = normalize_domain(target_url)
        fan_out, citations, text = _extract(dump, target_domain)
        usage = dump.get("usage") or {}
        in_tok = usage.get("input_tokens", 0) or 0
        out_tok = usage.get("output_tokens", 0) or 0
        cost = round(
            in_tok * _RATE_IN + out_tok * _RATE_OUT
            + _WEB_SEARCH_SURCHARGE_USD, 6,
        )
        result = {
            "query": kw,
            "response_text": text[:500],
            "citations": citations,
            "target_site_cited": any(c["is_target_site"] for c in citations),
            "fan_out_queries": fan_out,
        }
        return result, cost
    except Exception as e:  # noqa: BLE001 — preserve skip-finding contract
        logger.warning(
            "extract_chatgpt_response parse failed: %s: %s",
            type(e).__name__, e,
        )
        return None, 0.0
