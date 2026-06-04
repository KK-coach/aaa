# -*- coding: utf-8 -*-
"""AAA-143 Sub-step 1 — static (no-JS) HTML presentation layer over the AAA-96
content layer.

Input: audit_output + lang + the localized markdown doc (customer_summary_translations[lang]).
Output: a self-contained HTML page (embedded CSS, no external deps, no JS), 17
sections (§1..§11, §8.1..§8.6) + §12, exec-summary-leading, per-section deep-link
anchors.

Parser contract (locked with report/customer_render.assemble_document): each
section is delimited by a machine-generated level-2 header `## §<id> — <title>`
(em-dash separator). Section bodies use only ###/#### internally. split_sections
pre-splits on `(?m)^(?=## §)` and parses that header; a block that does not start
with the contract header raises (caller treats as a halt).

Structured enrichments (bars/chips/badges) are built from audit_output fields and
reuse the AAA-96 helpers (dim_label / resolve_anchor / anchor_name) — never
hardcoded keys, never a synthesized composite/0-100 score. Dimension bars show the
two raw measured values (client vs the resolved anchor) per dimension; categorical
dimensions (e.g. ai_visibility) render as chips, not bars.
"""

from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt
import nh3

from report.customer_render import (
    _dim, dim_label, resolve_anchor, anchor_name, _g, _reg,
)

# --- parser contract ---------------------------------------------------------
SECTION_HEADER_RE = re.compile(r"^## (§\S+) — (.+)$")

# --- sanitizer allowlist (markdown bodies only) ------------------------------
_ALLOWED_TAGS = {
    "h2", "h3", "h4", "p", "ul", "ol", "li", "table", "thead", "tbody", "tr",
    "th", "td", "strong", "em", "a", "code", "br", "details", "summary",
}
_ALLOWED_ATTR = {"a": {"href"}}

_MD = MarkdownIt("commonmark").enable("table")


def slug(section_id: str) -> str:
    """'§5' -> 's5', '§8.2' -> 's8-2' (URL-safe deep-link anchor)."""
    return "s" + section_id.lstrip("§").replace(".", "-")


def md_to_html(body_md: str) -> str:
    """Render a section body to sanitized HTML (raw HTML disabled; tight allowlist;
    force rel=noopener noreferrer on links)."""
    raw = _MD.render(body_md or "")
    return nh3.clean(
        raw, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTR,
        link_rel="noopener noreferrer",
    )


def split_sections(md: str):
    """Pre-split the assembled doc into ordered {id, title, body} blocks.
    Raises ValueError on a contract break (caller halts)."""
    blocks = re.split(r"(?m)^(?=## §)", md or "")
    out = []
    for b in blocks:
        b = b.strip("\n")
        if not b.strip():
            continue
        first, _, rest = b.partition("\n")
        m = SECTION_HEADER_RE.match(first.strip())
        if not m:
            raise ValueError(
                "PARSER-CONTRACT BREAK: block does not start with "
                "'## §<id> — <title>': %r" % (first[:80],))
        out.append({"id": m.group(1), "title": m.group(2), "body": rest.lstrip("\n")})
    return out


# --- localizable renderer-chrome stringtable (EN full; HU/DE/ES stubs) -------
STRINGS = {
    "en": {
        "report_title": "SEO / AI-Visibility Report",
        "lang_name": "English",
        "contents": "Contents",
        "comparison_vs": "Comparison vs {anchor}",
        "primary_benchmark": "Primary benchmark",
        "full_table": "Show full comparison table",
        "measures_note": "Factual measured values — client vs the primary benchmark, per dimension. Not a score.",
        "ai_overview": "Google AI Overview",
        "chatgpt": "ChatGPT",
        "cited_sources": "Cited sources",
        "client_cited": "Your site IS cited",
        "client_not_cited": "Your site is NOT cited",
        "no_citations": "No cited sources captured.",
        "client_label": "Your site",
        "indexed": "Indexed",
        "not_indexed": "Not indexed",
        "https": "HTTPS",
        "canonical": "Canonical",
        "crux": "Real-user experience (CrUX)",
        "priority": "Priority",
        "no_data": "No data available for this element.",
        # Sub-step 2 — JS-injected interactive chrome (localizable):
        "expand_all": "Expand all",
        "collapse_all": "Collapse all",
        "technical_structure": "Technical structure",
        "sort_hint": "Click a column heading to sort",
        "sorted_asc": "sorted ascending",
        "sorted_desc": "sorted descending",
        # Sub-step 3 — enum-ish chrome (localizable):
        "yes": "yes", "no": "no",
        "sev_high": "high", "sev_medium": "medium", "sev_low": "low",
        "crux_fast": "FAST", "crux_average": "AVERAGE", "crux_slow": "SLOW",
        # AAA-158 — SERP-snippet health (deterministic display):
        "snippet_health": "Search-snippet health",
        "snippet_note": "Measured pixel width vs Google's search-result limits — factual, not a score.",
        "tm_title": "Title",
        "tm_desc": "Meta description",
        "tm_desktop": "desktop",
        "tm_mobile": "mobile",
        "tm_chars": "{n} chars",
        "tm_px": "≈{px}px / {limit}px",
        "tm_ok": "fits",
        "tm_borderline": "near limit",
        "tm_truncated": "truncated",
        "tm_missing_title": "No title set",
        "tm_no_desc": "No meta description",
        "tm_dup_h1": "Title duplicates the H1",
        "tm_brand_missing": "Brand not in title",
        "tm_kw_missing": "Target keyword not in title",
    },
    # Sub-step 3 — HU now fully populated (DE/ES remain stubs → EN fallback).
    "hu": {
        "report_title": "SEO / AI-láthatósági jelentés",
        "lang_name": "Magyar",
        "contents": "Tartalom",
        "comparison_vs": "Összehasonlítás: {anchor}",
        "primary_benchmark": "Elsődleges viszonyítási pont",
        "full_table": "Teljes összehasonlító táblázat megjelenítése",
        "measures_note": "Tényszerű mért értékek — a saját oldal vs. az elsődleges viszonyítási pont, dimenziónként. Nem pontszám.",
        "ai_overview": "Google AI Overview",
        "chatgpt": "ChatGPT",
        "cited_sources": "Idézett források",
        "client_cited": "Az Ön oldala IDÉZVE van",
        "client_not_cited": "Az Ön oldala NINCS idézve",
        "no_citations": "Nem rögzült idézett forrás.",
        "client_label": "Az Ön oldala",
        "indexed": "Indexelve",
        "not_indexed": "Nincs indexelve",
        "https": "HTTPS",
        "canonical": "Kanonikus",
        "crux": "Valós felhasználói élmény (CrUX)",
        "priority": "Prioritás",
        "no_data": "Ehhez az elemhez nincs adat.",
        "expand_all": "Összes kinyitása",
        "collapse_all": "Összes összecsukása",
        "technical_structure": "Technikai felépítés",
        "sort_hint": "Kattintson egy oszlopfejlécre a rendezéshez",
        "sorted_asc": "növekvő sorrendbe rendezve",
        "sorted_desc": "csökkenő sorrendbe rendezve",
        "yes": "igen", "no": "nem",
        "sev_high": "magas", "sev_medium": "közepes", "sev_low": "alacsony",
        "crux_fast": "gyors", "crux_average": "közepes", "crux_slow": "lassú",
        # AAA-158 — SERP-snippet health (deterministic display):
        "snippet_health": "Találati kódrészlet állapota",
        "snippet_note": "Mért képpont-szélesség a Google találati limitjeihez mérve — tényszerű, nem pontszám.",
        "tm_title": "Cím",
        "tm_desc": "Meta leírás",
        "tm_desktop": "asztali",
        "tm_mobile": "mobil",
        "tm_chars": "{n} karakter",
        "tm_px": "≈{px}px / {limit}px",
        "tm_ok": "befér",
        "tm_borderline": "limit közelében",
        "tm_truncated": "levágva",
        "tm_missing_title": "Nincs beállított cím",
        "tm_no_desc": "Nincs meta leírás",
        "tm_dup_h1": "A cím megegyezik a H1-gyel",
        "tm_brand_missing": "A márkanév nincs a címben",
        "tm_kw_missing": "A kulcsszó nincs a címben",
    },
    "de": {"lang_name": "Deutsch"},
    "es": {"lang_name": "Español"},
}

# §8.x render as a collapsible accordion (native <details open> → JS-off readable).
ACCORDION_IDS = {"§8.1", "§8.2", "§8.3", "§8.4", "§8.5", "§8.6"}

# Localized section-heading titles (display only). The parser still reads the
# EN `## §<id> — <title>` contract header; for non-EN we DISPLAY the localized
# title (EN fallback for any id not mapped) so headings aren't stray EN on a HU page.
SECTION_TITLES = {
    "hu": {
        "§1": "Nyitó / fő diagnózis", "§2": "Azonosítás és kontextus",
        "§3": "Kulcsszavak és keresési szándék", "§4": "Versenytársak",
        "§5": "Összehasonlítás a legjobbakkal", "§6": "AI-láthatóság",
        "§7": "Tartalomminőség", "§8.1": "Zónák / makrostruktúra",
        "§8.2": "Címsor-hierarchia", "§8.3": "Mikroszemantika + HTML5",
        "§8.4": "Beágyazott + link-szemantika", "§8.5": "Űrlapok",
        "§8.6": "Séma (strukturált adatok)",
        "§9": "Hajtás feletti terület + konverziós pontok",
        "§10": "Technikai állapot", "§11": "Záró prioritási összefoglaló",
        "§12": "Módszertan",
    },
}


def S(lang, key, **fmt):
    s = STRINGS.get(lang, {}).get(key) or STRINGS["en"][key]
    return s.format(**fmt) if fmt else s


def _esc(x):
    return html.escape("" if x is None else str(x))


def _first_number(s):
    """Extract the first numeric token (commas/decimals/%) -> float, or None."""
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


# --- structured component builders (trusted templates; data is escaped) ------

def _comparison_block(ao, lang):
    """§5 — per-dimension client-vs-anchor bars (numeric) / chips (categorical)."""
    dt = _dim(ao)
    if not dt:
        return ""
    anchor = anchor_name(ao) or "the benchmark"
    rows = []
    for key in dt.keys():
        v = dt.get(key) or {}
        client_raw, comp_raw = v.get("client"), v.get("competitor_best")
        if client_raw is None and comp_raw is None:
            continue
        label = _esc(dim_label(key, lang))
        cn, an = _first_number(client_raw), _first_number(comp_raw)
        if cn is not None and an is not None:
            mx = max(cn, an, 1)
            cw, aw = max(2, round(cn / mx * 100)), max(2, round(an / mx * 100))
            rows.append(
                '<div class="dim"><div class="dim-label">%s</div>'
                '<div class="bar-row"><span class="who">%s</span>'
                '<span class="bar client" style="width:%d%%"></span>'
                '<span class="val">%s</span></div>'
                '<div class="bar-row"><span class="who">%s</span>'
                '<span class="bar anchor" style="width:%d%%"></span>'
                '<span class="val">%s</span></div></div>' % (
                    label, _esc(S(lang, "client_label")), cw, _esc(client_raw),
                    _esc(anchor), aw, _esc(comp_raw)))
        else:
            # categorical / prose measure -> factual chip comparison (no bar)
            rows.append(
                '<div class="dim"><div class="dim-label">%s</div>'
                '<div class="chip-row"><span class="chip you">%s: %s</span>'
                '<span class="chip them">%s: %s</span></div></div>' % (
                    label, _esc(S(lang, "client_label")), _esc(client_raw),
                    _esc(anchor), _esc(comp_raw)))
    if not rows:
        return ""
    return ('<div class="comparison"><h3>%s</h3><p class="note">%s</p>%s</div>' % (
        _esc(S(lang, "comparison_vs", anchor=anchor)), _esc(S(lang, "measures_note")),
        "".join(rows)))


def _citation_chips(ao, lang):
    """§6 — AI Overview + ChatGPT cited sources with cited-state."""
    aio = ao.get("ai_overview") or {}
    cg = ao.get("chatgpt_query_response") or {}
    out = []
    for title_key, srcs, cited, cited_field in [
        (S(lang, "ai_overview"), aio.get("cited_sources") or [], aio.get("client_cited"), "client_cited"),
        (S(lang, "chatgpt"), cg.get("citations") or [], cg.get("target_site_cited"), "target_site_cited"),
    ]:
        state = ""
        if cited is True:
            state = '<span class="state yes">%s</span>' % _esc(S(lang, "client_cited"))
        elif cited is False:
            state = '<span class="state no">%s</span>' % _esc(S(lang, "client_not_cited"))
        chips = []
        for c in srcs:
            if not isinstance(c, dict):
                continue
            url = c.get("url") or c.get("link")
            t = c.get("title") or _reg(url) or url
            if not url:
                continue
            chips.append('<a class="cite" href="%s" rel="noopener noreferrer">%s</a>' % (
                _esc(url), _esc(t)))
        body = ("".join(chips) if chips else
                '<span class="muted">%s</span>' % _esc(S(lang, "no_citations")))
        out.append('<div class="cite-group"><h4>%s %s</h4><div class="chips">%s</div></div>' % (
            _esc(title_key), state, body))
    return '<div class="citations">%s</div>' % "".join(out) if out else ""


def _tech_badges(ao, lang):
    """§10 — indexed / HTTPS / canonical / CrUX status badges."""
    idx = ao.get("indexing") or {}
    tech = _g(ao, "crawl", "technical") or {}
    crux = _g(ao, "crux_field_data", "origin_level", "metrics") or {}
    try:
        from report.customer_render import corrected_canonical
        canon = corrected_canonical(ao)
    except Exception:  # noqa: BLE001
        canon = None
    badges = []
    indexed = idx.get("indexed")
    if indexed is not None:
        cls = "ok" if indexed is True else "warn"
        lbl = S(lang, "indexed") if indexed is True else S(lang, "not_indexed")
        badges.append('<span class="badge %s">%s</span>' % (cls, _esc(lbl)))
    if tech.get("https") is not None:
        cls = "ok" if tech.get("https") else "warn"
        val = S(lang, "yes") if tech.get("https") else S(lang, "no")
        badges.append('<span class="badge %s">%s: %s</span>' % (
            cls, _esc(S(lang, "https")), _esc(val)))
    if canon:
        badges.append('<span class="badge ok">%s: %s</span>' % (
            _esc(S(lang, "canonical")), _esc(canon)))
    _CRUX_KEY = {"FAST": "crux_fast", "AVERAGE": "crux_average", "SLOW": "crux_slow"}
    cru = []
    for m in ("lcp", "cls", "inp"):
        cat = (crux.get(m) or {}).get("category")
        if cat:
            up = str(cat).upper()
            cls = "ok" if up == "FAST" else ("warn" if up == "AVERAGE" else "bad")
            disp = S(lang, _CRUX_KEY[up]) if up in _CRUX_KEY else cat
            cru.append('<span class="badge %s">%s: %s</span>' % (cls, m.upper(), _esc(disp)))
    if cru:
        badges.append('<span class="crux-label">%s</span>%s' % (_esc(S(lang, "crux")), "".join(cru)))
    return '<div class="badges">%s</div>' % "".join(badges) if badges else ""


def _priority_tags(ao, lang):
    """§11 — severity tags from comparison.patterns. Severity word is localized
    chrome; the EN finding text is data (kept only on the EN page — on non-EN pages
    the localized §11 prose carries the findings, so we show a clean localized
    severity distribution instead of injecting EN finding text)."""
    pats = (_g(ao, "re_findings", "comparison", "patterns") or [])
    if not pats:
        return ""
    _SEV = {"high": ("bad", "sev_high"), "medium": ("warn", "sev_medium"), "low": ("ok", "sev_low")}
    if lang == "en":
        items = []
        for p in pats:
            sev = (p.get("severity") or "").lower()
            cls, key = _SEV.get(sev, ("muted", None))
            label = S(lang, key) if key else (sev or "—")
            items.append('<li><span class="badge %s">%s</span> %s</li>' % (
                cls, _esc(label), _esc(p.get("finding"))))
        return '<ul class="priority">%s</ul>' % "".join(items)
    # non-EN: localized severity badges only (findings are in the localized prose)
    chips = []
    for p in pats:
        sev = (p.get("severity") or "").lower()
        cls, key = _SEV.get(sev, ("muted", None))
        label = S(lang, key) if key else (sev or "—")
        chips.append('<span class="badge %s">%s</span>' % (cls, _esc(label)))
    return '<div class="badges">%s</div>' % "".join(chips)


def _title_meta_block(ao, lang):
    """§9 — deterministic SERP-snippet health: title + meta-description pixel
    width vs Google's limits (exact figures from title_meta_measurements; NEVER
    recomputed by the LLM) + the gated quality-signal flags. AAA-158."""
    tm = ao.get("title_meta_measurements") or {}
    if not tm or tm.get("_error"):
        return ""
    _VCLS = {"ok": "ok", "borderline": "warn", "truncated": "bad"}
    _VKEY = {"ok": "tm_ok", "borderline": "tm_borderline", "truncated": "tm_truncated"}

    def _badge(cls, label):
        return '<span class="badge %s">%s</span>' % (cls, _esc(label))

    rows = []
    # --- Title row ---
    t = tm.get("title") or {}
    if t.get("present") and t.get("verdict"):
        v = t["verdict"]
        meta_txt = "%s · %s" % (
            S(lang, "tm_chars", n=t.get("char_count")),
            S(lang, "tm_px", px=t.get("pixel_width"), limit=t.get("limit_px")))
        rows.append(
            '<div class="dim"><div class="dim-label">%s</div>'
            '<div class="badges">%s <span class="muted">%s</span></div></div>' % (
                _esc(S(lang, "tm_title")),
                _badge(_VCLS.get(v, "muted"), S(lang, _VKEY.get(v, "tm_ok"))),
                _esc(meta_txt)))
    elif t.get("finding"):
        rows.append('<div class="dim"><div class="dim-label">%s</div>'
                    '<div class="badges">%s</div></div>' % (
                        _esc(S(lang, "tm_title")),
                        _badge("bad", S(lang, "tm_missing_title"))))
    # --- Description row (desktop + mobile) ---
    d = tm.get("description") or {}
    if d.get("present"):
        dv = (d.get("desktop") or {}).get("verdict")
        mv = (d.get("mobile") or {}).get("verdict")
        b = []
        if dv:
            b.append("%s&nbsp;%s" % (_esc(S(lang, "tm_desktop")),
                                     _badge(_VCLS.get(dv, "muted"), S(lang, _VKEY.get(dv, "tm_ok")))))
        if mv:
            b.append("%s&nbsp;%s" % (_esc(S(lang, "tm_mobile")),
                                     _badge(_VCLS.get(mv, "muted"), S(lang, _VKEY.get(mv, "tm_ok")))))
        meta_txt = "%s · %s" % (
            S(lang, "tm_chars", n=d.get("char_count")),
            S(lang, "tm_px", px=d.get("pixel_width"), limit=(d.get("desktop") or {}).get("limit_px")))
        rows.append(
            '<div class="dim"><div class="dim-label">%s</div>'
            '<div class="badges">%s <span class="muted">%s</span></div></div>' % (
                _esc(S(lang, "tm_desc")), " ".join(b), _esc(meta_txt)))
    elif d.get("finding"):
        rows.append('<div class="dim"><div class="dim-label">%s</div>'
                    '<div class="badges">%s</div></div>' % (
                        _esc(S(lang, "tm_desc")),
                        _badge("warn", S(lang, "tm_no_desc"))))
    # --- Quality-signal flags (only surface the negatives worth showing) ---
    q = tm.get("quality_signals") or {}
    flags = []
    dup = q.get("title_h1_duplication") or {}
    if dup.get("available") and dup.get("exact_duplicate"):
        flags.append(_badge("warn", S(lang, "tm_dup_h1")))
    bri = q.get("brand_in_title") or {}
    if bri.get("available") and bri.get("present") is False:
        flags.append(_badge("warn", S(lang, "tm_brand_missing")))
    kt = q.get("keyword_in_title") or {}
    if kt.get("available") and kt.get("present") is False:
        flags.append(_badge("warn", S(lang, "tm_kw_missing")))
    if flags:
        rows.append('<div class="badges">%s</div>' % " ".join(flags))

    if not rows:
        return ""
    return ('<div class="comparison"><h3>%s</h3><p class="note">%s</p>%s</div>' % (
        _esc(S(lang, "snippet_health")), _esc(S(lang, "snippet_note")), "".join(rows)))


def _anchor_chip(ao, lang):
    a = anchor_name(ao)
    if not a:
        return ""
    return '<p class="anchor-chip"><strong>%s:</strong> %s</p>' % (
        _esc(S(lang, "primary_benchmark")), _esc(a))


# --- CSS (embedded, no external deps) ----------------------------------------
_CSS = """
:root{--ink:#1a2230;--muted:#5b6677;--line:#e3e8ef;--bg:#f7f9fc;--card:#fff;
--ok:#127a3d;--okbg:#e6f4ec;--warn:#9a6700;--warnbg:#fff4d6;--bad:#b3261e;--badbg:#fde8e6;
--client:#2563eb;--anchor:#7c8595;--accent:#2563eb}
*{box-sizing:border-box}body{margin:0;font:16px/1.6 -apple-system,Segoe UI,Roboto,Arial,sans-serif;
color:var(--ink);background:var(--bg)}
.wrap{max-width:880px;margin:0 auto;padding:32px 20px 80px}
header.rpt{border-bottom:2px solid var(--line);margin-bottom:8px}
header.rpt h1{font-size:26px;margin:0 0 4px}header.rpt .sub{color:var(--muted);margin:0 0 8px}
.langs{margin:0 0 14px}.langs a.lang{font-size:13px;color:var(--accent);text-decoration:none;border:1px solid var(--line);border-radius:8px;padding:3px 10px;margin-right:6px}
.langs a.lang:hover{background:#eef4ff}
nav.toc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin:18px 0}
nav.toc strong{display:block;color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px}
nav.toc a{display:inline-block;margin:2px 12px 2px 0;color:var(--accent);text-decoration:none;font-size:14px}
nav.toc a:hover{text-decoration:underline}
section.sec{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin:16px 0}
section.hero{background:linear-gradient(180deg,#eef4ff,#fff);border-color:#cfe0ff}
section.sec>h2{font-size:20px;margin:0 0 10px;scroll-margin-top:16px}
.sec h3{font-size:16px;margin:18px 0 6px}.sec h4{font-size:14px;margin:14px 0 4px;color:var(--muted)}
.sec p{margin:8px 0}.sec ul,.sec ol{margin:8px 0 8px 22px}.sec li{margin:3px 0}
.sec code{background:#eef1f6;padding:1px 5px;border-radius:4px;font-size:13px}
.sec a{color:var(--accent)}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:#f1f5fb}
details{margin:10px 0}summary{cursor:pointer;color:var(--accent);font-size:14px}
.comparison{margin:6px 0 4px}.comparison h3{margin-top:4px}.note{color:var(--muted);font-size:13px;margin:0 0 12px}
.dim{margin:10px 0}.dim-label{font-weight:600;font-size:14px;margin-bottom:3px}
.bar-row{display:flex;align-items:center;gap:8px;margin:2px 0}
.who{flex:0 0 84px;font-size:12px;color:var(--muted)}
.bar{height:14px;border-radius:7px;min-width:4px}
.bar.client{background:var(--client)}.bar.anchor{background:var(--anchor)}
.val{font-size:13px;color:var(--ink)}
.chip-row{display:flex;gap:8px;flex-wrap:wrap}
.chip{font-size:13px;border-radius:14px;padding:2px 10px;border:1px solid var(--line)}
.chip.you{background:#eef4ff;border-color:#cfe0ff}.chip.them{background:#f4f6f9}
.anchor-chip{background:#eef4ff;border:1px solid #cfe0ff;border-radius:8px;padding:6px 12px;display:inline-block;font-size:14px}
.citations{margin:6px 0}.cite-group{margin:10px 0}.cite-group h4{color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
a.cite{font-size:13px;background:#f4f6f9;border:1px solid var(--line);border-radius:14px;padding:3px 10px;text-decoration:none}
.state{font-size:12px;border-radius:12px;padding:2px 9px;margin-left:8px}
.state.yes{background:var(--okbg);color:var(--ok)}.state.no{background:var(--badbg);color:var(--bad)}
.badges{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0}
.badge{font-size:12px;border-radius:12px;padding:2px 9px;font-weight:600}
.badge.ok{background:var(--okbg);color:var(--ok)}.badge.warn{background:var(--warnbg);color:var(--warn)}
.badge.bad{background:var(--badbg);color:var(--bad)}.badge.muted{background:#eef1f6;color:var(--muted)}
.crux-label{font-size:12px;color:var(--muted);margin-right:4px}
ul.priority{list-style:none;margin:8px 0;padding:0}ul.priority li{margin:6px 0}
.muted{color:var(--muted)}
footer.rpt{color:var(--muted);font-size:12px;margin-top:24px;text-align:center}
/* Sub-step 2 — sticky nav (CSS-only; JS adds active-highlight) */
nav.toc{position:sticky;top:0;z-index:5;box-shadow:0 1px 0 var(--line)}
nav.toc a.active{font-weight:700;text-decoration:underline}
/* accordion (§8.x) — native <details>; JS-off => open via [open] */
section.accordion{padding:0}
section.accordion>details>summary{list-style:none;cursor:pointer;padding:16px 24px;font-size:20px;font-weight:600;
display:flex;align-items:center;gap:8px}
section.accordion>details>summary::-webkit-details-marker{display:none}
section.accordion>details>summary::before{content:"\\25B8";color:var(--muted);font-size:14px;transition:transform .15s}
section.accordion>details[open]>summary::before{transform:rotate(90deg)}
section.accordion>details>.acc-body{padding:0 24px 18px}
.acc-toolbar{display:flex;gap:8px;margin:16px 0 4px}
.acc-toolbar button{font:inherit;font-size:13px;cursor:pointer;border:1px solid var(--line);background:var(--card);
color:var(--accent);border-radius:8px;padding:5px 12px}
.acc-toolbar button:hover{background:#eef4ff}
/* sortable table (JS adds role/aria-sort + this affordance) */
th[aria-sort]{cursor:pointer;user-select:none}
th[aria-sort]:hover{background:#e7eefb}
th[aria-sort]::after{content:"\\2195";color:var(--muted);font-size:11px;margin-left:4px}
th[aria-sort="ascending"]::after{content:"\\2191";color:var(--accent)}
th[aria-sort="descending"]::after{content:"\\2193";color:var(--accent)}
""".strip()


# --- inline progressive-enhancement JS (no external deps) --------------------
# Graceful degrade: JS-off leaves accordions open (<details open>), the nav as
# sticky anchor links, and tables in content order. JS only ADDS expand/collapse-all,
# scroll-spy active highlight, and column sorting. All UI strings come from
# window.__RPT_I18N (the EN stringtable; HU/DE/ES later). Defensive throughout —
# absent sections/tables/citations simply mean a loop runs zero times (no crash).
_JS = r"""
(function(){
  var I=(window.__RPT_I18N)||{};
  function t(k){return (I[k]!=null)?I[k]:k;}  // i18n always carries these keys; fall back to the key (never an EN phrase)
  // A) accordion: aria-expanded sync + expand/collapse-all toolbar
  var accs=[].slice.call(document.querySelectorAll('section.accordion>details'));
  accs.forEach(function(d){
    var s=d.querySelector('summary'); if(!s)return;
    s.setAttribute('aria-expanded', d.open?'true':'false');
    d.addEventListener('toggle',function(){s.setAttribute('aria-expanded', d.open?'true':'false');});
  });
  if(accs.length){
    var first=accs[0].closest('section.accordion');
    var bar=document.createElement('div'); bar.className='acc-toolbar';
    function mk(label,open){var b=document.createElement('button');b.type='button';b.textContent=label;
      b.addEventListener('click',function(){accs.forEach(function(d){d.open=open;});});return b;}
    bar.appendChild(mk(t('expand_all'),true));
    bar.appendChild(mk(t('collapse_all'),false));
    if(first&&first.parentNode){first.parentNode.insertBefore(bar,first);}
  }
  // B) sticky-nav scroll-spy active highlight (IntersectionObserver; graceful skip)
  var links={}; [].slice.call(document.querySelectorAll('nav.toc a')).forEach(function(a){
    links[a.getAttribute('href')]=a;});
  if('IntersectionObserver' in window){
    var obs=new IntersectionObserver(function(es){
      es.forEach(function(e){ if(e.isIntersecting){
        var l=links['#'+e.target.id]; if(!l)return;
        Object.keys(links).forEach(function(k){links[k].classList.remove('active');});
        l.classList.add('active');
      }});
    },{rootMargin:'-10% 0px -80% 0px'});
    [].slice.call(document.querySelectorAll('main section[id]')).forEach(function(sec){obs.observe(sec);});
  }
  // C) sortable tables (numeric-aware; default content order preserved JS-off)
  function num(s){var m=(s||'').replace(/,/g,'').match(/-?\d+(\.\d+)?/);return m?parseFloat(m[0]):null;}
  [].slice.call(document.querySelectorAll('table')).forEach(function(tb){
    var head=tb.querySelector('thead tr'); var body=tb.querySelector('tbody'); if(!head||!body)return;
    var ths=[].slice.call(head.children);
    ths.forEach(function(th,ci){
      th.setAttribute('role','button'); th.setAttribute('tabindex','0'); th.setAttribute('aria-sort','none');
      th.title=t('sort_hint');
      function sort(){
        var dir=th.getAttribute('aria-sort')==='ascending'?'descending':'ascending';
        ths.forEach(function(o){o.setAttribute('aria-sort','none');});
        th.setAttribute('aria-sort',dir);
        var rows=[].slice.call(body.querySelectorAll('tr'));
        rows.sort(function(a,b){
          var x=(a.children[ci]||{}).textContent||'', y=(b.children[ci]||{}).textContent||'';
          var nx=num(x), ny=num(y), c;
          if(nx!==null&&ny!==null){c=nx-ny;} else {c=x.localeCompare(y);}
          return dir==='ascending'?c:-c;
        });
        rows.forEach(function(r){body.appendChild(r);});
      }
      th.addEventListener('click',sort);
      th.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();sort();}});
    });
  });
})();
""".strip()


def _i18n_js(lang):
    """Resolve the JS-used chrome strings (lang fallback to EN) for embedding."""
    import json as _json
    keys = ("expand_all", "collapse_all", "sort_hint", "sorted_asc", "sorted_desc")
    return _json.dumps({k: S(lang, k) for k in keys}, ensure_ascii=False)


# Per-section enrichment dispatch (structured component above the prose body).
_ENRICH = {
    "§4": _anchor_chip,
    "§5": _comparison_block,
    "§6": _citation_chips,
    "§9": _title_meta_block,  # AAA-158 — SERP-snippet health
    "§10": _tech_badges,
    "§11": _priority_tags,
}


def render_html_report(audit_output, lang, markdown_doc, available_langs=None):
    """Render the localized markdown doc + structured enrichments to a self-contained
    HTML page. Returns (html_str, meta). Raises on parser-contract break.

    available_langs: optional iterable of langs that have a rendered artifact; a
    plain <a href="?lang=X"> toggle is emitted in the header for each OTHER lang
    present (works JS-off; the ?lang routing is AAA-97, out of scope). No toggle if
    no other lang exists (e.g. EN-only audits)."""
    sections = split_sections(markdown_doc)
    brand = _g(audit_output, "site_profile", "brand") or ""
    url = audit_output.get("url") or (audit_output.get("crawl") or {}).get("url") or ""

    # AAA-153 S1: ToC label = "§id — <localized title>" (mirrors the heading at
    # line ~538). Graceful fallback to the bare §-id if no title is available.
    def _toc_label(s):
        title = SECTION_TITLES.get(lang, {}).get(s["id"]) or s["title"]
        return ("%s — %s" % (s["id"], title)) if title else s["id"]
    toc = "".join(
        '<a href="#%s">%s</a>' % (slug(s["id"]), _esc(_toc_label(s))) for s in sections)
    body_parts = []
    for s in sections:
        sid = s["id"]
        hero = " hero" if sid == "§1" else ""
        enrich_fn = _ENRICH.get(sid)
        enrich = ""
        if enrich_fn:
            try:
                enrich = enrich_fn(audit_output, lang) or ""
            except Exception:  # noqa: BLE001 — no-data/skip-finding: never crash a section
                enrich = ""
        prose = md_to_html(s["body"])
        if sid == "§5" and enrich:
            # comparison bars primary; full GFM table prose as expandable fallback
            prose = "<details><summary>%s</summary>%s</details>" % (
                _esc(S(lang, "full_table")), prose)
        disp_title = SECTION_TITLES.get(lang, {}).get(sid) or s["title"]
        head = "%s — %s" % (_esc(sid), _esc(disp_title))
        if sid in ACCORDION_IDS:
            # native <details open> => fully readable with JS off; JS adds
            # expand/collapse-all + aria-expanded sync.
            body_parts.append(
                '<section id="%s" class="sec accordion"><details open>'
                '<summary>%s</summary><div class="acc-body">%s%s</div>'
                '</details></section>' % (slug(sid), head, enrich, prose))
        else:
            body_parts.append(
                '<section id="%s" class="sec%s"><h2>%s</h2>%s%s</section>' % (
                    slug(sid), hero, head, enrich, prose))

    others = [l for l in (available_langs or []) if l != lang]
    toggle = ""
    if others:
        toggle = '<div class="langs">%s</div>' % "".join(
            '<a class="lang" href="?lang=%s">%s</a>' % (_esc(l), _esc(S(l, "lang_name")))
            for l in others)

    title = "%s — %s" % (S(lang, "report_title"), brand) if brand else S(lang, "report_title")
    page = (
        "<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s</title><style>%s</style></head><body><div class=\"wrap\">"
        "<header class=\"rpt\"><h1>%s</h1><p class=\"sub\">%s</p>%s</header>"
        "<nav class=\"toc\"><strong>%s</strong>%s</nav>"
        "<main>%s</main>"
        "<footer class=\"rpt\">%s</footer>"
        "</div><script>window.__RPT_I18N=%s;</script><script>%s</script>"
        "</body></html>" % (
            _esc(lang), _esc(title), _CSS, _esc(title), _esc(url or brand), toggle,
            _esc(S(lang, "contents")), toc, "".join(body_parts),
            _esc(S(lang, "report_title")), _i18n_js(lang), _JS))
    return page, {"sections": len(sections), "lang": lang, "toggle_to": others,
                  "anchor": anchor_name(audit_output), "bytes": len(page.encode("utf-8"))}
