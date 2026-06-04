# -*- coding: utf-8 -*-
"""AAA-161 / RG1-S3 — consolidated render (one coherent Gemini pass).

ONE Gemini call writes the ~6-section customer report from the fact_base (v2)
+ decisions (S2). The render PHRASES, it never re-decides: primary diagnosis from
decisions.diagnosis_inputs, closing priority from decisions.ranked_findings, the
keyword stance from decisions.target_stance (honesty_note kept verbatim in
intent), the comparison from fact_base.competition (count/schema level only —
competitor entity-name claims are guard-forbidden).

INPUT IS EXCLUSIVELY (fact_base, decisions). If a section needed raw audit_output
that would mean S2.1 missed context → STOP (assert_inputs_complete()).

Production contract (AAA-130/143, unchanged): gemini-3.5-flash, temp 0.3,
thinking_level LOW; EN canonical here, HU via the existing TRANSLATION_PASS
(separate concern, not in this module); section headers keep the parser-contract
shape ``## §<id> — <title>``.

Determinism: the DATA the prompt embeds is a deterministic PROJECTION of
fact_base+decisions — not_measured facts are stripped, internal taxonomy labels
are humanized in code (not left to the model), guards/findings/stance are passed
as structured data. The model only phrases.

DRY-RUN GATE: assemble_render_prompt() is $0 (no API). The live call
(render_consolidated()) must NOT run before the dry-run prompt is reviewed.
"""
from __future__ import annotations

import json

from report.customer_render import AUDIENCE
from report.fact_base import MEASURED, ABSENT, NOT_MEASURED

RENDER_MODEL = "gemini-3.5-flash"
RENDER_VERSION = "consolidated_v1"

# Internal taxonomy → human language (no internal-label leak; deterministic).
_PAGE_TYPE_HUMAN = {
    "business_homepage": "company homepage",
    "business_blog_or_article": "blog post / article",
    "business_service": "service page",
    "business_product": "product page",
    "directory_listing": "directory / listing page",
    "comparison_page": "comparison page",
    "wiki_or_reference": "reference / explainer page",
    "search_results_page": "search-results page",
}
_BIZ_HUMAN = {
    "b2b_saas": "B2B software (SaaS)", "b2c_saas": "consumer software (SaaS)",
    "b2b_service": "B2B service business", "consultancy": "consultancy",
    "agency": "agency", "ecommerce": "online store",
}


def _human_pt(t):
    return _PAGE_TYPE_HUMAN.get(t, (t or "").replace("_", " ")) if t else None


# Landmarks NOT expected on a homepage (homepage_expectations guard) — filtered
# from missing_landmarks so the render cannot fault a guard-denied landmark.
_HOMEPAGE_NONREQUIRED_LANDMARKS = {"article", "aside"}


def _v(fact):
    return (fact or {}).get("value")


def _is(fact, *provs):
    return (fact or {}).get("provenance") in provs


def _keep(fact):
    """Include a fact only if measured/absent (not_measured is stripped — the
    render must never make a claim from a not_measured fact)."""
    return _v(fact) if _is(fact, MEASURED, ABSENT) else None


def _filter_landmarks(missing, page_type):
    """On a homepage, drop landmarks the homepage_expectations guard does NOT
    require (article/aside) so the render cannot fault a guard-denied landmark."""
    if not missing:
        return missing
    if page_type == "homepage":
        return [m for m in missing if m not in _HOMEPAGE_NONREQUIRED_LANDMARKS]
    return missing


# ---------------------------------------------------------------------------
# STOP guard — render inputs must be complete from fact_base + decisions
# ---------------------------------------------------------------------------
_REQUIRED_FB = [
    ("classification", "business_model"), ("classification", "page_type"),
    ("classification", "locality"), ("target", "primary_keyword"),
    ("competition", "competitors"), ("competition", "dimension_table"),
    ("competition", "serp_top10"), ("competition", "serp_fit"),
    ("ai_visibility", "ai_overview_client_cited"), ("technical", "indexed"),
]
_REQUIRED_DEC = ["anchor", "target_stance", "ranked_findings",
                 "recommendation_guards", "diagnosis_inputs"]


def assert_inputs_complete(fact_base: dict, decisions: dict) -> None:
    """Raise if any render section would need raw audit_output (i.e. a key the
    fact_base/decisions does not carry). This is the S3 STOP contract."""
    missing = []
    for sect, key in _REQUIRED_FB:
        if key not in (fact_base.get(sect) or {}):
            missing.append("fact_base.%s.%s" % (sect, key))
    for key in _REQUIRED_DEC:
        if key not in decisions:
            missing.append("decisions.%s" % key)
    if missing:
        raise ValueError(
            "RENDER STOP — inputs incomplete on fact_base+decisions (would need "
            "raw audit_output): %s" % ", ".join(missing))


# ---------------------------------------------------------------------------
# Deterministic render view (measured/absent only; humanized; $0)
# ---------------------------------------------------------------------------
def build_render_view(fact_base: dict, decisions: dict) -> dict:
    fb, dec = fact_base, decisions
    cls, tgt = fb["classification"], fb["target"]
    onp, aiv, tech, comp = fb["onpage"], fb["ai_visibility"], fb["technical"], fb["competition"]

    subject = {
        "brand": fb["meta"].get("brand"),
        "url": fb["meta"].get("url"),
        "topic_domain": _keep(cls["topic_domain"]),
        "business_model": _BIZ_HUMAN.get(_keep(cls["business_model"]), _keep(cls["business_model"])),
        "audience": _keep(cls["audience_primary"]),
        "page_kind": _human_pt(_keep(cls["page_type"])),
        "locality": _keep(cls["locality"]),
        "primary_keyword": _keep(tgt["primary_keyword"]),
        "keyword_intent": _keep(tgt["intent"]),
        "keyword_is_branded": _keep(tgt["is_branded"]),
    }

    onpage = {
        "h1_count": _keep(onp["headings"]["h1_count"]),
        "heading_level_skips": _keep(onp["headings"]["level_skips"]),
        "schema_types_present": _keep(onp["schema"]["types_found"]),
        "schema_matches_page_kind": _keep(onp["schema"]["pagetype_match"]),
        "form_label_coverage": _keep(onp["forms"]["label_coverage"]),
        "missing_landmarks": _filter_landmarks(
            _keep(onp["aria"]["landmarks_missing"]), _v(cls["page_type"])),
        "client_entities": {k: _keep(v) for k, v in onp["entities_client"].items()
                            if _keep(v)},
        "title_text": _keep(onp["title_meta"]["title_text"]),
        "meta_description": _keep(onp["title_meta"]["desc_text"]),
    }

    ai = {
        "ai_overview_present": _keep(aiv["ai_overview_present"]),
        "client_cited_in_ai_overview": (
            None if _is(aiv["ai_overview_client_cited"], NOT_MEASURED)
            else _v(aiv["ai_overview_client_cited"])),
        "ai_overview_cited_sources_count": (
            len(_keep(aiv["ai_overview_cited_sources"]) or [])
            if _keep(aiv["ai_overview_cited_sources"]) is not None else None),
        "client_cited_in_chatgpt": (
            None if _is(aiv["chatgpt_target_cited"], NOT_MEASURED)
            else _v(aiv["chatgpt_target_cited"])),
    }

    technical = {
        "indexed": _keep(tech["indexed"]),
        "https": _keep(tech["https"]),
        "canonical": _keep(tech["canonical_value"]),
        "has_redirect_chain": (len(_keep(tech["redirect_chain"]) or []) > 1
                               if _keep(tech["redirect_chain"]) is not None else None),
        "psi_mobile_performance": _keep(tech["psi_mobile_perf"]),
        "psi_desktop_performance": _keep(tech["psi_desktop_perf"]),
        "crux": {m: _v(tech["crux"][m]) for m in tech["crux"]
                 if _is(tech["crux"][m], MEASURED)},
    }

    # Competitors — count/schema level only (entity_lists are guard-forbidden).
    competitors = []
    for c in comp["competitors"]:
        if _v(c["discovery_status"]) != "ok":
            continue
        competitors.append({
            "brand": _keep(c["brand"]), "url": _keep(c["url"]),
            "serp_position": _keep(c["serp_position"]),
            "content_words": _keep(c["content_words"]),
            "schema_types": _keep(c["schema_types"]),
            "entity_counts": _keep(c["entity_counts"]),
            "perf_desktop": _keep(c["perf_desktop"]),
            "is_anchor": bool(c.get("is_anchor")),
        })
    serp_top10 = [{"position": e.get("position"), "url": e.get("url"),
                   "title": e.get("title"), "page_kind": _human_pt(e.get("page_type"))}
                  for e in (_keep(comp["serp_top10"]) or [])]
    sd = decisions["target_stance"].get("serp_dominant_type")
    competition = {
        "anchor": dec["anchor"]["value"] if _is(dec["anchor"], MEASURED) else None,
        "competitors": competitors,
        "dimension_table": _keep(comp["dimension_table"]),
        "comparison_patterns": _keep(comp["patterns"]),
        "serp_top10": serp_top10,
        "serp_landscape_dominant_kind": _human_pt(sd),
        "client_ranks_in_top10": (
            None if _is(comp["client_ranking"], NOT_MEASURED)
            else _v(comp["client_ranking"]).get("found_in_top_10")
            if _v(comp["client_ranking"]) else None),
    }

    # decisions — verbatim where it carries intent (honesty_note, guards, order)
    stance = dict(decisions["target_stance"])
    stance.pop("provenance", None)
    decisions_view = {
        "keyword_stance": stance,                       # honesty_note kept verbatim
        "ranked_findings": decisions["ranked_findings"],  # already impact-ordered
        "recommendation_guards": decisions["recommendation_guards"],
        "diagnosis_inputs": decisions["diagnosis_inputs"],
    }

    return {"subject": subject, "onpage": onpage, "ai_visibility": ai,
            "technical": technical, "competition": competition,
            "decisions": decisions_view}


# ---------------------------------------------------------------------------
# Hard rules + section map (prompt fragments)
# ---------------------------------------------------------------------------
HARD_RULES = """\
HARD RULES — non-negotiable, apply to every section:
1. PROVENANCE: state a fact ONLY if it appears in DATA. Every figure traces
   verbatim to DATA. The DATA already excludes anything not examined — so if a
   detail is not in DATA, it was not measured: NEVER assert, guess, or imply it.
   Do not write "no data"/"not available" filler; simply omit and move on.
2. RECOMMENDATION GUARDS (decisions.recommendation_guards): obey allow/deny
   exactly. Never recommend a denied schema type or topic. If local SEO / Google
   Business Profile is denied, do not mention it. On a homepage, do not fault a
   missing breadcrumb or demand long-form article content.
3. FABRICATION GUARD: never invent a secondary audience, a competitor entity
   name, or a page you were not given. Competitor claims stay at COUNT / SCHEMA-
   TYPE level only (e.g. "more organisations cited", "uses Product schema") —
   NEVER name a competitor's specific entities.
4. OFF-PAGE HEDGE: AI-visibility / citation findings must acknowledge that the
   off-page layer (backlinks, external authority) was NOT measured. Never give an
   on-page-only cause ("the reason you are not cited is X"). Frame as opportunity
   and contributing on-page factors, conditionally.
5. SCHEMA = hygiene / enhancement, NEVER a ranking blocker — even at medium
   severity. Frame structured-data gaps as machine-readability enhancements.
6. NO INTERNAL LABELS: no field names, ticket IDs, tool names, or internal
   taxonomy codes. Speak plain business language; explain any SEO term in a few
   words on first use.
7. ONE ANCHOR: use decisions.anchor as the single comparison thread; other
   competitors are supporting context only where DATA exists.
"""

AUDIENCE_NOTE = AUDIENCE

SECTION_MAP = """\
Write EXACTLY these sections, each headed `## §<n> — <title>` (en dash U+2014).
Collapse a section entirely (omit it) if DATA carries no signal for it — never
emit an empty section or a "no data" line.

## §1 — Where you stand
   Facts + classification opener: who this site is (brand, business type,
   audience, the page kind), the target keyword, and the single most important
   takeaway in ~2 sentences (from decisions.diagnosis_inputs — do NOT re-rank).

## §2 — Is anything wrong?
   The honest yes/no: are there real issues? Lead with the keyword stance
   (decisions.keyword_stance) — if it is an additive dedicated-page situation,
   state it EXACTLY per honesty_note: recommend evaluating a dedicated page
   ADDITIVELY; the homepage stays the brand page; make NO claim about that
   unmeasured page and NEVER say "reposition the homepage".

## §3 — The competitive facts
   What the market/SERP looks like for the keyword (humanised page kinds), and
   the anchor competitor's measured facts. Count/schema level only.

## §4 — How you compare
   Client vs the anchor across the measured dimensions (dimension_table +
   comparison_patterns). One coherent anchor thread.

## §5 — AI visibility
   AI Overview / assistant citation state (measured/absent only) WITH the
   off-page hedge from rule 4. Frame as opportunity, not on-page-only cause.

## §6 — Technical health + your priorities
   Technical facts (indexing, HTTPS, speed, redirects) framed in business terms,
   then the closing prioritised action list taken IN ORDER from
   decisions.ranked_findings (do NOT re-rank; schema stays hygiene; structure/
   accessibility items are not ranking-critical).
"""


def assemble_render_prompt(fact_base: dict, decisions: dict) -> str:
    """$0 — assemble the full consolidated-render prompt. No API call."""
    assert_inputs_complete(fact_base, decisions)
    view = build_render_view(fact_base, decisions)
    return "\n\n".join([
        "[AUDIENCE]\n" + AUDIENCE_NOTE,
        "[ROLE]\nYou are writing a customer-facing SEO / AI-visibility report. You "
        "PHRASE the supplied findings into clear business prose; you never compute, "
        "re-rank, or invent.",
        "[" "HARD RULES]\n" + HARD_RULES,
        "[SECTIONS]\n" + SECTION_MAP,
        "[DATA — the ONLY source of every claim; JSON]\n"
        + json.dumps(view, ensure_ascii=False, indent=1),
        "[OUTPUT]\nReturn ONLY the markdown sections (EN). No preamble, no JSON, no "
        "internal labels.",
    ])


def estimate_tokens(text: str) -> dict:
    """$0 heuristic token estimate (no tokenizer API). ~4 chars/token for EN."""
    chars = len(text)
    return {"chars": chars, "words": len(text.split()),
            "est_input_tokens": round(chars / 4)}


# ---------------------------------------------------------------------------
# Live call (STEP B only — do NOT run before dry-run review)
# ---------------------------------------------------------------------------
def render_consolidated(fact_base: dict, decisions: dict, *, client=None,
                        project=None, location="global", model=RENDER_MODEL) -> dict:
    """ONE live Gemini pass → {markdown, cost_usd, _meta}. Skip-finding on error."""
    from google.genai import types
    from report.customer_render import _make_client
    from site_profile.gemini_analyzer import compute_call_cost_usd

    prompt = assemble_render_prompt(fact_base, decisions)
    cl = client or _make_client(project=project, location=location)
    try:
        cfg = types.GenerateContentConfig(
            temperature=0.3,
            thinking_config=types.ThinkingConfig(thinking_level="LOW"))
        r = cl.models.generate_content(model=model, contents=prompt, config=cfg)
        um = r.usage_metadata
        itok = getattr(um, "prompt_token_count", 0) or 0
        otok = ((getattr(um, "candidates_token_count", 0) or 0)
                + (getattr(um, "thoughts_token_count", 0) or 0))
        cost = round(compute_call_cost_usd(model, itok, otok), 6)
        return {"markdown": (r.text or "").strip(),
                "_meta": {"render_version": RENDER_VERSION, "model": model,
                          "input_tokens": itok, "output_tokens": otok,
                          "cost_usd": cost, "_error": None}}
    except Exception as e:  # noqa: BLE001 — skip-finding
        return {"markdown": None,
                "_meta": {"render_version": RENDER_VERSION, "cost_usd": 0.0,
                          "_error": "%s: %s" % (type(e).__name__, e)}}
