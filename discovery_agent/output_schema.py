"""Pydantic models for the Discovery Agent's structured audit output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- AAA-91 search-intent taxonomy ----------------------------------------
# L1 (AAA-84, byte-unchanged) + L1-conditional L2 sublists. The L2 Literal
# aliases are the single source of truth, reused by keyword_classify's
# response-schema item models (discriminated union).
SearchIntentL1 = Literal[
    "informational", "commercial", "transactional", "navigational"
]
InformationalL2 = Literal[
    "definition", "how_to", "why", "knowledge", "comparison_info"
]
CommercialL2 = Literal[
    "review", "best_of", "versus", "alternatives", "pricing_research"
]
TransactionalL2 = Literal[
    "purchase", "sign_up", "download", "contact", "quote_request"
]
NavigationalL2 = Literal["branded", "direct", "section_lookup"]
L2_BY_L1: dict[str, tuple[str, ...]] = {
    "informational": ("definition", "how_to", "why", "knowledge",
                       "comparison_info"),
    "commercial": ("review", "best_of", "versus", "alternatives",
                   "pricing_research"),
    "transactional": ("purchase", "sign_up", "download", "contact",
                      "quote_request"),
    "navigational": ("branded", "direct", "section_lookup"),
}


class KeywordClassification(BaseModel):
    """Per-keyword classification produced by AAA-84 (keyword_classify).

    Emitted alongside (NOT replacing) the heterogeneous target_keywords
    dict — see AAA-87 (side-by-side tech-debt watch): keyword strings live
    in target_keywords; per-keyword classification lives in
    target_keywords_classified. AAA-87 tracks the future unification.

    EMPIRICAL STABILITY (AAA-84 Sub-step 2 variance characterization,
    2026-05-21) — measured across 5 stability URLs x 5 production runs
    = 25 audits:

    | Field           | Stability      | Confidence tier                  |
    |-----------------|----------------|----------------------------------|
    | keyword         | byte-stable    | TRUSTWORTHY (Discovery det.)     |
    | tail_type       | 81% mean       | MOSTLY STABLE (ambiguous lower)  |
    | search_intent   | 60% mean       | BEST-EFFORT (judgment-laden)     |
    | relevance_score | drift p90 0.24 | DIRECTIONAL (coarse ranking)     |

    Top-1 keyword (sorted desc by relevance_score, position [0]) is
    byte-stable across runs. Top-3 ordering is 2.4/5 byte-equal per URL —
    #1 stable, #2/#3 shuffle.

    DOWNSTREAM CONSUMERS:
    - Validation UI (AAA-67): all fields displayable; the human scorer's
      manual judgment dominates.
    - Future Evaluator agent: search_intent and fine-grained
      relevance_score MUST be consumed as best-effort / directional, NOT
      byte-stable ground truth. Variance reduction: see AAA-90
      (watch-only until the Evaluator is load-bearing on intent).

    AAA-76 VOLUME ENRICHMENT (added 2026-05-21):
    - search_volume_monthly: monthly Google Ads search volume (HU / EN-US)
    - trend_12m: list of {year, month, search_volume} for the last 12 months
    - cpc_usd: cost per click (Google Ads)
    - competition: LOW / MEDIUM / HIGH
    - competition_index: 0-100 numeric competition score

    EXPECTED FILL RATE: ~15% (AAA-76 Sub-step 1 empirical, 2026-05-21).
    Reason: AAA-84 keyword extraction generates LLM-natural page-topic
    phrases, which are NOT typically real user search queries. Null volume
    fields = legitimate "no measurable search volume" signal, NOT failure.
    For real-keyword discovery (alternative architecture): see AAA-92
    (watch-only).
    """
    keyword: str
    tail_type: Literal["shorttail", "midtail", "longtail"] | None = None
    search_intent: SearchIntentL1 | None = None  # L1 — AAA-84, byte-preserved
    # AAA-91 L2 — hierarchical subtype within search_intent (L1). Typed
    # str|None (NOT a strict Literal) on this public model: the
    # L1-conditional discriminated union is enforced at the Gemini
    # structured-output schema level (keyword_classify), not via Pydantic
    # cross-field validation — this keeps legacy entries backward-compatible.
    #
    # STABILITY (AAA-91 Sub-step 2, 5 URL x 5 run = 25 audits, 2026-05-21):
    #   - L2 CONDITIONAL byte-stability (given L1 agrees) = 82.8% mean
    #     -> MOSTLY STABLE. This is the L2 layer's own added noise.
    #   - L2 RAW byte-stability = 46.1% mean -> BEST-EFFORT, but this is
    #     mostly INHERITED L1 noise (L1 itself ~54-60% end-to-end); when L1
    #     is held fixed, L2 is reliable.
    #   - Within identical input: L2 is byte-deterministic (Sub-step 1).
    #   - Per-L1: transactional 89% / commercial 73% / informational 57%
    #     (informational L2 sub-types are the softest boundary).
    # Consume L2 as MOSTLY STABLE *when paired with a stable L1*; treat the
    # raw L2 of any single audit as BEST-EFFORT (it rides L1's noise).
    search_intent_l2: str | None = None
    relevance_score: float | None = None  # 0.0-1.0
    # AAA-76 volume enrichment (DataForSEO Google Ads; ~15% fill rate)
    search_volume_monthly: int | None = None
    trend_12m: list[dict] | None = None  # [{year, month, search_volume}, ...]
    cpc_usd: float | None = None
    competition: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    competition_index: int | None = None  # 0-100


class AuditMetadata(BaseModel):
    tools_called: list[str] = Field(default_factory=list)
    playwright_escalated: bool = False
    duration_seconds: float = 0.0
    cost_usd_estimate: float = 0.0
    errors: list[str] = Field(default_factory=list)


class AuditOutput(BaseModel):
    url: str
    grounding_confidence: str = "high"  # AAA-51: 'low' | 'high'
    eeat_signals: dict = Field(default_factory=dict)  # AAA-55: presence signals
    page_type: str = "other"            # AAA-55: LLM classifier
    page_type_model_version: str | None = None  # AAA-55/AAA-50 audit trail
    audit_kg_calls: int = 0          # AAA-56/AAA-53: KG request meter
    audit_kg_cost_usd: float = 0.0   # AAA-56: always 0.0 (KG free; see kg_validate)
    eeat_findings_count: int = 0     # AAA-56: injected E-E-A-T findings count
    audit_cost_usd: float = 0.0          # AAA-50: measured from usage_metadata
    audit_token_counts: dict = Field(default_factory=dict)  # {in, out}
    audit_metadata: AuditMetadata
    site_profile: dict = Field(default_factory=dict)
    crawl: dict = Field(default_factory=dict)
    rendered_crawl: dict | None = None
    target_keywords: dict = Field(default_factory=dict)
    entities: dict = Field(default_factory=dict)
    pagespeed: dict = Field(default_factory=dict)
    indexing: dict = Field(default_factory=dict)
    summary_markdown: str = ""
    # AAA-61 Sub-step 3 — summary_translations: dict[str, str]
    #   Mandatory keys: "en", "hu".
    #   "en" is the canonical learning artifact (identity copy of
    #   summary_markdown — Discovery agent always emits English).
    #   "hu" is the production HU-market rendering for the Validation UI.
    #   Future markets: add additional keys ("de", "es", "it", etc.) via the
    #   same translation pipeline. The dict structure supports lazy-future
    #   addition without schema migration.
    summary_translations: dict = Field(default_factory=dict)
    # AAA-61 Sub-step 4: Vertex AI RAG embedding pointer (EN canonical only).
    # {rag_file_id, embedded_at, embedded_language, embedding_model, _error}
    embedding_metadata: dict = Field(default_factory=dict)
    # AAA-64: active memory retrieval cost meter (AAA-53 separation —
    # NEVER folded into audit_cost_usd). Free quota -> 0.0.
    audit_memory_retrieval_calls: int = 0
    audit_memory_retrieval_cost_usd: float = 0.0
    # AAA-80: Google AI-Mode query fan-out for the primary target keyword
    # (verbatim from grounding_metadata.web_search_queries; diacritics may
    # be Search-normalized). audit_fan_out_cost_usd is SEPARATE (AAA-53).
    query_fan_out: list = Field(default_factory=list)
    audit_fan_out_cost_usd: float = 0.0
    # AAA-84 — side-by-side per-keyword classification (Option A; AAA-87
    # tracks the dual-field tech debt). target_keywords (above) stays the
    # current heterogeneous dict, byte-unchanged; this field carries the
    # batched LLM classification sorted desc by relevance_score.
    target_keywords_classified: list[KeywordClassification] = Field(
        default_factory=list
    )
    audit_keyword_classify_cost_usd: float = 0.0  # AAA-53 separation
    # AAA-76 — DataForSEO keyword-volume enrichment cost (AAA-53 separation;
    # batched $0.075 flat regardless of keyword count).
    audit_keywords_volume_cost_usd: float = 0.0
    # AAA-85 — AI Overview trigger state for the PRIMARY keyword only.
    #   None  = not measured (API failure, or no primary keyword)
    #   False = checked, AI Overview did NOT trigger
    #   True  = checked, AI Overview triggered
    # AAA-137: legacy boolean kept for back-compat; now DERIVED from
    # ai_overview.present (None when ai_overview unmeasured).
    ai_overview_triggered: bool | None = None
    audit_ai_overview_cost_usd: float = 0.0  # AAA-53 separation
    # AAA-137 — AI Overview cited-source capture (schema-additive, forward-only;
    # legacy audits keep None). Shape:
    #   {present: bool, markdown: str|None, cited_sources: [{title,url}],
    #    client_cited: bool|None, asynchronous: bool, note?: str}
    # present=False -> AIO didn't trigger. asynchronous=True OR empty references
    # -> present=True, cited_sources=[], client_cited=None, note="async,
    # citations unavailable" (skip-finding; no retry). None = not measured.
    ai_overview: dict | None = None
    # AAA-86 — single OpenAI Responses API call (gpt-5.4 + web_search tool)
    # combining citation tracking + query fan-out (fulfils AAA-80 Sub-step
    # 1c in the same call). None = not measured / API failure.
    # {query, response_text, citations[], target_site_cited, fan_out_queries}
    chatgpt_query_response: dict | None = None
    audit_chatgpt_cost_usd: float = 0.0  # AAA-53 separation
    # AAA-95 — fan-out variant_type enrichment: each AAA-80 + AAA-86 fan-out
    # query classified into one of 8 US11663201B2 transformation types.
    # Entry: {query, source, variant_type, _meta}. AAA-94 forward-compat —
    # a future `variant_types: list[str]` (multi-label) may sit beside the
    # single `variant_type`; readers must tolerate its absence.
    fan_out_enriched: list = Field(default_factory=list)
    audit_fan_out_enrichment_cost_usd: float = 0.0  # AAA-53 separation
    # AAA-95 Sub-step 2.1 — coverage classification: each fan_out_enriched
    # entry gains `coverage` + `suggestion` in-place. Cost SEPARATE.
    audit_fan_out_coverage_cost_usd: float = 0.0
    # AAA-42 — raw-HTML agent-friendliness measurements (selectolax-only,
    # $0, <2s). 7 dimensions: semantic_html, landmarks, heading, forms,
    # images, aria, schema_actions. Deterministic, no LLM.
    agent_friendly_measurements: dict = Field(default_factory=dict)
    # AAA-42 Sub-step 1b — which HTML source AAA-42 actually measured:
    # "httpx"                 = initial httpx fetch (Playwright either didn't
    #                            escalate, or escalated but was NOT promoted
    #                            (rendered shell had fewer/equal words))
    # "playwright_escalation" = Playwright-rendered DOM was promoted to active
    render_method_used: str = "httpx"
    # AAA-89 — Chrome UX Report (CrUX) field data parsed from the PSI
    # response (Option A: zero new endpoint/key). {url_level, origin_level,
    # form_factor, collection_period_end, _error}. has_data=False is a
    # legitimate "no CrUX coverage" signal; _error is reserved for PSI
    # call failures (timeout/4xx/5xx/config).
    crux_field_data: dict = Field(default_factory=dict)
    # AAA-77 v2 + AAA-81 v3 + AAA-113 — multi-dimensional Discovery
    # classification (coordinated ship, 2026-05-25). Single multi-field
    # Gemini call populates these 7 fields (8 incl. derived parent intent).
    # Forward-only contract: old audits keep `None`, NEW audits populate.
    #
    # NOTE on `page_type`: the existing field (AAA-55, 11-value taxonomy)
    # is OVERWRITTEN by the multi-dim classifier with the new AAA-81 v3
    # 27-leaf taxonomy. Old audits keep their legacy value. Downstream
    # consumers (e.g. select_validation_entities AAA-56) read the string
    # opaquely; the leaf names that drove the AAA-56 author/team gating
    # are subsumed by the new taxonomy (homepage / about_page → other leafs
    # in v3 — verify before deprecating AAA-55 classifier in a follow-up).
    page_type_parent_intent_group: str | None = None  # derived from page_type
    business_model: str | None = None                  # AAA-77 v2 (26-enum)
    topic_domain: str | None = None                    # IAB 3.1 Tier-1 (30+1)
    locality: str | None = None                        # 4-enum + unknown
    audience_relationship_primary: str | None = None   # 11-enum
    audience_relationship_secondary: str | None = None # 11-enum, opt
    audience_confidence: int | None = None             # 0-100, AAA-91 pattern
    audit_multi_dim_classify_cost_usd: float = 0.0     # AAA-53 separation

    # AAA-118 Sub-step 1 — Stage 1 SERP-fit classification.
    # Populated when the RE workflow's SERP fetch (AAA-50 / DataForSEO)
    # runs end-to-end. One list entry per fetched keyword (primary +
    # secondary). Each entry contains the top-10 organic results from
    # the SERP, each classified by serp_type (22-leaf taxonomy locked
    # 2026-05-26) + topic_relevance_score (0.0-1.0, Stage 2 formula-C-v2
    # topic-fit proxy per Opció X lockdown).
    # 24h Firestore cache (serp_fit_cache/) avoids re-classifying the
    # same (url, topic_cluster, category_keyword) tuple within TTL.
    # AAA-53 cost separation: audit_serp_fit_cost_usd is SEPARATE,
    # never folded into audit_cost_usd.
    # Forward-only: old audits keep `[]`; cost fields stay 0.0/0.
    serp_fit_analysis: list = Field(default_factory=list)
    audit_serp_fit_cost_usd: float = 0.0
    audit_serp_fit_call_count: int = 0
    audit_serp_fit_cache_hits: int = 0
    # AAA-118 Sub-step 2.2 — target_type deterministic mapping from
    # AAA-81 v3 page_type → AAA-118 22-leaf SERP type. Audit-level
    # because target_type is a property of the TARGET SITE, NOT of any
    # individual SERP keyword. ALSO duplicated per-keyword inside
    # serp_fit_analysis[i].target_type for downstream-consumer ergonomics
    # (single-iterate access pattern). audit_serp_fit_cost_usd ALSO
    # absorbs the per-keyword alternative_keyword_suggestions LLM-call
    # cost when target_type_fit == "low" (verdict bands in
    # page_analysis.serp_fit_classify.compute_target_type_fit).
    audit_target_type: str | None = None

    # AAA-114 Sub-step 1 — Stage 2 deterministic competitor filtering.
    # Consumes AAA-118 Stage 1 output + audit_target_type, applies formula
    # C v1 hard+soft filters, emits a top-3 selected competitor list with
    # full per-candidate audit-trail.
    # Forward-only: stand-alone Discovery audits keep `[]` / `False`.
    # F-additive contract: existing re_findings.competitor_audits (AAA-108
    # legacy) continues to populate independently and is NOT mutated.
    # Per-candidate dict shape:
    #   {url, position, keyword, keyword_role, serp_type,
    #    topic_relevance_score, hard_filter_pass, hard_filter_fail_reason,
    #    soft_score, soft_score_breakdown, selected, selection_rank}
    selected_competitors_v2: list = Field(default_factory=list)
    audit_no_comparable_competitors_found: bool = False

    # AAA-123 Sub-step 1 — Phase 2 raw-HTML structural + 2 MB cutoff +
    # rendering-mode measurements. Pure-Python, no LLM, deterministic;
    # consumes the same _raw_html_transient as AAA-42. Three sub-trees:
    # (A) semantic_structure (10 dims), (B) google_2mb_cutoff (cutoff
    # position + content-after-cutoff %), (C) rendering_mode
    # (is_csr_likely + SPA framework signals via v2 marker list).
    # Forward-only: stand-alone Discovery audits keep None until the
    # AAA-123 ship; legacy entries (pre-AAA-123) remain unmodified.
    # Skip-finding per sub-tree: each of the 3 sub-keys carries its own
    # _error string on independent failure (the audit + the other two
    # sub-trees continue).
    phase2_html_measurements: dict | None = None

    # AAA-124 Sub-step 1 (Option E narrow scope) — per-aspect page evaluations.
    # ONE Gemini 3.5 Flash holistic (V3) call producing 7 per-aspect findings:
    # macro_structure / heading_semantics / above_the_fold / micro_semantics /
    # inline_link_semantics / forms_conversion_points / schema_entity. Each
    # aspect: {structured_finding, confidence_0_1, justification, recommendation}.
    # Preventive-only ground-truth anchoring (AAA-42 + AAA-123); NO aggregate
    # index scoring + NO multi-axis weighting (Sub-step 0 (D.1) deferred).
    # Cost SEPARATE (audit_aspect_eval_cost_usd, AAA-53). Schema-additive
    # forward-only: legacy + failed audits keep None. Runs AFTER multi_dim
    # classify (page_type) + AFTER phase2_html_measurements, BEFORE write_audit.
    aaa124_aspect_evaluations: dict | None = None
    audit_aspect_eval_cost_usd: float | None = None

    # AAA-158 Sub-step 1 — deterministic ($0) title + meta-description SERP
    # measurement: pixel length + truncation verdict (title 600px; desc 920px
    # desktop / 680px mobile) via a pure-Python Arial advance-width LUT
    # (WIDTH_TABLE_VERSION stamp), plus gated quality signals (title↔H1 dup,
    # brand-in-title, keyword presence). No LLM, no new dependency. Forward-only:
    # legacy + crawl-failed audits keep None / carry an _error skip-finding.
    title_meta_measurements: dict | None = None

    # AAA-108 — Reverse-engineering workflow output. Populated ONLY when the
    # RE workflow ran end-to-end (client + SERP × 2 + competitors +
    # comparison) and the RE persistence step (post-workflow dotted-path
    # update via reverse_engineering_agent.tools.persist_re_findings) fired.
    # None for stand-alone Discovery audits — the field never exists on the
    # archive doc until RE attaches it. Same precedent as rendered_crawl /
    # chatgpt_query_response.
    # Shape (8 dimensions; see persist_re_findings for source-of-truth):
    #   serp_branded, serp_category, serps_identical,
    #   selected_competitors {branded, category},
    #   client_ranking_status {branded, category},
    #   competitor_audits {url -> "ok" | "error: ..."},
    #   comparison, memory_retrieval,
    #   audit_re_serp_cost_usd, audit_re_comparison_cost_usd,
    #   re_workflow_completed.
    # Costs are SEPARATE (AAA-53 pattern); NEVER folded into audit_cost_usd.
    re_findings: dict | None = None
