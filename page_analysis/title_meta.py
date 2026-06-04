# -*- coding: utf-8 -*-
"""AAA-158 Sub-step 1 — deterministic ($0) title + meta-description SERP-snippet
measurement. Pure-Python, no LLM, no network, no new dependency.

Two parts (AAA-158 S0 design):
  Part 1 — pixel length + truncation (ALWAYS): per-character advance-width LUT
    for the SERP font (Arial/Helvetica-metric, the font Google's SERP renders
    in), scaled to the SERP font sizes (title ≈ 20px, description ≈ 14px). The
    measured string pixel-width is compared to the documented container limits
    (mirroring AAA-123's GOOGLE_2MB_BYTES constant pattern):
      TITLE_PX_LIMIT          = 600
      DESC_PX_LIMIT_DESKTOP   = 920
      DESC_PX_LIMIT_MOBILE    = 680
    Verdict: ok / borderline / truncated (per surface). Empty title/description
    text → a finding ("missing title" / "no meta description"), NOT an _error.
  Part 2 — quality signals (GATED; skip cleanly if the input is absent):
    - title↔H1 duplication (crawl.headings.h1; deterministic string compare)
    - brand position in title (prefer brand_context.og_site_name / a JSON-LD
      Organization name over the bare domain; skip if no real brand string)
    - keyword presence in title/description (target_keywords; skip if absent)

Whole `crawl.meta` absent (crawl failed → no parse) → AAA-123-style skip-finding:
{"_error": ..., "width_table_version": WIDTH_TABLE_VERSION}.

LUT accuracy: Arial advance widths are stored in 1000-units-per-em (the standard
core-font AFM metric); px = Σ(advance)/1000 × font_size_px. Diacritics are folded
to their base glyph (an accent does not change Arial advance width), so Hungarian
text (á/é/ő/ű…) measures accurately. Glyphs outside the table fall back to the
table's mean advance width. Validated against Pillow glyph rendering within a few
percent (AAA-158 S1 verify).
"""
from __future__ import annotations

import logging
import unicodedata

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Locked constants (documented; mirror AAA-123 GOOGLE_2MB_BYTES pattern)
# ---------------------------------------------------------------------------
WIDTH_TABLE_VERSION = "arial_serp_v1"

# SERP container pixel limits (Google desktop/mobile, 2026 layout).
TITLE_PX_LIMIT = 600          # desktop title truncation threshold
DESC_PX_LIMIT_DESKTOP = 920   # desktop meta-description snippet width
DESC_PX_LIMIT_MOBILE = 680    # mobile meta-description snippet width

# SERP render font sizes (px) for the Arial-metric advance-width scaling.
TITLE_FONT_PX = 20
DESC_FONT_PX = 14

# "borderline" band: at/above this fraction of the limit but not over it.
BORDERLINE_RATIO = 0.95

# Arial / Helvetica advance widths in 1000-units-per-em (core-font AFM metrics;
# Arial is metrically a Helvetica clone — within a few % for SERP estimation).
_ARIAL_WIDTHS_1000: dict[str, int] = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667,
    "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
    ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556,
    "7": 556, "8": 556, "9": 556,
    ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556, "@": 1015,
    "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722,
    "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722,
    "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611,
    "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556, "`": 333,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556,
    "h": 556, "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556,
    "o": 556, "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556,
    "v": 500, "w": 722, "x": 500, "y": 500, "z": 500,
    "{": 334, "|": 260, "}": 334, "~": 584,
}
# Mean advance — fallback for any glyph outside the table (e.g. CJK, symbols).
_AVG_WIDTH_1000 = round(sum(_ARIAL_WIDTHS_1000.values()) / len(_ARIAL_WIDTHS_1000))


def _char_width_1000(ch: str) -> int:
    """Advance width of one char in 1000-units-per-em. Diacritics fold to their
    base glyph (Arial advance is accent-independent); unknown glyphs → mean."""
    if ch in _ARIAL_WIDTHS_1000:
        return _ARIAL_WIDTHS_1000[ch]
    # Fold combining marks: 'á' (U+00E1) -> 'a' + combining acute -> base 'a'.
    base = "".join(
        c for c in unicodedata.normalize("NFD", ch)
        if not unicodedata.combining(c)
    )
    if base and base != ch:
        return sum(_char_width_1000(c) for c in base) if len(base) > 1 \
            else _ARIAL_WIDTHS_1000.get(base, _AVG_WIDTH_1000)
    return _AVG_WIDTH_1000


def text_pixel_width(text: str, font_px: int) -> float:
    """Pixel width of `text` rendered in the SERP Arial font at `font_px`."""
    if not text:
        return 0.0
    units = sum(_char_width_1000(ch) for ch in text)
    return round(units / 1000.0 * font_px, 1)


def _verdict(width_px: float, limit_px: int) -> str:
    if width_px > limit_px:
        return "truncated"
    if width_px >= limit_px * BORDERLINE_RATIO:
        return "borderline"
    return "ok"


# ---------------------------------------------------------------------------
# Part 2 helpers — quality signals (each gated; skip cleanly if input absent)
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _title_h1_duplication(title: str, h1_list) -> dict:
    h1s = [h for h in (h1_list or []) if isinstance(h, str) and h.strip()]
    if not title.strip() or not h1s:
        return {"available": False, "_skip": "no title or no H1"}
    h1 = h1s[0]
    nt, nh = _norm(title), _norm(h1)
    exact = nt == nh
    tw, hw = set(nt.split()), set(nh.split())
    jacc = round(len(tw & hw) / len(tw | hw), 3) if (tw | hw) else 0.0
    return {
        "available": True, "h1": h1[:300],
        "exact_duplicate": exact,
        "token_overlap": jacc,
        # "near" if not exact but heavily overlapping (informational)
        "near_duplicate": (not exact) and jacc >= 0.8,
    }


def _resolve_brand(ao: dict) -> str | None:
    """Prefer a real brand STRING (og:site_name / JSON-LD Organization name)
    over the bare registrable domain. Returns None if no real brand string."""
    cr = ao.get("crawl") or {}
    bc = cr.get("brand_context") or {}
    cand = bc.get("og_site_name")
    if isinstance(cand, str) and cand.strip():
        return cand.strip()
    for ent in (bc.get("json_ld_entities") or []):
        if not isinstance(ent, dict):
            continue
        t = ent.get("type")
        types = t if isinstance(t, list) else [t]
        if any(str(x) in ("Organization", "Corporation", "LocalBusiness") for x in types):
            nm = ent.get("name")
            if isinstance(nm, str) and nm.strip():
                return nm.strip()
    # site_profile.brand is typically the domain (e.g. "kk.coach") — only use
    # brand_name (a real display name) if present; never the bare domain.
    sp = ao.get("site_profile") or {}
    bn = sp.get("brand_name")
    if isinstance(bn, str) and bn.strip():
        return bn.strip()
    return None


def _brand_in_title(title: str, brand: str | None) -> dict:
    if not brand:
        return {"available": False, "_skip": "no real brand string"}
    if not title.strip():
        return {"available": False, "_skip": "no title"}
    nt, nb = _norm(title), _norm(brand)
    if nb not in nt:
        pos = "absent"
    elif nt.startswith(nb):
        pos = "start"
    elif nt.endswith(nb):
        pos = "end"
    else:
        pos = "middle"
    return {"available": True, "brand": brand[:120], "present": nb in nt,
            "position": pos}


def _keyword_presence(text: str, primary_kw: str | None) -> dict:
    if not primary_kw or not primary_kw.strip():
        return {"available": False, "_skip": "no target keyword"}
    if not text.strip():
        return {"available": True, "keyword": primary_kw[:120], "present": False}
    return {"available": True, "keyword": primary_kw[:120],
            "present": _norm(primary_kw) in _norm(text)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def measure_title_meta(audit_output: dict) -> dict:
    """Deterministic title + meta-description SERP measurement. $0, never raises.

    Reads: crawl.meta.{title,description}.text, crawl.headings.h1,
    crawl.brand_context, site_profile, target_keywords. Returns the
    `title_meta_measurements` dict. Whole crawl.meta absent → skip-finding.
    """
    try:
        ao = audit_output or {}
        cr = ao.get("crawl") or {}
        meta = cr.get("meta")
        if not isinstance(meta, dict) or not meta:
            return {"_error": "no crawl.meta available (crawl produced no HTML)",
                    "width_table_version": WIDTH_TABLE_VERSION}

        title_text = ((meta.get("title") or {}).get("text") or "").strip()
        desc_text = ((meta.get("description") or {}).get("text") or "").strip()

        # ----- Part 1: pixel length + truncation -----
        title_px = text_pixel_width(title_text, TITLE_FONT_PX)
        title_block = {
            "text": title_text,
            "present": bool(title_text),
            "char_count": len(title_text),
            "pixel_width": title_px,
            "limit_px": TITLE_PX_LIMIT,
            "font_px": TITLE_FONT_PX,
            "verdict": _verdict(title_px, TITLE_PX_LIMIT) if title_text else None,
        }
        if not title_text:
            title_block["finding"] = "missing title"

        desc_px = text_pixel_width(desc_text, DESC_FONT_PX)
        desc_block = {
            "text": desc_text,
            "present": bool(desc_text),
            "char_count": len(desc_text),
            "pixel_width": desc_px,
            "font_px": DESC_FONT_PX,
            "desktop": {
                "limit_px": DESC_PX_LIMIT_DESKTOP,
                "verdict": _verdict(desc_px, DESC_PX_LIMIT_DESKTOP) if desc_text else None,
            },
            "mobile": {
                "limit_px": DESC_PX_LIMIT_MOBILE,
                "verdict": _verdict(desc_px, DESC_PX_LIMIT_MOBILE) if desc_text else None,
            },
        }
        if not desc_text:
            desc_block["finding"] = "no meta description"

        # ----- Part 2: quality signals (gated) -----
        tk = ao.get("target_keywords") or {}
        primary_kw = tk.get("primary_keyword") if isinstance(tk, dict) else None
        quality = {
            "title_h1_duplication": _title_h1_duplication(
                title_text, (cr.get("headings") or {}).get("h1")),
            "brand_in_title": _brand_in_title(title_text, _resolve_brand(ao)),
            "keyword_in_title": _keyword_presence(title_text, primary_kw),
            "keyword_in_description": _keyword_presence(desc_text, primary_kw),
        }

        return {
            "width_table_version": WIDTH_TABLE_VERSION,
            "title": title_block,
            "description": desc_block,
            "quality_signals": quality,
            "_error": None,
        }
    except Exception as e:  # noqa: BLE001 — skip-finding; never fail the audit
        logger.warning("measure_title_meta failed: %s: %s", type(e).__name__, e)
        return {"_error": f"{type(e).__name__}: {e}",
                "width_table_version": WIDTH_TABLE_VERSION}
