"""AAA-89 Sub-step 1 — CrUX field-data extraction from PSI response.

Option A: parse the `loadingExperience` + `originLoadingExperience` blocks
already present in the PSI response (no new endpoint, no new API key, no
new quota). Sub-step 0 (2026-05-23) verified Option A viability across
8 URLs.

CONTRACT:
- Pure function on a PSI response dict. Never raises.
- `_error` is DISTINCT from `has_data=False`: `_error` means the PSI call
  itself failed (timeout / 4xx / 5xx / config) — caller passes the raw
  PSI response which carries `error` / `error_type` keys; the module
  surfaces those into `_error`. `has_data=False` means PSI succeeded but
  the CrUX block is missing/`NONE` (low-traffic site — legitimate signal).

Sub-step 0 finding #1: PSI run-to-run flakiness — the same URL can return
a populated block once and `null` the next call. Implication: callers
should treat `has_data` as a single-snapshot signal, not a guarantee.

Sub-step 0 finding #4 (forward-compat): metric names tolerated via the
alias map — if Google later promotes "EXPERIMENTAL_*" out of experimental
status, the matcher accepts both names.
"""

from __future__ import annotations

from typing import Any

FORM_FACTOR = "phone"  # Phase 1: mobile only (matches the mobile PSI call)

# Output-key -> ordered list of PSI metric names to try (first match wins).
_METRIC_ALIASES: dict[str, list[str]] = {
    "lcp": ["LARGEST_CONTENTFUL_PAINT_MS"],
    "inp": [
        "INTERACTION_TO_NEXT_PAINT",
        "EXPERIMENTAL_INTERACTION_TO_NEXT_PAINT",
    ],
    "cls": ["CUMULATIVE_LAYOUT_SHIFT_SCORE"],
    "fcp": ["FIRST_CONTENTFUL_PAINT_MS"],
    "ttfb": [
        "EXPERIMENTAL_TIME_TO_FIRST_BYTE",
        "TIME_TO_FIRST_BYTE",
    ],
}
_VALID_CATEGORIES = {"FAST", "AVERAGE", "SLOW"}


def _empty_scope() -> dict:
    return {"has_data": False, "overall_category": None, "metrics": {}}


def _parse_metric(key: str, metric_block: dict | None) -> dict | None:
    """Convert a PSI metric block into {p75[_ms], category}.

    CrUX CLS percentile is x100 integer (e.g. PSI returns 13 → 0.13).
    All other metrics are millisecond integers passed through unchanged.
    """
    if not isinstance(metric_block, dict):
        return None
    pct = metric_block.get("percentile")
    cat = metric_block.get("category")
    if pct is None or cat not in _VALID_CATEGORIES:
        return None
    if key == "cls":
        return {"p75": round(float(pct) / 100.0, 4), "category": cat}
    try:
        return {"p75_ms": int(pct), "category": cat}
    except (TypeError, ValueError):
        return None


def _parse_scope(block: dict | None) -> dict:
    """Parse one of {loadingExperience, originLoadingExperience} → scope."""
    if not isinstance(block, dict):
        return _empty_scope()
    overall = block.get("overall_category")
    if overall not in _VALID_CATEGORIES:
        # PSI returns block with overall_category=None / "NONE" when no
        # CrUX data — treat as has_data=False (legitimate signal).
        return _empty_scope()
    metrics_in = block.get("metrics") or {}
    metrics_out: dict[str, dict] = {}
    for out_key, aliases in _METRIC_ALIASES.items():
        for alias in aliases:
            parsed = _parse_metric(out_key, metrics_in.get(alias))
            if parsed is not None:
                metrics_out[out_key] = parsed
                break  # first-match-wins (name-tolerant)
    return {
        "has_data": True,
        "overall_category": overall,
        "metrics": metrics_out,
    }


def _collection_period_end(psi_response: dict) -> str | None:
    """Try several known PSI keys for the CrUX collection-period end date.
    PSI sometimes carries this, sometimes not (Sub-step 0 sample didn't);
    tolerant lookup, returns None if absent."""
    le = psi_response.get("loadingExperience") or {}
    for path in (
        ("loadingExperience", "collection_period", "lastDate"),
        ("loadingExperience", "collectionPeriod", "lastDate"),
    ):
        node: Any = psi_response
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if isinstance(node, dict):
            y = node.get("year"); m = node.get("month"); d = node.get("day")
            if isinstance(y, int) and isinstance(m, int) and isinstance(d, int):
                return f"{y:04d}-{m:02d}-{d:02d}"
        if isinstance(node, str):
            return node
    # Some PSI variants put it directly on the LE block.
    cp = le.get("collection_period") or le.get("collectionPeriod")
    if isinstance(cp, dict):
        y = cp.get("year"); m = cp.get("month"); d = cp.get("day")
        if isinstance(y, int) and isinstance(m, int) and isinstance(d, int):
            return f"{y:04d}-{m:02d}-{d:02d}"
    return None


def extract_crux_from_psi_response(psi_response: dict) -> dict:
    """Extract the AAA-89 CrUX schema from a PSI response dict.

    `_error` precedence:
      - PSI call failed (response has `error` / `error_type`)
        -> _error = error_type, scopes empty.
      - PSI call succeeded but CrUX block missing/NONE
        -> _error = None, has_data = False on the affected scope.
    """
    if not isinstance(psi_response, dict):
        return {
            "url_level": _empty_scope(),
            "origin_level": _empty_scope(),
            "form_factor": FORM_FACTOR,
            "collection_period_end": None,
            "_error": "invalid_psi_response",
        }
    if psi_response.get("error"):
        return {
            "url_level": _empty_scope(),
            "origin_level": _empty_scope(),
            "form_factor": FORM_FACTOR,
            "collection_period_end": None,
            "_error": (
                psi_response.get("error_type")
                or str(psi_response.get("error"))[:60]
            ),
        }
    return {
        "url_level": _parse_scope(psi_response.get("loadingExperience")),
        "origin_level": _parse_scope(
            psi_response.get("originLoadingExperience")
        ),
        "form_factor": FORM_FACTOR,
        "collection_period_end": _collection_period_end(psi_response),
        "_error": None,
    }
