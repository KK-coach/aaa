# -*- coding: utf-8 -*-
"""AAA-161 Gate 3 — NEW 8-section fact-first customer render (PARALLEL artifact).

Consumes the Gate 1+2 data layer (audit_output.fact_base = fact_base_v4 +
audit_output.decisions = decisions_v2) and emits a styled 8-section HTML report,
per language (hu / en). DETERMINISTIC for all structure / numbers / tables / bars /
chips / findings — NO LLM for those. AI-értelmezés prose blocks REUSE already-
stored interpretive data (aaa124_aspect_evaluations, eeat_score verdicts,
re_findings.comparison) — ZERO new LLM calls this gate (render cost $0).

Parallel to the legacy render (report/html_render.py): written to
reports/{audit_id}.{lang}.ff.html; ref persisted at
audit_output.customer_report_html_uri_ff. Legacy untouched.

Every rendered data point shows its layer-tag chip from the leaf's `layer`
(mért / becslés / AI-értelmezés / következtetés). No-fabricate: absent /
not_measured → "nincs adat" / omitted; never invented. Competitor names are
fine (measured facts). The content-volume / word-count finding is SUPPRESSED
at render (product decision).
"""
from __future__ import annotations

import html as _html

SECTION_IDS = ["§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8"]

# Layer chip → (css class, hu label, en label)
_LAYER_CHIP = {
    "mért": ("l-meas", "mért", "measured"),
    "becslés": ("l-est", "becslés", "estimate"),
    "AI-értelmezés": ("l-ai", "AI-értelmezés", "AI interpretation"),
    "következtetés": ("l-infer", "következtetés", "inference"),
}

UI = {
    "hu": {
        "title": "Tényalapú audit-riport",
        "s1": "Összefoglaló státusz", "s2": "Keresési környezet",
        "s3": "AI-láthatóság", "s4": "Saját oldal", "s5": "E-E-A-T bizalmi olvasat",
        "s6": "Konkurens benchmark", "s7": "Javaslatok", "s8": "Adatminőség / provenance",
        "domain": "Domain", "keyword": "Kulcsszó", "market": "Piac", "date": "Audit dátuma",
        "nodata": "nincs adat", "snapshot": "Pillanatkép az audit napján",
        "ax_ai": "AI-láthatóság", "ax_page": "Saját oldal", "ax_tech": "Technikai egészség", "ax_eeat": "E-E-A-T",
        "cited": "Idézve", "not_cited": "Nincs idézve", "competitor": "Versenytárs",
        "fam_content": "Tartalom", "fam_seo": "On-site SEO", "fam_tech": "Technikai SEO", "fam_eeat": "E-E-A-T",
        "rank": "Rangsor", "client": "Ügyfél", "total": "Összesen",
        "cwv_lab": "Labor (Lighthouse)", "cwv_field": "Mező (CrUX p75)", "cwv_blended": "Vegyes",
        "tier1": "Magas hatás", "tier2": "Közepes hatás", "tier3": "Alacsony hatás",
        "fresh_source": "Forrás", "fresh_when": "Mikor rögzítve", "fresh_state": "Frissesség",
        "prov_summary": "Adat-provenance összegzés", "word_count": "Szószám", "page_weight": "Oldalsúly",
        "verdict": "Összegző értékelés", "see_s6": "Az összevetést lásd a §6-ban.",
    },
    "en": {
        "title": "Fact-first audit report",
        "s1": "Status summary", "s2": "Search environment",
        "s3": "AI visibility", "s4": "Your page", "s5": "E-E-A-T trust read",
        "s6": "Competitor benchmark", "s7": "Recommendations", "s8": "Data quality / provenance",
        "domain": "Domain", "keyword": "Keyword", "market": "Market", "date": "Audit date",
        "nodata": "no data", "snapshot": "Snapshot as of the audit date",
        "ax_ai": "AI visibility", "ax_page": "Your page", "ax_tech": "Technical health", "ax_eeat": "E-E-A-T",
        "cited": "Cited", "not_cited": "Not cited", "competitor": "Competitor",
        "fam_content": "Content", "fam_seo": "On-site SEO", "fam_tech": "Technical SEO", "fam_eeat": "E-E-A-T",
        "rank": "Rank", "client": "Client", "total": "Total",
        "cwv_lab": "Lab (Lighthouse)", "cwv_field": "Field (CrUX p75)", "cwv_blended": "Blended",
        "tier1": "High impact", "tier2": "Medium impact", "tier3": "Low impact",
        "fresh_source": "Source", "fresh_when": "Captured", "fresh_state": "Freshness",
        "prov_summary": "Data-provenance summary", "word_count": "Word count", "page_weight": "Page weight",
        "verdict": "Overall read", "see_s6": "See §6 for the comparison.",
    },
}

_CSS = """
:root{--bg:#0f1420;--card:#1a2233;--ink:#e8edf6;--mut:#94a3b8;--line:#2a3550;
--meas:#3b82f6;--est:#a855f7;--ai:#f59e0b;--infer:#10b981;--good:#22c55e;--warn:#f59e0b;--bad:#ef4444}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
.hdr{background:linear-gradient(135deg,#1e293b,#0f1420);border:1px solid var(--line);
border-radius:16px;padding:22px 24px;margin-bottom:22px}
.hdr h1{margin:0 0 10px;font-size:22px}.hdr .meta{display:flex;gap:24px;flex-wrap:wrap;color:var(--mut);font-size:13px}
.hdr .meta b{color:var(--ink)}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin:16px 0}
h2{margin:0 0 14px;font-size:18px;border-left:4px solid var(--meas);padding-left:10px}
h3{margin:18px 0 8px;font-size:15px;color:#cbd5e1}
.chip{display:inline-block;font-size:10px;font-weight:700;padding:1px 7px;border-radius:10px;
vertical-align:middle;margin-left:6px;letter-spacing:.3px}
.l-meas{background:rgba(59,130,246,.18);color:#93c5fd;border:1px solid var(--meas)}
.l-est{background:rgba(168,85,247,.18);color:#d8b4fe;border:1px solid var(--est)}
.l-ai{background:rgba(245,158,11,.18);color:#fcd34d;border:1px solid var(--ai)}
.l-infer{background:rgba(16,185,129,.18);color:#6ee7b7;border:1px solid var(--infer)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.axis{background:#141c2c;border:1px solid var(--line);border-radius:12px;padding:14px}
.axis .st{font-size:20px;font-weight:800}.axis .nm{color:var(--mut);font-size:13px}
.st.good{color:var(--good)}.st.warn{color:var(--warn)}.st.bad{color:var(--bad)}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:13px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600}.num{text-align:right;font-variant-numeric:tabular-nums}
.cl{color:#fcd34d;font-weight:700}
.bar{height:8px;background:#243049;border-radius:6px;overflow:hidden;min-width:80px;display:inline-block;width:120px;vertical-align:middle}
.bar>i{display:block;height:100%;background:var(--meas)}
.nd{color:var(--mut);font-style:italic}
.rec{border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:10px;padding:10px 14px;margin:8px 0;background:#141c2c}
.rec.t1{border-left-color:var(--bad)}.rec.t2{border-left-color:var(--warn)}.rec.t3{border-left-color:var(--meas)}
.rec .sev{font-size:11px;font-weight:700;color:var(--mut);text-transform:uppercase}
.prose{background:#141c2c;border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:8px 0;color:#cbd5e1;font-size:14px}
.small{color:var(--mut);font-size:12px}
a.toc{color:#93c5fd;text-decoration:none;font-size:12px}
"""


# ---------------------------------------------------------------------------
# Fact helpers
# ---------------------------------------------------------------------------
def _is_fact(o):
    return isinstance(o, dict) and "value" in o and "provenance" in o


def _esc(s):
    return _html.escape(str(s)) if s is not None else ""


def _chip(layer, lang):
    c = _LAYER_CHIP.get(layer)
    if not c:
        return ""
    cls, hu, en = c
    return '<span class="chip %s">%s</span>' % (cls, hu if lang == "hu" else en)


def _fv(fact, lang, fmt=None):
    """Render a fact value + its layer chip; absent/not_measured → 'nincs adat'."""
    nd = '<span class="nd">%s</span>' % UI[lang]["nodata"]
    if not _is_fact(fact):
        return nd
    prov = fact.get("provenance")
    val = fact.get("value")
    if prov in ("absent", "not_measured") or val is None:
        return nd
    shown = fmt(val) if fmt else _esc(val)
    return "%s %s" % (shown, _chip(fact.get("layer"), lang))


def _raw_fact(value, layer):
    """Wrap a directly-read audit_output value as a pseudo-fact for chip render."""
    return {"value": value, "provenance": "measured" if value is not None else "not_measured",
            "layer": layer}


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


# ---------------------------------------------------------------------------
# Section builders (all deterministic)
# ---------------------------------------------------------------------------
def _axis(name, state_cls, state_txt, oneliner, link):
    return ('<div class="axis"><div class="nm">%s · <a class="toc" href="#%s">→</a></div>'
            '<div class="st %s">%s</div><div class="small">%s</div></div>'
            % (_esc(name), link, state_cls, _esc(state_txt), _esc(oneliner)))


def _s1(fb, dec, ao, lang):
    t = UI[lang]
    m = fb.get("meta") or {}
    hook = ""
    rf = dec.get("ranked_findings") or []
    if rf:
        hook = '<div class="prose">%s %s</div>' % (_esc(rf[0].get("finding")),
                                                   _chip("következtetés", lang))
    # 4 status axes (qualitative)
    av = fb.get("ai_visibility") or {}
    cited = (av.get("ai_overview_client_cited") or {}).get("provenance")
    ai_state = ("bad", t["not_cited"]) if cited == "absent" else (
        ("good", t["cited"]) if cited == "measured" else ("warn", t["nodata"]))
    cq = ((fb.get("onpage") or {}).get("content_qa") or {}).get("page_flag") or {}
    page_state = ("bad", "⚠") if cq.get("value") is True and cq.get("provenance") == "measured" else ("good", "✓")
    perf = (fb.get("technical") or {}).get("psi_mobile_perf") or {}
    pv = perf.get("value")
    tech_state = ("good", str(pv)) if isinstance(pv, int) and pv >= 90 else (
        ("warn", str(pv)) if isinstance(pv, int) and pv >= 50 else (("bad", str(pv)) if isinstance(pv, int) else ("warn", "?")))
    et = (((fb.get("eeat") or {}).get("client") or {}).get("total_0_40") or {}).get("value")
    eeat_state = ("good", "%d/40" % et) if isinstance(et, int) and et >= 30 else (
        ("warn", "%d/40" % et) if isinstance(et, int) and et >= 20 else (("bad", "%d/40" % et) if isinstance(et, int) else ("warn", "?")))
    axes = (_axis(t["ax_ai"], ai_state[0], ai_state[1], "→ §3", "s3")
            + _axis(t["ax_page"], page_state[0], page_state[1], "→ §4", "s4")
            + _axis(t["ax_tech"], tech_state[0], tech_state[1], "→ §4.4", "s4")
            + _axis(t["ax_eeat"], eeat_state[0], eeat_state[1], "→ §5", "s5"))
    return hook + '<div class="grid2">%s</div>' % axes


def _s2(fb, ao, lang):
    t = UI[lang]
    tg = fb.get("target") or {}
    cl = fb.get("classification") or {}
    rows = [
        (t["keyword"], _fv(tg.get("primary_keyword"), lang)),
        ("Intent", _fv(tg.get("intent"), lang)),
        ("Difficulty", _fv(tg.get("difficulty"), lang)),
        ("Business model", _fv(cl.get("business_model"), lang)),
        ("Topic domain", _fv(cl.get("topic_domain"), lang)),
    ]
    out = "<table>" + "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows) + "</table>"
    # SERP list (top organic)
    serp = _dig(fb, "competition", "primary_keyword_serp", "top10")
    if _is_fact(serp) and serp.get("provenance") == "measured":
        items = serp.get("value") or []
        out += "<h3>SERP %s</h3><table><tr><th>#</th><th>URL</th></tr>" % _chip("mért", lang)
        for r in items[:10]:
            out += "<tr><td class='num'>%s</td><td>%s</td></tr>" % (
                _esc(r.get("position")), _esc(r.get("url")))
        out += "</table>"
    return out


def _s3(fb, ao, lang):
    t = UI[lang]
    av = fb.get("ai_visibility") or {}
    out = '<p class="small">%s</p>' % t["snapshot"]
    out += "<table>"
    out += "<tr><th>AI Overview — %s</th><td>%s</td></tr>" % (
        t["cited"], _fv(av.get("ai_overview_client_cited"), lang,
                        fmt=lambda v: (t["cited"] if v else t["not_cited"])))
    out += "<tr><th>ChatGPT — %s</th><td>%s</td></tr>" % (
        t["cited"], _fv(av.get("chatgpt_target_cited"), lang,
                        fmt=lambda v: (t["cited"] if v else t["not_cited"])))
    out += "</table>"
    # AIO cited sources
    src = av.get("ai_overview_cited_sources")
    if _is_fact(src) and src.get("provenance") == "measured":
        out += "<h3>AI Overview %s %s</h3><ul>" % (
            "cited sources" if lang == "en" else "idézett források", _chip("mért", lang))
        for s in (src.get("value") or [])[:10]:
            u = s.get("url") if isinstance(s, dict) else s
            out += "<li class='small'>%s</li>" % _esc(u)
        out += "</ul>"
    # fan-out coverage
    fo = av.get("fan_out_enriched")
    if _is_fact(fo) and fo.get("value"):
        items = fo.get("value")
        cov = sum(1 for x in items if isinstance(x, dict) and x.get("coverage") == "covered")
        out += '<p>Fan-out coverage: <b>%d / %d</b> %s</p>' % (cov, len(items), _chip("AI-értelmezés", lang))
    return out


def _s4(fb, ao, lang):
    t = UI[lang]
    op = fb.get("onpage") or {}
    tech = fb.get("technical") or {}
    # 4.1 content profile
    words = _dig(ao, "crawl", "main_content", "words")
    cq = op.get("content_qa") or {}
    out = "<h3>4.1 %s</h3><table>" % ("Tartalmi profil" if lang == "hu" else "Content profile")
    out += "<tr><th>%s</th><td>%s</td></tr>" % (t["word_count"], _fv(_raw_fact(words, "mért"), lang))
    out += "<tr><th>Content-QA flag</th><td>%s</td></tr>" % _fv(cq.get("page_flag"), lang,
        fmt=lambda v: ("⚠ placeholder/leak" if v else "clean"))
    out += "<tr><th>Hard hits</th><td>%s</td></tr>" % _fv(cq.get("hard_hit_count"), lang)
    out += "</table>"
    # 4.2 semantics+structure — reuse stored aspect prose (AI-értelmezés)
    out += "<h3>4.2 %s</h3>" % ("Szemantika + struktúra" if lang == "hu" else "Semantics + structure")
    ae = ao.get("aaa124_aspect_evaluations") or {}
    for asp in ("macro_structure", "micro_semantics", "text_level_semantics"):
        blk = ae.get(asp) or {}
        f = blk.get("structured_finding")
        if f:
            out += '<div class="prose"><b>%s</b> %s<br>%s</div>' % (
                _esc(asp), _chip("AI-értelmezés", lang), _esc(f))
    # 4.3 machine readability
    out += "<h3>4.3 %s</h3><table>" % ("Gép-olvashatóság" if lang == "hu" else "Machine-readability")
    h = op.get("headings") or {}
    img = op.get("images") or {}
    altc = None
    if _is_fact(img.get("img_count")) and (img.get("img_count") or {}).get("value"):
        ic = img["img_count"]["value"]; ac = (img.get("alt_count") or {}).get("value") or 0
        altc = round(100*ac/ic, 1) if ic else None
    rows43 = [
        ("H1 / total / skips", "%s / %s / %s" % (_fv(h.get("h1_count"), lang),
            _fv(h.get("total_headings") if _is_fact(h.get("total_headings")) else h.get("h1_count"), lang),
            _fv(h.get("level_skips"), lang))),
        ("Alt coverage %", _fv(_raw_fact(altc, "következtetés"), lang)),
        ("Form-label coverage", _fv((op.get("forms") or {}).get("label_coverage"), lang)),
        ("Landmarks present", _fv((op.get("aria") or {}).get("landmarks_present"), lang,
            fmt=lambda v: ", ".join(v) if isinstance(v, list) else _esc(v))),
        ("Schema (JSON-LD)", _fv((op.get("schema") or {}).get("json_ld_present"), lang)),
    ]
    out += "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows43) + "</table>"
    # 4.4 technical health — CWV 3-view
    out += "<h3>4.4 %s</h3>" % ("Technikai egészség" if lang == "hu" else "Technical health")
    out += _cwv_3view(ao, lang)
    rows44 = [
        ("PSI perf (mobile/desktop)", "%s / %s" % (_fv(tech.get("psi_mobile_perf"), lang),
            _fv(tech.get("psi_desktop_perf"), lang))),
        ("Indexed", _fv(tech.get("indexed"), lang)),
        ("HTTPS", _fv(tech.get("https"), lang)),
        (t["page_weight"], _fv(_raw_fact(_dig(ao, "crawl", "content", "raw_html_bytes"), "mért"), lang,
            fmt=lambda v: "%d B (%.1f%% / 2MB)" % (v, 100*v/2097152))),
    ]
    out += "<table>" + "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows44) + "</table>"
    return out


def _cwv_3view(ao, lang):
    t = UI[lang]
    out = "<table><tr><th>%s</th><th>LCP</th><th>INP</th><th>CLS</th></tr>" % ("Nézet" if lang == "hu" else "View")
    for label, key in ((t["cwv_field"], "core_web_vitals_field"), (t["cwv_lab"], "core_web_vitals_lab")):
        b = _dig(ao, "pagespeed", "mobile", key) or {}
        lcp = _dig(b, "lcp", "value_ms"); inp = _dig(b, "inp", "value_ms"); cls = _dig(b, "cls", "value")
        layer = "mért"
        out += "<tr><td>%s %s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td></tr>" % (
            _esc(label), _chip(layer, lang),
            "%s ms" % int(lcp) if isinstance(lcp, (int, float)) else "—",
            "%s ms" % int(inp) if isinstance(inp, (int, float)) else "—",
            cls if isinstance(cls, (int, float)) else "—")
    out += "</table>"
    return out


def _s5(fb, ao, lang):
    t = UI[lang]
    ee = fb.get("eeat") or {}
    cl = ee.get("client") or {}
    DIMS = [("experience", "Experience"), ("expertise", "Expertise"),
            ("authoritativeness", "Authoritativeness"), ("trustworthiness", "Trustworthiness")]
    out = "<table><tr><th>%s</th><th class='num'>0–10</th><th>%s</th></tr>" % (
        "Dimenzió" if lang == "hu" else "Dimension", "Állapot" if lang == "hu" else "State")
    for k, lbl in DIMS:
        f = cl.get(k) or {}
        v = f.get("value")
        state = ("közepes" if lang == "hu" else "moderate") if isinstance(v, int) and v >= 5 else (
            "gyenge" if lang == "hu" else "weak")
        out += "<tr><td>%s</td><td class='num'>%s</td><td>%s</td></tr>" % (
            _esc(lbl), _fv(f, lang), _esc(state) if isinstance(v, int) else "")
    tot = cl.get("total_0_40") or {}
    out += "<tr><th>%s</th><th class='num'>%s</th><th></th></tr>" % (t["total"], _fv(tot, lang))
    out += "</table>"
    # verdict — reuse stored eeat client verdict (AI-értelmezés)
    verdict = _dig(ao, "eeat_score", "client", "verdict")
    if verdict:
        out += '<div class="prose"><b>%s</b> %s<br>%s</div>' % (
            t["verdict"], _chip("AI-értelmezés", lang), _esc(verdict))
    out += '<p class="small">%s</p>' % t["see_s6"]
    return out


def _s6(fb, ao, lang):
    t = UI[lang]
    comps = (fb.get("competition") or {}).get("competitors") or []
    def cv(c, k):
        f = c.get(k) or {}
        return f.get("value")
    names = [(cv(c, "brand") or "?") for c in comps]
    cl = (fb.get("eeat") or {}).get("client") or {}

    def fam_table(title, rows, layer):
        h = "<h3>%s %s</h3><table><tr><th>%s</th>" % (title, _chip(layer, lang), t["competitor"])
        h += "".join("<th class='num'>%s</th>" % _esc(n) for n in names) + "</tr>"
        for label, key, fmt in rows:
            h += "<tr><td>%s</td>" % label
            for c in comps:
                v = cv(c, key)
                h += "<td class='num'>%s</td>" % (fmt(v) if (v is not None and fmt) else (_esc(v) if v is not None else "—"))
            h += "</tr>"
        return h + "</table>"

    out = fam_table(t["fam_content"], [
        ("Word count", "word_count_doc", None), ("Orgs", "orgs_count", None)], "mért")
    out += fam_table(t["fam_seo"], [
        ("Title chars", "title_chars", None), ("Meta chars", "meta_chars", None),
        ("H1", "h1_count", None), ("Headings", "total_headings", None)], "mért")
    out += fam_table(t["fam_tech"], [
        ("Schema types", "schema_types_count", None), ("Alt %", "alt_coverage_pct", None),
        ("Perf (mobile/lab)", "perf_mobile_lab", None)], "mért")
    # E-E-A-T family: raw per-dimension + total + ranking
    h = "<h3>%s %s</h3><table><tr><th>E-E-A-T</th>" % (t["fam_eeat"], _chip("AI-értelmezés", lang))
    h += "<th class='num cl'>%s</th>" % t["client"]
    h += "".join("<th class='num'>%s</th>" % _esc(n) for n in names) + "</tr>"
    for dk, dl in [("experience", "E"), ("expertise", "Ex"), ("authoritativeness", "A"),
                   ("trustworthiness", "T"), ("total_0_40", t["total"])]:
        h += "<tr><td>%s</td>" % dl
        h += "<td class='num cl'>%s</td>" % _esc((cl.get(dk) or {}).get("value") if cl.get(dk) else "—")
        for c in comps:
            ev = (c.get("eeat") or {}).get(dk) or {}
            h += "<td class='num'>%s</td>" % _esc(ev.get("value") if ev.get("value") is not None else "—")
        h += "</tr>"
    h += "</table>"
    out += h
    # ranking
    rk = (fb.get("eeat") or {}).get("ranking") or {}
    if _is_fact(rk) and rk.get("value"):
        out += "<p class='small'>%s: %s</p>" % (t["rank"], " &gt; ".join(
            "%s (%s)" % (_esc(r.get("brand")), _esc(r.get("total_0_40"))) for r in rk["value"]))
    # RE synthesis — reuse stored comparison narrative (AI-értelmezés)
    syn = _dig(ao, "re_findings", "comparison", "ai_overview_summary")
    if syn:
        out += '<div class="prose">%s %s</div>' % (_esc(syn), _chip("AI-értelmezés", lang))
    return out


_VOLUME_RE = ("volume", "word count", "word-count", "content volume", "tartalom",
              "szószám", "content depth", "deficit")


def _is_volume_finding(f):
    txt = (f.get("finding") or "").lower()
    cat = f.get("category")
    return cat == "content" and any(w in txt for w in ("volume", "word", "deficit", "depth"))


def _s7(fb, dec, lang):
    t = UI[lang]
    findings = dec.get("ranked_findings") or []
    # SUPPRESS the content-volume / word-count finding (product decision).
    findings = [f for f in findings if not _is_volume_finding(f)]
    tiers = {"high": [], "medium": [], "low": []}
    for f in findings:
        tiers.get(f.get("impact_severity"), tiers["low"]).append(f)
    out = ""
    for sev, label, cls in (("high", t["tier1"], "t1"), ("medium", t["tier2"], "t2"), ("low", t["tier3"], "t3")):
        if not tiers[sev]:
            continue
        out += "<h3>%s</h3>" % label
        for f in tiers[sev]:
            rec = f.get("recommendation") or ""
            out += '<div class="rec %s"><span class="sev">%s · %s</span><div><b>%s</b></div>%s</div>' % (
                cls, _esc(sev), _esc(f.get("category")), _esc(f.get("finding")),
                ("<div class='small'>%s</div>" % _esc(rec)) if rec else "")
    return out


def _s8(fb, ao, dec, lang):
    t = UI[lang]
    # provenance summary across all leaves
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
    out = "<p><b>%s</b> — provenance: %s · layers: %s</p>" % (
        t["prov_summary"],
        ", ".join("%s %d" % (k, n) for k, n in prov.most_common()),
        ", ".join("%s %d" % (k, n) for k, n in layer.most_common()))
    # date-only freshness table
    audit_date = (ao.get("audit_date") or ao.get("created_at") or "")[:10]
    rows = [
        ("Crawl / on-page", audit_date, "in-run"),
        ("PageSpeed (lab+field)", audit_date, "in-run"),
        ("CrUX field", audit_date, "28-%s" % ("napos ablak" if lang == "hu" else "day window")),
        ("SERP / AI Overview / ChatGPT", audit_date, "in-run"),
        ("E-E-A-T / aspect eval", audit_date, "in-run"),
    ]
    out += "<table><tr><th>%s</th><th>%s</th><th>%s</th></tr>" % (
        t["fresh_source"], t["fresh_when"], t["fresh_state"])
    out += "".join("<tr><td>%s</td><td>%s</td><td class='small'>%s</td></tr>" % (a, b, c) for a, b, c in rows)
    out += "</table>"
    out += '<p class="small">Date-only freshness (AAA-177): no precise time / engine-version.</p>'
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def render_factfirst_report(audit_output, lang="en", available_langs=None):
    """audit_output (incl. fact_base + decisions) → (html, meta). Deterministic;
    reuses stored interpretive prose. Returns ({}, ...) cost 0.0 (no new LLM)."""
    lang = lang if lang in UI else "en"
    t = UI[lang]
    ao = audit_output or {}
    fb = ao.get("fact_base") or {}
    dec = ao.get("decisions") or {}
    m = fb.get("meta") or {}
    domain = m.get("url") or ao.get("url") or "—"
    keyword = (((fb.get("target") or {}).get("primary_keyword") or {}).get("value")) or "—"
    market = (((fb.get("classification") or {}).get("locality") or {}).get("value")) or "—"
    date = (ao.get("audit_date") or ao.get("created_at") or "")[:10]

    secs = [
        ("§1", t["s1"], "s1", _s1(fb, dec, ao, lang)),
        ("§2", t["s2"], "s2", _s2(fb, ao, lang)),
        ("§3", t["s3"], "s3", _s3(fb, ao, lang)),
        ("§4", t["s4"], "s4", _s4(fb, ao, lang)),
        ("§5", t["s5"], "s5", _s5(fb, ao, lang)),
        ("§6", t["s6"], "s6", _s6(fb, ao, lang)),
        ("§7", t["s7"], "s7", _s7(fb, dec, lang)),
        ("§8", t["s8"], "s8", _s8(fb, ao, dec, lang)),
    ]
    body = ""
    for sid, title, anchor, html_in in secs:
        body += '<section id="%s"><h2>%s — %s</h2>%s</section>' % (anchor, sid, _esc(title), html_in)

    doc = ("<!doctype html><html lang=\"%s\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           "<title>%s — %s</title><style>%s</style></head><body><div class=\"wrap\">"
           "<div class=\"hdr\"><h1>%s</h1><div class=\"meta\">"
           "<span>%s: <b>%s</b></span><span>%s: <b>%s</b></span>"
           "<span>%s: <b>%s</b></span><span>%s: <b>%s</b></span></div></div>%s</div></body></html>") % (
        lang, _esc(t["title"]), _esc(domain), _CSS, _esc(t["title"]),
        t["domain"], _esc(domain), t["keyword"], _esc(keyword),
        t["market"], _esc(market), t["date"], _esc(date), body)

    return doc, {"cost_usd": 0.0, "lang": lang,
                 "sections": [s[0] for s in secs], "render_version": "factfirst_v1"}
