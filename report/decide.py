# -*- coding: utf-8 -*-
"""AAA-161 / RG1-S2 — decide pass (closed, deterministic decision scaffold).

Consumes the RG1-S1 fact_base (+ a few raw SERP-fit lookups the S1 mapper did
not surface) and computes a CLOSED ``decisions`` scaffold that the consolidated
render (RG1-S3) turns into prose. This module is deterministic and $0 — NO LLM,
NO prose generation. It only DECIDES; phrasing is S3's job.

Five decision fields (S2 spec):
  (1) anchor               — chosen primary competitor (best SERP rank among
                             ok-discovery real competitors; tie-break business-
                             model proximity; absent if no real competitor).
  (2) target_stance        — {good_fit | page_type_mismatch | intent_mismatch}
                             + dedicated_page_recommendation, with the honesty
                             contract (additive dedicated-page rec; never claim
                             "reposition the homepage", never claim about an
                             unmeasured page).
  (3) ranked_findings      — all findings (comparison.patterns + on-page absent
                             + technical) in ONE impact-driven severity order.
                             schema never High; heading-order = structure/a11y
                             (not ranking-critical); not_measured fully excluded;
                             a real redirect finding kept.
  (4) recommendation_guards— allow/deny object from classification the render
                             MUST obey (locality/page_type/business_model +
                             fabrication guard + competitor-entity guard).
  (5) diagnosis_inputs     — selected ranked measured/absent facts the §1/§11
                             diagnosis builds on (NOT prose). offpage_unmeasured
                             flag so S3 hedges; not_measured excluded.

AAA-161 S2.1: this pass now reads EXCLUSIVELY from the fact_base — never from
raw audit_output. The SERP-fit context decide previously read raw (competitor
SERP positions, competitor intent, serp_type_distribution, serp_top10,
target_type/fit/keyword_recommendation_trigger) was promoted to
fact_base.competition (serp_fit / serp_top10 / competitors[].serp_position /
competitors[].intent) in fact_base_v2. The decide pass is a single-source-of-
truth consumer of (fact_base, decisions only).
"""
from __future__ import annotations

from report.fact_base import MEASURED, ABSENT, NOT_MEASURED

DECISIONS_VERSION = "decisions_v2"  # AAA-161 G2: content-QA / placeholder finding

_SEV_RANK = {"high": 3, "medium": 2, "low": 1}
# category priority for tie-break within the same severity (higher first).
# AAA-161 G2: `trust` ranks above ranking/visibility — an unfinished-content leak
# is the highest-impact Trust gap and should surface at/near the top.
_CAT_PRIORITY = {
    "trust": 6, "visibility": 5, "ranking": 4, "content": 3, "schema": 2,
    "technical": 1, "structure_accessibility": 0,
}

# business_model → schema/recommendation profile. NOTE: the S2 spec lists
# "consultancy"; the kk.coach canary is "b2b_service" — both are service
# businesses, grouped under the same SERVICE profile (allow Person/Service,
# deny Local*/Product), per the kk.coach spot-check.
_SERVICE_MODELS = {"consultancy", "b2b_service", "b2c_service", "agency", "service"}
_SAAS_MODELS = {"b2b_saas", "b2c_saas", "saas"}


def _prov(fact) -> str:
    return (fact or {}).get("provenance")


def _val(fact):
    return (fact or {}).get("value")


# ---------------------------------------------------------------------------
# (1) anchor
# ---------------------------------------------------------------------------
def decide_anchor(fact_base: dict) -> dict:
    comps = fact_base["competition"]["competitors"]
    ok = [c for c in comps if _val(c["discovery_status"]) == "ok"]
    if not ok:
        return {"value": None, "provenance": ABSENT,
                "selection_basis": "no_real_competitor",
                "source": "re_findings.competitor_audits"}
    target_intent = _val(fact_base["target"]["intent"])

    def keyed(c):
        sp = _val(c["serp_position"])              # fact_base (v2)
        c_intent = _val(c["intent"])               # fact_base (v2)
        intent_match = 1 if (c_intent and c_intent == target_intent) else 0
        return sp, intent_match, _val(c["content_words"]) or 0

    ranked_by_serp = [c for c in ok if _val(c["serp_position"]) is not None]
    if ranked_by_serp:
        # best SERP position; tie-break: intent match, then content_words
        best = min(ranked_by_serp,
                   key=lambda c: (keyed(c)[0], -keyed(c)[1], -keyed(c)[2]))
        basis = "serp_rank"
    else:
        # no ok competitor appears in the captured SERP → fallback
        best = max(ok, key=lambda c: (keyed(c)[1], keyed(c)[2]))
        basis = "fallback_intent_then_content"
    return {
        "value": {"url": _val(best["url"]), "brand": _val(best["brand"]),
                  "serp_position": _val(best["serp_position"])},
        "provenance": MEASURED,
        "selection_basis": basis,
        "source": "competition.competitors[].serp_position + discovery_status",
    }


# ---------------------------------------------------------------------------
# (2) target_stance
# ---------------------------------------------------------------------------
# SERP types that are NOT a homepage (a dedicated page wins the SERP)
_DEDICATED_TYPES = {
    "business_service": "dedicated service page",
    "business_blog_or_article": "dedicated content/resource page",
    "directory_listing": "comparison/listing page",
    "comparison_page": "comparison page",
    "wiki_or_reference": "reference/explainer page",
}
_DOMINANCE = 0.5


def decide_target_stance(fact_base: dict) -> dict:
    page_type = _val(fact_base["classification"]["page_type"])
    intent_group = _val(fact_base["classification"]["page_type_intent_group"])
    kw_intent = _val(fact_base["target"]["intent"])
    sf = fact_base["competition"]["serp_fit"]           # fact_base (v2)
    dist = _val(sf["serp_type_distribution"]) or {}
    target_type = _val(sf["target_type"])
    fit = _val(sf["target_type_fit"])
    kw_rec_trigger = _val(sf["keyword_recommendation_trigger"])

    if not dist:
        return {"verdict": None, "provenance": NOT_MEASURED,
                "dedicated_page_recommendation": False,
                "note": "SERP per-URL page-type distribution not available"}

    total = sum(dist.values()) or 1
    dominant_type = max(dist, key=dist.get)
    dominant_share = round(dist[dominant_type] / total, 2)
    client_is_homepage = (target_type == "business_homepage" or page_type == "homepage")

    verdict = "good_fit"
    dedicated = False
    honesty_note = None
    rec_page_kind = None

    if (client_is_homepage and dominant_type in _DEDICATED_TYPES
            and dominant_share >= _DOMINANCE):
        verdict = "page_type_mismatch"
        dedicated = True
        rec_page_kind = _DEDICATED_TYPES[dominant_type]
        honesty_note = (
            "SERP for the target keyword is dominated by %s (%.0f%%). "
            "Recommendation is ADDITIVE: evaluate building a %s targeting this "
            "keyword. Do NOT recommend repositioning the homepage (it stays the "
            "brand/portfolio page), and make NO claim about that dedicated page's "
            "content — it is not measured." % (dominant_type, dominant_share * 100, rec_page_kind))
    elif kw_rec_trigger is True:
        # Authoritative upstream signal (AAA-118): the keyword itself is a poor
        # fit and an alternative is suggested. We do NOT infer intent_mismatch
        # from page_type_intent_group vs keyword-intent alone — a homepage is
        # navigational by nature, so that crossing would flag nearly every
        # homepage and re-introduce the §2/§3/§4 flip-flop.
        verdict = "intent_mismatch"
        honesty_note = (
            "Upstream keyword-fit analysis flags the target keyword as a poor "
            "fit (page intent %s vs keyword intent %s); frame the keyword-fit "
            "gap and the suggested alternative, not a homepage rewrite." % (intent_group, kw_intent))

    return {
        "verdict": verdict,
        "provenance": MEASURED,
        "dedicated_page_recommendation": dedicated,
        "recommended_page_kind": rec_page_kind,
        "serp_dominant_type": dominant_type,
        "serp_dominant_share": dominant_share,
        "target_type": target_type,
        "target_type_fit": fit,
        "honesty_note": honesty_note,
        "evidence": ["competition.serp_fit.serp_type_distribution",
                     "classification.page_type", "target.intent"],
    }


# ---------------------------------------------------------------------------
# (3) ranked_findings
# ---------------------------------------------------------------------------
def _categorize(text: str) -> str:
    t = (text or "").lower()
    if "schema" in t or "structured data" in t:
        return "schema"
    if any(w in t for w in ("cited", "ai overview", "ai-overview", "chatgpt", "citation")):
        return "visibility"
    if any(w in t for w in ("rank", "serp", "top 10", "top-10")):
        return "ranking"
    if any(w in t for w in ("heading", "landmark", "aria", "structure")):
        return "structure_accessibility"
    if any(w in t for w in ("redirect", "canonical", "https", "index", "speed",
                            "performance", "perf", "crux", "core web")):
        return "technical"
    if any(w in t for w in ("content", "word", "depth", "entity", "coverage")):
        return "content"
    return "content"


def _normalize_sev(text: str, base: str, category: str) -> str:
    """Impact-driven caps: schema never High; structure/a11y not ranking-critical."""
    sev = base if base in _SEV_RANK else "medium"
    if category == "schema" and sev == "high":
        sev = "medium"
    if category == "structure_accessibility" and sev == "high":
        sev = "low"
    return sev


def _finding(text, sev, category, evidence, conditional=False, recommendation=None):
    return {"finding": text, "impact_severity": sev, "category": category,
            "evidence_facts": evidence, "conditional": conditional,
            "recommendation": recommendation}


def decide_ranked_findings(fact_base: dict) -> list:
    fnds = []
    fb = fact_base
    # --- (a) competitive patterns ---
    patterns = fb["competition"]["patterns"]
    if _prov(patterns) == MEASURED:
        for i, p in enumerate(_val(patterns) or []):
            if not isinstance(p, dict):
                continue
            text = p.get("finding") or ""
            cat = _categorize(text)
            sev = _normalize_sev(text, (p.get("severity") or "").lower(), cat)
            fnds.append(_finding(text, sev, cat,
                                 ["re_findings.comparison.patterns[%d]" % i],
                                 recommendation=p.get("recommendation")))
    has_schema_pattern = any(f["category"] == "schema" for f in fnds)

    # --- (b) ranking (measured/absent only) ---
    rk = fb["competition"]["client_ranking"]
    if _prov(rk) == ABSENT:
        fnds.append(_finding(
            "Client does not rank in the top 10 for the primary keyword",
            "high", "ranking", [rk["source"]]))

    # --- (c) AI visibility (measured/absent only; not_measured EXCLUDED) ---
    cc = fb["ai_visibility"]["ai_overview_client_cited"]
    if _prov(cc) == ABSENT:  # evaluated, not cited
        fnds.append(_finding(
            "Client is not cited in the Google AI Overview for the query",
            "high", "visibility", [cc["source"]], conditional=True))
    cg = fb["ai_visibility"]["chatgpt_target_cited"]
    if _prov(cg) == ABSENT:
        fnds.append(_finding(
            "Client is not cited in the ChatGPT answer for the query",
            "medium", "visibility", [cg["source"]], conditional=True))

    # --- (d) technical (measured negatives kept; real redirect kept) ---
    https = fb["technical"]["https"]
    if _prov(https) == MEASURED and _val(https) is False:
        fnds.append(_finding("Site is not served over HTTPS", "high",
                             "technical", [https["source"]]))
    idx = fb["technical"]["indexed"]
    if _prov(idx) == MEASURED and _val(idx) is False:
        fnds.append(_finding("Page is not indexed by Google", "high",
                             "technical", [idx["source"]]))
    rc = fb["technical"]["redirect_chain"]
    if _prov(rc) == MEASURED and isinstance(_val(rc), list) and len(_val(rc)) > 1:
        fnds.append(_finding("Entry URL goes through a redirect chain", "low",
                             "technical", [rc["source"]]))

    # --- (e) on-page absent / structure (not ranking-critical) ---
    sm = fb["onpage"]["schema"]["pagetype_match"]
    if (not has_schema_pattern and _prov(sm) == MEASURED and _val(sm) is False):
        fnds.append(_finding(
            "Structured-data types do not fully match the page type",
            "medium", "schema", [sm["source"]]))
    ls = fb["onpage"]["headings"]["level_skips"]
    if _prov(ls) == MEASURED and (_val(ls) or 0) > 0:
        fnds.append(_finding("Heading hierarchy has level skips", "low",
                             "structure_accessibility", [ls["source"]]))
    lm = fb["onpage"]["aria"]["landmarks_missing"]
    if _prov(lm) == MEASURED and _val(lm):
        fnds.append(_finding("Some structural landmarks are missing", "low",
                             "structure_accessibility", [lm["source"]], conditional=True))
    lc = fb["onpage"]["forms"]["label_coverage"]
    if _prov(lc) == MEASURED and isinstance(_val(lc), (int, float)) and _val(lc) < 1.0:
        fnds.append(_finding("Some form fields lack bound labels", "medium",
                             "content", [lc["source"]], conditional=True))

    # --- (f) AAA-161 G2: content-QA / placeholder leak (Trust, HIGH) ---
    # page_flag provenance MEASURED == a positive leak (AAA-173 hard/name hit);
    # ABSENT == detector ran clean; not_measured == no detector. Only the
    # positive-measured case raises a finding.
    cq_flag = fb["onpage"].get("content_qa", {}).get("page_flag")
    if cq_flag and _prov(cq_flag) == MEASURED and _val(cq_flag) is True:
        hh = fb["onpage"]["content_qa"].get("hard_hit_count") or {}
        ev = [cq_flag["source"]]
        if hh.get("source"):
            ev.append(hh["source"])
        fnds.append(_finding(
            "Unfinished / placeholder content on the page",
            "high", "trust", ev))

    # impact-driven order: severity desc, then category priority, stable
    fnds.sort(key=lambda f: (-_SEV_RANK.get(f["impact_severity"], 0),
                             -_CAT_PRIORITY.get(f["category"], 0)))
    return fnds


# ---------------------------------------------------------------------------
# (4) recommendation_guards
# ---------------------------------------------------------------------------
def decide_recommendation_guards(fact_base: dict) -> dict:
    cls = fact_base["classification"]
    locality = _val(cls["locality"])
    page_type = _val(cls["page_type"])
    bm = _val(cls["business_model"])

    allow, deny, flags = [], [], {}

    # locality
    if locality == "global":
        deny += ["local_seo", "google_business_profile", "local_citations"]
        flags["local_seo"] = "deny"

    # page_type
    if page_type == "homepage":
        flags["homepage_expectations"] = (
            "do NOT require breadcrumb/article landmarks; do NOT expect deep "
            "article-length content on the homepage")
        deny += ["require_breadcrumb", "expect_long_form_article_on_homepage"]

    # business_model → schema/recommendation profile
    if bm in _SAAS_MODELS:
        allow += ["SoftwareApplication", "Offer", "Organization", "lead_form"]
        deny += ["LocalBusiness", "Product_schema_for_service"]
        flags["schema_profile"] = "saas"
    elif bm in _SERVICE_MODELS:
        allow += ["Person", "Service", "Organization"]
        deny += ["LocalBusiness", "ProfessionalService", "Product"]
        flags["schema_profile"] = "service"
    else:
        allow += ["Organization", "WebPage"]
        flags["schema_profile"] = "generic"

    # fabrication guard (absent AND not_measured both forbid fabrication)
    flags["fabrication_guard"] = (
        "never assert a value whose provenance is absent or not_measured "
        "(e.g. secondary audience, an unmeasured page); state plainly it is "
        "not available")

    # competitor-entity guard (RG4 mitigation)
    flags["competitor_entity_guard"] = (
        "competitor entity name lists are not_measured — only count-level and "
        "schema-type-level competitor claims are allowed; NO concrete competitor "
        "entity-name claims")

    return {"allow": sorted(set(allow)), "deny": sorted(set(deny)), "flags": flags}


# ---------------------------------------------------------------------------
# (5) diagnosis_inputs
# ---------------------------------------------------------------------------
def _ref(key, fact):
    return {"key": key, "value": _val(fact), "provenance": _prov(fact),
            "source": (fact or {}).get("source")}


def decide_diagnosis_inputs(fact_base: dict, ranked_findings: list) -> dict:
    fb = fact_base
    ranked_facts = []
    excluded = []

    # client ranking — include if measured/absent
    rk = fb["competition"]["client_ranking"]
    if _prov(rk) in (MEASURED, ABSENT):
        ranked_facts.append(_ref("client_ranking", rk))
    else:
        excluded.append("client_ranking")

    # AI overview citation — ONLY if measured/absent (kk.coach not_measured → out)
    cc = fb["ai_visibility"]["ai_overview_client_cited"]
    if _prov(cc) in (MEASURED, ABSENT):
        ranked_facts.append(_ref("ai_overview_client_cited", cc))
    else:
        excluded.append("ai_overview_client_cited")

    # measured content/entity gap (dimension_table)
    dt = fb["competition"]["dimension_table"]
    if _prov(dt) == MEASURED:
        ranked_facts.append(_ref("dimension_table", dt))

    # top ranked findings (impact carrier; not_measured already excluded upstream)
    top = [{"finding": f["finding"], "impact_severity": f["impact_severity"],
            "category": f["category"]} for f in ranked_findings[:4]]

    return {
        "ranked_facts": ranked_facts,
        "top_findings": top,
        "offpage_unmeasured": True,  # we never measure backlinks/off-page —
        # S3 MUST hedge: no on-page-only causal claim for non-citation/non-ranking
        "excluded_not_measured": excluded,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def build_decisions(fact_base: dict) -> dict:
    """Pure: fact_base → decisions scaffold. Reads ONLY the fact_base (single
    source of truth). Deterministic, $0, no LLM."""
    ranked = decide_ranked_findings(fact_base)
    return {
        "meta": {"schema_version": DECISIONS_VERSION,
                 "audit_id": fact_base["meta"].get("audit_id"),
                 "url": fact_base["meta"].get("url")},
        "anchor": decide_anchor(fact_base),
        "target_stance": decide_target_stance(fact_base),
        "ranked_findings": ranked,
        "recommendation_guards": decide_recommendation_guards(fact_base),
        "diagnosis_inputs": decide_diagnosis_inputs(fact_base, ranked),
    }
