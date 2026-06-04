# -*- coding: utf-8 -*-
"""AAA-96 — customer-facing report renderer (Sub-step 1.5).

Two-pass architecture: render each section in EN canonical (the prompt language),
then translate to HU via TRANSLATION_PASS. §12 is a static slot-filled template.

Cross-cutting contracts are enforced both by the assemblers (deterministic field
extraction + NO_DATA markers + single-anchor + corrected canonical + page_type
fallback + comparison gating) and by GROUNDING_RULES (the single source of the
grounding contract, appended to every FELADAT variant).
"""

from __future__ import annotations

from urllib.parse import urlparse

from discovery_agent.tools import _select_canonical

NO_DATA = "[no data]"
RENDER_MODEL = "gemini-3.5-flash"

# ---------------------------------------------------------------------------
# Shared constants (EN canonical prompt fragments)
# ---------------------------------------------------------------------------

AUDIENCE = (
    "The reader is a marketing leader or company executive, NOT an SEO specialist; "
    "they must be able to hand this off as a task to a developer/agency. Write "
    "clearly, in business language. Explain any technical term in a few words on "
    "first use. The audited site belongs to the reader (the owner). Address the "
    "reader in the second person; never refer to the audited site as 'we'/'our'."
)

# Single source of the grounding contract — appended to every FELADAT variant.
GROUNDING_RULES = (
    "GROUNDING RULES — apply to everything above:\n"
    "- Base every statement solely on the provided data; never invent a value.\n"
    "- Where there is no competitor data for an aspect, do not compare and do not "
    "speculate about the competitor's strength, position, or behaviour — simply "
    "state that no competitor comparison is available for that aspect.\n"
    "- Recommendations must target aspects actually measured in this audit. Do not "
    "recommend fixes for anything not present in the provided data (e.g. robots.txt, "
    "crawler directives, backlinks), not even as generic best-practice advice.\n"
    "- Use conditional phrasing wherever you infer; if a step goes beyond the "
    "measured data, frame it conditionally and never contradict a measured fact.\n"
    "- Do not use internal data-field or measurement jargon in the customer-facing "
    "text (e.g. \"gap data\", \"schema-gap data\", raw field names).\n"
    "- No internal references: ticket IDs, tool names, section numbers.\n"
    "- Emit an action only for a measured gap or weakness. If a dimension is "
    "adequate or strong, acknowledge it in one phrase and move on — never invent "
    "a task to 'maintain', 'preserve', 'keep', or 'monitor' something already fine.\n"
    "- More is not automatically better. Do not recommend increasing a quantity "
    "(word count, number of links, etc.) unless a measured deficiency justifies "
    "it; if the measured value is adequate or already exceeds the competitor, do "
    "not recommend increasing it.\n"
    "- Judge every finding against the page's type and purpose. Do not treat the "
    "absence of an element that isn't expected for this page type as a gap (e.g. "
    "breadcrumb or an aside landmark on a homepage; a contact form on a page whose "
    "job isn't lead capture).\n"
    "- Do not assert or recommend changes to an element unless its presence is "
    "confirmed in the data (e.g. never recommend a form/field attribute when no "
    "form is reported).\n"
    "- Never quote raw internal strings verbatim — search/fan-out query fragments, "
    "variant strings, or raw field identifiers (e.g. target_cited, "
    "entity_richness). Express the point in natural business language."
)

# Schema-only guard (UNCHANGED behaviour — applied to schema-bearing sections).
SCHEMA_GUARD = (
    "GUARD: speak ONLY about the schema types actually present or actually missing "
    "in the provided schema comparison. Do NOT name any specific rich-result / "
    "rich-snippet type (e.g. star ratings, FAQ expansion, price display) that cannot "
    "be directly derived from the provided missing schema types."
)

TASK_STD = (
    "1. Brief executive summary (2-3 sentences).\n"
    "2. Detailed analysis along the rules above. Where competitor data is available "
    "for an aspect, build the comparison anchored to the primary competitor named in the data.\n"
    "3. Concrete, hand-off-ready action plan.\n\n"
    + GROUNDING_RULES
)

FELADAT_1 = (
    "1. Main diagnosis in 2-3 sentences, business language: why the site is not "
    "visible organically and in AI search.\n"
    "2. The 2-3 biggest reasons, in plain language, in the given priority order. "
    "Explain any technical term on first use. Where competitor data exists, briefly "
    "mention the gap to the primary competitor named in the data.\n"
    "3. One closing sentence: what the report will walk through (lead-in to the "
    "detailed sections).\n"
    "No detailed action plan in this section.\n\n"
    + GROUNDING_RULES
)

FELADAT_11 = (
    "1. One-sentence closing frame: where the site stands overall.\n"
    "2. The 3-5 most important actions in priority order (by measured severity). For "
    "each: WHAT to do + WHY it matters (business impact) + OWNER (developer / content "
    "/ agency). Consolidate — do not repeat the detailed analysis. Treat thematically "
    "different structural topics (e.g. heading hierarchy vs conversion form) as "
    "separate actions; do not merge them into one.\n"
    "3. Short positive close building on the measured strengths.\n\n"
    + GROUNDING_RULES
)

TRANSLATION_PASS = (
    "You are a professional EN->HU business translator. Translate the following "
    "audit-report section into natural, fluent Hungarian for a marketing/executive "
    "reader. STRICT rules: preserve every number, fact, schema-type name, and URL "
    "EXACTLY. Preserve all 'no data'/conditional framing. Do NOT add, remove, or "
    "reinterpret any finding. Keep the markdown structure. Render second person as "
    "formal Hungarian 'Ön/Önök' throughout; never first-person plural ('mi', "
    "'oldalunk') or informal 'te'. Output only the Hungarian "
    "translation.\n\n--- SECTION TO TRANSLATE ---\n{section}"
)

# §12 is static (no Gemini) — slot-filled methodology template (EN canonical).
SECTION_12_TEMPLATE = (
    "## §12 — Methodology\n\n"
    "This report rests on four measurement pillars: (1) Discovery audit (page "
    "structure, semantic coding, structured data), (2) Competitor reverse-engineering "
    "(measured against the primary competitor, {competitor}, for the main keyword: "
    "\"{keyword}\"), (3) AI visibility (Google AI Overview + ChatGPT + fan-out "
    "queries), (4) Technical measurements (PageSpeed, CrUX, indexation, canonical URL, "
    "redirects). Models: gemini-3-flash-preview, gemini-3.5-flash. Data sources: "
    "direct programmatic measurements, Google grounded data, ChatGPT API, Chrome User "
    "Experience Report (CrUX), PageSpeed Insights."
)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _nd(v):
    if v is None:
        return NO_DATA
    if isinstance(v, str) and (not v.strip() or v.strip().lower() == "null"):
        return NO_DATA
    if isinstance(v, (list, dict)) and len(v) == 0:
        return NO_DATA
    return v


def _g(d, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _re(ao): return ao.get("re_findings") or {}
def _comp(ao): return (_re(ao).get("comparison") or {})
def _dim(ao): return (_comp(ao).get("dimension_table") or {})
def _raw(ao): return (_comp(ao).get("_raw_dimensions") or {})
def _client_raw(ao): return (_raw(ao).get("client") or {})


def _ss(ao): return (ao.get("phase2_html_measurements") or {}).get("semantic_structure") or {}
def _afm(ao): return ao.get("agent_friendly_measurements") or {}


def _reg(url):
    """Registrable domain (last two labels), scheme/www/path-stripped."""
    if not url:
        return None
    n = urlparse(url if "://" in url else "https://" + url).netloc.lower().split(":")[0]
    if n.startswith("www."):
        n = n[4:]
    parts = [x for x in n.split(".") if x]
    return ".".join(parts[-2:]) if len(parts) >= 2 else (n or None)


def resolve_anchor(ao):
    """D1: anchor = the measured competitor (_raw_dimensions.competitors) with the
    best SERP rank, paired to the SERP landscape by registrable domain. Fallback to
    competitors[0] if none pair to a SERP rank. None if no competitor was measured."""
    comps = _raw(ao).get("competitors") or []
    if not comps:
        return None
    sfa = (ao.get("serp_fit_analysis") or [{}])[0]
    serp_by_reg = {}
    for s in (sfa.get("serp_top10_classifications") or []):
        r = _reg(s.get("url"))
        if r and r not in serp_by_reg:
            serp_by_reg[r] = s.get("position")
    best, best_pos = None, None
    for c in comps:
        pos = serp_by_reg.get(_reg(c.get("url")))
        if pos is not None and (best_pos is None or pos < best_pos):
            best, best_pos = c, pos
    if best is None:
        best = comps[0]  # fallback: no SERP-rank pairing available
    return best


def anchor_name(ao):
    c = resolve_anchor(ao)
    if not c:
        return None
    return c.get("brand") or _reg(c.get("url"))


# D2: logical-category -> the audit's actual dimension_table key candidates.
C_CONTENT = ["content_depth", "content_length", "content_volume"]
C_SCHEMA = ["schema_sophistication", "schema_depth", "schema_diversity"]
C_ENTITY = ["entity_richness_orgs", "entity_richness_places", "entity_richness_products"]
C_PERF_DESKTOP = ["performance_desktop"]


# Localized entity-richness suffix vocabulary (AAA-143 Sub-step 3).
_ENT_SUFFIX = {
    "en": {"orgs": "organizations", "organizations": "organizations", "places": "places", "products": "products"},
    "hu": {"orgs": "szervezetek", "organizations": "szervezetek", "places": "helyek", "products": "termékek"},
}


def dim_label(key, lang="en"):
    """Localized label for a dimension_table key (prefix-mapped; humanizing EN
    fallback for any unknown key — never returns a raw key, never crashes).

    lang defaults to 'en' so the AAA-96 content layer (EN canonical markdown) is
    unaffected; the AAA-143 presentation layer passes the page language for the
    structured bar labels."""
    k = (key or "").lower()
    hu = (lang == "hu")
    if k.startswith("content"):
        return "Tartalom mélysége (szószám)" if hu else "Content depth (word count)"
    if k.startswith("schema"):
        return "Strukturált adatok (séma)" if hu else "Structured data (schema)"
    if k.startswith("entity_richness"):
        # AAA-153 S1: only show the (suffix) parenthetical for a RECOGNIZED
        # suffix; the bare key (or an unrecognized one) returns the clean label
        # — never leak the raw key, e.g. "(entity_richness)".
        suffix = k[len("entity_richness"):].lstrip("_")
        suf = _ENT_SUFFIX.get(lang, {}).get(suffix)
        if not suf:
            return "Entitás-gazdagság" if hu else "Entity richness"
        return ("Entitás-gazdagság (%s)" if hu else "Entity richness (%s)") % suf
    if k == "performance_desktop":
        return "Asztali sebesség (PageSpeed)" if hu else "Desktop speed (PageSpeed)"
    if k in ("mobile_performance", "performance_mobile"):
        return "Mobil sebesség (PageSpeed)" if hu else "Mobile speed (PageSpeed)"
    if k == "ai_visibility":
        return "AI-láthatóság" if hu else "AI visibility"
    if k in ("accessibility_alt_text", "alt_text_coverage", "alt_coverage"):
        # AAA-153 S1 (item 5a): alt_text_coverage is the live dimension key; it
        # was hitting the title-case fallback -> untranslated "Alt Text Coverage".
        return "Alt-szöveg lefedettség" if hu else "Alt-text coverage"
    return (key or "").replace("_", " ").title()  # EN-style fallback for unknown keys


def _dim_present_key(ao, candidates):
    dt = _dim(ao)
    for c in candidates:
        if c in dt:
            return c
    return None


def _dim_line(ao, key, anchor):
    """Single comparison line; competitor column uses the resolved anchor name."""
    v = _dim(ao).get(key) or {}
    comp = anchor or "the measured competitor"
    return "  - %s: client=%s | %s=%s | gap=%s" % (
        dim_label(key), _nd(v.get("client")), comp,
        _nd(v.get("competitor_best")), _nd(v.get("gap")))


def _dim_body(ao, key, anchor):
    return _dim_line(ao, key, anchor).strip().lstrip("- ")


def _all_dim_lines(ao, anchor):
    """Every measured dimension (dynamic keys), anchored to the resolved anchor."""
    return [_dim_line(ao, k, anchor) for k in _dim(ao).keys()]


def page_type_fallback(ao):
    return ao.get("page_type_v3") or ao.get("page_type")


def corrected_canonical(ao):
    idx = ao.get("indexing") or {}
    ivars = [v for v in (idx.get("variants") or []) if v.get("indexed") is True]
    can, _mismatch = _select_canonical(ivars, idx.get("rel_canonical"))
    # AAA-151: never imply "canonical missing" when the page actually declares
    # one. If no indexed variant resolved a canonical, fall back to the crawled
    # rel=canonical value (indexing.rel_canonical, else crawl.technical.canonical).
    if not can:
        can = idx.get("rel_canonical") or _g(ao, "crawl", "technical", "canonical", "value")
    return can


# ---------------------------------------------------------------------------
# Per-section ADAT assemblers (EN canonical data blocks)
# ---------------------------------------------------------------------------

def adat_s1(ao):
    rf = _re(ao); crs = (rf.get("client_ranking_status") or {}).get("branded") or {}
    aio = ao.get("ai_overview") or {}; cg = ao.get("chatgpt_query_response") or {}
    kw0 = (ao.get("target_keywords_classified") or [{}])[0]
    sfa = (ao.get("serp_fit_analysis") or [{}])[0]
    L = []
    L.append("Driver (primary) keyword: %s" % _nd(sfa.get("keyword")))
    L.append("Ranking for the primary keyword: in top 10? %s (position: %s)" % (
        _nd(crs.get("found_in_top_10")), _nd(crs.get("position"))))
    L.append("AI visibility: does AI Overview cite the client? %s | does ChatGPT cite? %s" % (
        _nd(aio.get("client_cited")), _nd(cg.get("target_site_cited"))))
    L.append("Intent gap: page-intent=%s; keyword-intent=%s/%s" % (
        _nd(ao.get("page_type_parent_intent_group")),
        _nd(kw0.get("search_intent")), _nd(kw0.get("search_intent_l2"))))
    anchor = anchor_name(ao)
    if anchor and _dim(ao):
        L.append("Measured gaps (anchored to %s):" % anchor)
        L.extend(_all_dim_lines(ao, anchor))
    else:
        L.append("Measured gaps: no competitor was measured for this audit, so no competitor comparison is available.")
    pats = _comp(ao).get("patterns") or []
    if pats:
        L.append("Prioritized patterns (with severity — use this for the priority order):")
        for p in pats:
            L.append("  - [%s] %s" % (_nd(p.get("severity")), _nd(p.get("finding"))))
    return "\n".join(L)


def adat_s2(ao):
    ee = ao.get("eeat_signals") or {}; ent = _client_raw(ao).get("entity_counts") or {}
    kw0 = (ao.get("target_keywords_classified") or [{}])[0]
    crs = (_re(ao).get("client_ranking_status") or {}).get("branded") or {}
    aio = ao.get("ai_overview") or {}; cg = ao.get("chatgpt_query_response") or {}
    L = []
    L.append("Brand: %s" % _nd(_g(ao, "site_profile", "brand")))
    L.append("Business model: %s" % _nd(ao.get("business_model")))
    # AAA-152: page language (omit the line entirely if neither field is set).
    _lang = _g(ao, "site_profile", "language") or ao.get("audit_language")
    if _lang:
        L.append("Page language: %s" % _lang)
    L.append("Page type (v3 absent -> fallback): %s | page-intent: %s" % (
        _nd(page_type_fallback(ao)), _nd(ao.get("page_type_parent_intent_group"))))
    L.append("IMPORTANT: the targeted KEYWORD intent is separate from page-intent: %s/%s" % (
        _nd(kw0.get("search_intent")), _nd(kw0.get("search_intent_l2"))))
    L.append("Topic domain: %s | Locality: %s" % (_nd(ao.get("topic_domain")), _nd(ao.get("locality"))))
    L.append("Audience: %s (confidence: %s%%)" % (
        _nd(ao.get("audience_relationship_primary")), _nd(ao.get("audience_confidence"))))
    L.append("Entities: organizations=%s, products=%s, technologies=%s, concepts=%s, places=%s, people=%s" % (
        _nd(ent.get("organizations")), _nd(ent.get("products")), _nd(ent.get("technologies")),
        _nd(ent.get("concepts")), _nd(ent.get("places")), _nd(ent.get("people"))))
    L.append("Social-proof links: %s | brand mentions: %s | named people: %s" % (
        _nd(ee.get("social_proof_links")), _nd(ee.get("brand_mentions")), _nd(ee.get("named_people"))))
    L.append("Market position: in top 10=%s; AI Overview client_cited=%s; ChatGPT target_cited=%s" % (
        _nd(crs.get("found_in_top_10")), _nd(aio.get("client_cited")), _nd(cg.get("target_site_cited"))))
    L.append("(No competitor data is provided for this section.)")
    return "\n".join(L)


def adat_s3(ao):
    tk = ao.get("target_keywords") or {}
    tkc = ao.get("target_keywords_classified") or []
    sfa = (ao.get("serp_fit_analysis") or [{}])[0]
    crs = (_re(ao).get("client_ranking_status") or {}).get("branded") or {}
    cr = ao.get("crawl") or {}; links = cr.get("links") or {}
    L = []
    L.append("Driver keyword: %s | topic cluster: %s" % (_nd(sfa.get("keyword")), _nd(tk.get("topic_cluster"))))
    L.append("Target keywords (%s) — text | intent | volume | tail | relevance:" % (len(tkc) or NO_DATA))
    if not tkc:
        L.append("  " + NO_DATA)
    for c in tkc:
        vol = c.get("search_volume_monthly")
        vs = ("%s/month" % vol) if vol is not None else "no Google volume data (longtail)"
        L.append("  - %s | %s/%s | %s | %s | %s" % (
            _nd(c.get("keyword")), _nd(c.get("search_intent")), _nd(c.get("search_intent_l2")),
            vs, _nd(c.get("tail_type")), _nd(c.get("relevance_score"))))
    L.append("SERP fit (gate 1): target_type=%s, fit=%s" % (
        _nd(sfa.get("target_type")), _nd(sfa.get("target_type_fit"))))
    L.append("Page types Google prefers (serp_type_distribution): %s" % _nd(sfa.get("serp_type_distribution")))
    alt = sfa.get("alternative_keyword_suggestions")
    L.append("Alternative keyword suggestion: %s (recommendation triggered=%s)" % (
        (alt if alt else "none (fit is high, not triggered)"), _nd(sfa.get("keyword_recommendation_trigger"))))
    L.append("SERP top 10:")
    s10 = sfa.get("serp_top10_classifications") or []
    if not s10:
        L.append("  " + NO_DATA)
    for s in s10:
        L.append("  #%s [%s] %s — %s" % (_nd(s.get("position")), _nd(s.get("serp_type")), _nd(s.get("url")), _nd(s.get("title"))))
    L.append("Ranking status: in top 10=%s, position=%s, severity=%s" % (
        _nd(crs.get("found_in_top_10")), _nd(crs.get("position")), _nd(crs.get("ranking_severity"))))
    anchor = anchor_name(ao)
    L.append("Gate 2 gap (does it deserve to rank) — anchored to %s:" % (anchor or "no measured competitor"))
    for cands, lbl in [(C_CONTENT, "Content depth"), (C_SCHEMA, "Structured data (schema)"), (C_ENTITY, "Entity richness")]:
        k = _dim_present_key(ao, cands)
        L.append(_dim_line(ao, k, anchor) if k else ("  - %s: %s" % (lbl, NO_DATA)))
    anchors = [a.get("href") for a in (links.get("internal_anchors") or [])[:8] if a.get("href")]
    L.append("Hub signal: page type=%s, internal links=%s, external=%s, internal anchors=%s" % (
        _nd(page_type_fallback(ao)), _nd(links.get("internal_count")), _nd(links.get("external_count")),
        (", ".join(anchors) if anchors else NO_DATA)))
    return "\n".join(L)


def adat_s4(ao):
    sfa = (ao.get("serp_fit_analysis") or [{}])[0]
    v2 = [c for c in (ao.get("selected_competitors_v2") or []) if c.get("selected")]
    L = []
    L.append("Driver keyword (competitor identification is built on this): %s" % _nd(sfa.get("keyword")))
    L.append("SELECTED competitors (landscape; the detailed comparison anchor is the primary competitor named below):")
    if not v2:
        L.append("  " + NO_DATA)
    for c in sorted(v2, key=lambda x: x.get("selection_rank") or 99):
        L.append("  rank%s: %s | SERP position %s | type %s | role %s" % (
            _nd(c.get("selection_rank")), _nd(c.get("url")), _nd(c.get("position")),
            _nd(c.get("serp_type")), _nd(c.get("keyword_role"))))
    L.append("SERP top-10 landscape (context only):")
    s10 = sfa.get("serp_top10_classifications") or []
    if not s10:
        L.append("  " + NO_DATA)
    for s in s10:
        L.append("  #%s [%s] %s" % (_nd(s.get("position")), _nd(s.get("serp_type")), _nd(s.get("url"))))
    a = resolve_anchor(ao)
    if a:
        L.append("Primary benchmark (consistent anchor) = %s (%s) — the best-ranked measured competitor." % (
            a.get("brand") or _reg(a.get("url")), _nd(a.get("url"))))
    else:
        L.append("No competitor was measured for this audit; no benchmark anchor is available.")
    return "\n".join(L)


def adat_s5(ao):
    anchor = anchor_name(ao)
    a = resolve_anchor(ao) or {}
    if anchor and _dim(ao):
        L = ["Measurable dimensions (all anchored to %s):" % anchor]
        L.extend(_all_dim_lines(ao, anchor))
        L.append("%s's actual schema types: %s" % (anchor, _nd(a.get("schema_types"))))
    else:
        L = ["No competitor was measured for this audit; no competitor comparison is available."]
    pats = _comp(ao).get("patterns") or []
    L.append("Prioritized patterns (with severity):")
    if not pats:
        L.append("  " + NO_DATA)
    for p in pats:
        L.append("  - [%s] %s" % (_nd(p.get("severity")), _nd(p.get("finding"))))
    return "\n".join(L)


def adat_s6(ao):
    aio = ao.get("ai_overview") or {}; cg = ao.get("chatgpt_query_response") or {}
    fe = ao.get("fan_out_enriched") or []
    summ = _comp(ao).get("ai_overview_summary")
    L = []
    L.append("AI OVERVIEW: present=%s, client_cited=%s, async=%s" % (
        _nd(aio.get("present")), _nd(aio.get("client_cited")), _nd(aio.get("asynchronous"))))
    cs = aio.get("cited_sources") or []
    L.append("AIO cited sources (%s):" % (len(cs) if cs else NO_DATA))
    for c in cs:
        L.append("  - %s — %s" % (_nd(c.get("url")), _nd(c.get("title"))))
    L.append("CHATGPT: target_cited=%s" % _nd(cg.get("target_site_cited")))
    cits = cg.get("citations") or []
    L.append("ChatGPT cited sources (%s):" % (len(cits) if cits else NO_DATA))
    for c in cits:
        if isinstance(c, dict):
            L.append("  - %s — %s" % (_nd(c.get("url") or c.get("link")), _nd(c.get("title"))))
        else:
            L.append("  - %s" % _nd(c))
    L.append("FAN-OUT (query variants):")
    if not fe:
        L.append("  " + NO_DATA)
    for e in fe:
        L.append("  - variant: %s | source: %s | coverage: %s" % (
            _nd(e.get("query") or e.get("variant") or e.get("variant_type")),
            _nd(e.get("source")), _nd(e.get("coverage"))))
    L.append("Reason the client is excluded: %s" % _nd(summ))
    anchor = anchor_name(ao)
    L.append("Primary competitor anchor: %s." % (anchor if anchor else "no competitor was measured for this audit"))
    return "\n".join(L)


def adat_s7(ao):
    ent = _client_raw(ao).get("entity_counts") or {}; ee = ao.get("eeat_signals") or {}
    anchor = anchor_name(ao)
    L = []
    kc = _dim_present_key(ao, C_CONTENT)
    L.append(_dim_line(ao, kc, anchor) if kc else ("  - Content depth: %s" % NO_DATA))
    L.append("Entity richness (client): organizations=%s, products=%s, technologies=%s, concepts=%s, places=%s, people=%s" % (
        _nd(ent.get("organizations")), _nd(ent.get("products")), _nd(ent.get("technologies")),
        _nd(ent.get("concepts")), _nd(ent.get("places")), _nd(ent.get("people"))))
    ke = _dim_present_key(ao, C_ENTITY)
    L.append(_dim_line(ao, ke, anchor) if ke else ("  - Entity richness (comparison): %s" % NO_DATA))
    L.append("E-E-A-T signals: named authors=%s | brand mentions=%s | social-proof links=%s" % (
        _nd(ee.get("named_people")), _nd(ee.get("brand_mentions")), _nd(ee.get("social_proof_links"))))
    L.append("(No numeric content score — qualitative analysis only.)")
    return "\n".join(L)


def adat_s81(ao):
    lm = _afm(ao).get("landmarks") or {}; ss = _ss(ao); h = _afm(ao).get("heading") or {}
    L = []
    L.append("Landmark zones — present: %s | missing: %s" % (_nd(lm.get("present")), _nd(lm.get("missing"))))
    L.append("Heading zone distribution: %s" % _nd(ss.get("headings_by_zone")))
    L.append("Total headings: %s | H1: %s | level skips: %s" % (
        _nd(h.get("total_headings")), _nd(h.get("h1_count")), _nd(h.get("level_skips"))))
    L.append("Semantic-to-visual ratio: %s | structural-noise warning: %s" % (
        _nd(ss.get("semantic_to_visual_ratio")), _nd(ss.get("structural_noise_warning"))))
    L.append("(No competitor data is provided for this section.)")
    return "\n".join(L)


def adat_s82(ao):
    ss = _ss(ao)
    tree = ss.get("heading_tree")
    L = []
    if not tree:
        L.append("Zone-labeled heading tree: %s" % NO_DATA)
        return "\n".join(L)
    from collections import Counter
    texts = Counter((h.get("text") or "").strip() for h in tree)
    lvl = Counter("H%s" % h.get("level") for h in tree)
    L.append("Zone-labeled heading tree (in position order):")
    for h in sorted(tree, key=lambda x: x.get("position", 0)):
        dup = "  [DUPLICATE]" if texts[(h.get("text") or "").strip()] > 1 else ""
        L.append("  %s. H%s | zone: %s | \"%s\"%s" % (
            _nd(h.get("position")), _nd(h.get("level")), _nd(h.get("zone")), _nd(h.get("text")), dup))
    L.append("Count per level: %s" % dict(lvl))
    dups = {t: c for t, c in texts.items() if c > 1}
    L.append("Duplicate heading texts: %s" % (dups if dups else "none"))
    L.append("(No competitor data is provided for this section.)")
    return "\n".join(L)


def adat_s83(ao):
    ss = _ss(ao); ls = ss.get("list_structure") or {}; tb = ss.get("table_structure") or {}
    ent = _client_raw(ao).get("entity_counts") or {}; words = _client_raw(ao).get("main_content_words")
    L = []
    L.append("Lists: ul=%s, ol=%s, li=%s, dl=%s" % (_nd(ls.get("ul")), _nd(ls.get("ol")), _nd(ls.get("li")), _nd(ls.get("dl"))))
    L.append("Tables: table=%s, thead=%s, tbody=%s, th=%s, tr=%s" % (
        _nd(tb.get("table")), _nd(tb.get("thead")), _nd(tb.get("tbody")), _nd(tb.get("th")), _nd(tb.get("tr"))))
    L.append("Blockquote: %s (with cite: %s)" % (_nd(ss.get("blockquote_count")), _nd(ss.get("blockquote_with_cite"))))
    L.append("Figure: %s (with figcaption: %s)" % (_nd(ss.get("figure_count")), _nd(ss.get("figure_with_figcaption"))))
    L.append("Suspicious div pseudo-table: %s | semantic-to-visual ratio: %s" % (
        _nd(ss.get("div_table_suspicious")), _nd(ss.get("semantic_to_visual_ratio"))))
    L.append("Entity density (in content): organizations=%s, products=%s, technologies=%s, concepts=%s, places=%s, people=%s" % (
        _nd(ent.get("organizations")), _nd(ent.get("products")), _nd(ent.get("technologies")),
        _nd(ent.get("concepts")), _nd(ent.get("places")), _nd(ent.get("people"))))
    L.append("Main content word count (context): %s" % _nd(words))
    L.append("(No competitor data is provided for this section.)")
    return "\n".join(L)


def adat_s84(ao):
    ss = _ss(ao); ie = ss.get("inline_emphasis") or {}; lk = ss.get("link_semantic") or {}
    words = _client_raw(ao).get("main_content_words")
    L = []
    L.append("Semantic emphasis: strong=%s, em=%s | visual-only: b=%s, i=%s" % (
        _nd(ie.get("strong")), _nd(ie.get("em")), _nd(ie.get("b")), _nd(ie.get("i"))))
    L.append("Emphasis RATIO: not directly measured (raw count: %s strong, against ~%s words — exact %% not measured)" % (
        _nd(ie.get("strong")), _nd(words)))
    L.append("Total links: %s | non-descriptive/generic anchor text: %s" % (
        _nd(lk.get("anchor_count")), _nd(lk.get("generic_anchor_text_count"))))
    L.append("Open-in-new-tab (target=_blank): %s | without safety rel: %s" % (
        _nd(lk.get("blank_target_count")), _nd(lk.get("blank_target_unsafe_count"))))
    L.append("Separate nofollow measurement: %s" % NO_DATA)
    L.append("(No competitor data is provided for this section.)")
    return "\n".join(L)


def adat_s85(ao):
    fo = _afm(ao).get("forms") or {}; ar = _afm(ao).get("aria") or {}
    fq = _ss(ao).get("form_quality_extended") or {}
    lc = fo.get("label_coverage")
    L = []
    L.append("Forms: %s" % _nd(fq.get("form_count")))
    L.append("Input fields: %s in the rendered main view; %s in full HTML (incl. hidden fields)" % (
        _nd(fo.get("input_count")), _nd(fq.get("input_count"))))
    # AAA-151 S3: gate form-attribute facts (label coverage / input types /
    # submission) on a real form; with 0 inputs they describe a non-existent form.
    if (fo.get("input_count") or 0) > 0:
        L.append("Label coverage: %s" % (("%.1f%%" % (lc * 100)) if isinstance(lc, (int, float)) else NO_DATA))
        L.append("Input-type distribution: %s" % _nd(fq.get("input_type_distribution")))
        L.append("Submission: input[type=submit] present (standard); button[type=submit] count: %s" % _nd(fq.get("submit_button_count")))
    else:
        L.append("No form or input fields on the page (label coverage / input types / submission mechanism not applicable).")
    L.append("Elements with ARIA: %s | total interactive: %s" % (_nd(ar.get("with_aria_count")), _nd(ar.get("interactive_count"))))
    L.append("(No competitor data is provided for this section.)")
    return "\n".join(L)


def adat_s86(ao):
    cl = _client_raw(ao); a = resolve_anchor(ao) or {}; anchor = anchor_name(ao)
    ksch = _dim_present_key(ao, C_SCHEMA)
    gap = _g(_dim(ao), ksch, "gap") if ksch else None
    L = []
    L.append("Client schema types (%s): %s" % (_nd(cl.get("schema_count")), _nd(cl.get("schema_types"))))
    L.append("Page type: %s (business model: %s)" % (_nd(page_type_fallback(ao)), _nd(ao.get("business_model"))))
    if anchor:
        L.append("%s schema types (%s): %s" % (anchor, _nd(a.get("schema_count")), _nd(a.get("schema_types"))))
    else:
        L.append("Competitor schema types: no competitor was measured for this audit.")
    L.append("Missing industry-specific schemas (measured gap): %s" % _nd(gap))
    return "\n".join(L)


def adat_s9(ao):
    cr = ao.get("crawl") or {}; meta = cr.get("meta") or {}
    ss = _ss(ao); ht = ss.get("heading_tree") or []
    h1s = [h.get("text") for h in ht if h.get("level") == 1]
    img = cr.get("images") or {}; ar = _afm(ao).get("aria") or {}; fo = _afm(ao).get("forms") or {}
    atf = (ao.get("aaa124_aspect_evaluations") or {}).get("above_the_fold") or {}
    lc = fo.get("label_coverage")
    L = []
    L.append("ABOVE-THE-FOLD indirect signals (exact fold-line NOT measured):")
    L.append("- Title: %s" % _nd(_g(meta, "title", "text")))
    L.append("- Meta description: %s" % _nd(_g(meta, "description", "text")))
    L.append("- Main heading (H1): %s (total %s H1)" % ((h1s[0] if h1s else NO_DATA), (len(h1s) if h1s else NO_DATA)))
    L.append("- Hero image: NO dedicated hero-image measurement; only aggregate image data: total=%s, with alt=%s, alt coverage=%s%%" % (
        _nd(img.get("total_count")), _nd(img.get("with_alt")), _nd(img.get("alt_coverage_percent"))))
    L.append("- Primary CTA presence/position: NO direct measurement; indirect: native buttons=0, interactive=%s, with ARIA=%s" % (
        _nd(ar.get("interactive_count")), _nd(ar.get("with_aria_count"))))
    L.append("- Fold-line position and exact CTA placement: %s" % NO_DATA)
    L.append("- Holistic context observation: %s" % _nd((atf.get("structured_finding") or atf.get("justification"))))
    L.append("FORMS (conversion lens, NOT a technical fix):")
    # AAA-151 S3: gate on a real form (input_count > 0). The previous hardcoded
    # "Forms: 2" asserted a phantom form regardless of measurement.
    if (fo.get("input_count") or 0) > 0:
        L.append("- Conversion form inputs: %s visible fields | submission: present (standard)" % _nd(fo.get("input_count")))
        L.append("- Field-label coverage (label, NOT placeholder) as a completion-friction signal: %s" % (
            ("%.1f%%" % (lc * 100)) if isinstance(lc, (int, float)) else NO_DATA))
    else:
        L.append("- No form or input fields on the page; do NOT reference form fields, label coverage, or input attributes.")
    return "\n".join(L)


def adat_s10(ao):
    idx = ao.get("indexing") or {}; tech = _g(ao, "crawl", "technical") or {}
    ps = ao.get("pagespeed") or {}
    crux = _g(ao, "crux_field_data", "origin_level", "metrics") or {}
    L = []
    L.append("Indexed: %s" % _nd(idx.get("indexed")))
    L.append("Canonical URL (corrected value): %s" % _nd(corrected_canonical(ao)))
    # AAA-151: explicit, mismatch-gated canonical status so the narrative does
    # NOT report a "canonical missing/discrepancy" off a null. Only a real
    # canonical_mismatch == True is a discrepancy; a present self-canonical with
    # mismatch False/None is clean.
    _can_present = bool(_g(ao, "crawl", "technical", "canonical", "present"))
    L.append("Canonical tag present on page: %s; canonical/indexing discrepancy: %s" % (
        _nd(_can_present), "yes" if idx.get("canonical_mismatch") is True else "no"))
    L.append("HTTPS: %s" % _nd(tech.get("https")))
    L.append("Redirect chain (client-side, no competitor data): %s" % _nd(tech.get("redirect_chain")))
    L.append("PageSpeed: mobile=%s, desktop=%s" % (
        _nd(_g(ps, "mobile", "scores", "performance")), _nd(_g(ps, "desktop", "scores", "performance"))))
    kp = _dim_present_key(ao, C_PERF_DESKTOP)
    if kp:
        L.append(_dim_line(ao, kp, anchor_name(ao)))
    else:
        L.append("  - Desktop speed (PageSpeed) comparison: %s" % NO_DATA)
    L.append("CrUX (client-side, no competitor data): LCP=%s, CLS=%s, INP=%s" % (
        _nd(_g(crux, "lcp", "category")), _nd(_g(crux, "cls", "category")), _nd(_g(crux, "inp", "category"))))
    return "\n".join(L)


def adat_s11(ao):
    ss = _ss(ao); fo = _afm(ao).get("forms") or {}; lc = fo.get("label_coverage")
    fq = ss.get("form_quality_extended") or {}
    has_tel = "tel" in (fq.get("input_type_distribution") or {})
    idx = ao.get("indexing") or {}; tech = _g(ao, "crawl", "technical") or {}
    crux = _g(ao, "crux_field_data", "origin_level", "metrics") or {}
    crs = (_re(ao).get("client_ranking_status") or {}).get("branded") or {}
    aio = ao.get("ai_overview") or {}; cg = ao.get("chatgpt_query_response") or {}
    pats = _comp(ao).get("patterns") or []
    anchor = anchor_name(ao)
    if anchor and _dim(ao):
        L = ["MEASURED GAPS (anchored to %s):" % anchor]
        L.extend(_all_dim_lines(ao, anchor))
    else:
        L = ["MEASURED GAPS: no competitor was measured for this audit; no competitor comparison is available."]
    L.append("PATTERNS (with measured severity — drives the priority order):")
    for p in pats:
        L.append("  - [%s] %s" % (_nd(p.get("severity")), _nd(p.get("finding"))))
    L.append("KEY STRUCTURAL FINDINGS (separate topics):")
    L.append("  - Heading hierarchy: organize same-level headings under H2 main topics (zone: %s)" % _nd(ss.get("headings_by_zone")))
    # AAA-151 S3: only assert form/field-attribute facts when a form actually
    # exists (input_count > 0). With 0 inputs, "type=tel MISSING" is a fact about
    # a non-existent field -> the LLM fabricates a phone field. Gate it.
    if (fo.get("input_count") or 0) > 0:
        L.append("  - Conversion form: %s visible fields, label coverage %s (friction)" % (
            _nd(fo.get("input_count")), (("%.1f%%" % (lc * 100)) if isinstance(lc, (int, float)) else NO_DATA)))
        L.append("  - Mobile field type: type=tel %s" % ("present" if has_tel else "MISSING"))
    else:
        L.append("  - Conversion form: none on the page (no form/input fields measured; do NOT "
                 "recommend form-field, label, or type=tel changes)")
    L.append("  - Semantic HTML / zones: all headings in the main content zone, no structural noise")
    L.append("MEASURED STRENGTHS: indexed=%s, HTTPS=%s, clean canonical=%s, CrUX LCP=%s / CLS=%s" % (
        _nd(idx.get("indexed")), _nd(tech.get("https")), _nd(corrected_canonical(ao)),
        _nd(_g(crux, "lcp", "category")), _nd(_g(crux, "cls", "category"))))
    L.append("BUSINESS STAKE: in top 10=%s (position %s); AI Overview client_cited=%s, ChatGPT target_cited=%s" % (
        _nd(crs.get("found_in_top_10")), _nd(crs.get("position")), _nd(aio.get("client_cited")), _nd(cg.get("target_site_cited"))))
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Section registry
# ---------------------------------------------------------------------------

class Section:
    __slots__ = ("id", "title", "domain", "feladat", "schema_guard", "comparison", "adat_assembler")

    def __init__(self, id, title, domain, feladat, schema_guard, comparison, adat_assembler):
        self.id = id
        self.title = title
        self.domain = domain
        self.feladat = feladat
        self.schema_guard = schema_guard
        self.comparison = comparison
        self.adat_assembler = adat_assembler


_D = {
 "§1": "Opening section of the report: the executive should grasp the main message in ~20 seconds — why the site is not visible organically and in AI search, and the 2-3 biggest reasons. This is a framing lead-in, not a deep analysis.",
 "§2": "Search engines and AI identify from the content who you are (brand), what business, who it serves, and on what topic. IMPORTANT: the page's own search intent (page-intent) and the targeted keyword's intent are two different things — do not conflate them. If the page-intent is navigational while the targeted keyword is transactional, frame the mismatch explicitly as the actionable insight (the homepage isn't optimized to capture that transactional search) — don't merely label the page 'navigational'. If a language variant is identified, name it precisely (e.g. 'the Hungarian-language homepage'), not just 'the homepage'.",
 "§3": "A page surfaces if you target a good keyword, with the right TYPE of page, AND enough content depth for Google to actually rank it. Two gates: (1) type fit, (2) does it deserve to rank. Hub: only press the hub frame for a true collection page.",
 "§4": "Who competes with you for the same searches, and who we benchmark against in detail. Show the driver keyword first. The primary competitor named in the data is the consistent anchor; the others are landscape context. Do not conflate the selected list with the measured list. Use ONLY competitor names that appear in the provided data.",
 "§5": "The 'you vs. the market leader' overview across the measurable dimensions — where and by how much you lag, and the priority. A comparison table is allowed. Anchor = the primary competitor named in the data.",
 "§6": "More and more searches end in an AI answer. If you are not cited there as a source, you are invisible. Frame the absence as an opportunity (query-dependent). AI Overview + ChatGPT + fan-out.",
 "§7": "Content depth, coverage, and professional credibility — is it detailed and expert enough. NO numeric score — qualitative analysis plus facts.",
 "§8.1": "The page skeleton must be split into zones: the real content in the main zone; header/nav/footer are structural noise. Logical sections belong in separate blocks.",
 "§8.2": "Headings (H1-H6) form the skeleton. Exactly one H1; a logical hierarchy without level skips; menu items must not be headings; no duplicate or dumped same-level headings.",
 "§8.3": "HTML5 elements aid extraction: lists for enumerations, tables for prices/comparisons/specs, blockquote for quotes, figure/figcaption for images. A process/enumeration without a list/table is a gap.",
 "§8.4": "Emphasize important parts with semantic tags (strong/em), not visual ones (b/i); optimum ~5-10%. Descriptive link text (not 'click here'). External target=_blank needs rel=noopener/noreferrer.",
 "§8.5": "Every field needs its own label bound to the input id (accessibility + mobile autofill). Field-specific input type (email/tel) drives the mobile keyboard. input[type=submit] is a standard submission mechanism — the absence of button[type=submit] is NOT an error.",
 "§8.6": "JSON-LD structured data must fit the page type: Organization for B2B, SoftwareApplication and Offer for a software product. Their absence loses rich snippets and weakens AI interpretability. Anchor = the primary competitor named in the data.",
 "§9": "The above-the-fold area decides the first impression. CONCEPTUAL: a label (always-visible caption bound to an input) is NOT a placeholder. Fold-line/CTA position is NOT measured -> treat conditionally. Forms: conversion angle only, do not prescribe the technical label fix.",
 "§10": "Technical foundations in business terms: is it indexable, fast (especially on mobile), and is the canonical/redirect clean. indexation = is it in Google's database; canonical = the 'official' URL; PageSpeed = a speed score; CrUX = real-user experience.",
 "§11": "Closing section of the report — prioritized action summary. CONSOLIDATE, do not repeat. Priority order by measured severity (high -> medium -> low). For competitor data, anchor to the primary competitor named in the data.",
}

SECTION_REGISTRY = [
    Section("§1", "Opening / main diagnosis", _D["§1"], FELADAT_1, True, True, adat_s1),
    Section("§2", "Identification and context", _D["§2"], TASK_STD, True, False, adat_s2),
    Section("§3", "Keywords and search intent", _D["§3"], TASK_STD, False, True, adat_s3),
    Section("§4", "Competitors", _D["§4"], TASK_STD, False, False, adat_s4),
    Section("§5", "Comparison with the best", _D["§5"], TASK_STD, True, True, adat_s5),
    Section("§6", "AI visibility", _D["§6"], TASK_STD, False, True, adat_s6),
    Section("§7", "Content quality", _D["§7"], TASK_STD, False, True, adat_s7),
    Section("§8.1", "Zones / macro-structure", _D["§8.1"], TASK_STD, False, False, adat_s81),
    Section("§8.2", "Heading hierarchy", _D["§8.2"], TASK_STD, False, False, adat_s82),
    Section("§8.3", "Micro-semantics + HTML5", _D["§8.3"], TASK_STD, False, False, adat_s83),
    Section("§8.4", "Inline + link semantics", _D["§8.4"], TASK_STD, False, False, adat_s84),
    Section("§8.5", "Forms", _D["§8.5"], TASK_STD, False, False, adat_s85),
    Section("§8.6", "Schema (structured data)", _D["§8.6"], TASK_STD, True, True, adat_s86),
    Section("§9", "Above-the-fold + conversion points", _D["§9"], TASK_STD, False, False, adat_s9),
    Section("§10", "Technical health", _D["§10"], TASK_STD, False, True, adat_s10),
    Section("§11", "Closing prioritized summary", _D["§11"], FELADAT_11, True, False, adat_s11),
]


def assemble_prompt(section, audit_output):
    """AUDIENCE + DOMAIN + (SCHEMA_GUARD if flagged) + DATA + FELADAT(+GROUNDING_RULES)."""
    parts = ["[AUDIENCE]\n" + AUDIENCE, "[DOMAIN]\n" + section.domain]
    if section.schema_guard:
        parts.append("[GUARD]\n" + SCHEMA_GUARD)
    parts.append("[DATA]\n" + section.adat_assembler(audit_output))
    parts.append("[TASK]\n" + section.feladat)
    return "\n\n".join(parts)


def render_section_12(audit_output):
    sfa = (audit_output.get("serp_fit_analysis") or [{}])[0]
    keyword = sfa.get("keyword") or (audit_output.get("target_keywords") or {}).get("primary_keyword") or NO_DATA
    competitor = anchor_name(audit_output) or "the market leader"
    return SECTION_12_TEMPLATE.format(competitor=competitor, keyword=keyword)


# ---------------------------------------------------------------------------
# Gemini render layer (one call per section; §12 stays static) + HU pass
# ---------------------------------------------------------------------------

def _make_client(project=None, location="global"):
    from site_profile.gemini_analyzer import make_genai_client  # AAA-155 (retry)
    return make_genai_client(project=project, location=location)


def _gen(client, contents, model):
    from google.genai import types
    from site_profile.gemini_analyzer import compute_call_cost_usd
    cfg = types.GenerateContentConfig(
        temperature=0.3, thinking_config=types.ThinkingConfig(thinking_level="LOW"))
    r = client.models.generate_content(model=model, contents=contents, config=cfg)
    um = r.usage_metadata
    itok = getattr(um, "prompt_token_count", 0) or 0
    otok = ((getattr(um, "candidates_token_count", 0) or 0)
            + (getattr(um, "thoughts_token_count", 0) or 0))
    thoughts = getattr(um, "thoughts_token_count", 0) or 0
    cost = round(compute_call_cost_usd(model, itok, otok), 6)
    return (r.text or "").strip(), itok, otok, thoughts, cost


def render_section(section, audit_output, client, *, model=RENDER_MODEL):
    text, itok, otok, thoughts, cost = _gen(client, assemble_prompt(section, audit_output), model)
    return {"id": section.id, "title": section.title, "text": text,
            "input_tokens": itok, "output_tokens": otok, "thoughts_tokens": thoughts, "cost_usd": cost}


def translate_to_hu(en_text, client, *, model=RENDER_MODEL):
    text, itok, otok, thoughts, cost = _gen(client, TRANSLATION_PASS.format(section=en_text), model)
    return {"text": text, "input_tokens": itok, "output_tokens": otok, "cost_usd": cost}


def render_report(audit_output, *, client=None, project=None, location="global",
                  model=RENDER_MODEL, translate=False):
    """Render all 16 prompted sections (EN) + static §12. If translate=True, also
    run the EN->HU pass on each section and on §12."""
    client = client or _make_client(project=project, location=location)
    sections, total = [], 0.0
    for s in SECTION_REGISTRY:
        res = render_section(s, audit_output, client, model=model)
        if translate:
            hu = translate_to_hu(res["text"], client, model=model)
            res["text_hu"] = hu["text"]
            res["hu_cost_usd"] = hu["cost_usd"]
            res["hu_input_tokens"] = hu["input_tokens"]
            res["hu_output_tokens"] = hu["output_tokens"]
            total += hu["cost_usd"]
        total += res["cost_usd"]
        sections.append(res)
    s12_en = render_section_12(audit_output)
    s12_hu = translate_to_hu(s12_en, client, model=model) if translate else None
    if s12_hu:
        total += s12_hu["cost_usd"]
    return {"sections": sections, "section_12": s12_en,
            "section_12_hu": (s12_hu["text"] if s12_hu else None),
            "total_cost_usd": round(total, 6)}


def assemble_document(out, lang):
    """Join the rendered sections (+ §12) into one markdown document.
    lang='en' uses section['text'] + section_12; lang='hu' uses text_hu + section_12_hu.

    PARSER CONTRACT (AAA-143): every section is delimited by a machine-generated
    level-2 header of the exact form `## §<id> — <title>` (em-dash U+2014, single
    spaces). report/html_render.split_sections depends on this — section bodies use
    only ###/#### internally. Do NOT change this heading shape without updating the
    renderer's SECTION_HEADER_RE / split regex."""
    key = "text" if lang == "en" else "text_hu"
    parts = []
    for s in out["sections"]:
        body = s.get(key) or s.get("text") or ""
        parts.append("## %s — %s\n\n%s" % (s["id"], s["title"], body))
    s12 = out["section_12"] if lang == "en" else (out.get("section_12_hu") or out["section_12"])
    parts.append(s12)
    return "\n\n".join(parts)


def build_customer_summary_translations(audit_output, *, client=None):
    """Ship entry point: render the full bilingual customer report and return the
    {"en", "hu"} documents (+ cost). Skip-finding: any failure -> {"_error": ...},
    never raises — callers persist the flag and continue."""
    try:
        out = render_report(audit_output, client=client, translate=True)
        return {
            "en": assemble_document(out, "en"),
            "hu": assemble_document(out, "hu"),
            "cost_usd": out["total_cost_usd"],
        }
    except Exception as e:  # noqa: BLE001 — skip-finding contract
        return {"_error": "%s: %s" % (type(e).__name__, e)}
