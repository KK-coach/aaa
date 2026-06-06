# -*- coding: utf-8 -*-
"""AAA-161 / RG1-S1 — deterministic fact_base mapper + provenance resolvers.

Maps a persisted ``audit_output`` dict into a CLOSED fact_base object grouped by
DECISION UNIT (meta / classification / target / onpage / ai_visibility /
technical / competition). Every leaf fact is a uniform wrapper:

    {"value": <any>, "provenance": "measured"|"absent"|"not_measured", "source": "<dotted path>"}

The decide/render pass (RG1-S2) consumes this; this module does NOT render and
is NOT wired into a live pipeline. Pure function, $0, no I/O, no LLM.

PROVENANCE MODEL (AAA-161 RG1-S0 C.2)
------------------------------------
- measured     : the measurement ran and produced a present-positive value.
- absent       : the measurement ran and the thing genuinely is NOT there
                 (this IS the finding) — e.g. count 0, empty list, client_cited
                 False, found_in_top_10 False, schema pagetype no-match.
- not_measured : the measurement did NOT run / failed / N-A — never build a
                 finding on it. e.g. missing key (forward-only feature), any
                 ``_error`` subtree, competitor discovery failed, client_cited
                 None (NOT False!), position None with no found_in_top_10 flag.

RULE: ``None`` NEVER decides alone — always disambiguate with a companion flag
(found_in_top_10, _error, present, discovery_status, client_cited True/False/None).
``0`` / ``[]`` default to measured+absent UNLESS the parent subtree is _error →
not_measured. A missing key → not_measured (forward-only).

MEASUREMENT-SOURCE RECONCILIATION (AAA-161 RG1-S1, part 1)
----------------------------------------------------------
Two overlapping on-page sources with different numbers. Investigated, NOT chosen
blindly:

* FORMS — phase2 ``form_quality_extended.input_count`` = 21 counts ALL non-CMP
  ``<input>`` (incl. hidden:9, submit:2). agent_friendly ``forms.input_count`` =
  12 EXCLUDES ``type=hidden`` (agent_friendly.py:161) → 21 − 9 = 12 exactly. A
  deterministic FILTERING difference, not a semantic conflict.
  DECISION: structural counts (input_count, form_count, input_type_distribution)
  come from the deterministic phase2 (canonical). ``label_coverage`` has NO
  phase2 equivalent → agent_friendly.

* LANDMARKS, ARIA (interactive/with_aria), heading.level_skips, image alt counts
  have NO phase2 equivalent → agent_friendly.

* SCHEMA lives in 3 COMPLEMENTARY facets (not duplicates), consolidated into one
  ``onpage.schema``:
    1) crawl.schema_markup        → json_ld_present / microdata_present (raw detect)
    2) phase2.schema_pagetype_match → found_schemas (CANONICAL types) + pagetype fit
    3) agent_friendly.schema_actions → schema.org Action types (e.g. SearchAction)
  ``types_found`` is taken from phase2.found_schemas (deterministic parse, canonical).

COMPETITOR CAVEAT (RG4 stop-condition mitigation)
-------------------------------------------------
Only competitor entity COUNTS persist (``entity_counts``), never the entity
name LISTS. So competition.competitors[*].entity_lists is ALWAYS not_measured.
Competitor ``schema_types[]`` DO persist → measured. Competitor discovery_status
is derived from re_findings.competitor_audits (``"ok"`` vs error string).
"""
from __future__ import annotations

import re
from typing import Any

_RE_HOST = re.compile(r"https?://([^/]+)")


def _reg(url: str) -> str:
    """Registrable-ish host (strip scheme + leading www) for SERP/URL matching."""
    m = _RE_HOST.search(url or "")
    h = (m.group(1).lower() if m else "")
    return h[4:] if h.startswith("www.") else h


def _serp_position_map(ao: dict):
    """regdomain → best (lowest) SERP position across serp_branded + serp_category.
    Returns (map, serp_present). serp_present True iff either SERP carried
    organic_results — lets us tell 'not in SERP' (absent) from 'no SERP'
    (not_measured)."""
    rf = (ao or {}).get("re_findings") or {}
    pos, present = {}, False
    for serp in ("serp_branded", "serp_category"):
        org = (rf.get(serp) or {}).get("organic_results")
        if isinstance(org, list):
            present = present or len(org) > 0
            for o in org:
                r, p = _reg(o.get("url")), o.get("position")
                if r and p is not None and (r not in pos or p < pos[r]):
                    pos[r] = p
    return pos, present

SCHEMA_VERSION = "fact_base_v3"  # v2: SERP-fit promoted; v3: eeat passthrough (AAA-170 S2)

# Provenance enum
MEASURED = "measured"
ABSENT = "absent"
NOT_MEASURED = "not_measured"

_MISSING = object()


# ---------------------------------------------------------------------------
# Low-level access + fact wrapper
# ---------------------------------------------------------------------------
def _dig(d: Any, *path: str):
    """Return (value, present). ``present`` is True iff the FULL key chain
    exists (even if the final value is None) — this is what lets us tell a
    missing key (not_measured) apart from an explicit None."""
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None, False
    return cur, True


def _fact(value: Any, provenance: str, source: str) -> dict:
    return {"value": value, "provenance": provenance, "source": source}


def _has_error(subtree: Any) -> bool:
    """True if a measurement subtree carries a non-null ``_error``."""
    return isinstance(subtree, dict) and subtree.get("_error") not in (None, "")


# ---------------------------------------------------------------------------
# Per-field provenance resolvers (NOT a global heuristic)
# ---------------------------------------------------------------------------
def r_scalar(ao, *path, none_is_absent: bool = False) -> dict:
    """Classification/scalar value. Missing key → not_measured. Explicit None →
    absent (if the field is a genuine optional, none_is_absent=True) else
    not_measured. Otherwise measured."""
    src = ".".join(path)
    val, present = _dig(ao, *path)
    if not present:
        return _fact(None, NOT_MEASURED, src)
    if val is None:
        return _fact(None, ABSENT if none_is_absent else NOT_MEASURED, src)
    return _fact(val, MEASURED, src)


def r_count(ao, *path, error_subtree: Any = _MISSING) -> dict:
    """Integer count. Subtree _error → not_measured. Missing/None → not_measured.
    0 → absent (genuinely none). >0 → measured."""
    src = ".".join(path)
    if error_subtree is not _MISSING and _has_error(error_subtree):
        val, _ = _dig(ao, *path)
        return _fact(val, NOT_MEASURED, src)
    val, present = _dig(ao, *path)
    if not present or val is None:
        return _fact(val, NOT_MEASURED, src)
    if val == 0:
        return _fact(0, ABSENT, src)
    return _fact(val, MEASURED, src)


def r_list(ao, *path, error_subtree: Any = _MISSING) -> dict:
    """List of items. Subtree _error → not_measured. Missing/None → not_measured.
    [] → absent (measurement ran, nothing found). non-empty → measured."""
    src = ".".join(path)
    if error_subtree is not _MISSING and _has_error(error_subtree):
        val, _ = _dig(ao, *path)
        return _fact(val, NOT_MEASURED, src)
    val, present = _dig(ao, *path)
    if not present or val is None:
        return _fact(val, NOT_MEASURED, src)
    if isinstance(val, (list, tuple, dict)) and len(val) == 0:
        return _fact(val, ABSENT, src)
    return _fact(val, MEASURED, src)


def r_bool(ao, *path) -> dict:
    """A genuinely-measured boolean fact (e.g. https, indexed, mismatch). Present
    True/False → measured (the negative is a measured fact, not 'absent of
    measurement'). Missing/None → not_measured."""
    src = ".".join(path)
    val, present = _dig(ao, *path)
    if not present or val is None:
        return _fact(val, NOT_MEASURED, src)
    return _fact(bool(val), MEASURED, src)


def r_client_cited(ao, *path) -> dict:
    """SPECIAL (S0 C.2): True → measured (cited); False → absent (evaluated, not
    cited — a finding); None → not_measured (not evaluated). Missing → not_measured."""
    src = ".".join(path)
    val, present = _dig(ao, *path)
    if not present or val is None:
        return _fact(None, NOT_MEASURED, src)
    return _fact(bool(val), MEASURED if val else ABSENT, src)


def r_ranking(ao, branch: str) -> dict:
    """client_ranking_status: disambiguate position==None via found_in_top_10.
    found_in_top_10 True → measured (carries position); False → absent (evaluated,
    not in top 10); neither present → not_measured."""
    base = ("re_findings", "client_ranking_status", branch)
    src = ".".join(base)
    node, present = _dig(ao, *base)
    if not present or not isinstance(node, dict):
        return _fact(None, NOT_MEASURED, src)
    found = node.get("found_in_top_10")
    payload = {"position": node.get("position"),
               "found_in_top_10": found,
               "ranking_severity": node.get("ranking_severity")}
    if found is True:
        return _fact(payload, MEASURED, src)
    if found is False:
        return _fact(payload, ABSENT, src)
    return _fact(payload, NOT_MEASURED, src)


# ---------------------------------------------------------------------------
# Section mappers
# ---------------------------------------------------------------------------
def _map_classification(ao) -> dict:
    primary = r_scalar(ao, "audience_relationship_primary")
    # secondary is a genuine optional: if primary was classified, the classifier
    # ran → an explicit None means "no distinct secondary" (absent).
    sec_present = primary["provenance"] == MEASURED
    return {
        "topic_domain": r_scalar(ao, "topic_domain"),
        "business_model": r_scalar(ao, "business_model"),
        "audience_primary": primary,
        "audience_secondary": r_scalar(ao, "audience_relationship_secondary",
                                       none_is_absent=sec_present),
        "page_type": r_scalar(ao, "page_type"),
        "page_type_intent_group": r_scalar(ao, "page_type_parent_intent_group"),
        "locality": r_scalar(ao, "locality"),
        "target_type": r_scalar(ao, "audit_target_type"),
        "grounding_confidence": r_scalar(ao, "grounding_confidence"),
    }


def _map_target(ao) -> dict:
    return {
        "primary_keyword": r_scalar(ao, "target_keywords", "primary_keyword"),
        "intent": r_scalar(ao, "target_keywords", "intent"),
        "is_branded": r_scalar(ao, "target_keywords", "is_branded_primary"),
        "difficulty": r_scalar(ao, "target_keywords", "estimated_difficulty"),
        "keyword_gap_severity": r_scalar(ao, "target_keywords", "keyword_gap_severity"),
        "secondary_keywords": r_list(ao, "target_keywords", "secondary_keywords"),
        "long_tail_keywords": r_list(ao, "target_keywords", "long_tail_keywords"),
        "keywords_classified": r_list(ao, "target_keywords_classified"),
    }


def _map_onpage(ao) -> dict:
    ss, _ = _dig(ao, "phase2_html_measurements", "semantic_structure")
    ss = ss if isinstance(ss, dict) else {}
    afm, _ = _dig(ao, "agent_friendly_measurements")
    afm = afm if isinstance(afm, dict) else {}
    P = ("phase2_html_measurements", "semantic_structure")
    A = ("agent_friendly_measurements",)

    # Headings: phase2 tree is canonical (carries order+depth+zone); level_skips
    # / h1_count come from agent_friendly (no phase2 equivalent).
    headings = {
        "tree": r_list(ao, *P, "heading_tree", error_subtree=ss),  # {level,position,zone,text,char_count}
        "by_zone": r_scalar(ao, *P, "headings_by_zone"),
        "stacking_candidate": r_bool(ao, *P, "heading_stacking_candidate"),
        "h1_count": r_count(ao, *A, "heading", "h1_count", error_subtree=afm),
        "level_skips": r_count(ao, *A, "heading", "level_skips", error_subtree=afm),
    }
    structure = {
        "list_structure": r_scalar(ao, *P, "list_structure"),
        "table_count": r_count(ao, *P, "table_structure", "table", error_subtree=ss),
        "blockquote_count": r_count(ao, *P, "blockquote_count", error_subtree=ss),
        "figure_count": r_count(ao, *P, "figure_count", error_subtree=ss),
        "div_table_suspicious": r_count(ao, *P, "div_table_suspicious", error_subtree=ss),
    }
    links = {
        "anchor_count": r_count(ao, *P, "link_semantic", "anchor_count", error_subtree=ss),
        "generic_anchor_count": r_count(ao, *P, "link_semantic", "generic_anchor_text_count", error_subtree=ss),
        "blank_unsafe_count": r_count(ao, *P, "link_semantic", "blank_target_unsafe_count", error_subtree=ss),
    }
    # FORMS: structural counts from phase2 (canonical); label_coverage from
    # agent_friendly (no phase2 equivalent).
    forms = {
        "form_count": r_count(ao, *P, "form_quality_extended", "form_count", error_subtree=ss),
        "input_count": r_count(ao, *P, "form_quality_extended", "input_count", error_subtree=ss),
        "input_type_distribution": r_scalar(ao, *P, "form_quality_extended", "input_type_distribution"),
        "label_coverage": r_scalar(ao, *A, "forms", "label_coverage"),
    }
    aria = {
        "interactive_count": r_count(ao, *A, "aria", "interactive_count", error_subtree=afm),
        "with_aria_count": r_count(ao, *A, "aria", "with_aria_count", error_subtree=afm),
        "landmarks_present": r_list(ao, *A, "landmarks", "present", error_subtree=afm),
        "landmarks_missing": r_list(ao, *A, "landmarks", "missing", error_subtree=afm),
    }
    images = {
        "img_count": r_count(ao, *A, "images", "img_count", error_subtree=afm),
        "alt_count": r_count(ao, *A, "images", "alt_count", error_subtree=afm),
    }
    # SCHEMA consolidated (3 facets → 1).
    schema = {
        "types_found": r_list(ao, *P, "schema_pagetype_match", "found_schemas", error_subtree=ss),
        "pagetype_expected": r_list(ao, *P, "schema_pagetype_match", "expected_schemas"),
        "pagetype_match": r_bool(ao, *P, "schema_pagetype_match", "match"),
        "actions": r_list(ao, *A, "schema_actions", error_subtree=afm),
        "json_ld_present": r_bool(ao, "crawl", "schema_markup", "json_ld_present"),
        "microdata_present": r_bool(ao, "crawl", "schema_markup", "microdata_present"),
    }
    # Client entities — real name LISTS (contrast competitor: counts only).
    ent, _ = _dig(ao, "entities")
    ent = ent if isinstance(ent, dict) else {}
    entities_client = {
        k: r_list(ao, "entities", k)
        for k in ("organizations", "products", "technologies", "people",
                  "concepts", "places")
    }
    # Title/meta — pixel measurement is AAA-158 forward-only (missing on old
    # audits → not_measured); raw text always present via crawl.meta.
    title_meta = {
        "title_text": r_scalar(ao, "crawl", "meta", "title", "text"),
        "desc_text": r_scalar(ao, "crawl", "meta", "description", "text"),
        "title_pixel": r_scalar(ao, "title_meta_measurements", "title", "pixel_width"),
        "title_verdict": r_scalar(ao, "title_meta_measurements", "title", "verdict"),
        "desc_verdict_desktop": r_scalar(ao, "title_meta_measurements", "description", "desktop", "verdict"),
        "desc_verdict_mobile": r_scalar(ao, "title_meta_measurements", "description", "mobile", "verdict"),
    }
    return {
        "headings": headings, "structure": structure, "links": links,
        "forms": forms, "aria": aria, "images": images, "schema": schema,
        "entities_client": entities_client, "title_meta": title_meta,
    }


def _map_ai_visibility(ao) -> dict:
    return {
        "ai_overview_present": r_bool(ao, "ai_overview", "present"),
        "ai_overview_client_cited": r_client_cited(ao, "ai_overview", "client_cited"),
        "ai_overview_cited_sources": r_list(ao, "ai_overview", "cited_sources"),
        "chatgpt_target_cited": r_client_cited(ao, "chatgpt_query_response", "target_site_cited"),
        "chatgpt_citations": r_list(ao, "chatgpt_query_response", "citations"),
        "fan_out_client_queries": r_list(ao, "query_fan_out"),
        "fan_out_enriched": r_list(ao, "fan_out_enriched"),
    }


def _map_technical(ao) -> dict:
    crux, _ = _dig(ao, "crux_field_data")
    crux = crux if isinstance(crux, dict) else {}
    metrics = {}
    cm, present = _dig(ao, "crux_field_data", "origin_level", "metrics")
    if present and isinstance(cm, dict) and not _has_error(crux):
        for m in ("lcp", "inp", "cls", "fcp", "ttfb"):
            mv = cm.get(m)
            if isinstance(mv, dict):
                metrics[m] = _fact({"p75": mv.get("p75_ms", mv.get("p75")),
                                    "category": mv.get("category")}, MEASURED,
                                   f"crux_field_data.origin_level.metrics.{m}")
            else:
                metrics[m] = _fact(None, NOT_MEASURED,
                                   f"crux_field_data.origin_level.metrics.{m}")
    else:
        for m in ("lcp", "inp", "cls", "fcp", "ttfb"):
            metrics[m] = _fact(None, NOT_MEASURED,
                               f"crux_field_data.origin_level.metrics.{m}")
    return {
        "indexed": r_bool(ao, "indexing", "indexed"),
        "canonical_value": r_scalar(ao, "crawl", "technical", "canonical", "value"),
        "canonical_mismatch": r_bool(ao, "indexing", "canonical_mismatch"),
        "redirect_chain": r_list(ao, "crawl", "technical", "redirect_chain"),
        "https": r_bool(ao, "crawl", "technical", "https"),
        "psi_mobile_perf": r_scalar(ao, "pagespeed", "mobile", "scores", "performance"),
        "psi_desktop_perf": r_scalar(ao, "pagespeed", "desktop", "scores", "performance"),
        "psi_seo": r_scalar(ao, "pagespeed", "mobile", "scores", "seo"),
        "psi_accessibility": r_scalar(ao, "pagespeed", "mobile", "scores", "accessibility"),
        "crux": metrics,
    }


def _map_competition(ao) -> dict:
    rf, _ = _dig(ao, "re_findings")
    rf = rf if isinstance(rf, dict) else {}
    comp, _ = _dig(ao, "re_findings", "comparison")
    comp = comp if isinstance(comp, dict) else {}
    raw, _ = _dig(ao, "re_findings", "comparison", "_raw_dimensions")
    raw = raw if isinstance(raw, dict) else {}
    audits = rf.get("competitor_audits") or {}
    posmap, serp_present = _serp_position_map(ao)

    competitors = []
    raw_comps = raw.get("competitors") if isinstance(raw.get("competitors"), list) else []
    anchored = False
    for i, c in enumerate(raw_comps):
        if not isinstance(c, dict):
            continue
        url = c.get("url")
        status = audits.get(url, "")
        ok = isinstance(status, str) and status.strip().lower() == "ok"
        # SERP position (both SERPs): present-in-SERP → measured; SERP captured
        # but competitor not in it → absent; no SERP captured → not_measured.
        sp_pos = posmap.get(_reg(url)) if url else None
        if not serp_present:
            sp_prov = NOT_MEASURED
        elif sp_pos is not None:
            sp_prov = MEASURED
        else:
            sp_prov = ABSENT
        # First successfully-discovered competitor is treated as the anchor
        # (mirrors comparison's competitor_best=highest-content choice well enough
        # for the fact_base; the decide pass may refine).
        is_anchor = ok and not anchored
        if is_anchor:
            anchored = True
        ec = c.get("entity_counts") or {}
        sp = f"re_findings.comparison._raw_dimensions.competitors[{i}]"
        competitors.append({
            "url": _fact(url, MEASURED if url else NOT_MEASURED, sp + ".url"),
            "brand": _fact(c.get("brand"), MEASURED if c.get("brand") else NOT_MEASURED, sp + ".brand"),
            "is_anchor": is_anchor,
            "discovery_status": _fact("ok" if ok else "failed",
                                      MEASURED, f"re_findings.competitor_audits[{url}]"),
            "content_words": _fact(c.get("main_content_words"),
                                   MEASURED if c.get("main_content_words") else NOT_MEASURED,
                                   sp + ".main_content_words"),
            "schema_count": _fact(c.get("schema_count"),
                                  NOT_MEASURED if not ok else (ABSENT if c.get("schema_count") == 0 else MEASURED),
                                  sp + ".schema_count"),
            "schema_types": _fact(c.get("schema_types") or [],
                                  NOT_MEASURED if not ok else (ABSENT if not (c.get("schema_types")) else MEASURED),
                                  sp + ".schema_types"),
            # COUNTS persist (measured/absent); LISTS never persist → not_measured.
            "entity_counts": _fact(ec if ec else None,
                                   NOT_MEASURED if not ok else (MEASURED if ec else ABSENT),
                                   sp + ".entity_counts"),
            "entity_lists": _fact(None, NOT_MEASURED, sp + ".entity_lists (NOT PERSISTED — RG4 gap)"),
            "perf_desktop": _fact(c.get("perf_desktop"),
                                  MEASURED if c.get("perf_desktop") is not None else NOT_MEASURED,
                                  sp + ".perf_desktop"),
            # AAA-161 S2.1: promoted from decide.py raw reads.
            "intent": _fact(c.get("intent"),
                            MEASURED if c.get("intent") else (NOT_MEASURED if not ok else ABSENT),
                            sp + ".intent"),
            "serp_position": _fact(sp_pos, sp_prov,
                                   "re_findings.serp_branded/serp_category.organic_results[url=%s]" % url),
        })

    # --- AAA-161 S2.1: SERP-fit context promoted from decide.py raw reads ---
    sfa_list, _ = _dig(ao, "serp_fit_analysis")
    sfa = sfa_list[0] if isinstance(sfa_list, list) and sfa_list and isinstance(sfa_list[0], dict) else None
    sfa_err = _has_error(sfa) if sfa is not None else True
    SFA_SRC = "serp_fit_analysis[0]"

    def _sfa_scalar(key, none_is_absent=False):
        if sfa is None:
            return _fact(None, NOT_MEASURED, f"{SFA_SRC}.{key}")
        if sfa_err:
            return _fact(sfa.get(key), NOT_MEASURED, f"{SFA_SRC}.{key}")
        v = sfa.get(key)
        if v is None:
            return _fact(None, ABSENT if none_is_absent else NOT_MEASURED, f"{SFA_SRC}.{key}")
        return _fact(v, MEASURED, f"{SFA_SRC}.{key}")

    # serp_type_distribution (full bucket distribution)
    dist = sfa.get("serp_type_distribution") if sfa else None
    if sfa is None or sfa_err or dist is None:
        dist_fact = _fact(dist, NOT_MEASURED, f"{SFA_SRC}.serp_type_distribution")
    elif isinstance(dist, dict) and len(dist) == 0:
        dist_fact = _fact(dist, ABSENT, f"{SFA_SRC}.serp_type_distribution")
    else:
        dist_fact = _fact(dist, MEASURED, f"{SFA_SRC}.serp_type_distribution")

    # serp_top10 — classified per-URL list {position, url, title, page_type}
    t10_raw = sfa.get("serp_top10_classifications") if sfa else None
    if isinstance(t10_raw, list) and t10_raw:
        t10 = [{"position": e.get("position"), "url": e.get("url"),
                "title": e.get("title"), "page_type": e.get("serp_type")}
               for e in t10_raw if isinstance(e, dict)]
        t10_fact = _fact(t10, MEASURED, f"{SFA_SRC}.serp_top10_classifications")
    elif isinstance(t10_raw, list):
        t10_fact = _fact([], ABSENT, f"{SFA_SRC}.serp_top10_classifications")
    else:
        t10_fact = _fact(None, NOT_MEASURED, f"{SFA_SRC}.serp_top10_classifications")

    serp_fit = {
        "keyword": _sfa_scalar("keyword"),
        "target_type": _sfa_scalar("target_type"),
        "target_type_fit": _sfa_scalar("target_type_fit"),
        "keyword_recommendation_trigger": _sfa_scalar("keyword_recommendation_trigger"),
        "serp_type_distribution": dist_fact,
    }

    return {
        "primary_keyword_serp": {
            "top10": r_list(ao, "re_findings", "serp_branded", "organic_results"),
            "ai_overview_citations": r_list(ao, "re_findings", "serp_branded", "ai_overview_citations"),
        },
        "client_ranking": r_ranking(ao, "branded"),
        "no_comparable_competitors": r_bool(ao, "audit_no_comparable_competitors_found"),
        "competitors": competitors,
        "dimension_table": r_scalar(ao, "re_findings", "comparison", "dimension_table"),
        "patterns": r_list(ao, "re_findings", "comparison", "patterns",
                           error_subtree=comp),
        "serp_fit": serp_fit,          # AAA-161 S2.1 (target_stance inputs)
        "serp_top10": t10_fact,        # AAA-161 S2.1 (classified SERP, render presentation)
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def build_fact_base(audit_output: dict) -> dict:
    """Pure: audit_output dict → closed fact_base (S0 C.1 structure). Never raises
    on a well-formed dict; missing subtrees resolve to not_measured facts."""
    ao = audit_output or {}
    crawl = ao.get("crawl") or {}
    sp = ao.get("site_profile") or {}
    # AAA-170 S2: client E-E-A-T diagnostic passthrough (composite pre-scored
    # block, not a measured leaf). None when absent or errored.
    _es = ao.get("eeat_score") if isinstance(ao.get("eeat_score"), dict) else None
    _eeat_client = (_es or {}).get("client") if _es else None
    eeat = _eeat_client if (isinstance(_eeat_client, dict)
                            and not ((_es or {}).get("_meta") or {}).get("error")) else None
    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "audit_id": ao.get("audit_id"),
            "url": ao.get("url") or crawl.get("url"),
            "brand": sp.get("brand"),
            "lang": sp.get("language"),
        },
        "classification": _map_classification(ao),
        "target": _map_target(ao),
        "onpage": _map_onpage(ao),
        "ai_visibility": _map_ai_visibility(ao),
        "technical": _map_technical(ao),
        "competition": _map_competition(ao),
        "eeat": eeat,  # AAA-170 S2 client E-E-A-T passthrough (None if absent/errored)
    }


# Reference map (fact → source) for documentation/tests.
SOURCE_MAP_NOTES = {
    "onpage.forms.input_count": "phase2.form_quality_extended.input_count (ALL non-CMP inputs; canonical structural)",
    "onpage.forms.label_coverage": "agent_friendly.forms.label_coverage (no phase2 equivalent)",
    "onpage.aria.*": "agent_friendly.aria/landmarks (no phase2 equivalent)",
    "onpage.headings.tree": "phase2.heading_tree (canonical; carries level+position+zone order)",
    "onpage.headings.level_skips": "agent_friendly.heading.level_skips (no phase2 equivalent)",
    "onpage.schema.types_found": "phase2.schema_pagetype_match.found_schemas (canonical deterministic parse)",
    "onpage.schema.actions": "agent_friendly.schema_actions",
    "competition.competitors[].entity_lists": "NOT PERSISTED — always not_measured (RG4 stop-condition)",
    "competition.competitors[].entity_counts": "re_findings...._raw_dimensions (counts persist)",
}
