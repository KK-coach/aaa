"""AAA-76 Sub-step 2 — DataForSEO keyword-volume enrichment.

One batched DataForSEO Google Ads "search_volume/live" call enriches every
keyword in target_keywords_classified with monthly volume, 12-month trend,
CPC, and competition. Cost is $0.075 FLAT regardless of keyword count
(AAA-76 Sub-step 1 verified) — stored separately in
audit_keywords_volume_cost_usd (AAA-53 separation).

EXPECTED FILL RATE ~15%: AAA-84 keywords are LLM-generated page-topic
phrases, not real search queries — Google Ads has no volume for ~85% of
them. Null fields are a LEGITIMATE "no measurable search volume" SEO
signal (Path A, accepted), NOT failure. AAA-92 (watch-only) tracks a
real-keyword-discovery alternative.

Direct REST (NOT the project MCP — the MCP trims the `cost` envelope).
Skip-finding contract: any error -> ([], 0.0) + WARN, audit continues.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# AAA-135 — DataForSEO Keywords Data (Google Ads) rejects keyword strings with
# interfering chars ("Invalid Field: 'keywords'"). We sanitize a COPY of each
# keyword for the PAYLOAD ONLY; the canonical target_keywords text is never
# mutated (it's used for display/classification/storage — "2,5 cm" is correct
# there). Locked rules (Krisztián): comma->period; strip apostrophes/quotes and
# all other interfering symbols; degenerate -> skip. KEEP letters (incl. HU
# accents), digits, spaces, and the allowed/ignored "." "-" "+".
_KEYWORD_MAX_CHARS = 80
_KEYWORD_MAX_WORDS = 10
# Rule 6 allow-list of non-alphanumeric chars to KEEP (everything else that is
# not a letter/digit is dropped — this subsumes the explicit strip sets for
# apostrophes U+0027/U+2019, curly quotes, and ! @ % ^ ( ) = { } ; ~ ` < > ? \
# | ― · etc., so no interfering symbol can slip through).
_KEEP_PUNCT = frozenset(" .-+")


def _sanitize_keyword(kw: str) -> str | None:
    """Return a DataForSEO-safe copy of one keyword, or None to skip it.

    Applies the AAA-135 locked rules in order:
      1) comma -> period   2-4) strip apostrophes/quotes/invalid symbols
      5) drop 4-byte (astral) codepoints (emoji etc.)
      6) keep letters/digits/spaces/. - +   7) collapse spaces + trim
      8) >80 chars OR >10 words -> skip      9) empty -> skip
    """
    if not kw:
        return None
    s = kw.replace(",", ".")  # rule 1
    out = []
    for ch in s:
        if ord(ch) > 0xFFFF:  # rule 5: drop astral-plane codepoints (emoji)
            continue
        if ch.isalnum() or ch in _KEEP_PUNCT:  # rules 2-4/6 via allow-list
            out.append(ch)
        # else: dropped (apostrophes, quotes, invalid symbols, other punct)
    s = re.sub(r"\s+", " ", "".join(out)).strip()  # rule 7
    if not s:  # rule 9
        return None
    if len(s) > _KEYWORD_MAX_CHARS or len(s.split()) > _KEYWORD_MAX_WORDS:
        return None  # rule 8
    return s

_ENDPOINT = (
    "https://api.dataforseo.com/v3/keywords_data/google_ads/"
    "search_volume/live"
)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Phase 1: HU + EN-US. Forward-compat: add UK 2826 / AU 2036 etc. later.
LOCATION_CODE_MAP = {"hu": 2348, "en": 2840}


def resolve_location_code(audit_language: str) -> int:
    return LOCATION_CODE_MAP.get((audit_language or "").lower(), 2840)


def _credentials() -> tuple[str, str]:
    from dotenv import dotenv_values

    v = dotenv_values(_ENV_PATH)
    return v.get("DATAFORSEO_LOGIN") or "", v.get("DATAFORSEO_PASSWORD") or ""


async def fetch_keywords_volume(
    keywords: list[str],
    language_code: str,
    location_code: int,
) -> tuple[list[dict], float]:
    """Return (per_keyword_volume_data, cost_usd).

    Each result dict: {keyword, search_volume, monthly_searches, cpc,
    competition, competition_index, ...}. Unknown keywords are returned
    with null fields (not dropped). Skip-finding: errors -> ([], 0.0).
    """
    kws = [k for k in (keywords or []) if k and k.strip()]
    if not kws:
        return [], 0.0

    login, password = _credentials()
    if not login or not password:
        logger.warning("fetch_keywords_volume: DataForSEO creds missing")
        return [], 0.0

    # AAA-135: build the sanitized PAYLOAD copy (canonical kws untouched). Keep a
    # sanitized->canonical map (lower-cased keys; DataForSEO echoes keywords
    # lower-cased) so the caller's canonical-keyed join still matches after we
    # restore the canonical text onto each returned result below. Per-keyword
    # skip-finding: a degenerate keyword is omitted from the payload (cost is a
    # flat $0.075 regardless of count), the rest of the batch proceeds.
    payload_keywords: list[str] = []
    sanitized_to_canonical: dict[str, str] = {}
    skipped: list[str] = []
    for canon in kws:
        san = _sanitize_keyword(canon)
        if san is None:
            skipped.append(canon)
            continue
        payload_keywords.append(san)
        sanitized_to_canonical.setdefault(san.lower(), canon)
    if skipped:
        logger.info(
            "fetch_keywords_volume: %d/%d keyword(s) skipped after sanitize: %s",
            len(skipped), len(kws), skipped,
        )
    if not payload_keywords:
        return [], 0.0

    body = [{
        "keywords": payload_keywords,
        "language_code": language_code,
        "location_code": location_code,
    }]

    def _call() -> tuple[list[dict], float]:
        import requests
        from requests.auth import HTTPBasicAuth

        resp = requests.post(
            _ENDPOINT, auth=HTTPBasicAuth(login, password),
            json=body, timeout=120,
        )
        resp.raise_for_status()
        j = resp.json()
        cost = float(j.get("cost") or 0.0)
        tasks = j.get("tasks") or []
        result = (tasks[0].get("result") or []) if tasks else []
        return list(result), cost

    try:
        result, cost = await asyncio.to_thread(_call)
    except Exception as e:  # noqa: BLE001 — skip-finding contract
        logger.warning(
            "fetch_keywords_volume failed: %s: %s — returning ([], 0.0)",
            type(e).__name__, e,
        )
        return [], 0.0

    # AAA-135: restore the canonical keyword onto each result so the caller's
    # canonical-keyed join (vol_map keyed on c["keyword"]) still attaches volume
    # to sanitized keywords. We only relabel DataForSEO's response copy; the
    # canonical target_keywords source is never mutated.
    for r in result:
        echoed = (r.get("keyword") or "").lower()
        canon = sanitized_to_canonical.get(echoed)
        if canon is not None:
            r["keyword"] = canon
    return list(result), round(cost, 6)
