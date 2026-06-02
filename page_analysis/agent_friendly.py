"""AAA-42 Sub-step 1 — agent-friendliness raw-HTML measurement.

Pure deterministic selectolax measurement on the crawler's raw HTML. NO
Gemini, NO Playwright, NO paid API. Cost $0. Latency <2s per audit.

7 dimensions (Sub-step 0 capability probe validated): semantic_html,
landmarks, heading, forms, images, aria, schema_actions. CTA quality
(Sub-step 0 dimension 8) deferred to Sub-step 2/Gemini judgment — the
8-word heuristic landed 91-96% of CTAs in "ambivalent" (Sub-step 0
finding); not viable as deterministic measurement.

Sub-step 0 ARIA refinement applied: anchors counted in `interactive`
ONLY if they have non-empty inner text OR an aria-label/labelledby —
icon-only-no-aria anchors are EXCLUDED from the denominator (was
inflating the count on icon-heavy sites like vercel).

Skip-finding (AAA-56 family): if selectolax parsing fails, every
sub-dimension returns its default and `_error` is set; per-dimension
exceptions degrade only that dimension and accumulate into `_error`.
The audit always continues.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_LANDMARKS = ("nav", "main", "article", "aside", "header", "footer")
_ACTION_TYPE_ALLOWLIST = {
    "BuyAction", "ReservationAction", "ContactPoint", "OrderAction",
    "SearchAction", "EventReservation", "FoodEstablishment",
    "ScheduleAction", "PayAction", "CommunicateAction",
    "ConfirmAction", "RsvpAction",
}


def _default() -> dict:
    return {
        "semantic_html": {
            "button_count": 0, "div_onclick_count": 0,
            "has_div_onclick_antipattern": False,
        },
        "landmarks": {"present": [], "missing": list(_LANDMARKS),
                      "count": 0},
        "heading": {"h1_count": 0, "total_headings": 0, "level_skips": 0},
        "forms": {"input_count": 0, "label_coverage": 1.0},
        "images": {"img_count": 0, "alt_count": 0},
        "aria": {"interactive_count": 0, "with_aria_count": 0},
        "schema_actions": [],
        "_error": None,
    }


def _safe(name: str, fn, out: dict, errors: list[str]) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 — per-dimension skip-finding
        errors.append(name)
        logger.warning("agent_friendly: dimension %s failed: %s: %s",
                       name, type(e).__name__, e)


def measure_agent_friendliness(raw_html: str) -> dict:
    """Measure 7 raw-HTML agent-friendliness dimensions on `raw_html`.

    Returns the schema documented in the module docstring + AAA-42 spec.
    Per-dimension skip-finding: failures degrade that dimension and
    accumulate into `_error`; the rest still run.
    """
    out = _default()
    if not raw_html or not raw_html.strip():
        out["_error"] = "empty_html"
        return out

    try:
        from selectolax.parser import HTMLParser

        p = HTMLParser(raw_html)
    except Exception as e:  # noqa: BLE001
        out["_error"] = "html_parse_failed"
        logger.warning("agent_friendly: parse failed: %s: %s",
                       type(e).__name__, e)
        return out

    errors: list[str] = []

    # (1) Semantic HTML
    def _sem() -> None:
        btn = len(p.css("button"))
        div_oc = len(p.css("div[onclick]")) + len(p.css("a[onclick]"))
        out["semantic_html"] = {
            "button_count": btn,
            "div_onclick_count": div_oc,
            "has_div_onclick_antipattern": div_oc > 0,
        }
    _safe("semantic_html", _sem, out, errors)

    # (2) Landmarks
    def _lm() -> None:
        present = [t for t in _LANDMARKS if p.css_first(t) is not None]
        missing = [t for t in _LANDMARKS if t not in present]
        out["landmarks"] = {"present": present, "missing": missing,
                            "count": len(present)}
    _safe("landmarks", _lm, out, errors)

    # (3) Headings — in-document-order
    def _hd() -> None:
        levels: list[int] = []
        H = {"h1", "h2", "h3", "h4", "h5", "h6"}
        for node in p.root.traverse(include_text=False):
            if node.tag in H:
                levels.append(int(node.tag[1]))
        skips = sum(
            1 for i in range(1, len(levels))
            if levels[i] - levels[i - 1] > 1
        )
        out["heading"] = {
            "h1_count": sum(1 for x in levels if x == 1),
            "total_headings": len(levels),
            "level_skips": skips,
        }
    _safe("heading", _hd, out, errors)

    # (4) Forms — non-hidden inputs + label coverage
    def _fm() -> None:
        inputs = [
            i for i in p.css("input")
            if (i.attributes.get("type") or "").lower() != "hidden"
        ]
        n = len(inputs)
        label_for = {
            (lab.attributes.get("for") or "").strip()
            for lab in p.css("label")
            if lab.attributes.get("for")
        }
        matched = 0
        for inp in inputs:
            iid = (inp.attributes.get("id") or "").strip()
            if iid and iid in label_for:
                matched += 1
                continue
            par = inp.parent
            while par is not None:
                if par.tag == "label":
                    matched += 1
                    break
                par = par.parent
        cov = (matched / n) if n else 1.0
        out["forms"] = {"input_count": n, "label_coverage": round(cov, 3)}
    _safe("forms", _fm, out, errors)

    # (5) Images — alt
    def _img() -> None:
        imgs = p.css("img")
        n = len(imgs)
        alt = sum(
            1 for i in imgs if (i.attributes.get("alt") or "").strip()
        )
        out["images"] = {"img_count": n, "alt_count": alt}
    _safe("images", _img, out, errors)

    # (6) ARIA on text-bearing interactive (Sub-step 0 refinement)
    def _aria() -> None:
        interactive: list[Any] = []
        for b in p.css("button"):
            interactive.append(b)
        for i in p.css("input"):
            if (i.attributes.get("type") or "").lower() != "hidden":
                interactive.append(i)
        for a in p.css("a[href]"):
            txt = (a.text(deep=True) or "").strip()
            has_aria = any(
                a.attributes.get(k)
                for k in ("aria-label", "aria-labelledby")
            )
            if txt or has_aria:
                interactive.append(a)
        with_aria = sum(
            1 for e in interactive if any(
                e.attributes.get(k)
                for k in ("aria-label", "aria-labelledby", "role")
            )
        )
        out["aria"] = {
            "interactive_count": len(interactive),
            "with_aria_count": with_aria,
        }
    _safe("aria", _aria, out, errors)

    # (7) Schema.org actions
    def _sch() -> None:
        actions: set[str] = set()

        def walk(n: Any) -> None:
            if isinstance(n, dict):
                t = n.get("@type")
                if isinstance(t, str) and t in _ACTION_TYPE_ALLOWLIST:
                    actions.add(t)
                elif isinstance(t, list):
                    for x in t:
                        if isinstance(x, str) and x in _ACTION_TYPE_ALLOWLIST:
                            actions.add(x)
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)

        for s in p.css('script[type="application/ld+json"]'):
            block = s.text(deep=True) or ""
            if not block.strip():
                continue
            try:
                data = json.loads(block)
            except (json.JSONDecodeError, ValueError):
                continue
            walk(data)
        out["schema_actions"] = sorted(actions)
    _safe("schema_actions", _sch, out, errors)

    if errors:
        out["_error"] = ",".join(errors)
    return out
