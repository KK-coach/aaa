"""AAA-173 — deterministic placeholder / content-QA-leak detector.

$0, httpx-only, NO LLM. Scans already-extracted text (crawl.main_content.text +
crawl.content.visible_text + heading_tree) for high-precision unfinished-content
markers: literal Lorem-ipsum, keyboard-mash placeholders, and dev/template leaks
(form-state strings, Webflow "div block" placeholder text). Validated in S0:
0 false positives across 5 finished pages; every hit on the one broken page
(taxually) was a genuine leak.

Marker tiers (S0 verdict):
  HARD  — high-precision unfinished-content strings. ANY hard hit raises the
          page-level "unfinished/placeholder content" flag.
  NAME  — canonical placeholder names (John/Jane Doe, John Smith, Test User).
          Feed the PAGE FLAG, but are reported separately (a real person could
          bear such a name) — never a hard standalone assertion on their own.
  SOFT  — corroborating-only (\bplaceholder\b literal, example.com, test@,
          555-phone). Annotated, but NEVER raise the page flag alone (they have
          legitimate uses: UI term, RFC-reserved demo domain, docs).

Category B (placeholder ALT-TEXT) is DEFERRED: per-image alt strings are not
persisted (crawl.images stores only counts), so alt-text evaluation is marked
"not_evaluated" — never fabricated.

Deterministic: same input -> byte-identical output (drift must be 0%).
Schema-additive forward-only; written to audit_output.content_qa_leak.
Skip-finding: any failure -> {"_error": ...}; the audit continues.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Marker tiers (regex, label, category) — case-insensitive
# --------------------------------------------------------------------------
HARD_MARKERS = [
    (r"lorem\s+ipsum", "lorem ipsum", "lorem_ipsum"),
    (r"dolor\s+sit\s+amet", "dolor sit amet", "lorem_ipsum"),
    (r"\basdf\b", "asdf", "keyboard_mash"),
    (r"\bfoo\s?bar\b", "foobar", "keyboard_mash"),
    (r"\berror\s+state\b", "error state", "form_template_leak"),
    (r"\bvalidated\s+state\b", "validated state", "form_template_leak"),
    (r"\bfield\s+focused\s+state\b", "field focused state", "form_template_leak"),
    (r"this is some text inside of a div block", "div block placeholder", "form_template_leak"),
    (r"\bform\s+styling\b", "form styling", "form_template_leak"),
]

# Canonical placeholder names -> feed the page flag, reported separately.
NAME_MARKERS = [
    (r"\bjohn\s+doe\b", "john doe", "placeholder_name"),
    (r"\bjane\s+doe\b", "jane doe", "placeholder_name"),
    (r"\bjohn\s+smith\b", "john smith", "placeholder_name"),
    (r"\btest\s+user\b", "test user", "placeholder_name"),
]

# Corroborating-only -> NEVER raise the page flag alone.
SOFT_MARKERS = [
    (r"\bplaceholder\b", "'placeholder' literal", "soft_placeholder_term"),
    (r"\bexample\.com\b", "example.com", "soft_demo_contact"),
    (r"\btest@", "test@", "soft_demo_contact"),
    (r"\+?1[\s\-]?\(?555\)?[\s\-]?\d{3,4}\b", "555-phone", "soft_demo_contact"),
]

_SNIPPET_PAD = 40


def _gather_text(audit_output: dict) -> str:
    cr = audit_output.get("crawl") or {}
    mc = (cr.get("main_content") or {}).get("text") or ""
    vt = (cr.get("content") or {}).get("visible_text") or ""
    ss = (audit_output.get("phase2_html_measurements") or {}).get("semantic_structure") or {}
    heads = " ".join(
        (h.get("text") or "") for h in (ss.get("heading_tree") or [])
        if isinstance(h, dict)
    )
    return "\n".join([mc, vt, heads])


def _scan(text: str, markers: list) -> list:
    """Return a hit dict per marker that fires (count + first-occurrence snippet).
    Deterministic: markers in fixed order, regex case-insensitive."""
    hits = []
    for pat, label, category in markers:
        found = list(re.finditer(pat, text, re.I))
        if not found:
            continue
        m = found[0]
        s = max(0, m.start() - _SNIPPET_PAD)
        snippet = text[s:m.end() + _SNIPPET_PAD].replace("\n", " ").strip()
        hits.append({
            "label": label,
            "category": category,
            "count": len(found),
            "snippet": snippet,
        })
    return hits


def detect_placeholder_leaks(audit_output: dict) -> dict:
    """AAA-173 deterministic placeholder/QA-leak detector.

    Returns a schema-additive dict:
      {
        "page_flag": bool,                 # >=1 HARD or NAME hit
        "hard_hits": [...],                # high-precision unfinished content
        "name_hits": [...],                # canonical placeholder names
        "soft_hits": [...],                # corroborating-only (never flags alone)
        "categories": {cat: total_count},  # rolled up across hard+name+soft
        "alt_text_eval": "not_evaluated",  # Category B deferred (no alt strings)
        "_meta": {"detector_version": ...}
      }
    Never raises; on failure returns {"_error": ...}.
    """
    try:
        text = _gather_text(audit_output)
        hard = _scan(text, HARD_MARKERS)
        names = _scan(text, NAME_MARKERS)
        soft = _scan(text, SOFT_MARKERS)

        # PAGE FLAG: any HARD or canonical-NAME hit. SOFT never raises alone.
        page_flag = bool(hard or names)

        categories: dict = {}
        for h in hard + names + soft:
            categories[h["category"]] = categories.get(h["category"], 0) + h["count"]

        return {
            "page_flag": page_flag,
            "page_flag_reason": (
                "unfinished/placeholder content detected (hard/name marker present)"
                if page_flag else "no hard placeholder marker"
            ),
            "hard_hits": hard,
            "name_hits": names,
            "soft_hits": soft,
            "categories": categories,
            "hard_hit_count": sum(h["count"] for h in hard),
            "name_hit_count": sum(h["count"] for h in names),
            "alt_text_eval": "not_evaluated",  # Category B deferred (alt strings not persisted)
            "_meta": {"detector_version": "aaa173_v1", "error": None},
        }
    except Exception as e:  # noqa: BLE001 — never fail the audit
        return {"_error": f"{type(e).__name__}: {e}",
                "_meta": {"detector_version": "aaa173_v1"}}
