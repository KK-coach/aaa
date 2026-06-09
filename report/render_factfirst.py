# -*- coding: utf-8 -*-
"""AAA-161 Gate 3 / 3.5 — NEW 8-section fact-first customer render (PARALLEL artifact).

Consumes the Gate 1+2 data layer (audit_output.fact_base = fact_base_v4 +
audit_output.decisions = decisions_v2) and emits a styled 8-section HTML report,
per language (hu / en). Gate 3.5: cream editorial skin lifted from
report/reference/mockup.html (CSS only; the mockup's HU text is ignored),
plus §3 citation wiring, audit-date wiring, §1 dashboard enrichment, and the
"not measured" / EN §8 labels.

DETERMINISTIC for all structure / numbers / tables / bars / chips / findings —
NO LLM. AI-értelmezés PROSE blocks REUSE already-stored interpretive data
(aaa124_aspect_evaluations, eeat_score verdict, re_findings.comparison) — ZERO
new LLM calls (render cost $0).

Parallel to the legacy render: written to reports/{audit_id}.{lang}.ff.html;
ref persisted at audit_output.customer_report_html_uri_ff. Legacy untouched.
No-fabricate: absent/not_measured → "—" / "not measured"; never invented.
Competitor names are fine (measured facts). The content-volume / word-count
finding is SUPPRESSED at render (product decision).
"""
from __future__ import annotations

import html as _html
import re as _re

# AAA-181 — §4.2 aspect dict-keys → customer-facing display labels (no raw keys).
_ASPECT_LABELS = {
    "macro_structure": {"hu": "Makró-struktúra", "en": "Macro structure"},
    "micro_semantics": {"hu": "Mikró-szemantika", "en": "Micro semantics"},
    "text_level_semantics": {"hu": "Szövegszintű szemantika", "en": "Text-level semantics"},
}

# AAA-181 — strip internal page-handle leaks (PAGE_1 = client, PAGE_2.. = competitors)
# from any customer-facing prose (E-E-A-T verdict, aspect findings, RE synthesis).
_PAGE_RE = _re.compile(r"\bPAGE[_\s-]?(\d+)\b", _re.I)


def _page_names(ao):
    """PAGE_N → display name: PAGE_1 = client brand / 'This page'; PAGE_2.. =
    the comparative competitors in order (brand / neutral)."""
    fb = ao.get("fact_base") or {}
    client = (fb.get("meta") or {}).get("brand") or (ao.get("site_profile") or {}).get("brand")
    names = {1: client or "This page"}
    comps = ((ao.get("eeat_score") or {}).get("competitors")) or []
    for i, c in enumerate(comps, start=2):
        names[i] = (c.get("brand") if isinstance(c, dict) else None) or "a competitor"
    return names


def _sanitize_labels(text, page_names):
    """Replace any leaked PAGE_N handle in customer prose with a display name."""
    if not text:
        return text
    return _PAGE_RE.sub(
        lambda m: str(page_names.get(int(m.group(1)), "This page")), text)

SECTION_IDS = ["§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8"]

# AAA-161 Gate 4: single source of truth for the render version (persisted ref
# reads THIS, so the label can't drift from the actual output again).
RENDER_VERSION = "factfirst_v2_skin"

# layer value (stored, HU) -> (mockup css class, {en,hu} chip label)
_LAYER_CHIP = {
    "mért": ("t-mert", {"en": "measured", "hu": "mért"}),
    "becslés": ("t-becs", {"en": "estimate", "hu": "becslés"}),
    "AI-értelmezés": ("t-ai", {"en": "AI interpretation", "hu": "AI-értelmezés"}),
    "következtetés": ("t-kov", {"en": "inference", "hu": "következtetés"}),
}

UI = {
    "hu": {
        "doc_title": "Láthatósági és tartalmi audit",
        "sub": "Egy weboldal teljesítményének visszafejtése a keresőben és az AI-keresésben — tényalapú riport.",
        "legend": "Réteg-jelölés:", "legend_note": "— minden adatpont mellett jelezzük, honnan jön.",
        "s1": "Összefoglaló státusz", "s2": "Keresési környezet", "s3": "AI-láthatóság",
        "s4": "Saját oldal", "s5": "E-E-A-T bizalmi olvasat", "s6": "Konkurens benchmark",
        "s7": "Javaslatok", "s8": "Adatminőség / provenance",
        "r1": "Mit nézel és hogy állsz — egy képernyőnyi összegzés, fentről.",
        "r2": "A színpad: melyik kulcsszó, milyen szándék, hogy néz ki a találati lista.",
        "r3": "Megjelensz-e az AI-válaszokban — pillanatkép az audit napján.",
        "r4": "A te oldalad mért állapota: tartalom, szemantika, gép-olvashatóság, technikai egészség.",
        "r5": "Mennyire tükröz az oldal tapasztalatot, szakértelmet, tekintélyt, megbízhatóságot — a mért on-page jelekből.",
        "r6": "Hogyan állsz a valódi versenytársakhoz képest — négy családban, nevesítve.",
        "r7": "Mit tegyél — hatás szerint rangsorolva.",
        "r8": "Honnan jön az adat és mikor rögzült.",
        "section": "szekció", "domain": "Domain", "keyword": "Kulcsszó", "market": "Piac",
        "date": "Audit dátuma", "nd": "nincs mérve",
        "snapshot": "Pillanatkép az audit napján", "cited": "Idézve", "not_cited": "Nincs idézve",
        "excluded": "Kihagyva", "competitor": "Versenytárs", "competitors_cited": "Idézett versenytársak",
        "ax_ai": "AI-láthatóság", "ax_page": "Saját oldal", "ax_tech": "Technikai egészség", "ax_eeat": "E-E-A-T",
        "st_weak": "Gyenge", "st_attn": "Odafigyelést igényel", "st_ok": "Rendben",
        "fam_content": "Tartalom", "fam_seo": "On-site SEO", "fam_tech": "Technikai SEO", "fam_eeat": "E-E-A-T",
        "rank": "Helyezés a mezőnyben", "client": "Ez az oldal", "total": "Összesen",
        "dim": "Dimenzió", "cwv_field": "Mező (CrUX p75)", "cwv_lab": "Labor (Lighthouse)",
        "t1": "Magas hatás", "t2": "Közepes hatás", "t3": "Alacsony hatás",
        "fresh_source": "Forrás", "fresh_when": "Mikor rögzült", "fresh_state": "Frissesség",
        "prov_summary": "Adat-provenance összegzés", "word_count": "Szószám", "page_weight": "Oldalsúly",
        "verdict": "Verdikt", "see_s6": "A dimenzió-szintű összevetést lásd a §6-ban.",
        "in_run": "audit-futás", "crux_window": "28 napos ablak",
        "fan_cov": "Fan-out lefedettség", "schema_jsonld": "Séma (JSON-LD)",
        "landmarks": "Landmarkok", "altcov": "Alt-lefedettség", "labelcov": "Űrlap-címke lefedettség",
        "headings": "Címsorok (H1 / összes / ugrás)", "indexed": "Indexelt", "perf": "Teljesítmény (mobil/asztali)",
        " contentqa": "Tartalom-QA jelzés",
    },
    "en": {
        "doc_title": "Visibility & content audit",
        "sub": "Reverse-engineering a site's performance in search and AI search — a fact-first report.",
        "legend": "Layer tags:", "legend_note": "— shown next to every data point so you know where it comes from.",
        "s1": "Status summary", "s2": "Search environment", "s3": "AI visibility",
        "s4": "Your page", "s5": "E-E-A-T trust read", "s6": "Competitor benchmark",
        "s7": "Recommendations", "s8": "Data quality / provenance",
        "r1": "What you're looking at and where you stand — a one-screen summary, top-down.",
        "r2": "The stage: which keyword, what intent, what the results page looks like.",
        "r3": "Whether you show up in AI answers — a snapshot as of the audit date.",
        "r4": "Your page's measured state: content, semantics, machine-readability, technical health.",
        "r5": "How much the page reflects experience, expertise, authority and trust — from measured on-page signals.",
        "r6": "How you stand against the real competitors — across four families, named.",
        "r7": "What to do — ranked by impact.",
        "r8": "Where the data comes from and when it was captured.",
        "section": "section", "domain": "Domain", "keyword": "Keyword", "market": "Market",
        "date": "Audit date", "nd": "not measured",
        "snapshot": "Snapshot as of the audit date", "cited": "Cited", "not_cited": "Not cited",
        "excluded": "Excluded", "competitor": "Competitor", "competitors_cited": "Competitors cited",
        "ax_ai": "AI visibility", "ax_page": "Your page", "ax_tech": "Technical health", "ax_eeat": "E-E-A-T",
        "st_weak": "Weak", "st_attn": "Needs attention", "st_ok": "OK",
        "fam_content": "Content", "fam_seo": "On-site SEO", "fam_tech": "Technical SEO", "fam_eeat": "E-E-A-T",
        "rank": "Rank in the field", "client": "This page", "total": "Total",
        "dim": "Dimension", "cwv_field": "Field (CrUX p75)", "cwv_lab": "Lab (Lighthouse)",
        "t1": "High impact", "t2": "Medium impact", "t3": "Low impact",
        "fresh_source": "Source", "fresh_when": "Captured", "fresh_state": "Freshness",
        "prov_summary": "Data-provenance summary", "word_count": "Word count", "page_weight": "Page weight",
        "verdict": "Verdict", "see_s6": "See §6 for the per-dimension comparison.",
        "in_run": "in-run", "crux_window": "28-day window",
        "fan_cov": "Fan-out coverage", "schema_jsonld": "Schema (JSON-LD)",
        "landmarks": "Landmarks", "altcov": "Alt coverage", "labelcov": "Form-label coverage",
        "headings": "Headings (H1 / total / skips)", "indexed": "Indexed", "perf": "Performance (mobile/desktop)",
        " contentqa": "Content-QA flag",
    },
}

# Cream editorial skin — lifted verbatim from report/reference/mockup.html :root + classes.
_CSS = """
:root{--bg:#f6f1e7;--surface:#fffdf8;--card:#fffefb;--ink:#2a2622;--muted:#6f6657;--faint:#938974;
--line:#e6ddc9;--line-strong:#d6c9ab;--accent:#9c4a21;--bad:#b3261e;--bad-bg:#fbeae8;
--warn:#9a6a00;--warn-bg:#fbf2dd;--ok:#2e6b3e;--ok-bg:#e9f3ea;
--t-mert:#2f5d8c;--t-becs:#8a6d00;--t-ai:#6b4d8a;--t-kov:#9c4221;
--serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Times New Roman",serif;
--sans:ui-sans-serif,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.6;font-size:16px;-webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:40px 22px 90px}
h1,h2,h3{font-family:var(--serif);font-weight:600;line-height:1.2;color:var(--ink)}
h1{font-size:30px;margin:0 0 4px}.sub{color:var(--muted);font-size:14.5px;margin-bottom:26px}
h2.sec{font-size:21px;margin:0 0 2px}
.secnum{font-family:var(--sans);font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.role{color:var(--faint);font-size:13.5px;font-style:italic;margin:2px 0 16px}
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:24px 26px;margin:0 0 18px;scroll-margin-top:16px}
p{margin:0 0 12px}.lead{font-size:17px}ul{margin:0 0 12px;padding-left:20px}li{margin:3px 0}
.tag{display:inline-block;font-family:var(--sans);font-size:11px;font-weight:600;letter-spacing:.02em;padding:1px 7px;border-radius:20px;border:1px solid currentColor;vertical-align:middle;white-space:nowrap}
.t-mert{color:var(--t-mert)}.t-becs{color:var(--t-becs)}.t-ai{color:var(--t-ai)}.t-kov{color:var(--t-kov)}
.st{display:inline-block;font-size:12.5px;font-weight:700;padding:3px 10px;border-radius:6px}
.st-bad{background:var(--bad-bg);color:var(--bad)}.st-warn{background:var(--warn-bg);color:var(--warn)}.st-ok{background:var(--ok-bg);color:var(--ok)}
.hook{border-left:3px solid var(--accent);padding:6px 0 6px 16px;margin:6px 0 20px;font-family:var(--serif);font-size:20px;line-height:1.4}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.axis{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 15px;display:flex;flex-direction:column;gap:7px}
.axis .top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.axis .name{font-weight:600;font-size:15.5px}.axis .why{color:var(--muted);font-size:13.5px;line-height:1.45;flex:1}
.axis .foot{display:flex;justify-content:space-between;align-items:center;gap:8px}
.lnk{color:var(--accent);font-size:12.5px;font-weight:600;text-decoration:none;white-space:nowrap}.lnk:hover{text-decoration:underline}
table{border-collapse:collapse;width:100%;font-size:14px;margin:6px 0 4px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-family:var(--sans);font-size:12px;letter-spacing:.03em;text-transform:uppercase;color:var(--faint);font-weight:700}
td.num{font-variant-numeric:tabular-nums}.ph{color:var(--faint);font-style:italic}
.bar{height:7px;border-radius:5px;background:var(--line);overflow:hidden;min-width:80px}
.bar>i{display:block;height:100%;border-radius:5px;background:var(--accent)}.bar.low>i{background:var(--bad)}
.dimrow{display:grid;grid-template-columns:150px 56px 1fr;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--line)}
.dimrow:last-child{border-bottom:0}.dimname{font-weight:600;font-size:14.5px}
.dimname small{display:block;color:var(--faint);font-weight:400;font-size:12px}.dimsig{color:var(--muted);font-size:13px}
.band{display:inline-block;background:var(--card);border:1px solid var(--line-strong);border-radius:8px;padding:8px 14px;font-family:var(--serif);font-size:17px;margin:2px 0 10px}.band b{color:var(--accent)}
.note{background:var(--card);border:1px dashed var(--line-strong);border-radius:10px;padding:14px 16px;color:var(--muted);font-size:13.5px;margin-top:10px}
.placeholder{border:2px dashed var(--accent);background:#fdf4ec}
.subsec{margin:18px 0 6px}.subsec .n{font-family:var(--sans);font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--accent)}
.legend{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:0 0 8px;font-size:12.5px}
.legend b{font-family:var(--sans);color:var(--faint);font-weight:700;text-transform:uppercase;letter-spacing:.05em;font-size:11px;margin-right:2px}
nav.toc{font-size:13px;color:var(--muted);margin:0 0 26px;line-height:1.9}nav.toc a{color:var(--accent);text-decoration:none}nav.toc a:hover{text-decoration:underline}
.snapshot{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;font-size:12.5px;color:var(--muted);margin:0 0 14px;display:flex;flex-wrap:wrap;gap:4px 16px}
.snapshot span b{color:var(--ink);font-weight:600}
.kwhero{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;background:var(--card);border:1px solid var(--line-strong);border-left:4px solid var(--accent);border-radius:10px;padding:16px 20px;margin:6px 0 10px}
.kwhero .kw{font-family:var(--serif);font-size:26px;font-weight:600;color:var(--ink)}.kwhero .kwmeta{color:var(--muted);font-size:14px}.kwhero .kwmeta b{color:var(--ink)}
.rec{border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:10px;padding:10px 15px;margin:8px 0;background:var(--card)}
.rec.t1{border-left-color:var(--bad)}.rec.t2{border-left-color:var(--warn)}.rec.t3{border-left-color:var(--t-mert)}
.rec .sev{font-size:11px;font-weight:700;color:var(--faint);text-transform:uppercase;letter-spacing:.04em}
td.brand{font-weight:600}tr.clientrow td{background:var(--bad-bg)}
@media(max-width:560px){.grid{grid-template-columns:1fr}.dimrow{grid-template-columns:1fr 50px;gap:8px}.dimsig{grid-column:1/-1}}
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _is_fact(o):
    return isinstance(o, dict) and "value" in o and "provenance" in o


def _esc(s):
    return _html.escape(str(s)) if s is not None else ""


def _chip(layer, lang):
    c = _LAYER_CHIP.get(layer)
    if not c:
        return ""
    cls, lbl = c
    return '<span class="tag %s">%s</span>' % (cls, lbl[lang])


def _nd(lang):
    return '<span class="ph">%s</span>' % UI[lang]["nd"]


def _fv(fact, lang, fmt=None):
    if not _is_fact(fact):
        return _nd(lang)
    prov, val = fact.get("provenance"), fact.get("value")
    if prov in ("absent", "not_measured") or val is None:
        return _nd(lang)
    shown = fmt(val) if fmt else _esc(val)
    return "%s %s" % (shown, _chip(fact.get("layer"), lang))


def _raw(value, layer):
    return {"value": value, "provenance": "measured" if value is not None else "not_measured", "layer": layer}


def _dig(d, *path):
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and isinstance(k, int) and -len(cur) <= k < len(cur):
            cur = cur[k]
        else:
            return None
    return cur


def _audit_date(ao):
    return (ao.get("audit_date") or ao.get("created_at") or "")[:10]


# ---------------------------------------------------------------------------
# §1 dashboard
# ---------------------------------------------------------------------------
def _axis(name, st_cls, st_txt, why, layer, link, lang):
    return ('<div class="axis"><div class="top"><span class="name">%s</span>'
            '<span class="st %s">%s</span></div><div class="why">%s</div>'
            '<div class="foot">%s<a class="lnk" href="#%s">→ %s</a></div></div>'
            % (_esc(name), st_cls, _esc(st_txt), _esc(why), _chip(layer, lang), link, link))


def _s1(fb, dec, ao, lang):
    t = UI[lang]
    rf = dec.get("ranked_findings") or []
    # full-sentence hook from the top finding
    hook = ""
    if rf:
        top = rf[0]
        lead = ("A legnagyobb hatású megállapítás: " if lang == "hu"
                else "The highest-impact finding: ")
        hook = '<div class="hook">%s%s.</div>' % (lead, _esc(top.get("finding")))
    av = fb.get("ai_visibility") or {}
    aio = av.get("ai_overview_client_status") or {}
    if aio.get("provenance") == "absent":
        ai = ("st-bad", t["st_weak"], (t["excluded"] + " — AI Overview" if lang == "en"
              else "Kihagyva az AI Overview-ból"), "mért")
    elif aio.get("provenance") == "measured" and aio.get("value"):
        ai = ("st-ok", t["st_ok"], t["cited"], "mért")
    else:
        ai = ("st-warn", t["st_attn"], t["nd"], "mért")
    cq = ((fb.get("onpage") or {}).get("content_qa") or {}).get("page_flag") or {}
    if cq.get("value") is True and cq.get("provenance") == "measured":
        page = ("st-bad", t["st_weak"], ("Befejezetlen/helykitöltő tartalom az oldalon"
                if lang == "hu" else "Unfinished / placeholder content on the page"), "mért")
    else:
        page = ("st-ok", t["st_ok"], ("Nincs tartalmi-QA jelzés" if lang == "hu" else "No content-QA flag"), "mért")
    perf = ((fb.get("technical") or {}).get("psi_mobile_perf") or {}).get("value")
    if isinstance(perf, int):
        pc = "st-ok" if perf >= 90 else ("st-warn" if perf >= 50 else "st-bad")
        pl = t["st_ok"] if perf >= 90 else (t["st_attn"] if perf >= 50 else t["st_weak"])
        tech = (pc, pl, ("Mobil teljesítmény-pontszám: %d/100" % perf if lang == "hu"
                else "Mobile performance score: %d/100" % perf), "mért")
    else:
        tech = ("st-warn", t["st_attn"], t["nd"], "mért")
    et = (((fb.get("eeat") or {}).get("client") or {}).get("total_0_40") or {}).get("value")
    if isinstance(et, int):
        ec = "st-ok" if et >= 30 else ("st-warn" if et >= 22 else "st-bad")
        el = t["st_ok"] if et >= 30 else (t["st_attn"] if et >= 22 else t["st_weak"])
        eeat = (ec, el, ("Összesített E-E-A-T: %d/40" % et if lang == "hu"
                else "Overall E-E-A-T: %d/40" % et), "AI-értelmezés")
    else:
        eeat = ("st-warn", t["st_attn"], t["nd"], "AI-értelmezés")
    grid = (_axis(t["ax_ai"], *ai[:2], ai[2], ai[3], "s3", lang)
            + _axis(t["ax_page"], *page[:2], page[2], page[3], "s4", lang)
            + _axis(t["ax_tech"], *tech[:2], tech[2], tech[3], "s4", lang)
            + _axis(t["ax_eeat"], *eeat[:2], eeat[2], eeat[3], "s5", lang))
    return hook + '<div class="grid">%s</div>' % grid


def _s2(fb, ao, lang):
    t = UI[lang]
    tg = fb.get("target") or {}
    cl = fb.get("classification") or {}
    kw = (tg.get("primary_keyword") or {}).get("value") or "—"
    market = (cl.get("locality") or {}).get("value") or "—"
    intent = (tg.get("intent") or {}).get("value") or "—"
    out = ('<div class="kwhero"><span class="kw">„%s"</span>'
           '<span class="kwmeta">%s: <b>%s</b> &nbsp;·&nbsp; intent: <b>%s</b> &nbsp;·&nbsp; %s</span></div>'
           % (_esc(kw), t["market"], _esc(market), _esc(intent), _chip("mért", lang)))
    rows = [("Difficulty", _fv(tg.get("difficulty"), lang)),
            ("Business model", _fv(cl.get("business_model"), lang)),
            ("Topic domain", _fv(cl.get("topic_domain"), lang))]
    out += "<table>" + "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows) + "</table>"
    serp = _dig(fb, "competition", "primary_keyword_serp", "top10")
    if _is_fact(serp) and serp.get("provenance") == "measured":
        out += "<div class='subsec'><span class='n'>SERP %s</span></div><table><tr><th>#</th><th>URL</th></tr>" % _chip("mért", lang)
        for r in (serp.get("value") or [])[:10]:
            out += "<tr><td class='num'>%s</td><td>%s</td></tr>" % (_esc(r.get("position")), _esc(r.get("url")))
        out += "</table>"
    return out


def _s3(fb, ao, lang):
    t = UI[lang]
    av = fb.get("ai_visibility") or {}
    out = '<div class="snapshot"><span>%s</span></div>' % t["snapshot"]
    out += "<table><tr><th>%s</th><th>%s</th></tr>" % (t["competitor"] if False else "AI surface", t["cited"])

    def _cite_cell(fact, excluded_label=None):
        if not _is_fact(fact):
            return _nd(lang)
        prov, val = fact.get("provenance"), fact.get("value")
        if prov == "measured" and val:
            return '<span class="st st-ok">%s</span> %s' % (t["cited"], _chip("mért", lang))
        if prov == "absent":  # evaluated, NOT cited (a real finding)
            lbl = excluded_label or t["not_cited"]
            return '<span class="st st-bad">%s</span> %s' % (lbl, _chip("mért", lang))
        return _nd(lang)

    out += "<tr><td>Google AI Overview</td><td>%s</td></tr>" % _cite_cell(
        av.get("ai_overview_client_status"), excluded_label=t["excluded"])
    out += "<tr><td>ChatGPT</td><td>%s</td></tr>" % _cite_cell(av.get("chatgpt_target_cited"))
    out += "</table>"
    # competitors cited in AIO (client vs competitors)
    cc = av.get("ai_overview_cited_competitors")
    if _is_fact(cc) and cc.get("provenance") == "measured" and cc.get("value"):
        from urllib.parse import urlparse
        names = [urlparse(u).netloc.replace("www.", "") for u in cc["value"]]
        out += "<p>%s: <b>%s</b> %s</p>" % (t["competitors_cited"], ", ".join(_esc(n) for n in names), _chip("mért", lang))
    # AI-interpretation: exclusion reason (reuse stored RE comparison summary)
    syn = _dig(ao, "re_findings", "comparison", "ai_overview_summary")
    if syn:
        out += '<div class="note">%s %s</div>' % (_esc(_sanitize_labels(syn, _page_names(ao))), _chip("AI-értelmezés", lang))
    # fan-out coverage (already correct)
    fo = av.get("fan_out_enriched")
    if _is_fact(fo) and fo.get("value"):
        items = fo.get("value")
        cov = sum(1 for x in items if isinstance(x, dict) and x.get("coverage") == "covered")
        out += '<p>%s: <b>%d / %d</b> %s</p>' % (t["fan_cov"], cov, len(items), _chip("AI-értelmezés", lang))
    return out


def _subsec(n, title):
    return '<div class="subsec"><span class="n">%s</span> <b style="font-family:var(--serif)">%s</b></div>' % (_esc(n), _esc(title))


def _cwv_view(ao, lang, key, label):
    b = _dig(ao, "pagespeed", "mobile", key) or {}
    def cell(metric, sub):
        node = b.get(metric) or {}
        v = node.get(sub); rating = node.get("rating")
        if not isinstance(v, (int, float)):
            return '<td class="num"><span class="ph">%s</span></td>' % UI[lang]["nd"]
        cls = {"good": "st-ok", "needs_improvement": "st-warn", "poor": "st-bad"}.get(rating, "")
        disp = ("%d ms" % int(v)) if sub == "value_ms" else ("%.3f" % v)
        chip = '<span class="st %s">%s</span>' % (cls, disp) if cls else disp
        return '<td class="num">%s</td>' % chip
    return ("<tr><td>%s %s</td>%s%s%s</tr>" % (
        _esc(label), _chip("mért", lang), cell("lcp", "value_ms"),
        cell("inp", "value_ms"), cell("cls", "value")))


def _s4(fb, ao, lang):
    t = UI[lang]
    op = fb.get("onpage") or {}
    tech = fb.get("technical") or {}
    words = _dig(ao, "crawl", "main_content", "words")
    cq = op.get("content_qa") or {}
    out = _subsec("4.1", "Tartalmi profil" if lang == "hu" else "Content profile")
    out += "<table>"
    out += "<tr><th>%s</th><td>%s</td></tr>" % (t["word_count"], _fv(_raw(words, "mért"), lang))
    out += "<tr><th>%s</th><td>%s</td></tr>" % (t[" contentqa"], _fv(cq.get("page_flag"), lang,
        fmt=lambda v: ("⚠ placeholder/leak" if v else "clean")))
    out += "</table>"
    out += _subsec("4.2", "Szemantika + struktúra" if lang == "hu" else "Semantics + structure")
    ae = ao.get("aaa124_aspect_evaluations") or {}
    pn = _page_names(ao)
    for asp in ("macro_structure", "micro_semantics", "text_level_semantics"):
        f = (ae.get(asp) or {}).get("structured_finding")
        if f:
            label = _ASPECT_LABELS.get(asp, {}).get(lang) or asp  # AAA-181: friendly label
            out += '<div class="note"><b>%s</b> %s<br>%s</div>' % (
                _esc(label), _chip("AI-értelmezés", lang),
                _esc(_sanitize_labels(f, pn)))
    out += _subsec("4.3", "Gép-olvashatóság" if lang == "hu" else "Machine-readability")
    h = op.get("headings") or {}
    img = op.get("images") or {}
    altc = None
    if _is_fact(img.get("img_count")) and (img.get("img_count") or {}).get("value"):
        ic = img["img_count"]["value"]; ac = (img.get("alt_count") or {}).get("value") or 0
        altc = round(100 * ac / ic, 1) if ic else None
    rows = [
        (t["headings"], "%s / %s / %s" % (_fv(h.get("h1_count"), lang),
            _fv(h.get("total_headings") if _is_fact(h.get("total_headings")) else _raw(None, "mért"), lang),
            _fv(h.get("level_skips"), lang))),
        (t["altcov"], _fv(_raw(altc, "következtetés"), lang, fmt=lambda v: "%s%%" % v)),
        (t["labelcov"], _fv((op.get("forms") or {}).get("label_coverage"), lang)),
        (t["landmarks"], _fv((op.get("aria") or {}).get("landmarks_present"), lang,
            fmt=lambda v: ", ".join(v) if isinstance(v, list) else _esc(v))),
        (t["schema_jsonld"], _fv((op.get("schema") or {}).get("json_ld_present"), lang)),
    ]
    out += "<table>" + "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows) + "</table>"
    out += _subsec("4.4", "Technikai egészség" if lang == "hu" else "Technical health")
    out += "<table><tr><th>%s</th><th>LCP</th><th>INP</th><th>CLS</th></tr>" % (
        "Nézet" if lang == "hu" else "View")
    out += _cwv_view(ao, lang, "core_web_vitals_field", t["cwv_field"])
    out += _cwv_view(ao, lang, "core_web_vitals_lab", t["cwv_lab"])
    out += "</table>"
    rows44 = [
        (t["perf"], "%s / %s" % (_fv(tech.get("psi_mobile_perf"), lang), _fv(tech.get("psi_desktop_perf"), lang))),
        (t["indexed"], _fv(tech.get("indexed"), lang)),
        ("HTTPS", _fv(tech.get("https"), lang)),
        (t["page_weight"], _fv(_raw(_dig(ao, "crawl", "content", "raw_html_bytes"), "mért"), lang,
            fmt=lambda v: "%d B (%.1f%% / 2MB)" % (v, 100 * v / 2097152))),
    ]
    out += "<table>" + "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows44) + "</table>"
    return out


def _s5(fb, ao, lang):
    t = UI[lang]
    cl = (fb.get("eeat") or {}).get("client") or {}
    tot = (cl.get("total_0_40") or {}).get("value")
    if isinstance(tot, int):
        band = ("gyenge–közepes" if lang == "hu" else "weak–moderate") if tot < 30 else ("erős" if lang == "hu" else "strong")
        out = '<div class="band">%s: <b>≈ %d / 40</b> &nbsp;·&nbsp; %s</div>' % (
            t["total"], tot, band)
    else:
        out = ""
    DIMS = [("experience", "Tapasztalat" if lang == "hu" else "Experience", "Experience"),
            ("expertise", "Szakértelem" if lang == "hu" else "Expertise", "Expertise"),
            ("authoritativeness", "Tekintély" if lang == "hu" else "Authority", "Authoritativeness"),
            ("trustworthiness", "Megbízhatóság" if lang == "hu" else "Trust", "Trustworthiness")]
    out += '<div style="margin-top:10px">'
    for k, lbl, sub in DIMS:
        f = cl.get(k) or {}
        v = f.get("value")
        band_cls = "band low" if isinstance(v, int) and v <= 3 else "band"
        style = "margin:0;padding:4px 10px;font-size:15px"
        if band_cls == "band low":
            style += ";border-color:var(--bad);color:var(--bad)"
        val_html = ('<span class="%s" style="%s">%s/10</span>' % (band_cls, style, v)) if isinstance(v, int) else _nd(lang)
        out += ('<div class="dimrow"><div class="dimname">%s<small>%s</small></div>'
                '<div>%s</div><div class="dimsig">%s</div></div>'
                % (_esc(lbl), _esc(sub), val_html, _chip("AI-értelmezés", lang)))
    out += "</div>"
    verdict = _dig(ao, "eeat_score", "client", "verdict")
    if verdict:
        verdict = _sanitize_labels(verdict, _page_names(ao))  # AAA-181: strip PAGE_N
        out += '<div class="subsec"><span class="n">%s</span></div><p>%s %s</p>' % (
            t["verdict"], _esc(verdict), _chip("AI-értelmezés", lang))
    out += '<p class="role">%s</p>' % t["see_s6"]
    return out


def _s6(fb, ao, lang):
    t = UI[lang]
    comps = (fb.get("competition") or {}).get("competitors") or []
    names = [((c.get("brand") or {}).get("value") or "?") for c in comps]
    cl = (fb.get("eeat") or {}).get("client") or {}

    def fam(title, rows, layer):
        h = _subsec("", title) + '<table><tr><th>%s %s</th>' % (t["competitor"], _chip(layer, lang))
        h += "".join("<th class='num'>%s</th>" % _esc(n) for n in names) + "</tr>"
        for label, key in rows:
            h += "<tr><td>%s</td>" % label
            for c in comps:
                v = (c.get(key) or {}).get("value")
                h += "<td class='num'>%s</td>" % (_esc(v) if v is not None else '<span class="ph">—</span>')
            h += "</tr>"
        return h + "</table>"

    out = fam(t["fam_content"], [("Word count", "word_count_doc"), ("Orgs", "orgs_count")], "mért")
    out += fam(t["fam_seo"], [("Title chars", "title_chars"), ("Meta chars", "meta_chars"),
                              ("H1", "h1_count"), ("Headings", "total_headings")], "mért")
    out += fam(t["fam_tech"], [("Schema types", "schema_types_count"), ("Alt %", "alt_coverage_pct"),
                               ("Perf (mobile/lab)", "perf_mobile_lab")], "mért")
    # E-E-A-T family: raw per-dim + total
    h = _subsec("", t["fam_eeat"]) + '<table><tr><th>E-E-A-T %s</th><th class="num">%s</th>' % (
        _chip("AI-értelmezés", lang), t["client"])
    h += "".join("<th class='num'>%s</th>" % _esc(n) for n in names) + "</tr>"
    for dk, dl in [("experience", "E"), ("expertise", "Ex"), ("authoritativeness", "A"),
                   ("trustworthiness", "T"), ("total_0_40", t["total"])]:
        h += "<tr><td>%s</td>" % dl
        cv = (cl.get(dk) or {}).get("value")
        h += '<td class="num"><b>%s</b></td>' % (_esc(cv) if cv is not None else "—")
        for c in comps:
            ev = ((c.get("eeat") or {}).get(dk) or {}).get("value")
            h += "<td class='num'>%s</td>" % (_esc(ev) if ev is not None else '<span class="ph">—</span>')
        h += "</tr>"
    out += h + "</table>"
    rk = (fb.get("eeat") or {}).get("ranking") or {}
    if _is_fact(rk) and rk.get("value"):
        out += '<div class="subsec"><span class="n">%s</span></div><table><tr><th>#</th><th>%s</th><th>%s</th></tr>' % (
            t["rank"], "Oldal" if lang == "hu" else "Page", t["total"])
        rows = rk["value"]
        mx = max([r.get("total_0_40") or 0 for r in rows] + [40])
        for r in rows:
            tot = r.get("total_0_40") or 0
            cls = " clientrow" if r.get("is_client") else ""
            barcls = "bar low" if r.get("is_client") else "bar"
            out += ('<tr class="%s"><td class="num">#%s</td><td class="brand">%s</td>'
                    '<td><div class="%s"><i style="width:%d%%"></i></div> <span class="num">%s</span></td></tr>'
                    % (cls.strip(), _esc(r.get("rank")), _esc(r.get("brand")), barcls, int(100 * tot / mx), _esc(tot)))
        out += "</table>"
    syn = _dig(ao, "re_findings", "comparison", "ai_overview_summary")
    if syn:
        out += '<div class="note">%s %s</div>' % (_esc(_sanitize_labels(syn, _page_names(ao))), _chip("AI-értelmezés", lang))
    return out


def _is_volume_finding(f):
    txt = (f.get("finding") or "").lower()
    return f.get("category") == "content" and any(w in txt for w in ("volume", "word", "deficit", "depth"))


def _s7(fb, dec, lang):
    t = UI[lang]
    findings = [f for f in (dec.get("ranked_findings") or []) if not _is_volume_finding(f)]
    tiers = {"high": [], "medium": [], "low": []}
    for f in findings:
        tiers.get(f.get("impact_severity"), tiers["low"]).append(f)
    out = ""
    for sev, label, cls in (("high", t["t1"], "t1"), ("medium", t["t2"], "t2"), ("low", t["t3"], "t3")):
        if not tiers[sev]:
            continue
        out += _subsec("", label)
        for f in tiers[sev]:
            rec = f.get("recommendation") or ""
            out += ('<div class="rec %s"><span class="sev">%s · %s</span><div><b>%s</b></div>%s</div>'
                    % (cls, _esc(sev), _esc(f.get("category")), _esc(f.get("finding")),
                       ("<div class='dimsig'>%s</div>" % _esc(rec)) if rec else ""))
    return out


def _s8(fb, ao, dec, lang):
    t = UI[lang]
    from collections import Counter
    prov = Counter(); layer = Counter()
    def walk(o):
        if _is_fact(o):
            prov[o.get("provenance")] += 1; layer[o.get("layer")] += 1; return
        if isinstance(o, dict):
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    for g, v in fb.items():
        if g != "meta": walk(v)
    # §8 layer labels in EN (G3.5 E)
    en_lbl = {"mért": "measured", "becslés": "estimate", "AI-értelmezés": "AI interpretation",
              "következtetés": "inference"}
    layer_str = ", ".join("%s %d" % (en_lbl.get(k, k) if lang == "en" else k, n) for k, n in layer.most_common())
    prov_str = ", ".join("%s %d" % (k, n) for k, n in prov.most_common())
    out = "<p><b>%s</b> — provenance: %s · layers: %s</p>" % (t["prov_summary"], _esc(prov_str), layer_str)
    d = _audit_date(ao)
    rows = [
        ("Crawl / on-page", d, t["in_run"]),
        ("PageSpeed (lab+field)", d, t["in_run"]),
        ("CrUX field", d, t["crux_window"]),
        ("SERP / AI Overview / ChatGPT", d, t["in_run"]),
        ("E-E-A-T / aspect eval", d, t["in_run"]),
    ]
    out += "<table><tr><th>%s</th><th>%s</th><th>%s</th></tr>" % (t["fresh_source"], t["fresh_when"], t["fresh_state"])
    out += "".join("<tr><td>%s</td><td class='num'>%s</td><td class='dimsig'>%s</td></tr>" % (a, b or "—", c) for a, b, c in rows)
    out += "</table>"
    out += '<div class="note">Date-only freshness (AAA-177): no precise time / engine-version.</div>'
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def render_factfirst_report(audit_output, lang="en", available_langs=None):
    """audit_output (incl. fact_base + decisions) → (html, meta). Deterministic;
    reuses stored interpretive prose; render cost 0.0 (no new LLM)."""
    lang = lang if lang in UI else "en"
    t = UI[lang]
    ao = audit_output or {}
    fb = ao.get("fact_base") or {}
    dec = ao.get("decisions") or {}
    m = fb.get("meta") or {}
    domain = m.get("url") or ao.get("url") or "—"
    keyword = (((fb.get("target") or {}).get("primary_keyword") or {}).get("value")) or "—"
    market = (((fb.get("classification") or {}).get("locality") or {}).get("value")) or "—"
    date = _audit_date(ao)

    secs = [
        ("§1", t["s1"], t["r1"], "s1", _s1(fb, dec, ao, lang)),
        ("§2", t["s2"], t["r2"], "s2", _s2(fb, ao, lang)),
        ("§3", t["s3"], t["r3"], "s3", _s3(fb, ao, lang)),
        ("§4", t["s4"], t["r4"], "s4", _s4(fb, ao, lang)),
        ("§5", t["s5"], t["r5"], "s5", _s5(fb, ao, lang)),
        ("§6", t["s6"], t["r6"], "s6", _s6(fb, ao, lang)),
        ("§7", t["s7"], t["r7"], "s7", _s7(fb, dec, lang)),
        ("§8", t["s8"], t["r8"], "s8", _s8(fb, ao, dec, lang)),
    ]
    legend = ('<div class="legend"><b>%s</b>%s%s%s%s<span style="color:var(--faint)">%s</span></div>'
              % (t["legend"], _chip("mért", lang), _chip("becslés", lang),
                 _chip("AI-értelmezés", lang), _chip("következtetés", lang), t["legend_note"]))
    toc = '<nav class="toc">' + " &nbsp;·&nbsp; ".join(
        '<a href="#%s">%d · %s</a>' % (s[3], i + 1, _esc(s[1])) for i, s in enumerate(secs)) + "</nav>"
    snap = ('<div class="snapshot"><span>%s: <b>%s</b></span><span>%s: <b>%s</b></span>'
            '<span>%s: <b>%s</b></span><span>%s: <b>%s</b></span></div>'
            % (t["domain"], _esc(domain), t["keyword"], _esc(keyword),
               t["market"], _esc(market), t["date"], _esc(date)))
    body = ""
    for sid, title, role, anchor, html_in in secs:
        body += ('<section id="%s"><div class="secnum">%s. %s</div>'
                 '<h2 class="sec">%s</h2><div class="role">%s</div>%s</section>'
                 % (anchor, sid.lstrip("§"), t["section"], _esc(title), _esc(role), html_in))

    doc = ("<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           "<title>%s — %s</title><style>%s</style></head><body><div class=\"wrap\">"
           "<h1>%s</h1><div class=\"sub\">%s</div>%s%s%s%s</div></body></html>") % (
        lang, _esc(t["doc_title"]), _esc(domain), _CSS,
        _esc(t["doc_title"]), _esc(t["sub"]), legend, toc, snap, body)

    return doc, {"cost_usd": 0.0, "lang": lang,
                 "sections": [s[0] for s in secs], "render_version": RENDER_VERSION}
