"""AAA-96 Phase 1 Sub-step 1 — deterministic Readiness scoring engine.

Pure-Python, NO AI, NO UI, NO network. Transforms a stored audit_output into
pillar sub-scores (0-100) + a weighted overall + band. rubric_version="v1".

Skip-finding contract: a missing/None sub-criterion is DROPPED and the pillar
renormalizes over the criteria that are present; a pillar with NO usable input
returns None and is excluded from the overall (overall renormalizes over the
present pillars' weights). Content Quality is an OPTIONAL input (AI-judged in a
later phase); absent -> cq_status="pending" and its weight drops out.

Every coefficient here is INITIAL and meant to be tuned — the formulas are
reported verbatim via FORMULAS + the per-aspect functions.
"""
from __future__ import annotations

RUBRIC_VERSION = "v1"

# Pillar weights (sum = 100). CQ is AI-judged (later phase); optional here.
WEIGHTS = {
    "findability": 15,
    "content_quality": 25,       # AI — optional this sub-step
    "semantic_structure": 15,
    "technical": 15,
    "ai_visibility": 20,
    "keywords": 5,
    "eeat": 5,
}

BANDS = [(80, "Excellent"), (60, "Good"), (40, "Needs work"), (0, "Poor")]


def _band(score: float | None) -> str | None:
    if score is None:
        return None
    for floor, name in BANDS:
        if score >= floor:
            return name
    return "Poor"


def _wavg(parts: list[tuple[float | None, float]]) -> float | None:
    """Weighted average over (value_0_1 | None, weight); drops None and
    renormalizes. Returns 0-100 or None if every value is None."""
    kept = [(v, w) for v, w in parts if v is not None and w > 0]
    if not kept:
        return None
    tot_w = sum(w for _, w in kept)
    return round(100.0 * sum(v * w for v, w in kept) / tot_w, 1)


def _get(d: dict | None, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


# ---------------------------------------------------------------------------
# FINDABILITY  (indexing AAA-136 + crawl.technical + phase2 2MB)
# ---------------------------------------------------------------------------
def score_findability(ao: dict) -> tuple[float | None, dict]:
    idx = ao.get("indexing") or {}
    tech = _get(ao, "crawl", "technical", default={}) or {}
    cut = _get(ao, "phase2_html_measurements", "google_2mb_cutoff", default={}) or {}

    indexed = idx.get("indexed")
    c_mismatch = idx.get("canonical_mismatch")
    dup = idx.get("duplication_signal")
    https = tech.get("https")
    chain = tech.get("redirect_chain")
    exceeds = cut.get("exceeds_2mb_cutoff")

    # redirect_chain clean: list incl. start+final. 1 entry=no redirect, 2=one
    # canonical hop (fine), >2=chained (partial credit).
    chain_v = None
    if isinstance(chain, list) and chain:
        chain_v = 1.0 if len(chain) <= 2 else 0.5

    # AAA-96 S2 Part A (comment 13221): when `indexed` is unmeasured
    # (None/"unknown"), KEEP the criterion at a NEUTRAL 0.5 (do NOT drop it) so
    # unmeasured-indexing pages land ~60-70, not 100. The dependent
    # canonical_mismatch / duplication_signal keep the minor-signal drop+renorm.
    indexing_not_confirmed = indexed in (None, "unknown")
    if indexed is True:
        indexed_v = 1.0
    elif indexed is False:
        indexed_v = 0.0
    else:
        indexed_v = 0.5  # neutral, kept

    parts = [
        (indexed_v, 50),
        (1.0 if c_mismatch is False else (0.0 if c_mismatch is True else None), 15),
        (1.0 if dup is False else (0.0 if dup is True else None), 10),
        (1.0 if https is True else (0.0 if https is False else None), 10),
        (chain_v, 10),
        (1.0 if exceeds is False else (0.0 if exceeds is True else None), 5),
    ]
    return _wavg(parts), {
        "indexed": indexed, "indexing_not_confirmed": indexing_not_confirmed,
        "canonical_mismatch": c_mismatch,
        "duplication_signal": dup, "https": https,
        "redirect_chain_len": len(chain) if isinstance(chain, list) else None,
        "exceeds_2mb": exceeds,
    }


# ---------------------------------------------------------------------------
# SEMANTIC STRUCTURE  (7 AAA-124 aspects, deterministic measured grades)
# above_the_fold = NEUTRAL/excluded (no clean objective measure).
# ---------------------------------------------------------------------------
def _g_macro(ao: dict) -> float | None:
    lm = _get(ao, "agent_friendly_measurements", "landmarks", default={}) or {}
    present = set(lm.get("present") or [])
    sh = _get(ao, "agent_friendly_measurements", "semantic_html", default={}) or {}
    core = {"nav", "main", "header", "footer"}
    if not lm.get("present") and not lm.get("missing"):
        return None
    score = len(present & core) / 4.0
    if sh.get("has_div_onclick_antipattern"):
        score = max(0.0, score - 0.2)
    return round(score, 4)


def _g_heading(ao: dict) -> float | None:
    h = _get(ao, "agent_friendly_measurements", "heading", default=None)
    if not isinstance(h, dict):
        return None
    total = h.get("total_headings")
    if total is None:
        return None
    if total == 0:
        return 0.0  # no heading hierarchy at all
    s = 0.0
    s += 0.5 if h.get("h1_count") == 1 else (0.2 if (h.get("h1_count") or 0) >= 1 else 0.0)
    s += 0.25 if (h.get("level_skips") or 0) == 0 else 0.0
    s += 0.25 if total >= 3 else 0.1  # some hierarchy depth
    return round(min(1.0, s), 4)


def _g_micro(ao: dict) -> float | None:
    aria = _get(ao, "agent_friendly_measurements", "aria", default={}) or {}
    sh = _get(ao, "agent_friendly_measurements", "semantic_html", default={}) or {}
    ss = _get(ao, "phase2_html_measurements", "semantic_structure", default={}) or {}
    inter = aria.get("interactive_count")
    aria_cov = (aria.get("with_aria_count", 0) / inter) if inter else None
    emph = ss.get("inline_emphasis") or {}
    has_emph = 1.0 if sum(v for v in emph.values() if isinstance(v, int)) > 0 else 0.0
    lists = ss.get("list_structure") or {}
    has_lists = 1.0 if sum(v for v in lists.values() if isinstance(v, int)) > 0 else 0.0
    parts = [(aria_cov, 0.5), (has_emph, 0.25), (has_lists, 0.25)]
    g = _wavg(parts)
    if g is None:
        return None
    g = g / 100.0
    if sh.get("has_div_onclick_antipattern"):
        g = max(0.0, g - 0.15)
    return round(g, 4)


def _g_schema(ao: dict) -> float | None:
    actions = _get(ao, "agent_friendly_measurements", "schema_actions", default=None)
    sm = _get(ao, "crawl", "schema_markup", default={}) or {}
    blocks = sm.get("json_ld_blocks") or []
    match = _get(ao, "phase2_html_measurements", "semantic_structure",
                 "schema_pagetype_match", "match", default=None)
    if actions is None and not blocks and match is None:
        return None
    s = 0.0
    s += 0.4 if blocks else 0.0
    s += 0.3 if match is True else 0.0
    s += 0.3 if (actions and len(actions) > 0) else 0.0
    return round(s, 4)


def _g_forms(ao: dict) -> float | None:
    f = _get(ao, "agent_friendly_measurements", "forms", default=None)
    if not isinstance(f, dict):
        return None
    if (f.get("input_count") or 0) == 0:
        return None  # no forms to grade -> skip (renormalize)
    lc = f.get("label_coverage")
    return round(float(lc), 4) if isinstance(lc, (int, float)) else None


def _g_inline_link(ao: dict) -> float | None:
    links = _get(ao, "crawl", "links", default={}) or {}
    anchors = links.get("internal_anchors")
    if not isinstance(anchors, list) or not anchors:
        return None
    described = sum(1 for a in anchors if (a.get("text") or "").strip())
    return round(described / len(anchors), 4)


SEM_ASPECTS = {
    "macro_structure": _g_macro,
    "heading_semantics": _g_heading,
    "micro_semantics": _g_micro,
    "schema_entity": _g_schema,
    "forms_conversion_points": _g_forms,
    "inline_link_semantics": _g_inline_link,
    # above_the_fold intentionally absent — NEUTRAL/narrative-only.
}


def score_semantic_structure(ao: dict) -> tuple[float | None, dict]:
    grades = {name: fn(ao) for name, fn in SEM_ASPECTS.items()}
    grades["above_the_fold"] = None  # excluded (narrative-only)
    parts = [(g, 1.0) for n, g in grades.items()
             if n != "above_the_fold" and g is not None]
    return _wavg(parts), grades


# ---------------------------------------------------------------------------
# TECHNICAL & SPEED
# ---------------------------------------------------------------------------
_CWV_CAT = {"FAST": 1.0, "GOOD": 1.0, "AVERAGE": 0.5, "NEEDS_IMPROVEMENT": 0.5,
            "SLOW": 0.0, "POOR": 0.0}


def score_technical(ao: dict) -> tuple[float | None, dict]:
    ps = ao.get("pagespeed") or {}
    m_perf = _get(ps, "mobile", "scores", "performance")
    d_perf = _get(ps, "desktop", "scores", "performance")
    metrics = _get(ao, "crux_field_data", "origin_level", "metrics", default={}) or {}
    cwv_vals = []
    for k in ("lcp", "cls", "inp"):
        cat = (metrics.get(k) or {}).get("category")
        if cat:
            cwv_vals.append(_CWV_CAT.get(str(cat).upper(), 0.5))
    cwv = (sum(cwv_vals) / len(cwv_vals)) if cwv_vals else None
    csr = _get(ao, "phase2_html_measurements", "rendering_mode", "is_csr_likely")
    csr_v = 0.0 if csr is True else (1.0 if csr is False else None)

    parts = [
        ((m_perf / 100.0) if isinstance(m_perf, (int, float)) else None, 40),
        ((d_perf / 100.0) if isinstance(d_perf, (int, float)) else None, 20),
        (cwv, 30),
        (csr_v, 10),
    ]
    return _wavg(parts), {
        "mobile_perf": m_perf, "desktop_perf": d_perf,
        "cwv_good_frac": round(cwv, 3) if cwv is not None else None,
        "is_csr_likely": csr,
    }


# ---------------------------------------------------------------------------
# AI VISIBILITY  (fairness: presence positive; absence -> lower floor, not 0)
# ---------------------------------------------------------------------------
def score_ai_visibility(ao: dict) -> tuple[float | None, dict]:
    cited = _get(ao, "chatgpt_query_response", "target_site_cited")
    # cited True -> 1.0; explicitly not cited -> 0.3 floor (opportunity, not 0)
    cited_v = 1.0 if cited is True else (0.3 if cited is False else None)
    aio = ao.get("ai_overview_triggered")
    # AIO present -> 0.7 (citation field not reliably captured); absent -> 0.3
    aio_v = 0.7 if aio is True else (0.3 if aio is False else None)
    fe = ao.get("fan_out_enriched") or []
    cov_map = {"covered": 1.0, "partial": 0.5, "missing": 0.0,
               "off_topic": 0.0}  # n_a -> skip
    cov_vals = [cov_map[e.get("coverage")] for e in fe
                if e.get("coverage") in cov_map]
    cov = (sum(cov_vals) / len(cov_vals)) if cov_vals else None
    parts = [(cited_v, 45), (aio_v, 35), (cov, 20)]
    return _wavg(parts), {
        "chatgpt_cited": cited, "ai_overview_triggered": aio,
        "fan_out_coverage_frac": round(cov, 3) if cov is not None else None,
        "fan_out_n": len(cov_vals),
    }


# ---------------------------------------------------------------------------
# KEYWORDS & INTENT
# ---------------------------------------------------------------------------
_GAP_MAP = {"none": 1.0, "low": 0.7, "minor": 0.7, "medium": 0.4,
            "moderate": 0.4, "high": 0.1, "severe": 0.1}


def score_keywords(ao: dict) -> tuple[float | None, dict]:
    tkc = ao.get("target_keywords_classified") or []
    rels = [c.get("relevance_score") for c in tkc
            if isinstance(c.get("relevance_score"), (int, float))]
    rel_avg = (sum(rels) / len(rels)) if rels else None
    # intent-coverage: fraction of classified kws carrying a search_intent
    intent_cov = None
    if tkc:
        with_intent = sum(1 for c in tkc if (c.get("search_intent") or "").strip())
        intent_cov = with_intent / len(tkc)
    gap = (ao.get("target_keywords") or {}).get("keyword_gap_severity")
    gap_v = _GAP_MAP.get(str(gap).lower()) if gap is not None else None
    parts = [(rel_avg, 60), (intent_cov, 25), (gap_v, 15)]
    return _wavg(parts), {
        "relevance_avg": round(rel_avg, 3) if rel_avg is not None else None,
        "intent_coverage": round(intent_cov, 3) if intent_cov is not None else None,
        "gap_severity": gap, "n_keywords": len(tkc),
    }


# ---------------------------------------------------------------------------
# E-E-A-T  (presence-based)
# ---------------------------------------------------------------------------
def score_eeat(ao: dict) -> tuple[float | None, dict]:
    e = ao.get("eeat_signals") or {}
    bm = e.get("brand_mentions")
    np = e.get("named_people")
    sp = e.get("social_proof_links")
    if bm is None and np is None and sp is None:
        return None, {}
    parts = [
        (1.0 if (bm) else 0.0, 40),
        (1.0 if (np) else 0.0, 30),
        (1.0 if (sp) else 0.0, 30),
    ]
    return _wavg(parts), {
        "brand_mentions": len(bm or []), "named_people": len(np or []),
        "social_proof_links": len(sp or []),
    }


# ---------------------------------------------------------------------------
# AAA-96 S2 Parts B–E: findings / severity / quick-wins / flags
# ---------------------------------------------------------------------------
SEVERITY_SCORE = {"critical": 4, "high": 3, "medium": 2, "low": 1}
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}  # tiebreak

# AAA-96 S3 Part B (decision 13223): aspects grading >= this emit NO finding
# ("fine"); only grade < THRESHOLD emits. Tunable (0.5 / 0.6 / 0.65).
ASPECT_FINDING_THRESHOLD = 0.6

PILLAR_LABELS = {
    "findability": "Findability", "content_quality": "Content Quality",
    "semantic_structure": "Semantic Structure", "technical": "Technical & Speed",
    "ai_visibility": "AI Visibility", "keywords": "Keywords & Intent",
    "eeat": "E-E-A-T",
}
PILLAR_ORDER = ["findability", "content_quality", "semantic_structure",
                "technical", "ai_visibility", "keywords", "eeat"]

# Per-pillar signal specs: (signal_name, detail_key, contribution_weight).
# `contribution` = the criterion's weight in the pillar formula (the share it
# carries), surfaced for transparency. semantic_structure is built from its
# per-aspect grades separately.
SIGNAL_SPECS = {
    "findability": [("indexed", "indexed", 50),
                    ("canonical_match", "canonical_mismatch", 15),
                    ("no_duplication", "duplication_signal", 10),
                    ("https", "https", 10),
                    ("redirect_chain", "redirect_chain_len", 10),
                    ("under_2mb", "exceeds_2mb", 5)],
    "technical": [("mobile_performance", "mobile_perf", 40),
                  ("desktop_performance", "desktop_perf", 20),
                  ("core_web_vitals", "cwv_good_frac", 30),
                  ("server_rendered", "is_csr_likely", 10)],
    "ai_visibility": [("chatgpt_cited", "chatgpt_cited", 45),
                      ("ai_overview", "ai_overview_triggered", 35),
                      ("fan_out_coverage", "fan_out_coverage_frac", 20)],
    "keywords": [("keyword_relevance", "relevance_avg", 60),
                 ("intent_coverage", "intent_coverage", 25),
                 ("keyword_gap", "gap_severity", 15)],
    "eeat": [("brand_mentions", "brand_mentions", 40),
             ("named_people", "named_people", 30),
             ("social_proof_links", "social_proof_links", 30)],
}

# Effort weight per finding CODE (Part D). low=1, low-med=1.5, med=2,
# med-high=2.5, high=3. Tunable lookup.
EFFORT_BY_CODE = {
    "not_indexed": 2.5,            # diagnose why; could be robots/canonical/new
    "canonical_mismatch": 1.0,     # fix canonical tag
    "duplication_signal": 1.5,     # consolidate variants + canonical/redirects
    "indexing_not_confirmed": 1.0, # request indexing / verify GSC
    "no_https": 1.0,
    "slow_mobile": 2.5, "slow_desktop": 2.5, "cwv_poor": 2.5,
    "csr_heavy": 2.5,
    "no_chatgpt_citation": 3.0, "no_ai_overview": 3.0, "low_fanout_coverage": 3.0,
    "keyword_gap": 3.0, "low_keyword_relevance": 3.0,
    "eeat_no_named_people": 1.5, "eeat_no_social_proof": 1.5, "eeat_no_brand": 2.0,
    # semantic aspects
    "aspect_macro_structure": 1.5, "aspect_heading_semantics": 1.5,
    "aspect_micro_semantics": 1.0, "aspect_schema_entity": 1.0,
    "aspect_forms_conversion_points": 1.5, "aspect_inline_link_semantics": 1.0,
}
EFFORT_LABEL = {1.0: "low", 1.5: "low-med", 2.0: "medium", 2.5: "med-high",
                3.0: "high"}


def _aspect_grade_severity(g: float) -> str | None:
    # AAA-96 S3 Part B: emit only below ASPECT_FINDING_THRESHOLD (0.6).
    if g >= ASPECT_FINDING_THRESHOLD:
        return None  # "fine" -> no finding
    return "high" if g < 0.4 else "medium"


def _f(code, pillar, sev, signal_name, signal_value, source_field,
       title, detail, rec) -> dict:
    return {"code": code, "pillar": pillar, "severity": sev,
            "signal_name": signal_name, "signal_value": signal_value,
            "source_field": source_field, "default_title": title,
            "default_detail": detail, "default_recommendation": rec}


def generate_findings(ao: dict, pillars: dict) -> list[dict]:
    """Deterministic findings — emitted ONLY for below-threshold/negative
    signals. Semantic-aspect detail/rec are READ from the existing
    aaa124_aspect_evaluations field; objective pillars use templated text."""
    out: list[dict] = []
    fdet = pillars["findability"]["detail"]
    tdet = pillars["technical"]["detail"]
    adet = pillars["ai_visibility"]["detail"]
    kdet = pillars["keywords"]["detail"]
    edet = pillars["eeat"]["detail"]
    aspect_grades = pillars["semantic_structure"]["detail"]
    aspect_evals = ao.get("aaa124_aspect_evaluations") or {}

    # --- Findability ---
    if fdet.get("indexed") is False:
        out.append(_f("not_indexed", "findability", "critical", "indexed",
            False, "indexing.indexed",
            "Page is not indexed", "The page was not found in the search index.",
            "Diagnose blockers (robots/noindex/canonical) and request indexing."))
    elif fdet.get("indexing_not_confirmed"):
        out.append(_f("indexing_not_confirmed", "findability", "low", "indexed",
            fdet.get("indexed"), "indexing.indexed",
            "Indexing not confirmed", "Index status could not be confirmed for this audit.",
            "Verify indexing in Search Console; re-run the indexing check."))
    if fdet.get("canonical_mismatch") is True:
        out.append(_f("canonical_mismatch", "findability", "high",
            "canonical_mismatch", True, "indexing.canonical_mismatch",
            "Canonical mismatch", "The indexed URL differs from the declared rel=canonical.",
            "Align rel=canonical with the preferred indexed variant."))
    if fdet.get("duplication_signal") is True:
        out.append(_f("duplication_signal", "findability", "high",
            "duplication_signal", True, "indexing.duplication_signal",
            "Duplicate variants indexed", "More than one URL variant is independently indexed.",
            "Consolidate variants via 301 redirects + a single canonical."))
    if fdet.get("https") is False:
        out.append(_f("no_https", "findability", "high", "https", False,
            "crawl.technical.https", "Not served over HTTPS",
            "The page is not served over HTTPS.", "Enable HTTPS site-wide and redirect HTTP."))

    # --- Technical ---
    mp = tdet.get("mobile_perf")
    if isinstance(mp, (int, float)):
        if mp < 50:
            out.append(_f("slow_mobile", "technical", "high", "mobile_performance",
                mp, "pagespeed.mobile.scores.performance",
                f"Mobile performance is {mp}/100",
                f"Mobile PageSpeed performance score is {mp}/100 (slow).",
                "Optimize mobile load: compress/defer assets, reduce render-blocking JS/CSS."))
        elif mp < 90:
            out.append(_f("slow_mobile", "technical", "medium", "mobile_performance",
                mp, "pagespeed.mobile.scores.performance",
                f"Mobile performance is {mp}/100",
                f"Mobile PageSpeed performance score is {mp}/100 (room to improve).",
                "Improve mobile load time toward 90+ (image/JS optimization)."))
    dp = tdet.get("desktop_perf")
    if isinstance(dp, (int, float)):
        if dp < 50:
            out.append(_f("slow_desktop", "technical", "medium", "desktop_performance",
                dp, "pagespeed.desktop.scores.performance",
                f"Desktop performance is {dp}/100",
                f"Desktop PageSpeed performance score is {dp}/100.",
                "Optimize desktop load (assets, caching, render path)."))
        elif dp < 90:
            out.append(_f("slow_desktop", "technical", "low", "desktop_performance",
                dp, "pagespeed.desktop.scores.performance",
                f"Desktop performance is {dp}/100",
                f"Desktop PageSpeed performance score is {dp}/100 (minor).",
                "Minor desktop performance tuning."))
    cwv = tdet.get("cwv_good_frac")
    if isinstance(cwv, (int, float)) and cwv == 0.0:
        out.append(_f("cwv_poor", "technical", "high", "cwv_good_frac", cwv,
            "crux_field_data", "Core Web Vitals are poor",
            "All measured Core Web Vitals (LCP/CLS/INP) are below 'good'.",
            "Address the failing CWV metrics (LCP image/server, CLS layout, INP responsiveness)."))
    if tdet.get("is_csr_likely") is True:
        out.append(_f("csr_heavy", "technical", "medium", "is_csr_likely", True,
            "phase2_html_measurements.rendering_mode.is_csr_likely",
            "Client-side-rendering heavy", "The page relies on client-side rendering; crawlers may see little content.",
            "Add server-side rendering / pre-rendering so crawlers receive full content."))

    # --- AI Visibility (opportunity framing) ---
    if adet.get("chatgpt_cited") is False:
        out.append(_f("no_chatgpt_citation", "ai_visibility", "medium",
            "chatgpt_cited", False, "chatgpt_query_response.target_site_cited",
            "Not cited by ChatGPT", "The site was not cited in the ChatGPT answer for its query (opportunity).",
            "Strengthen citable, well-structured passages + entity/schema signals to earn AI citations."))
    if adet.get("ai_overview_triggered") is False:
        out.append(_f("no_ai_overview", "ai_visibility", "medium",
            "ai_overview_triggered", False, "ai_overview_triggered",
            "No AI Overview presence", "No Google AI Overview was triggered/cited for the query (opportunity).",
            "Target question-style queries with concise, extractable answers."))
    fc = adet.get("fan_out_coverage_frac")
    if isinstance(fc, (int, float)) and fc < 0.5:
        out.append(_f("low_fanout_coverage", "ai_visibility", "medium",
            "fan_out_coverage_frac", fc, "fan_out_enriched[].coverage",
            f"Low fan-out coverage ({round(fc*100)}%)",
            f"The page covers only {round(fc*100)}% of the AI fan-out sub-queries.",
            "Add content addressing the uncovered fan-out queries."))

    # --- Keywords ---
    gap = kdet.get("gap_severity")
    if str(gap).lower() in ("high", "severe"):
        out.append(_f("keyword_gap", "keywords", "medium", "keyword_gap_severity",
            gap, "target_keywords.keyword_gap_severity", "High keyword gap",
            "There is a high gap between target keywords and current ranking content.",
            "Build content for the high-gap target keywords."))
    elif str(gap).lower() in ("medium", "moderate", "low", "minor"):
        out.append(_f("keyword_gap", "keywords", "low", "keyword_gap_severity",
            gap, "target_keywords.keyword_gap_severity", f"Keyword gap: {gap}",
            f"Keyword gap severity is '{gap}'.", "Close minor keyword gaps opportunistically."))
    rel = kdet.get("relevance_avg")
    if isinstance(rel, (int, float)) and rel < 0.6:
        out.append(_f("low_keyword_relevance", "keywords", "low", "relevance_avg",
            rel, "target_keywords_classified[].relevance_score",
            f"Low average keyword relevance ({rel})",
            f"Average target-keyword relevance is {rel}.",
            "Re-focus content on the most relevant target keywords."))

    # --- E-E-A-T ---
    if edet.get("brand_mentions", 1) == 0:
        out.append(_f("eeat_no_brand", "eeat", "medium", "brand_mentions", 0,
            "eeat_signals.brand_mentions", "No brand mentions detected",
            "No brand-entity mentions were detected on the page.",
            "Add clear brand/organization signals (About, Organization schema)."))
    if edet.get("named_people", 1) == 0:
        out.append(_f("eeat_no_named_people", "eeat", "low", "named_people", 0,
            "eeat_signals.named_people", "No named authors/experts",
            "No named people (authors/experts) were detected — weakens E-E-A-T.",
            "Add named authors with bios/credentials and Person/author schema."))
    if edet.get("social_proof_links", 1) == 0:
        out.append(_f("eeat_no_social_proof", "eeat", "low", "social_proof_links", 0,
            "eeat_signals.social_proof_links", "No social-proof links",
            "No social-proof links (reviews/profiles) were detected.",
            "Add links to reviews, profiles, or third-party validation."))

    # --- Semantic Structure aspects (grade-based; detail/rec from AAA-124) ---
    for aspect, grade in aspect_grades.items():
        if aspect == "above_the_fold" or grade is None:
            continue
        sev = _aspect_grade_severity(grade)
        if sev is None:
            continue
        ev = aspect_evals.get(aspect) or {}
        detail = (ev.get("structured_finding")
                  or f"{aspect} measured grade is {round(grade, 2)} (below target).")
        rec = (ev.get("recommendation")
               or f"Improve {aspect.replace('_', ' ')}.")
        out.append(_f(f"aspect_{aspect}", "semantic_structure", sev,
            f"{aspect}_grade", round(grade, 3),
            f"aaa124_aspect_evaluations.{aspect}",
            f"{aspect.replace('_', ' ').title()} needs work (grade {round(grade, 2)})",
            detail, rec))

    return out


def select_quick_wins(findings: list[dict], pillars: dict, top_n: int = 3) -> list[dict]:
    """impact = severity_score × (pillar_weight/100); effort_weight per code;
    quick_win_score = impact / effort_weight. Top N by score (impact×low-effort)."""
    scored = []
    for f in findings:
        sev_s = SEVERITY_SCORE.get(f["severity"], 1)
        w = pillars.get(f["pillar"], {}).get("weight", 0)
        impact = round(sev_s * (w / 100.0), 4)
        eff = EFFORT_BY_CODE.get(f["code"], 2.0)
        qws = round(impact / eff, 4) if eff else 0.0
        scored.append({**f, "impact": impact, "effort_weight": eff,
                       "effort_label": EFFORT_LABEL.get(eff, "medium"),
                       "quick_win_score": qws})
    scored.sort(key=lambda x: (-x["quick_win_score"], -x["impact"]))
    return scored[:top_n]


def select_priority_fix(findings: list[dict], pillars: dict) -> dict | None:
    """AAA-96 S3 Part A: single highest-IMPACT finding (severity × weight/100),
    IGNORING effort. Tiebreak: higher pillar_weight, then severity rank, then
    pillar order."""
    if not findings:
        return None
    def keyf(f):
        sev_s = SEVERITY_SCORE.get(f["severity"], 1)
        w = pillars.get(f["pillar"], {}).get("weight", 0)
        impact = sev_s * (w / 100.0)
        return (-round(impact, 4), -w, SEVERITY_RANK.get(f["severity"], 9),
                PILLAR_ORDER.index(f["pillar"]) if f["pillar"] in PILLAR_ORDER else 99)
    best = sorted(findings, key=keyf)[0]
    sev_s = SEVERITY_SCORE.get(best["severity"], 1)
    w = pillars.get(best["pillar"], {}).get("weight", 0)
    return {
        "pillar": best["pillar"], "finding_code": best["code"],
        "title": best["default_title"], "severity": best["severity"],
        "impact": round(sev_s * (w / 100.0), 4),
        "default_why_it_matters": (
            f"This is the single highest-impact issue: a {best['severity']} "
            f"problem in {PILLAR_LABELS.get(best['pillar'], best['pillar'])} "
            f"(pillar weight {w}). {best['default_detail']}"),
    }


def _pillar_signals(pillar_id: str, detail: dict, aspect_grades: dict) -> list[dict]:
    """Build [{name, value, contribution}] for a pillar from its detail dict."""
    if pillar_id == "semantic_structure":
        return [{"name": a, "value": g, "contribution": "equal-weight"}
                for a, g in aspect_grades.items()]
    out = []
    for name, key, weight in SIGNAL_SPECS.get(pillar_id, []):
        out.append({"name": name, "value": detail.get(key),
                    "contribution": weight})
    return out


def compute_flags(ao: dict, pillars: dict) -> dict:
    fdet = pillars["findability"]["detail"]
    tdet = pillars["technical"]["detail"]
    adet = pillars["ai_visibility"]["detail"]
    sm = _get(ao, "crawl", "schema_markup", default={}) or {}
    actions = _get(ao, "agent_friendly_measurements", "schema_actions", default=[]) or []
    return {
        "not_indexed": fdet.get("indexed") is False,
        "canonical_mismatch": fdet.get("canonical_mismatch") is True,
        "duplication": fdet.get("duplication_signal") is True,
        "indexing_not_confirmed": bool(fdet.get("indexing_not_confirmed")),
        "no_ai_presence": (adet.get("chatgpt_cited") is False
                           and adet.get("ai_overview_triggered") is False),
        "slow_mobile": isinstance(tdet.get("mobile_perf"), (int, float))
                       and tdet["mobile_perf"] < 50,
        "csr_heavy": tdet.get("is_csr_likely") is True,
        "missing_schema": not (sm.get("json_ld_blocks") or actions),
    }


# ---------------------------------------------------------------------------
# OVERALL
# ---------------------------------------------------------------------------
def _cq_findings(cq_result: dict) -> list[dict]:
    """Content-quality findings for 'no' (high) / 'partial' (medium) criteria —
    fed into quick-wins / priority_fix like any other finding."""
    out = []
    for c in (cq_result.get("criteria") or []):
        v = c.get("verdict")
        if v not in ("no", "partial"):
            continue
        sev = "high" if v == "no" else "medium"
        name = c["name"]
        out.append(_f(f"cq_{name}", "content_quality", sev, name, v,
            "cq_eval", f"Content quality: {name.replace('_', ' ')} = {v}",
            c.get("reason") or f"{name} judged '{v}' by the content-quality rubric.",
            f"Improve {name.replace('_', ' ')} of the page content."))
    return out


def build_report_model(ao: dict, cq_result: dict | None = None,
                       generated_at: str | None = None) -> dict:
    """Assemble the full locked-schema report_model.

    cq_result = output of report.cq_eval.evaluate_content_quality (or None):
      - sub_score_0_1 present -> content_quality filled, cq_status='included',
        overall over ALL 7 pillars (/100).
      - _error set            -> cq_status='error', CQ excluded (overall /75).
      - None                  -> cq_status='pending', CQ excluded (overall /75).
    `generated_at` is caller-supplied (engine stays pure/time-free); meta also
    reads ao['_audit_id'] if the caller injected it."""
    pillars: dict[str, dict] = {}

    for name, fn in (
        ("findability", score_findability),
        ("semantic_structure", score_semantic_structure),
        ("technical", score_technical),
        ("ai_visibility", score_ai_visibility),
        ("keywords", score_keywords),
        ("eeat", score_eeat),
    ):
        sub, detail = fn(ao)
        pillars[name] = {"sub_score": sub, "weight": WEIGHTS[name],
                         "detail": detail}

    # --- Content Quality (AI) ---
    cq_findings: list[dict] = []
    if cq_result and cq_result.get("_error"):
        cq_status = "error"
        pillars["content_quality"] = {
            "sub_score": None, "weight": WEIGHTS["content_quality"],
            "detail": {"error": cq_result.get("_error"),
                       "rubric_version": cq_result.get("rubric_version")}}
    elif cq_result and cq_result.get("sub_score_0_1") is not None:
        cq_status = "included"
        pillars["content_quality"] = {
            "sub_score": round(cq_result["sub_score_0_1"] * 100, 1),
            "weight": WEIGHTS["content_quality"],
            "detail": {"band": cq_result.get("band"),
                       "criteria": cq_result.get("criteria"),
                       "rubric_version": cq_result.get("rubric_version"),
                       "source": "ai", "cost_usd": cq_result.get("cost_usd")}}
        cq_findings = _cq_findings(cq_result)
    else:
        cq_status = "pending"
        pillars["content_quality"] = {
            "sub_score": None, "weight": WEIGHTS["content_quality"],
            "detail": {"note": "AI-judged; not yet evaluated"}}

    # overall = Σ(sub × weight) / Σ(present weights). CQ included -> /100.
    present = [(p["sub_score"], p["weight"]) for p in pillars.values()
               if p["sub_score"] is not None]
    if present:
        tot_w = sum(w for _, w in present)
        overall = round(sum(s * w for s, w in present) / tot_w, 1)
    else:
        overall, tot_w = None, 0

    findings = generate_findings(ao, pillars) + cq_findings
    quick_wins = select_quick_wins(findings, pillars)
    priority_fix = select_priority_fix(findings, pillars)
    flags_map = compute_flags(ao, pillars)
    aspect_grades = pillars["semantic_structure"]["detail"]

    # --- Part C: locked-schema pillar list ---
    pillars_out = []
    for pid in PILLAR_ORDER:
        p = pillars[pid]
        ptype = "ai_assessed" if pid == "content_quality" else "measured"
        pf = [f for f in findings if f["pillar"] == pid]
        if pid == "content_quality":
            # signals = the 6 rubric criteria verdicts (each ~1/6 of the band)
            crits = (p.get("detail") or {}).get("criteria") or []
            signals = [{"name": c["name"], "value": c["verdict"],
                        "contribution": "1/6"} for c in crits]
        else:
            signals = _pillar_signals(pid, p.get("detail") or {}, aspect_grades)
        pillars_out.append({
            "id": pid, "label": PILLAR_LABELS[pid], "type": ptype,
            "weight": p["weight"], "sub_score": p["sub_score"],
            "band": _band(p["sub_score"]),
            "signals": signals, "findings": pf,
        })

    idx = ao.get("indexing") or {}
    flags_list = sorted(k for k, v in flags_map.items() if v)
    score_inputs_present = [pid for pid in PILLAR_ORDER
                            if pillars[pid]["sub_score"] is not None]

    return {
        "rubric_version": RUBRIC_VERSION,
        "audited_url": ao.get("url") or ao.get("client_url"),
        "indexed": idx.get("indexed"),
        "canonical_indexed": idx.get("canonical_indexed"),
        "overall_score": overall,
        "overall_band": _band(overall),
        "pillars": pillars_out,
        "quick_wins": quick_wins,
        "priority_fix": priority_fix,
        "flags": flags_list,
        "competitor": build_competitor_block(ao),
        "meta": {
            "audit_id": ao.get("_audit_id"),
            "generated_at": generated_at,
            "rubric_version": RUBRIC_VERSION,
            "cq_status": cq_status,
            "score_inputs_present": score_inputs_present,
            "present_weight_total": tot_w,
        },
    }


# ---------------------------------------------------------------------------
# Part D — competitor block (LOCKED/teaser; graceful when RE never ran)
# ---------------------------------------------------------------------------
def _domain(u: str | None) -> str | None:
    if not u:
        return None
    from urllib.parse import urlparse
    return (urlparse(u if "://" in u else f"https://{u}").netloc or "").replace("www.", "") or None


def build_competitor_block(ao: dict) -> dict:
    rf = ao.get("re_findings") or {}
    v2 = ao.get("selected_competitors_v2") or []
    sfa = ao.get("serp_fit_analysis") or []
    available = bool(rf or v2 or sfa)

    if not available:
        return {
            "locked": True, "available": False,
            "teaser": {
                "competitors_analyzed": 0, "client_ranks_in_serp": None,
                "top_category_competitor": None,
                "one_line_teaser": "Competitor analysis was not run for this audit.",
            },
            "detail": None,
        }

    # selected count (prefer Stage-2 v2; fall back to AAA-108 legacy)
    sel = rf.get("selected_competitors") or {}
    legacy_n = sum(len(v) for v in sel.values() if isinstance(v, list)) if isinstance(sel, dict) else 0
    n = len(v2) or legacy_n
    crs = rf.get("client_ranking_status") or {}
    ranks = None
    if isinstance(crs, dict) and crs:
        ranks = any(bool(s) for s in crs.values())
    top = _domain(v2[0].get("url")) if v2 and isinstance(v2[0], dict) else None
    return {
        "locked": True, "available": True,
        "teaser": {
            "competitors_analyzed": n,
            "client_ranks_in_serp": ranks,
            "top_category_competitor": top,
            "one_line_teaser": (
                f"{n} competitors analyzed for this query — unlock to see the "
                f"gap analysis and how to outrank them."),
        },
        "detail": {
            "selected_competitors": sel,
            "selected_competitors_v2_count": len(v2),
            "client_ranking_status": crs,
            "comparison": rf.get("comparison"),
            "serp_fit_analysis_count": len(sfa),
        },
    }


# ---------------------------------------------------------------------------
# Part E — persist (DRY-RUN this round: build + validate, DO NOT write)
# ---------------------------------------------------------------------------
def persist_report_model(report_model: dict, dry_run: bool = True) -> dict:
    """Target the SEPARATE `reports/{audit_id}` collection (non-mutating,
    versionable). DRY-RUN builds + validates the payload but does NOT write."""
    import json as _json
    audit_id = (report_model.get("meta") or {}).get("audit_id")
    target = f"reports/{audit_id}" if audit_id else None
    try:
        _json.dumps(report_model)  # serializability check
        serializable = True
        ser_err = None
    except (TypeError, ValueError) as e:
        serializable = False
        ser_err = f"{type(e).__name__}: {e}"
    result = {
        "target": target,
        "key_present": bool(audit_id),
        "serializable": serializable,
        "serialize_error": ser_err,
        "would_write": dry_run and serializable and bool(audit_id),
        "wrote": False,  # DRY-RUN — never writes this round
        "payload_top_keys": sorted(report_model.keys()),
    }
    if not dry_run:
        result["_note"] = "real write not enabled this round (review shape first)"
    return result
