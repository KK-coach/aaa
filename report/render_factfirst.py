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


# AAA-195 FIX 2 — high-precision generic non-brand words. A resolved "brand"
# equal to one of these (e.g. matebalazs → "Weblap") is a mis-resolution, not a
# real brand → fall back to the registrable domain. Kept tiny so a real brand is
# never suppressed (MA "Marketing Astro" / TX "Taxually" are unaffected).
_GENERIC_BRANDS = frozenset({
    "weblap", "website", "webpage", "web", "honlap", "oldal", "home",
    "homepage", "site", "weboldal",
})


def _client_brand(ao):
    """AAA-195 FIX 2 — client brand for display: resolved brand, unless it's a
    generic non-brand word or empty → registrable domain (never 'Weblap')."""
    fb = ao.get("fact_base") or {}
    sp = ao.get("site_profile") or {}
    brand = sp.get("brand_name") or (fb.get("meta") or {}).get("brand") or sp.get("brand")
    if isinstance(brand, str) and brand.strip() and brand.strip().lower() not in _GENERIC_BRANDS:
        return brand
    return _host(ao.get("url")) or (brand if isinstance(brand, str) else "")


def _page_names(ao):
    """PAGE_N → display name: PAGE_1 = client brand / 'This page'; PAGE_2.. =
    the comparative competitors in order (brand / neutral)."""
    client = _client_brand(ao)  # AAA-195 FIX 2 — no generic "Weblap"
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
        "aio_none": "Nincs AI Overview erre a kulcsszóra (ellenőrizve)", "aio_none_short": "Nincs AI Overview",
        "serp_you": "(az Ön oldala)", "serp_comp": "(versenytárs)",
        "comp_unavail": "(nem volt elérhető a lekérdezés pillanatában%s)",
        "comp_usable": "%d kiválasztott versenytársból %d használható",
        "brand_unresolved": "(márka feloldatlan)",
        "ax_ai": "AI-láthatóság", "ax_page": "Saját oldal", "ax_tech": "Technikai egészség", "ax_eeat": "E-E-A-T",
        "st_weak": "Gyenge", "st_attn": "Odafigyelést igényel", "st_ok": "Rendben",
        "st_clean": "Tiszta", "cq_clean": "Tiszta — nincs helykitöltő",
        "cq_flag": "⚠ helykitöltő/befejezetlen tartalom", "cq_clean_why": "Nincs helykitöltő/befejezetlen tartalom",
        "fam_content": "Tartalom", "fam_seo": "On-site SEO", "fam_tech": "Technikai SEO", "fam_eeat": "E-E-A-T",
        "ee_band_pre": "E-E-A-T (saját oldal)",
        "ee_caveat": "a dimenzió-minta és a teendők a diagnosztikai jel, nem a pontos szám (a sáv render-szintű ±3 keret, nem mért szórás)",
        "ee_weak": "gyenge", "ee_moderate": "közepes", "ee_strong": "erős",
        "ee_fixes": "Teendők (hatás szerint)",
        "ee_twolens": "Ez a szakasz a saját oldalad profilját értékeli (oldal-intrinzik); a versenytárs-összevetés a §6-ban van, külön összehasonlító pontozással — két lencse, nem ellentmondás.",
        "ent_diff_title": "Entitás-különbség — a versenytárs említi, te nem",
        "ent_diff_none": "✓ Nincs mért megnevezett-szervezet különbség ezen a canaryn.",
        "rank": "Helyezés a mezőnyben", "client": "Ez az oldal", "total": "Összesen",
        "dim": "Dimenzió", "cwv_field": "Mező (CrUX p75)", "cwv_lab": "Labor (Lighthouse)",
        "t1": "Magas hatás", "t2": "Közepes hatás", "t3": "Finomítás",
        "r7_intro": "Hogyan olvasd: minden tétel egy konkrét, mért hiányhoz kötődik — többségük a bizalom, a tekintély vagy az AI-láthatóság körül van, nem a technikai mechanikáról szól. Az oldalon belüli javítások erősítik a minőség-/bizalom-jeleket, de nem garantálják a SERP-rangsort; az oldalon kívüli tényezők (linkek/domain-tekintély) nem tartoznak ide. Visszafordíthatatlan lépés előtt mentsd a munkád.",
        "rec_gap": "Mért hiány", "rec_src": "Forrás", "rec_improves": "Javítja", "rec_effort": "Ráfordítás", "rec_indic": "indikatív",
        "eff_low": "alacsony", "eff_medium": "közepes", "eff_high": "magas",
        "ee_see7": "A teljes, egységes teendőlista a §7-ben található.",
        "fresh_source": "Forrás", "fresh_when": "Mikor rögzült", "fresh_state": "Frissesség",
        "prov_summary": "Adat-provenance összegzés", "word_count": "Szószám", "page_weight": "Oldalsúly",
        "verdict": "Verdikt", "see_s6": "A dimenzió-szintű összevetést lásd a §6-ban.",
        "in_run": "audit-futás", "crux_window": "28 napos ablak",
        "fan_cov": "Fan-out lefedettség", "schema_jsonld": "Séma (JSON-LD)",
        "landmarks": "Landmarkok", "altcov": "Alt-lefedettség", "labelcov": "Űrlap-címke lefedettség",
        "headings": "Címsorok (H1 / összes / ugrás)", "indexed": "Indexelt", "perf": "Teljesítmény (mobil/asztali)",
        " contentqa": "Tartalom-QA jelzés",
        "lm_missing": "hiányzik", "schema_fit": "Séma-illeszkedés",
        "mr_struct_ok": "✓ Tiszta szerkezet — nincs div-túltengés vagy strukturális zaj; a címsorok a fő tartalomban összpontosulnak.",
        "mr_struct_warn": "⚠ Strukturális zaj észlelve (mély div-beágyazás) — nehezíti a gépi feldolgozást.",
        "mr_emph_ok": " A szövegkiemelés szemantikus (strong/em).",
        "mr_native_ok": "✓ Az interaktív elemek natív HTML-szemantikát használnak — nincs div-onclick antiminta.",
        "mr_native_warn": "⚠ div-onclick antiminta — kattintható div-ek natív gomb/link helyett.",
        "mr_lists_ok": "✓ Valódi listaszerkezet (ul/ol) jelen van.",
        "mr_fig_warn": " A képblokkok egy részének nincs figcaption-je.",
        "mr_schema_ok": "✓ A strukturált adat illeszkedik az oldaltípushoz.",
        "mr_schema_action": " SearchAction jelen van.",
        "mr_submit_generic": "A küldő/CTA gombok általános feliratot használnak — a leíró feliratok javítják az érthetőséget.",
        "cwv_lab_desktop": "Labor (asztali)", "cwv_support": "Kiegészítő metrikák",
        "cwv_ttfb": "TTFB (mező)", "cwv_tbt": "TBT (labor m/a)", "cwv_si": "Speed Index (labor m/a)",
        "cq_hard": "durva találatok", "cq_names": "név-helykitöltők", "cq_cats": "kategóriák",
        "canonical": "Canonical", "canon_ok": "✓ önhivatkozó (nincs eltérés)", "canon_bad": "⚠ canonical-eltérés",
        "ctx_pagetype": "Oldaltípus", "ctx_audience": "Közönség",
        "cg_cites": "ChatGPT által idézett források", "fan_detail": "Lekérdezésenként",
        "fan_covered": "lefedve", "fan_missing": "hiányzik",
        "aic_title": "AI-crawler láthatóság",
        "aic_clean": "✓ A tartalmad teljesen látható az AI/Google crawlerek számára, az indexelési kereten belül.",
        "aic_csr": "⚠ A tartalom egy része JavaScripttel renderelődik — az AI-crawlerek nem biztos, hogy látják.",
        "aic_2mb": "⚠ A HTML meghaladja a ~2 MB-os indexelési limitet; a tartalom %s%%-a a levágási pont után van — kimaradhat az indexből.",
        "ev_title": "E-E-A-T bizonyíték",
        "ev_people": "Megnevezett szakértők / szerzők",
        "ev_people_none": "⚠ Nincs megnevezett szerző/szakértő — gyengíti a Tapasztalat és a Tekintély dimenziót.",
        "ev_org": "Szervezet (tulajdonos)",
        "ev_org_none": "⚠ Nincs egyértelmű tulajdonos-szervezet azonosítva — gyengébb entitás-tekintély.",
        "ev_kg_none": "⚠ Nem található a Knowledge Graphban — gyengébb entitás-tekintély.",
        "ev_kg_ok": "Knowledge Graph által megerősítve",
        "ev_entities": "Tekintély-entitások",
        "ev_orgs": "Szervezetek", "ev_products": "Termékek / szolgáltatások", "ev_tech": "Technológiák",
        "tm_title": "Cím hossza (SERP)", "tm_kw": "Kulcsszó a címben", "tm_dup": "Cím ↔ H1",
        "kw_map": "Kulcsszó-térkép — mit céloz az oldal", "kw_kw": "Kulcsszó", "kw_type": "Típus",
        "kw_rel": "Relevancia", "kw_intent": "Szándék",
        "kw_demand": "Valós keresési kereslet — mérhető keresési volumenű kulcsszavak",
        "kw_vol": "Havi keresés", "kw_trend": "12 hó trend", "kw_cpc": "CPC",
        "kw_topic": "Témakör", "kw_branded": "Márkázott elsődleges kulcsszó",
        "kw_intentmix": "Szándék-összetétel", "kw_primary": "elsődleges",
        "rb_high": "magas", "rb_med": "közepes", "rb_low": "alacsony",
        "tail_short": "rövid", "tail_mid": "közepes", "tail_long": "long-tail", "yes": "igen", "no": "nem",
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
        "aio_none": "No AI Overview appears for this keyword (checked)", "aio_none_short": "No AI Overview",
        "serp_you": "(your site)", "serp_comp": "(competitor)",
        "comp_unavail": "(not available at the moment of the query%s)",
        "comp_usable": "%d of %d selected competitors usable",
        "brand_unresolved": "(brand unresolved)",
        "ax_ai": "AI visibility", "ax_page": "Your page", "ax_tech": "Technical health", "ax_eeat": "E-E-A-T",
        "st_weak": "Weak", "st_attn": "Needs attention", "st_ok": "OK",
        "st_clean": "Clean", "cq_clean": "Clean — no placeholder",
        "cq_flag": "⚠ placeholder/unfinished content", "cq_clean_why": "No placeholder/unfinished content",
        "fam_content": "Content", "fam_seo": "On-site SEO", "fam_tech": "Technical SEO", "fam_eeat": "E-E-A-T",
        "ee_band_pre": "E-E-A-T (your page)",
        "ee_caveat": "the dimension pattern + fixes are the diagnostic signal, not the exact number (the band is a render-level ±3 bracket, not a measured spread)",
        "ee_weak": "weak", "ee_moderate": "moderate", "ee_strong": "strong",
        "ee_fixes": "Fixes (by impact)",
        "ee_twolens": "This section reads your own page's profile (page-intrinsic); the competitor comparison is in §6, with a separate comparative scoring — two lenses, not a contradiction.",
        "ent_diff_title": "Entity gap — competitor cites, you don't",
        "ent_diff_none": "✓ No measured named-organization gap on this canary.",
        "rank": "Rank in the field", "client": "This page", "total": "Total",
        "dim": "Dimension", "cwv_field": "Field (CrUX p75)", "cwv_lab": "Lab (Lighthouse)",
        "t1": "High impact", "t2": "Medium impact", "t3": "Refinement",
        "r7_intro": "How to read: each item targets a concrete measured gap — most are about trust, authority, or AI-visibility, not technical mechanics. On-page fixes strengthen quality/trust signals but do not guarantee SERP ranking; off-page factors (backlinks/domain authority) are out of scope. Save your work before any irreversible step.",
        "rec_gap": "Measured gap", "rec_src": "Source", "rec_improves": "Improves", "rec_effort": "Effort", "rec_indic": "indicative",
        "eff_low": "low", "eff_medium": "medium", "eff_high": "high",
        "ee_see7": "The full, unified action list is in §7.",
        "fresh_source": "Source", "fresh_when": "Captured", "fresh_state": "Freshness",
        "prov_summary": "Data-provenance summary", "word_count": "Word count", "page_weight": "Page weight",
        "verdict": "Verdict", "see_s6": "See §6 for the per-dimension comparison.",
        "in_run": "in-run", "crux_window": "28-day window",
        "fan_cov": "Fan-out coverage", "schema_jsonld": "Schema (JSON-LD)",
        "landmarks": "Landmarks", "altcov": "Alt coverage", "labelcov": "Form-label coverage",
        "headings": "Headings (H1 / total / skips)", "indexed": "Indexed", "perf": "Performance (mobile/desktop)",
        " contentqa": "Content-QA flag",
        "lm_missing": "missing", "schema_fit": "Schema fit",
        "mr_struct_ok": "✓ Clean structure — no div-soup or structural noise; headings concentrate in the main content.",
        "mr_struct_warn": "⚠ Structural noise detected (deep div nesting) — harder for machines to parse.",
        "mr_emph_ok": " Text emphasis is semantic (strong/em).",
        "mr_native_ok": "✓ Interactive elements use native HTML semantics — no div-onclick antipattern.",
        "mr_native_warn": "⚠ div-onclick antipattern — clickable divs instead of native buttons/links.",
        "mr_lists_ok": "✓ Real list structure (ul/ol) is present.",
        "mr_fig_warn": " Some figures lack a figcaption.",
        "mr_schema_ok": "✓ Structured data matches the page type.",
        "mr_schema_action": " SearchAction present.",
        "mr_submit_generic": "Submit/CTA buttons use generic labels — descriptive labels improve clarity.",
        "cwv_lab_desktop": "Lab (desktop)", "cwv_support": "Supporting metrics",
        "cwv_ttfb": "TTFB (field)", "cwv_tbt": "TBT (lab m/d)", "cwv_si": "Speed Index (lab m/d)",
        "cq_hard": "hard hits", "cq_names": "name hits", "cq_cats": "categories",
        "canonical": "Canonical", "canon_ok": "✓ self-referencing (no mismatch)", "canon_bad": "⚠ canonical mismatch",
        "ctx_pagetype": "Page type", "ctx_audience": "Audience",
        "cg_cites": "Sources ChatGPT cited", "fan_detail": "Per query",
        "fan_covered": "covered", "fan_missing": "missing",
        "aic_title": "AI-crawler visibility",
        "aic_clean": "✓ Your content is fully visible to AI/Google crawlers, within the index budget.",
        "aic_csr": "⚠ Part of the content is JS-rendered — AI crawlers may not see it.",
        "aic_2mb": "⚠ The HTML exceeds the ~2MB index limit; %s%% of the content is past the cutoff — it may be dropped from the index.",
        "ev_title": "E-E-A-T evidence",
        "ev_people": "Named people",
        "ev_people_none": "⚠ No named author/expert found — weakens Experience & Authoritativeness.",
        "ev_org": "Organization (owner)",
        "ev_org_none": "⚠ No clear owner organization identified — weaker entity authority.",
        "ev_kg_none": "⚠ Not found in the Knowledge Graph — weaker entity authority.",
        "ev_kg_ok": "Knowledge Graph confirmed",
        "ev_entities": "Authority entities",
        "ev_orgs": "Organizations", "ev_products": "Products / services", "ev_tech": "Technologies",
        "tm_title": "Title length (SERP)", "tm_kw": "Keyword in title", "tm_dup": "Title vs H1",
        "kw_map": "Keyword map — what the page targets", "kw_kw": "Keyword", "kw_type": "Type",
        "kw_rel": "Relevance", "kw_intent": "Intent",
        "kw_demand": "Real search demand — keywords with measurable search volume",
        "kw_vol": "Monthly searches", "kw_trend": "12-mo trend", "kw_cpc": "CPC",
        "kw_topic": "Topic", "kw_branded": "Branded primary keyword",
        "kw_intentmix": "Intent mix", "kw_primary": "primary",
        "rb_high": "high", "rb_med": "medium", "rb_low": "low",
        "tail_short": "short", "tail_mid": "mid", "tail_long": "long-tail", "yes": "yes", "no": "no",
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


def _host(url):
    """AAA-194 — normalize a URL to a comparable host: strip scheme/www/path,
    lowercase. '' for non-strings so it never falsely matches."""
    if not isinstance(url, str) or not url.strip():
        return ""
    h = _re.sub(r"^https?://", "", url.strip().lower()).split("/")[0]
    return h[4:] if h.startswith("www.") else h


def _chip(layer, lang):
    c = _LAYER_CHIP.get(layer)
    if not c:
        return ""
    cls, lbl = c
    return '<span class="tag %s">%s</span>' % (cls, lbl[lang])


def _nd(lang):
    return '<span class="ph">%s</span>' % UI[lang]["nd"]


def _fv(fact, lang, fmt=None, absent_label=None):
    """AAA-182 field-aware three-state render:
      measured     -> value (+ layer chip)
      absent        -> `absent_label` (+ chip) if the field gives one
                       (e.g. content_qa absent = "Clean"); else a neutral "—"
                       — NEVER "not measured" (it WAS measured, value just absent).
      not_measured  -> "not measured" (never assessed).
    """
    if not _is_fact(fact):
        return _nd(lang)
    prov, val = fact.get("provenance"), fact.get("value")
    if prov == "not_measured":
        return _nd(lang)
    if prov == "absent":
        if absent_label:
            return "%s %s" % (_esc(absent_label), _chip(fact.get("layer"), lang))
        return '<span class="ph">—</span>'
    if val is None:  # measured-but-null guard
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


def _aio_render_state(av):
    """AAA-194 — unified Google AI Overview render state from the grounded SERP
    facts: 'cited' (client in AIO) / 'excluded' (AIO present, client not cited) /
    'none_checked' (SERP checked, NO AIO present → measured-absent, AAA-182) /
    'not_measured' (never checked)."""
    cs = av.get("ai_overview_client_status") or {}
    tr = av.get("ai_overview_triggered") or {}
    if _is_fact(cs) and cs.get("provenance") == "measured" and cs.get("value"):
        return "cited"
    if _is_fact(cs) and cs.get("provenance") == "absent":
        return "excluded"
    if _is_fact(tr) and tr.get("provenance") == "absent":
        return "none_checked"
    return "not_measured"


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
    # AAA-194 — grounded AIO state: cited / excluded / none_checked / not_measured.
    aio_state = _aio_render_state(av)
    if aio_state == "excluded":
        ai = ("st-bad", t["st_weak"], (t["excluded"] + " — AI Overview" if lang == "en"
              else "Kihagyva az AI Overview-ból"), "mért")
    elif aio_state == "cited":
        ai = ("st-ok", t["st_ok"], t["cited"], "mért")
    elif aio_state == "none_checked":  # AIO checked, none present → measured-absent (neutral)
        ai = ("st-ok", t["aio_none_short"], t["aio_none"], "mért")
    else:
        ai = ("st-warn", t["st_attn"], t["nd"], "mért")
    # AAA-182 — three-state, field-aware: measured-True=placeholder (bad);
    # absent=detector ran, page CLEAN (ok); not_measured=never ran (warn, NOT "OK").
    cq = ((fb.get("onpage") or {}).get("content_qa") or {}).get("page_flag") or {}
    cq_prov = cq.get("provenance")
    if cq.get("value") is True and cq_prov == "measured":
        page = ("st-bad", t["st_weak"], ("Befejezetlen/helykitöltő tartalom az oldalon"
                if lang == "hu" else "Unfinished / placeholder content on the page"), "mért")
    elif cq_prov == "absent":
        page = ("st-ok", t["st_clean"], t["cq_clean_why"], "mért")
    else:  # not_measured / missing — never assert "OK"
        page = ("st-warn", t["st_attn"], t["nd"], "mért")
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
    # AAA-190 (#8) — neutral page-type · audience context (descriptive, no
    # polarity — magnitude ≠ polarity, AAA-189).
    cl = fb.get("classification") or {}
    ctx_bits = []
    for key, lbl in (("page_type", "ctx_pagetype"), ("audience_primary", "ctx_audience")):
        v = (cl.get(key) or {}).get("value")
        if v:
            ctx_bits.append("%s: <b>%s</b>" % (t[lbl], _esc(v)))
    ctx = ('<div class="note">%s %s</div>' % (" &nbsp;·&nbsp; ".join(ctx_bits), _chip("mért", lang))
           if ctx_bits else "")
    return hook + ctx + '<div class="grid">%s</div>' % grid


_TAIL = {"shorttail": "tail_short", "midtail": "tail_mid", "longtail": "tail_long"}


def _rel_band(score, t):
    if not isinstance(score, (int, float)):
        return "—"
    return t["rb_high"] if score >= 0.85 else (t["rb_med"] if score >= 0.7 else t["rb_low"])


def _trend_arrow(tr):
    """trend_12m is newest-first {month,year,search_volume}; newest vs oldest."""
    vals = [x.get("search_volume") for x in (tr or [])
            if isinstance(x, dict) and isinstance(x.get("search_volume"), (int, float))]
    if len(vals) < 2:
        return "→"
    new, old = vals[0], vals[-1]
    if new > old * 1.15:
        return "↑"
    if new < old * 0.85:
        return "↓"
    return "→"


def _s2_keyword_blocks(fb, lang):
    """AAA-186 — §2 blocks A (keyword map) / B (real demand, volume-bearing only)
    / C (topic + aggregate intent). Provenance-aware; B omits if zero volume."""
    t, hu = UI[lang], (lang == "hu")
    tg = fb.get("target") or {}
    kc = tg.get("keywords_classified") or {}
    items = kc.get("value") if (_is_fact(kc) and kc.get("provenance") == "measured") else None
    out = ""

    # ---- (A) keyword map ----
    if items:
        out += _subsec("", t["kw_map"]) + (
            '<table><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>' % (
                t["kw_kw"], t["kw_type"], t["kw_rel"], t["kw_intent"]))
        for i, k in enumerate(items):
            tail = k.get("tail_type")
            typ = t["kw_primary"] if (k.get("relevance_score") == 1.0 or i == 0) else (
                t.get(_TAIL.get(tail, ""), tail or "—"))
            band = _rel_band(k.get("relevance_score"), t)
            l1 = k.get("search_intent") or "—"
            l2 = k.get("search_intent_l2")
            intent = "%s%s" % (_esc(l1), (" · %s" % _esc(l2) if l2 else ""))
            out += "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                _esc(k.get("keyword")), _esc(typ), _esc(band), intent)
        out += "</table>"
        out += '<p class="small">%s %s · %s %s</p>' % (
            ("Relevancia: sávként" if hu else "Relevance: shown as a band"), _chip("következtetés", lang),
            ("szándék: legjobb tipp" if hu else "intent: best-effort"), _chip("AI-értelmezés", lang))

    # ---- (B) real search demand — ONLY volume-bearing; omit block if none ----
    vb = [k for k in (items or []) if k.get("search_volume_monthly") is not None]
    if vb:
        out += _subsec("", t["kw_demand"]) + (
            '<table><tr><th>%s</th><th class="num">%s</th><th>%s</th><th class="num">%s</th></tr>' % (
                t["kw_kw"], t["kw_vol"], t["kw_trend"], t["kw_cpc"]))
        for k in sorted(vb, key=lambda x: -(x.get("search_volume_monthly") or 0)):
            cpc = k.get("cpc_usd")
            out += "<tr><td>%s</td><td class='num'>%s</td><td>%s</td><td class='num'>%s</td></tr>" % (
                _esc(k.get("keyword")), _esc(k.get("search_volume_monthly")),
                _trend_arrow(k.get("trend_12m")),
                ("$%.2f" % cpc) if isinstance(cpc, (int, float)) else "—")
        out += "</table>"
        out += '<p class="small">%s %s</p>' % (
            ("Forrás: DataForSEO (becsült keresési volumen)" if hu
             else "Source: DataForSEO (estimated search volume)"), _chip("becslés", lang))

    # ---- (C) topic + aggregate intent (1-2 lines, hedged) ----
    tc = (tg.get("topic_cluster") or {}).get("value")
    isb = (tg.get("is_branded") or {}).get("value")
    # aggregate intent from the L1 distribution across classified items
    bits = []
    if tc:
        bits.append("%s: <b>%s</b>" % (t["kw_topic"], _esc(tc)))
    if isb is not None:
        bits.append("%s: <b>%s</b>" % (t["kw_branded"], t["yes"] if isb else t["no"]))
    if items:
        from collections import Counter
        c = Counter((k.get("search_intent") or "").lower() for k in items if k.get("search_intent"))
        if c:
            ranked = [x for x, _ in c.most_common()]
            dom = ranked[0]
            rest = ranked[1:3]
            mix = ("elsősorban %s" % dom if hu else "primarily %s" % dom)
            if rest:
                mix += (", %s elemekkel" % "/".join(rest) if hu else ", with %s elements" % "/".join(rest))
            bits.append("%s: <b>%s</b> %s" % (t["kw_intentmix"], _esc(mix), _chip("AI-értelmezés", lang)))
    if bits:
        out += '<div class="note">%s</div>' % (" &nbsp;·&nbsp; ".join(bits))
    return out


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
    out += _s2_keyword_blocks(fb, lang)  # AAA-186: keyword map / real demand / topic+intent
    serp = _dig(fb, "competition", "primary_keyword_serp", "top10")
    if _is_fact(serp) and serp.get("provenance") == "measured":
        # AAA-194 — mark the client row + selected-competitor rows (domain-level
        # match so path differences don't break it). Render-only; the selected
        # set is unchanged (that's AAA-195).
        client_host = _host(ao.get("url"))
        comp_hosts = {}  # host -> resolved brand (if any)
        for c in ((fb.get("competition") or {}).get("competitors") or []):
            ch = _host((c.get("url") or {}).get("value") if isinstance(c.get("url"), dict) else c.get("url"))
            if ch:
                comp_hosts[ch] = (c.get("brand") or {}).get("value")
        out += "<div class='subsec'><span class='n'>SERP %s</span></div><table><tr><th>#</th><th>URL</th></tr>" % _chip("mért", lang)
        for r in (serp.get("value") or [])[:10]:
            host = _host(r.get("url"))
            mark = ""
            if client_host and host == client_host:
                mark = ' <b class="serpmark">%s</b>' % t["serp_you"]
            elif host in comp_hosts:
                brand = comp_hosts[host]
                mark = ' <b class="serpmark">%s</b>' % (
                    ("(%s)" % _esc(brand)) if brand else t["serp_comp"])
            out += "<tr><td class='num'>%s</td><td>%s%s</td></tr>" % (
                _esc(r.get("position")), _esc(r.get("url")), mark)
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

    # AAA-194 — checked-but-no-AIO → measured-absent line (not "not measured").
    if _aio_render_state(av) == "none_checked":
        aio_cell = '<span class="st st-ok">%s</span> %s' % (t["aio_none"], _chip("mért", lang))
    else:
        aio_cell = _cite_cell(av.get("ai_overview_client_status"), excluded_label=t["excluded"])
    out += "<tr><td>Google AI Overview</td><td>%s</td></tr>" % aio_cell
    out += "<tr><td>ChatGPT</td><td>%s</td></tr>" % _cite_cell(av.get("chatgpt_target_cited"))
    out += "</table>"
    # AAA-190 (#6) — ChatGPT citation list (the sources it cited instead).
    # AIO brand+URL list is DEFERRED to AAA-168 (reliability gated); not rendered.
    cg = av.get("chatgpt_citations")
    if _is_fact(cg) and cg.get("provenance") == "measured" and cg.get("value"):
        from urllib.parse import urlparse
        rows_cg = ""
        for c in cg["value"]:
            if not isinstance(c, dict) or c.get("is_target_site"):
                continue
            url = c.get("url") or ""
            dom = urlparse(url).netloc.replace("www.", "")
            title = c.get("title") or dom
            rows_cg += '<li>%s <span class="ph">%s</span></li>' % (_esc(title), _esc(dom))
        if rows_cg:
            out += '<div class="subsec"><span class="n">%s</span> %s</div><ul>%s</ul>' % (
                t["cg_cites"], _chip("mért", lang), rows_cg)
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
    # fan-out coverage aggregate (kept) + AAA-190 (#6) per-query detail.
    fo = av.get("fan_out_enriched")
    if _is_fact(fo) and fo.get("value"):
        items = [x for x in fo.get("value") if isinstance(x, dict)]
        cov = sum(1 for x in items if x.get("coverage") == "covered")
        out += '<p>%s: <b>%d / %d</b> %s</p>' % (t["fan_cov"], cov, len(items), _chip("AI-értelmezés", lang))
        if items:
            hdr_q = "Lekérdezés" if lang == "hu" else "Query"
            hdr_v = "Variáns" if lang == "hu" else "Variant"
            hdr_c = "Lefedettség" if lang == "hu" else "Coverage"
            out += ('<div class="subsec"><span class="n">%s</span> %s</div>'
                    '<table><tr><th>%s</th><th>%s</th><th>%s</th></tr>'
                    % (t["fan_detail"], _chip("AI-értelmezés", lang), hdr_q, hdr_v, hdr_c))
            for x in items:
                cvg = x.get("coverage")
                lbl = t["fan_covered"] if cvg == "covered" else (
                    t["fan_missing"] if cvg == "missing" else (cvg or "—"))
                cls = "st-ok" if cvg == "covered" else ("st-warn" if cvg == "missing" else "")
                cell = ('<span class="st %s">%s</span>' % (cls, _esc(lbl))) if cls else _esc(lbl)
                out += "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                    _esc(x.get("query") or "—"), _esc(x.get("variant_type") or "—"), cell)
            out += "</table>"
    return out


def _subsec(n, title):
    return '<div class="subsec"><span class="n">%s</span> <b style="font-family:var(--serif)">%s</b></div>' % (_esc(n), _esc(title))


_CWV_RATE = {"good": "st-ok", "needs_improvement": "st-warn", "poor": "st-bad"}


def _cwv_span(node, sub, lang):
    """A single rating-colored CWV metric span (AAA-190). None if not measured."""
    node = node or {}
    v = node.get(sub)
    if not isinstance(v, (int, float)):
        return None
    cls = _CWV_RATE.get(node.get("rating"), "")
    disp = ("%d ms" % int(v)) if sub == "value_ms" else ("%.3f" % v)
    return ('<span class="st %s">%s</span>' % (cls, disp)) if cls else disp


def _cwv_view(ao, lang, surface, key, label):
    """AAA-190 — one CWV view row. Columns LCP · INP · CLS · FCP. INP is field-
    only (lab has no INP — TBT is the lab proxy, shown in the supporting line).
    Polarity = PSI rating chips (canonical thresholds); no raw-ms verdict."""
    b = _dig(ao, "pagespeed", surface, key) or {}
    def cell(metric, sub):
        s = _cwv_span(b.get(metric), sub, lang)
        return '<td class="num">%s</td>' % (
            s if s is not None else '<span class="ph">%s</span>' % UI[lang]["nd"])
    return ("<tr><td>%s %s</td>%s%s%s%s</tr>" % (
        _esc(label), _chip("mért", lang), cell("lcp", "value_ms"),
        cell("inp", "value_ms"), cell("cls", "value"), cell("fcp", "value_ms")))


def _cwv_support(ao, lang):
    """AAA-190 — compact supporting-metrics line: field TTFB; lab TBT / Speed-
    Index (mobile / desktop). Client-only (competitor CWV stays AAA-139)."""
    t = UI[lang]
    fm = _dig(ao, "pagespeed", "mobile", "core_web_vitals_field") or {}
    lm = _dig(ao, "pagespeed", "mobile", "core_web_vitals_lab") or {}
    ld = _dig(ao, "pagespeed", "desktop", "core_web_vitals_lab") or {}
    bits = []
    ttfb = _cwv_span(fm.get("ttfb"), "value_ms", lang)
    if ttfb:
        bits.append("<b>%s</b> %s" % (t["cwv_ttfb"], ttfb))
    for label, metric in (("cwv_tbt", "tbt"), ("cwv_si", "speed_index")):
        m = _cwv_span(lm.get(metric), "value_ms", lang)
        d = _cwv_span(ld.get(metric), "value_ms", lang)
        if m or d:
            bits.append("<b>%s</b> %s / %s" % (t[label], m or "—", d or "—"))
    if not bits:
        return ""
    return '<div class="note"><b>%s:</b> %s %s</div>' % (
        t["cwv_support"], " &nbsp;·&nbsp; ".join(bits), _chip("mért", lang))


def _title_meta_rows(tm, lang):
    """AAA-185 — three customer-facing title/meta rows (AAA-158 signals),
    provenance-aware (AAA-182): measured → verdict/value; absent → field-aware
    finding/clean; not_measured → 'not measured'."""
    t = UI[lang]
    hu = (lang == "hu")
    rows = []

    # 1) title length / SERP truncation
    tv = tm.get("title_verdict") or {}
    px = (tm.get("title_pixel") or {}).get("value")
    lim = (tm.get("title_limit_px") or {}).get("value") or 600
    pxs = ("%d / %d px" % (int(px), int(lim))) if isinstance(px, (int, float)) else ""
    if _is_fact(tv) and tv.get("provenance") == "measured":
        v = tv.get("value")
        if v == "truncated":
            txt = ("⚠ A cím levágódik a Google találatban" if hu
                   else "⚠ Title is truncated in Google results")
        elif v == "borderline":
            txt = ("Határeset — a cím a levágás közelében" if hu
                   else "Borderline — near the truncation limit")
        else:
            txt = ("Megfelelő hosszúság" if hu else "Good length")
        # pixel width is a font-table estimate → becslés/estimate chip.
        rows.append((t["tm_title"], "%s%s %s" % (
            _esc(txt), (" (%s)" % pxs if pxs else ""), _chip("becslés", lang))))
    else:
        rows.append((t["tm_title"], _nd(lang)))

    # 2) keyword in title — deterministic substring check (mért). measured(True)=
    # present(good); absent(False)=keyword missing (a finding); else not_measured.
    kit = tm.get("keyword_in_title")
    if _is_fact(kit) and kit.get("provenance") == "measured":
        kw = ("✓ A kulcsszó szerepel a címben" if hu
              else "✓ Your keyword appears in the title")
        rows.append((t["tm_kw"], "%s %s" % (_esc(kw), _chip("mért", lang))))
    elif _is_fact(kit) and kit.get("provenance") == "absent":
        kw = ("⚠ A kulcsszó hiányzik a címből" if hu
              else "⚠ Keyword missing from the title")
        rows.append((t["tm_kw"], "%s %s" % (_esc(kw), _chip("mért", lang))))
    else:
        rows.append((t["tm_kw"], _nd(lang)))

    # 3) title ↔ H1 duplication — deterministic token overlap (mért)
    dup = tm.get("title_h1_dup") or {}
    if _is_fact(dup) and dup.get("provenance") == "measured":
        d = dup.get("value") or {}
        ov = d.get("token_overlap")
        ovs = (" (%d%% %s)" % (round(100 * ov), "átfedés" if hu else "overlap")) if isinstance(ov, (int, float)) else ""
        if d.get("exact_duplicate"):
            txt = ("⚠ A cím és a H1 azonos — érdemes megkülönböztetni" if hu
                   else "⚠ Title and H1 are identical — differentiate them")
        elif d.get("near_duplicate"):
            txt = ("Közel azonos a cím és a H1" if hu else "Title and H1 are near-duplicates")
        else:
            txt = ("A cím és a H1 eltér" if hu else "Title and H1 differ")
        rows.append((t["tm_dup"], "%s%s %s" % (_esc(txt), _esc(ovs), _chip("mért", lang))))
    else:
        rows.append((t["tm_dup"], _nd(lang)))
    return rows


def _landmarks_fmt(present, missing_fact, lang):
    """AAA-189 — show present landmarks AND the missing ones (was present-only)."""
    t = UI[lang]
    s = ", ".join(_esc(x) for x in present) if isinstance(present, list) else _esc(present)
    mv = missing_fact.get("value") if _is_fact(missing_fact) else None
    if isinstance(mv, list) and mv:
        s += ' &nbsp;·&nbsp; <span class="ph">%s: %s</span>' % (
            t["lm_missing"], ", ".join(_esc(x) for x in mv))
    return s


def _s43_verdicts(op, lang):
    """AAA-189 — §4.3 machine-readability cluster verdicts (B+C: curated rows +
    folded verdicts). measured-clean = positive (AAA-187); per-verdict chip, not
    blanket (AAA-185). ARIA stays neutral (no coverage verdict — native elements
    need no ARIA); link_semantic deferred to AAA-156 (not CMP-excluded). Heading-
    stacking is narrated in §4.2 — NOT restated here (single consistent statement)."""
    t = UI[lang]
    st = op.get("structure") or {}
    sch = op.get("schema") or {}
    forms = op.get("forms") or {}

    def _m(f):
        return _is_fact(f) and f.get("provenance") == "measured"

    def _v(f):
        return f.get("value") if _is_fact(f) else None

    notes = []  # (st-class, message, chip-layer)

    # 1) Structural cleanliness — structural_noise (deterministic) + semantic-to-
    #    visual emphasis ratio (estimate). headings_by_zone folds in implicitly.
    noise = st.get("structural_noise_warning")
    if _m(noise):
        if _v(noise):
            notes.append(("st-warn", t["mr_struct_warn"], "mért"))
        else:
            msg = t["mr_struct_ok"]
            ratio = st.get("semantic_to_visual_ratio")
            if _m(ratio) and isinstance(_v(ratio), (int, float)) and _v(ratio) >= 0.999:
                msg += t["mr_emph_ok"]
            notes.append(("st-ok", msg, "mért"))

    # 2) Native semantics — div-onclick antipattern (the real a11y signal, not
    #    ARIA count). Boolean negative → measured False → positive.
    anti = st.get("div_onclick_antipattern")
    if _m(anti):
        notes.append(("st-warn", t["mr_native_warn"], "mért") if _v(anti)
                      else ("st-ok", t["mr_native_ok"], "mért"))

    # 3) Lists & media — real lists (positive); figures without figcaption (minor).
    ls = _v(st.get("list_structure"))
    if isinstance(ls, dict) and ((ls.get("ul") or 0) + (ls.get("ol") or 0)) > 0:
        notes.append(("st-ok", t["mr_lists_ok"], "mért"))
    fig, figc = st.get("figure_count"), st.get("figure_with_figcaption")
    if _m(fig) and isinstance(_v(fig), int) and _v(fig) > 0 and (_v(figc) or 0) < _v(fig):
        notes.append(("st-warn", t["mr_fig_warn"].strip(), "mért"))

    # 4) Structured-data fit — pagetype match + schema actions.
    pm = sch.get("pagetype_match")
    if _m(pm) and _v(pm):
        msg = t["mr_schema_ok"]
        acts = _v(sch.get("actions"))
        if isinstance(acts, list) and acts:
            msg += t["mr_schema_action"]
        notes.append(("st-ok", msg, "mért"))

    # 5) Forms submit-quality — verdict-only, qualitative (no raw count; submit
    #    counter is NOT CMP-excluded). Surface only when ALL submits are generic.
    sb, sg = forms.get("submit_button_count"), forms.get("submit_button_generic_count")
    if _m(sb) and _m(sg) and isinstance(_v(sb), int) and _v(sb) > 0 and (_v(sg) or 0) >= _v(sb):
        notes.append(("st-warn", t["mr_submit_generic"], "mért"))

    return "".join(
        '<div class="note"><span class="st %s">%s</span> %s</div>'
        % (cls, _esc(msg), _chip(chip, lang)) for cls, msg, chip in notes)


def _canonical_cell(tech, lang):
    """AAA-190 (#8) — canonical verdict: self-referencing + no mismatch → positive
    (AAA-187); mismatch → weakness (AAA-188). not_measured → 'not measured'."""
    t = UI[lang]
    mm = tech.get("canonical_mismatch") or {}
    if not (_is_fact(mm) and mm.get("provenance") == "measured"):
        return _nd(lang)
    if mm.get("value"):  # mismatch → weakness, show the divergent target
        val = (tech.get("canonical_value") or {}).get("value")
        extra = (" → %s" % _esc(val)) if val else ""
        return '<span class="st st-bad">%s</span>%s %s' % (t["canon_bad"], extra, _chip("mért", lang))
    return '<span class="st st-ok">%s</span> %s' % (t["canon_ok"], _chip("mért", lang))


def _content_qa_breakdown(cq, lang):
    """AAA-190 (#8) — when content-QA is FLAGGED, render tiered counts + per-
    category breakdown. Tier counts are the measured facts (hard/name); the
    category dict is raw detail. NO conflated headline that doesn't sum
    (decision 3). Clean/not_measured → '' (the §4.1 page_flag row carries it)."""
    t = UI[lang]
    pf = cq.get("page_flag") or {}
    if not (_is_fact(pf) and pf.get("provenance") == "measured" and pf.get("value")):
        return ""
    bits = []
    for key, lbl in (("hard_hit_count", "cq_hard"), ("name_hit_count", "cq_names")):
        f = cq.get(key) or {}
        if _is_fact(f) and f.get("provenance") == "measured":
            bits.append("<b>%s</b> %s" % (t[lbl], _esc(f.get("value"))))
    cats = cq.get("categories") or {}
    cat_val = cats.get("value") if _is_fact(cats) else None
    cat_part = ""
    if isinstance(cat_val, dict) and cat_val:
        cat_str = ", ".join("%s %s" % (_esc(k), _esc(v)) for k, v in cat_val.items())
        cat_part = " &nbsp;·&nbsp; <b>%s:</b> %s" % (t["cq_cats"], cat_str)
    return '<div class="note"><span class="st st-bad">%s</span> %s%s %s</div>' % (
        t["cq_flag"], " &nbsp;·&nbsp; ".join(bits), cat_part, _chip("mért", lang))


def _s4(fb, ao, lang):
    t = UI[lang]
    op = fb.get("onpage") or {}
    tech = fb.get("technical") or {}
    words = _dig(ao, "crawl", "main_content", "words")
    cq = op.get("content_qa") or {}
    out = _subsec("4.1", "Tartalmi profil" if lang == "hu" else "Content profile")
    out += "<table>"
    out += "<tr><th>%s</th><td>%s</td></tr>" % (t["word_count"], _fv(_raw(words, "mért"), lang))
    # AAA-182 — three-state: measured-True → flag; absent → "Clean" (ran, no
    # placeholder); not_measured → "not measured". Agrees with §1.
    out += "<tr><th>%s</th><td>%s</td></tr>" % (t[" contentqa"], _fv(
        cq.get("page_flag"), lang, fmt=lambda v: t["cq_flag"], absent_label=t["cq_clean"]))
    out += "</table>"
    out += _content_qa_breakdown(cq, lang)  # AAA-190 (#8) — category breakdown when flagged
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
        # AAA-189: landmarks now show present AND missing (was present-only).
        (t["landmarks"], _fv((op.get("aria") or {}).get("landmarks_present"), lang,
            fmt=lambda v: _landmarks_fmt(v, (op.get("aria") or {}).get("landmarks_missing"), lang))),
        (t["schema_jsonld"], _fv((op.get("schema") or {}).get("json_ld_present"), lang)),
    ]
    # AAA-185: title_meta (AAA-158) — truncation verdict + keyword-in-title + title↔H1 dup.
    tm = op.get("title_meta") or {}
    rows += _title_meta_rows(tm, lang)
    out += "<table>" + "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows) + "</table>"
    out += _s43_verdicts(op, lang)  # AAA-189 — machine-readability cluster verdicts
    out += _subsec("4.4", "Technikai egészség" if lang == "hu" else "Technical health")
    # AAA-190 (#7) — 3-view CWV table (field-mobile / lab-mobile / lab-desktop),
    # columns LCP · INP · CLS · FCP, + a supporting-metrics line.
    out += "<table><tr><th>%s</th><th>LCP</th><th>INP</th><th>CLS</th><th>FCP</th></tr>" % (
        "Nézet" if lang == "hu" else "View")
    out += _cwv_view(ao, lang, "mobile", "core_web_vitals_field", t["cwv_field"])
    out += _cwv_view(ao, lang, "mobile", "core_web_vitals_lab", t["cwv_lab"])
    out += _cwv_view(ao, lang, "desktop", "core_web_vitals_lab", t["cwv_lab_desktop"])
    out += "</table>"
    out += _cwv_support(ao, lang)
    rows44 = [
        (t["perf"], "%s / %s" % (_fv(tech.get("psi_mobile_perf"), lang), _fv(tech.get("psi_desktop_perf"), lang))),
        (t["indexed"], _fv(tech.get("indexed"), lang)),
        ("HTTPS", _fv(tech.get("https"), lang)),
        # AAA-190 (#8) — canonical: self-ref + no mismatch → positive (AAA-187);
        # mismatch → weakness (AAA-188).
        (t["canonical"], _canonical_cell(tech, lang)),
        (t["page_weight"], _fv(_raw(_dig(ao, "crawl", "content", "raw_html_bytes"), "mért"), lang,
            fmt=lambda v: "%d B (%.1f%% / 2MB)" % (v, 100 * v / 2097152))),
    ]
    out += "<table>" + "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows44) + "</table>"
    out += _ai_crawler_block(tech, lang)  # AAA-187 — AI-crawler visibility sub-block
    return out


def _ai_crawler_block(tech, lang):
    """AAA-187 — AI-crawler readiness sub-block (§4.4). Always rendered WITH a
    verdict (AAA-182 'Clean' positive pattern — never hidden when clean): the
    reassurance case is itself customer value. Covers two threads:
      (1) CSR/SPA visibility — JS-rendered content a non-JS crawler can't see.
      (2) ~2MB byte budget — HTML past Googlebot's index cutoff may be dropped.
    Provenance-aware: if neither thread was measured → 'not measured'."""
    t = UI[lang]
    rend = (tech or {}).get("rendering") or {}
    bb = (tech or {}).get("byte_budget") or {}
    csr = rend.get("is_csr_likely") or {}
    warn = rend.get("ai_crawler_visibility_warning") or {}
    over = bb.get("exceeds_2mb") or {}

    def _meas(f):
        return _is_fact(f) and f.get("provenance") == "measured"

    # Distinct labeled sub-block under §4.4 (no number collision with the
    # technical-health table, which owns the 4.4 numbering).
    def _header(chip):
        return ('<div class="subsec"><b style="font-family:var(--serif)">%s</b> %s</div>'
                % (_esc(t["aic_title"]), chip))

    # not_measured on every thread → honest "not measured" (no measured chip).
    if not (_meas(csr) or _meas(warn) or _meas(over)):
        return _header("") + ('<div class="note">%s</div>' % _nd(lang))

    header = _header(_chip("mért", lang))

    lines = []
    # Thread 1 — CSR/SPA visibility warning.
    if (_meas(csr) and bool(csr.get("value"))) or (_meas(warn) and bool(warn.get("value"))):
        lines.append(('st-warn', t["aic_csr"]))
    # Thread 2 — byte budget cutoff.
    if _meas(over) and bool(over.get("value")):
        total = (bb.get("raw_html_bytes") or {}).get("value")
        overb = (bb.get("bytes_over_limit") or {}).get("value")
        pct = None
        if isinstance(total, (int, float)) and total and isinstance(overb, (int, float)):
            pct = round(100.0 * overb / total, 1)
        lines.append(('st-bad', t["aic_2mb"] % (pct if pct is not None else "?")))
    # Clean — positive reassurance (only when nothing flagged).
    if not lines:
        lines.append(('st-ok', t["aic_clean"]))

    rows = "".join(
        '<div style="margin:6px 0"><span class="st %s">%s</span></div>' % (cls, _esc(msg))
        for cls, msg in lines)
    return header + rows


_EEAT_DIMS = [("experience", "Tapasztalat", "Experience"),
              ("expertise", "Szakértelem", "Expertise"),
              ("authoritativeness", "Tekintély", "Authority"),
              ("trustworthiness", "Megbízhatóság", "Trust")]


def _clause(s, n=110):
    """First clause/sentence of a justification, capped — for the compact §5
    per-dim signal-note."""
    s = (s or "").strip()
    cut = s.find(". ")
    if 0 < cut < n:
        return s[:cut + 1]
    return (s[:n].rstrip() + "…") if len(s) > n else s


def _s5(fb, ao, lang):
    """AAA-170 S2 — client E-E-A-T capstone from PAGE-INTRINSIC scores (the page's
    own profile), NOT the comparative scores (§6.D). Band, not a hard standalone
    number (AAA-172): the dimension pattern + fix-list are the diagnostic signal.
    Verdict is signal-bound — HARD GUARD: no rank prediction (page-intrinsic
    verdict is about the page itself, not its SERP position)."""
    t = UI[lang]
    pi = (fb.get("eeat") or {}).get("page_intrinsic") or {}
    just = pi.get("justifications") or {}
    DIMS = [(k, hu if lang == "hu" else en, en) for k, hu, en in _EEAT_DIMS]

    # Band (page-intrinsic total ±3) — never a hard standalone number.
    tot = (pi.get("total_0_40") or {}).get("value")
    out = ""
    if isinstance(tot, int):
        lo, hi = max(0, tot - 3), min(40, tot + 3)
        lab = t["ee_weak"] if tot < 20 else (t["ee_moderate"] if tot < 30 else t["ee_strong"])
        out += ('<div class="band">%s: <b>≈ %d–%d / 40</b> &nbsp;·&nbsp; %s</div>'
                '<div class="note">%s %s</div>'
                % (t["ee_band_pre"], lo, hi, lab, t["ee_caveat"], _chip("AI-értelmezés", lang)))

    # 4 dim-rows: score + bar + compact signal-note from the page-intrinsic justification.
    out += '<div style="margin-top:10px">'
    for k, lbl, sub in DIMS:
        v = (pi.get(k) or {}).get("value")
        band_cls = "band low" if isinstance(v, int) and v <= 3 else "band"
        style = "margin:0;padding:4px 10px;font-size:15px"
        if band_cls == "band low":
            style += ";border-color:var(--bad);color:var(--bad)"
        val_html = ('<span class="%s" style="%s">%s/10</span>' % (band_cls, style, v)) if isinstance(v, int) else _nd(lang)
        out += ('<div class="dimrow"><div class="dimname">%s<small>%s</small></div>'
                '<div>%s</div><div class="dimsig">%s</div></div>'
                % (_esc(lbl), _esc(sub), val_html, _chip("AI-értelmezés", lang)))
        jn = (just.get(k) or {}).get("value")
        if jn:
            out += '<div class="note" style="font-size:13px;margin:2px 0 8px 0">%s</div>' % (
                _esc(_clause(_sanitize_labels(jn, _page_names(ao)))))
    out += "</div>"

    # Verdict (page-intrinsic, signal-bound — no rank prediction).
    verdict = (pi.get("verdict") or {}).get("value")
    if verdict:
        verdict = _sanitize_labels(verdict, _page_names(ao))  # AAA-181: strip PAGE_N
        out += '<div class="subsec"><span class="n">%s</span></div><p>%s %s</p>' % (
            t["verdict"], _esc(verdict), _chip("AI-értelmezés", lang))

    # AAA-192 — §5 dedupe: the E-E-A-T fixes now live in the single §7 action
    # list (was _eeat_fixlist here). Point to §7 instead of a duplicate list.
    out += '<p class="role">%s</p>' % t["ee_see7"]
    out += _eeat_evidence_block(fb, lang)  # AAA-188 — grounding beside the score
    # §5→§6 two-lens cross-reference (page-intrinsic here vs comparative in §6).
    out += '<p class="role">%s</p>' % t["ee_twolens"]
    return out


def _eeat_evidence_block(fb, lang):
    """AAA-188 — E-E-A-T evidence sub-block (§5). The GROUNDING beside the score
    (named people / owner org+KG / client authority entities), NOT a restatement
    of the 4-dim band. REVERSED polarity vs AAA-187: absent = a NEGATIVE
    weak-signal finding (no named author, not in KG), never reassurance.
    Deterministic extractions → explicit 'mért' chips (eeat group default is AI).
    named_people surfaced as-is (AAA-173: no content_qa placeholder cross-ref)."""
    t = UI[lang]
    ev = (fb.get("eeat") or {}).get("evidence") or {}

    def _prov(f):
        return f.get("provenance") if _is_fact(f) else "not_measured"

    def _cap(vals, n=8):
        vals = [v for v in (vals or []) if v]
        extra = len(vals) - n
        shown = ", ".join(_esc(v) for v in vals[:n])
        return shown + (" …(+%d)" % extra if extra > 0 else "")

    rows = []  # (label, html)

    # --- Named people (Experience / Expertise) — reversed polarity ---
    np_f = ev.get("named_people") or {}
    pv = _prov(np_f)
    if pv == "measured":
        rows.append((t["ev_people"], "%s %s" % (_cap(np_f.get("value")), _chip("mért", lang))))
    elif pv == "absent":
        rows.append((t["ev_people"], '<span class="st st-warn">%s</span> %s' % (
            _esc(t["ev_people_none"]), _chip("mért", lang))))
    else:
        rows.append((t["ev_people"], _nd(lang)))

    # --- Organization (Authoritativeness) — owner_org + KG-confirmed status ---
    org_f = ev.get("owner_org") or {}
    kg_f = ev.get("kg_calls") or {}
    ov = _prov(org_f)
    if ov == "measured":
        kg = (" · <span class=\"st st-ok\">%s</span>" % _esc(t["ev_kg_ok"])) \
            if _prov(kg_f) == "measured" else ""
        rows.append((t["ev_org"], "%s%s %s" % (_esc(org_f.get("value")), kg, _chip("mért", lang))))
    elif ov == "absent":
        # KG lookup ran (kg_calls measured) but confirmed no owner entity →
        # the sharper "not in Knowledge Graph" finding; else generic absence.
        msg = t["ev_kg_none"] if _prov(kg_f) == "measured" else t["ev_org_none"]
        rows.append((t["ev_org"], '<span class="st st-warn">%s</span> %s' % (
            _esc(msg), _chip("mért", lang))))
    else:
        rows.append((t["ev_org"], _nd(lang)))

    # --- Authority entities (brief) — client orgs/products/tech (topical
    # authority; removes the client↔competitor asymmetry of §6). Names shown,
    # consistent with the §6 entity families. ---
    ent_bits = []
    for key, lbl in (("client_orgs", t["ev_orgs"]), ("client_products", t["ev_products"]),
                     ("client_tech", t["ev_tech"])):
        f = ev.get(key) or {}
        if _prov(f) == "measured":
            ent_bits.append("<b>%s:</b> %s" % (_esc(lbl), _cap(f.get("value"), 6)))
    if ent_bits:
        rows.append((t["ev_entities"], "%s %s" % (
            " &nbsp;·&nbsp; ".join(ent_bits), _chip("mért", lang))))

    out = _subsec("", t["ev_title"])
    out += "<table>" + "".join(
        "<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in rows) + "</table>"
    return out


def _entity_diff(fb, lang):
    """AAA-164 — concrete entity set-difference: named ORGANIZATIONS each
    competitor cites that the CLIENT does not. ORG-SCOPED ONLY (decision
    2026-06-09): no product/tech fallback. Case-insensitive; original casing
    shown. Empty competitor org sets (e.g. marketingastro) → a clean
    measured-positive line (AAA-187), never product/tech substitution."""
    t = UI[lang]
    comps = (fb.get("competition") or {}).get("competitors") or []
    ev = (fb.get("eeat") or {}).get("evidence") or {}

    cl_f = ev.get("client_orgs") or {}
    cl_orgs = set(cl_f.get("value") or []) if (_is_fact(cl_f) and isinstance(cl_f.get("value"), list)) else set()
    cl_lower = {x.lower().strip() for x in cl_orgs if isinstance(x, str)}

    rows = []
    for c in comps:
        f = c.get("entity_orgs_list") or {}
        comp_set = {x for x in (f.get("value") or []) if isinstance(x, str)} if _is_fact(f) else set()
        diff = sorted({x for x in comp_set if x.lower().strip() not in cl_lower})
        if diff:
            rows.append(((c.get("brand") or {}).get("value") or "?", diff))
    if not rows:
        return '<div class="subsec"><span class="n">%s</span></div><div class="note"><span class="st st-ok">%s</span> %s</div>' % (
            t["ent_diff_title"], _esc(t["ent_diff_none"]), _chip("mért", lang))
    out = '<div class="subsec"><span class="n">%s</span> %s</div>' % (
        t["ent_diff_title"], _chip("mért", lang))
    for brand, diff in rows:
        out += '<div class="note"><b>%s</b> — %s</div>' % (
            _esc(brand), ", ".join(_esc(x) for x in diff[:10]))
    return out


def _comp_url(c):
    u = c.get("url")
    return (u.get("value") if isinstance(u, dict) else u) or ""


def _comp_name(c, lang):
    """AAA-195 FIX 2 — competitor column label: resolved brand → registrable
    domain → '(brand unresolved)'. Never '?'. Failed-crawl rows get the
    unavailable flag appended."""
    b = (c.get("brand") or {}).get("value")
    base = b or _host(_comp_url(c)) or UI[lang]["brand_unresolved"]
    return base


def _s6(fb, ao, lang):
    t = UI[lang]
    comps = (fb.get("competition") or {}).get("competitors") or []
    audit_dt = _audit_date(ao)
    # AAA-195 FIX 2 — brand→domain fallback (no "?"); flag failed-crawl columns.
    names = []
    for c in comps:
        nm = _comp_name(c, lang)
        if c.get("crawl_failed"):
            ts = (", " + audit_dt) if audit_dt else ""
            nm += " " + (t["comp_unavail"] % _esc(ts))
        names.append(nm)
    n_total = len(comps)
    n_usable = sum(1 for c in comps if not c.get("crawl_failed"))
    cl = (fb.get("eeat") or {}).get("client") or {}

    # AAA-164 — client column for §6.A/B/C (apples-to-apples; same paths as
    # _competitor_rich so semantics match). Deterministic measurements.
    def _ln(x):
        return len(x) if isinstance(x, (list, tuple)) else None
    ccells = {
        "word_count_doc": _dig(ao, "crawl", "main_content", "words"),
        "orgs_count": _ln(_dig(ao, "entities", "organizations")),
        "title_chars": _dig(ao, "crawl", "meta", "title", "chars"),
        "meta_chars": _dig(ao, "crawl", "meta", "description", "chars"),
        "h1_count": _dig(ao, "agent_friendly_measurements", "heading", "h1_count"),
        "total_headings": _dig(ao, "agent_friendly_measurements", "heading", "total_headings"),
        "schema_types_count": _ln(_dig(ao, "crawl", "schema_markup", "schema_types_detected")),
        "alt_coverage_pct": _dig(ao, "crawl", "images", "alt_coverage_percent"),
        "perf_mobile_lab": _dig(ao, "pagespeed", "mobile", "scores", "performance"),
    }

    def fam(title, rows, layer):
        h = _subsec("", title) + '<table><tr><th>%s %s</th><th class="num">%s</th>' % (
            t["competitor"], _chip(layer, lang), t["client"])
        h += "".join("<th class='num'>%s</th>" % _esc(n) for n in names) + "</tr>"
        for label, key in rows:
            h += "<tr><td>%s</td>" % label
            cv = ccells.get(key)
            h += '<td class="num"><b>%s</b></td>' % (
                _esc(cv) if cv is not None else '<span class="ph">—</span>')
            for c in comps:
                v = (c.get(key) or {}).get("value")
                h += "<td class='num'>%s</td>" % (_esc(v) if v is not None else '<span class="ph">—</span>')
            h += "</tr>"
        return h + "</table>"

    # AAA-195 FIX 2 — honest usable-count when a selected competitor's crawl failed.
    out = ""
    if n_total and n_usable < n_total:
        usable = (t["comp_usable"] % (n_total, n_usable)) if lang == "hu" else (
            t["comp_usable"] % (n_usable, n_total))
        out += '<div class="note"><span class="st st-warn">%s</span></div>' % _esc(usable)
    out += fam(t["fam_content"], [("Word count", "word_count_doc"), ("Orgs", "orgs_count")], "mért")
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
    out += _entity_diff(fb, lang)  # AAA-164 — concrete entity set-difference
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


# AAA-192 — deterministic per-fix-type recommendation TEMPLATES (no live LLM,
# AAA-129 hybrid: audit-independent action phrasing, the concrete gap is the
# finding it's bound to). Used only for template (non-competitive) findings;
# competitive-pattern findings keep their RG3-grounded recommendation as-is.
# Detection is by finding-text signature (the deterministic texts in decide.py).
_FIX_SIGNATURES = [
    ("top 10", "ranking"), ("ai overview", "aio"), ("chatgpt", "chatgpt"),
    ("https", "https"), ("not indexed", "indexed"), ("redirect", "redirect"),
    ("structured-data types do not", "schema_match"), ("heading hierarchy", "heading_skips"),
    ("landmarks", "landmarks"), ("form fields lack", "form_labels"), ("placeholder", "placeholder"),
]
_REC_TEMPLATES = {
    "ranking": {"en": "Deepen the page's topical coverage and trust signals for the target query — on-page quality is the lever you control here.",
                "hu": "Mélyítsd az oldal témafedését és bizalmi jeleit a célkulcsszóra — az oldalon belüli minőség az, amit befolyásolni tudsz."},
    "aio": {"en": "Mirror the structure of the cited sources (clear answers, structured data, named entities) so the page becomes citable in the AI Overview.",
            "hu": "Kövesd az idézett források szerkezetét (világos válaszok, strukturált adat, megnevezett entitások), hogy az oldal idézhetővé váljon az AI Overview-ban."},
    "chatgpt": {"en": "Add concise, well-structured answer passages and authoritative citations so the page is usable as a source in AI answers.",
                "hu": "Adj tömör, jól strukturált válaszrészeket és hiteles hivatkozásokat, hogy az oldal forrásként használható legyen az AI-válaszokban."},
    "https": {"en": "Serve the whole site over HTTPS with a valid certificate and redirect HTTP → HTTPS.",
              "hu": "Szolgáld ki a teljes oldalt HTTPS-en érvényes tanúsítvánnyal, és irányítsd át a HTTP-t HTTPS-re."},
    "indexed": {"en": "Resolve the indexing blocker (robots / meta-robots / canonical) so Google can index the page.",
                "hu": "Oldd fel az indexelési akadályt (robots / meta-robots / canonical), hogy a Google indexelni tudja az oldalt."},
    "redirect": {"en": "Point internal links and the canonical directly at the final URL to remove the redirect hop.",
                 "hu": "Mutasson a belső linkek és a canonical közvetlenül a végső URL-re, hogy megszűnjön az átirányítási lépés."},
    "schema_match": {"en": "Add the structured-data types that match this page type so machines can classify it correctly.",
                     "hu": "Add hozzá az oldaltípushoz illő strukturált-adat típusokat, hogy a gépek helyesen osztályozzák."},
    "heading_skips": {"en": "Fix the heading hierarchy so levels follow in order, with no skipped levels.",
                      "hu": "Javítsd a címsor-hierarchiát, hogy a szintek sorrendben kövessék egymást, kihagyás nélkül."},
    "landmarks": {"en": "Add the missing structural landmarks (e.g. header, article, aside) so crawlers can parse the page regions.",
                  "hu": "Add hozzá a hiányzó strukturális landmarkokat (pl. header, article, aside), hogy a crawlerek értelmezzék az oldalrészeket."},
    "form_labels": {"en": "Bind a label to every form field so the form is accessible and machine-readable.",
                    "hu": "Köss minden űrlapmezőhöz label-t, hogy az űrlap akadálymentes és gépileg olvasható legyen."},
    "placeholder": {"en": "Remove or replace the unfinished / placeholder text in the main content with final copy.",
                    "hu": "Távolítsd el vagy cseréld le a befejezetlen / helykitöltő szöveget a fő tartalomban végleges szövegre."},
}
# Enrichment (deterministic from category): which section surfaced it · what it improves.
_REC_SRC = {"ranking": "§3", "visibility": "§3", "content": "§4", "schema": "§4.3",
            "technical": "§4.4", "structure_accessibility": "§4.3", "trust": "§4.1"}
_REC_IMPROVES = {
    "ranking": {"en": "competitive positioning", "hu": "versenypozíció"},
    "visibility": {"en": "AI-visibility", "hu": "AI-láthatóság"},
    "content": {"en": "content depth & accessibility", "hu": "tartalmi mélység és akadálymentesség"},
    "schema": {"en": "machine-readability", "hu": "gép-olvashatóság"},
    "technical": {"en": "technical health", "hu": "technikai egészség"},
    "structure_accessibility": {"en": "machine-readability / accessibility", "hu": "gép-olvashatóság / akadálymentesség"},
    "trust": {"en": "trust signals", "hu": "bizalmi jelek"},
}
# Indicative effort per fix-type; category fallback for competitive-pattern findings.
_REC_EFFORT_FT = {"placeholder": "low", "heading_skips": "low", "landmarks": "low",
                  "form_labels": "low", "redirect": "low", "https": "low",
                  "schema_match": "medium", "chatgpt": "medium", "indexed": "medium",
                  "ranking": "high", "aio": "high"}
_REC_EFFORT_CAT = {"content": "medium", "schema": "medium", "technical": "medium",
                   "visibility": "high", "ranking": "high", "trust": "low",
                   "structure_accessibility": "low"}


def _fix_type(f):
    txt = (f.get("finding") or "").lower()
    for sig, key in _FIX_SIGNATURES:
        if sig in txt:
            return key
    return None


def _s7(fb, dec, lang):
    """AAA-192 — unified, impact-ranked action list. Deterministic collector/ranker
    (decide_ranked_findings, RG5 severity) → 3 tiers (high · medium · Refinement).
    Phrasing (no live LLM): RG3-grounded `recommendation` where present, else a
    per-fix-type action TEMPLATE; each item is bound to its concrete measured gap
    (the finding) + deterministic source/improves/indicative-effort enrichment.
    Rank-prediction-free by construction (static templates, hard-guard intro)."""
    t = UI[lang]
    findings = [f for f in (dec.get("ranked_findings") or []) if not _is_volume_finding(f)]
    tiers = {"high": [], "medium": [], "low": []}
    for f in findings:
        tiers.get(f.get("impact_severity"), tiers["low"]).append(f)
    # Static "how to read" framing + hard-guard + save-before-irreversible note.
    out = '<div class="note">%s</div>' % t["r7_intro"]
    for sev, label, cls in (("high", t["t1"], "t1"), ("medium", t["t2"], "t2"), ("low", t["t3"], "t3")):
        if not tiers[sev]:
            continue
        out += _subsec("", label)
        for f in tiers[sev]:
            cat = f.get("category") or ""
            ft = _fix_type(f)
            # Phrasing: RG3-grounded rec as-is, else the per-fix-type template.
            rec = (f.get("recommendation") or "").strip() or _REC_TEMPLATES.get(ft, {}).get(lang) or ""
            # Fallback (no template, no rec): action-frame from the finding so we
            # never render a raw gap-label as the recommendation.
            if not rec:
                rec = f.get("finding") or ""
            src = _REC_SRC.get(cat, "§4")
            improves = (_REC_IMPROVES.get(cat) or {}).get(lang, "")
            eff_key = _REC_EFFORT_FT.get(ft) or _REC_EFFORT_CAT.get(cat, "medium")
            eff = t["eff_" + eff_key]
            meta = "%s %s &nbsp;·&nbsp; %s: %s &nbsp;·&nbsp; %s: %s (%s)" % (
                t["rec_src"], src, t["rec_improves"], _esc(improves),
                t["rec_effort"], eff, t["rec_indic"])
            out += ('<div class="rec %s"><div><b>%s</b></div>'
                    '<div class="dimsig">%s: %s</div>'
                    '<div class="recmeta" style="font-size:12px;margin-top:3px">%s</div></div>'
                    % (cls, _esc(rec), t["rec_gap"], _esc(f.get("finding")), meta))
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
