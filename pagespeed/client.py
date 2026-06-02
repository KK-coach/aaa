"""Async Google PageSpeed Insights v5 client.

Returns a flat, structured dict of category scores + Core Web Vitals,
preferring real-user field data (CrUX) over Lighthouse lab data when both
are present. Never raises — failures come back as an error dict.
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
TIMEOUT_SECONDS = 120.0  # AAA-89 S0: 60s timed out on 2/8 probe URLs; 120s comfortable

# Google Core Web Vitals thresholds: (good_max, needs_improvement_max).
# Value < good_max -> "good"; < ni_max -> "needs_improvement"; else "poor".
_THRESHOLDS = {
    "lcp": (2500, 4000),
    "fid": (100, 300),
    "inp": (100, 300),
    "cls": (0.1, 0.25),
    "fcp": (1800, 3000),
    "ttfb": (800, 1800),
}

# metric -> (lab audit id, CrUX field metric key)
_METRIC_SOURCES = {
    "lcp": ("largest-contentful-paint", "LARGEST_CONTENTFUL_PAINT_MS"),
    "fid": ("max-potential-fid", "FIRST_INPUT_DELAY_MS"),
    "inp": ("interaction-to-next-paint", "INTERACTION_TO_NEXT_PAINT"),
    "cls": ("cumulative-layout-shift", "CUMULATIVE_LAYOUT_SHIFT_SCORE"),
    "fcp": ("first-contentful-paint", "FIRST_CONTENTFUL_PAINT_MS"),
    "ttfb": ("server-response-time", "EXPERIMENTAL_TIME_TO_FIRST_BYTE"),
}


def _rating(metric: str, value: float | None) -> str | None:
    if value is None:
        return None
    good_max, ni_max = _THRESHOLDS[metric]
    if value < good_max:
        return "good"
    if value < ni_max:
        return "needs_improvement"
    return "poor"


def _load_api_key() -> str | None:
    if not ENV_PATH.exists():
        return None
    return dotenv_values(ENV_PATH).get("GOOGLE_PAGESPEED_API_KEY") or None


def _score(categories: dict, key: str) -> int | None:
    cat = categories.get(key) or {}
    raw = cat.get("score")
    return round(raw * 100) if isinstance(raw, (int, float)) else None


def _cwv(metric: str, audits: dict, field_metrics: dict) -> dict:
    """Prefer CrUX field data; fall back to Lighthouse lab data."""
    lab_id, field_key = _METRIC_SOURCES[metric]
    value: float | None = None

    field = field_metrics.get(field_key)
    if isinstance(field, dict) and "percentile" in field:
        pct = field["percentile"]
        # CrUX CLS percentile is x100 integer (e.g. 10 -> 0.10).
        value = pct / 100.0 if metric == "cls" else float(pct)
    elif metric != "fid":
        # FID is deprecated and removed from CrUX. Do NOT fall back to the
        # lab `max-potential-fid` audit — it's a pessimistic worst-case that
        # misleads consumers. INP is the authoritative responsiveness signal,
        # so fid stays None/None when no real-user FID exists.
        audit = audits.get(lab_id) or {}
        num = audit.get("numericValue")
        if isinstance(num, (int, float)):
            value = float(num)

    if value is None:
        return {"value": None, "rating": None} if metric == "cls" else {
            "value_ms": None,
            "rating": None,
        }

    rating = _rating(metric, value)
    if metric == "cls":
        return {"value": round(value, 4), "rating": rating}
    return {"value_ms": round(value, 1), "rating": rating}


def _collect_audits(audits: dict) -> tuple[list[dict], list[dict]]:
    opportunities: list[dict] = []
    diagnostics: list[dict] = []
    for audit_id, audit in audits.items():
        if not isinstance(audit, dict):
            continue
        score = audit.get("score")
        mode = audit.get("scoreDisplayMode")
        if mode in ("notApplicable", "informative", "manual", "error"):
            continue
        if not isinstance(score, (int, float)) or score >= 1.0:
            continue
        details = audit.get("details") or {}
        title = audit.get("title", audit_id)
        desc = audit.get("description", "")
        if details.get("type") == "opportunity":
            savings = details.get("overallSavingsMs")
            if savings is None:
                num = audit.get("numericValue")
                savings = num if isinstance(num, (int, float)) else None
            opportunities.append(
                {
                    "id": audit_id,
                    "title": title,
                    "description": desc,
                    "savings_ms": int(savings) if savings is not None else None,
                }
            )
        else:
            diagnostics.append(
                {"id": audit_id, "title": title, "description": desc,
                 "_score": score}
            )

    opportunities.sort(key=lambda o: o["savings_ms"] or 0, reverse=True)
    diagnostics.sort(key=lambda d: d["_score"])
    for d in diagnostics:
        d.pop("_score", None)
    return opportunities[:5], diagnostics[:5]


async def get_pagespeed_score(url: str, strategy: str = "mobile") -> dict:
    """Get PageSpeed Insights score for a URL.

    strategy: "mobile" or "desktop". Returns a structured dict; on failure
    returns {"error", "error_type"} with error_type one of config_error,
    timeout, api_error, invalid_url.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {
            "url": url,
            "error": f"not a valid http(s) URL: {url!r}",
            "error_type": "invalid_url",
        }

    strategy = strategy if strategy in ("mobile", "desktop") else "mobile"

    api_key = _load_api_key()
    if not api_key:
        return {
            "url": url,
            "error": "API key missing (GOOGLE_PAGESPEED_API_KEY not in .env)",
            "error_type": "config_error",
        }

    params = [
        ("url", url),
        ("strategy", strategy),
        ("category", "performance"),
        ("category", "accessibility"),
        ("category", "best-practices"),
        ("category", "seo"),
        ("key", api_key),
    ]

    # PSI is slow and intermittently exceeds the timeout; one retry on
    # timeout ONLY is the standard production mitigation. Other errors
    # (network/api/config/url) are NOT retried.
    max_attempts = 2
    resp = None
    fetch_time_ms = 0
    for attempt in range(1, max_attempts + 1):
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                resp = await client.get(ENDPOINT, params=params)
            fetch_time_ms = int((time.perf_counter() - start) * 1000)
            break
        except httpx.TimeoutException as exc:
            if attempt < max_attempts:
                print(
                    f"[pagespeed] timeout on attempt {attempt}/{max_attempts} "
                    f"for {url} [{strategy}] - retrying once..."
                )
                continue
            return {
                "url": url,
                "error": (
                    f"PageSpeed analysis timed out after {TIMEOUT_SECONDS}s "
                    f"on {max_attempts} attempts: {exc}"
                ),
                "error_type": "timeout",
            }
        except httpx.RequestError as exc:
            return {
                "url": url,
                "error": f"network error: {exc!r}",
                "error_type": "api_error",
            }

    try:
        data = resp.json()
    except ValueError:
        return {
            "url": url,
            "error": f"non-JSON response (HTTP {resp.status_code})",
            "error_type": "api_error",
        }

    if "error" in data:
        msg = data["error"].get("message", "unknown API error")
        low = msg.lower()
        if any(s in low for s in ("invalid", "not valid", "malformed")) and (
            "url" in low
        ):
            return {"url": url, "error": msg, "error_type": "invalid_url"}
        return {"url": url, "error": msg, "error_type": "api_error"}

    if resp.status_code != 200:
        return {
            "url": url,
            "error": f"HTTP {resp.status_code} from PageSpeed API",
            "error_type": "api_error",
        }

    lh = data.get("lighthouseResult") or {}
    categories = lh.get("categories") or {}
    audits = lh.get("audits") or {}
    loading = data.get("loadingExperience") or {}
    field_metrics = loading.get("metrics") or {}

    field_available = bool(field_metrics)
    lab_available = bool(audits)

    cwv = {
        m: _cwv(m, audits, field_metrics) for m in _METRIC_SOURCES
    }
    opportunities, diagnostics = _collect_audits(audits)

    return {
        "url": url,
        "strategy": strategy,
        "fetch_time_ms": fetch_time_ms,
        "final_url": lh.get("finalUrl") or data.get("id") or url,
        "scores": {
            "performance": _score(categories, "performance"),
            "accessibility": _score(categories, "accessibility"),
            "best_practices": _score(categories, "best-practices"),
            "seo": _score(categories, "seo"),
        },
        "core_web_vitals": cwv,
        "field_data_available": field_available,
        "lab_data_available": lab_available,
        "opportunities": opportunities,
        "diagnostics": diagnostics,
        # AAA-89: raw CrUX field blocks for downstream extraction
        # (page_analysis/crux_field_data.py). Carried through verbatim;
        # the Discovery integration pops these before archive (transient).
        "loadingExperience": data.get("loadingExperience"),
        "originLoadingExperience": data.get("originLoadingExperience"),
    }
