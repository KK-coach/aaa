"""Run the Discovery Agent on the 5 demo URLs.

Run from project root:  python -m discovery_agent.test_agent
Optional single URL:    python -m discovery_agent.test_agent https://kk.coach
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from google.genai import types

from google.adk.runners import InMemoryRunner

from discovery_agent.agent import discovery_agent
from discovery_agent.output_schema import AuditMetadata, AuditOutput
from memory.firestore_archive import write_audit
from page_analysis.ai_overview_check import check_ai_overview_async
from page_analysis.keyword_classify import classify_keywords_with_l2
from page_analysis.keywords_volume import (
    fetch_keywords_volume,
    resolve_location_code,
)
from page_analysis.agent_friendly import measure_agent_friendliness
from page_analysis.crux_field_data import extract_crux_from_psi_response
from page_analysis.fan_out_coverage import analyze_fan_out_coverage
from page_analysis.fan_out_variant_classify import classify_fan_out_variants
from page_analysis.openai_audit import extract_chatgpt_response
from page_analysis.query_fan_out import detect_query_fan_out
from page_analysis.select_validation_entities import (
    select_entities_for_validation,
)
from page_analysis.kg_validate import kg_lookup, get_kg_usage, reset_kg_usage
from page_analysis.eeat_findings import generate_eeat_findings
from site_profile.gemini_analyzer import (
    _GEMINI_3_FLASH_INPUT_USD_PER_1M as _IN_PM,
    _GEMINI_3_FLASH_OUTPUT_USD_PER_1M as _OUT_PM,
    get_usage,
    reset_usage,
)

URLS = [
    "https://www.agrobook.hu",
    "https://kk.coach",
    "https://www.aboutyou.hu",
    "https://www.taxually.com",
    "https://vercel.com/products/vercel-platform",
]

OUT_DIR = Path(__file__).resolve().parent / "test_outputs"
PER_URL_TIMEOUT = 360  # seconds


async def audit(url: str, corpus_mode: bool = False,
                audit_id: str | None = None,
                eeat_anchor_keyword: str | None = None) -> dict:
    """Full client Discovery audit. AAA-75: corpus_mode=True produces a
    corpus-SUBSET entry for competitor archival — runs every KEEP step (crawl/
    site_profile/entities, grounding, KG E-E-A-T, multi-dim, CWV/CrUX, phase2,
    aspect-eval, industry, EN-canonical summary, embedding) but skips the
    client-strategy / external-API DROP steps (query fan-out, keyword classify+
    volume, AI-Overview + ChatGPT citation, fan-out variant/coverage, pre-write
    snapshot) and the HU translation pass."""
    runner = InMemoryRunner(discovery_agent, app_name="discovery")
    session = await runner.session_service.create_session(
        app_name="discovery", user_id="tester"
    )
    msg = types.Content(
        role="user", parts=[types.Part(text=f"Audit this URL: {url}")]
    )

    tools_called: list[str] = []
    summary_text = ""
    adk_in = adk_out = 0
    start = time.perf_counter()
    reset_usage()  # isolate this audit's vertex_generate token accounting

    async def _consume() -> None:
        nonlocal summary_text, adk_in, adk_out
        async for event in runner.run_async(
            user_id="tester", session_id=session.id, new_message=msg
        ):
            um = getattr(event, "usage_metadata", None)
            if um is not None:  # ADK Agent model turns (not via vertex_generate)
                adk_in += getattr(um, "prompt_token_count", 0) or 0
                adk_out += (getattr(um, "candidates_token_count", 0) or 0) + (
                    getattr(um, "thoughts_token_count", 0) or 0
                )
            for fc in (event.get_function_calls() or []):
                tools_called.append(fc.name)
            if event.content and event.content.parts:
                txt = "".join(
                    p.text for p in event.content.parts if getattr(p, "text", None)
                )
                if txt and event.content.role == "model":
                    summary_text = txt

    timed_out = False
    try:
        await asyncio.wait_for(_consume(), timeout=PER_URL_TIMEOUT)
    except asyncio.TimeoutError:
        timed_out = True

    duration = round(time.perf_counter() - start, 1)
    sess = await runner.session_service.get_session(
        app_name="discovery", user_id="tester", session_id=session.id
    )
    st = sess.state if sess else {}

    errors = []
    for k in ("crawl", "rendered_crawl", "site_profile"):
        v = st.get(k)
        if isinstance(v, dict) and v.get("error"):
            errors.append(f"{k}: {v['error']}")
    if timed_out:
        errors.append(f"agent exceeded {PER_URL_TIMEOUT}s timeout")

    # AAA-51: grounding confidence (from state; fall back to recompute).
    gc = st.get("grounding_confidence")
    if gc is None:
        from page_analysis._gemini import compute_grounding_confidence
        gc = compute_grounding_confidence(
            st.get("active_crawl") or st.get("crawl") or {}
        )

    if gc == "low":
        warning = (
            "> ⚠️ **AUDIT CONFIDENCE: LOW**\n"
            "> This site delivered limited content to search crawlers at the "
            "time of audit (JS-heavy rendering or thin server-side HTML). The "
            "audit was performed on the content available, but specific "
            "product, technology, or branding claims should be verified "
            "manually. This itself is an SEO/GEO finding: AI assistants and "
            "search bots see what we saw, not the full client-side "
            "experience.\n\n"
        )
        summary_text = warning + (summary_text or "")

    # --- AAA-56 Sub-step 5: deterministic E-E-A-T validation + injection ---
    reset_kg_usage()
    eeat = st.get("eeat_signals") or {}
    pt = st.get("page_type") or "other"
    spf = st.get("site_profile") or {}
    cands = select_entities_for_validation(eeat, pt, spf)
    kg_results = {
        c.name: await kg_lookup(c.name, list(c.expected_kg_types))
        for c in cands
    }
    eeat_findings = generate_eeat_findings(cands, kg_results, pt, eeat)
    kg_usage = get_kg_usage()
    eeat_findings_count = len(eeat_findings)

    if eeat_findings:  # empty -> NO section (zero pollution)
        strengths = [f for f in eeat_findings if f.type == "strength"]
        weaknesses = [f for f in eeat_findings if f.type == "weakness"]
        notes = [f for f in eeat_findings if f.type == "anomaly"]
        block = ["\n\n## E-E-A-T Validation (Knowledge Graph)\n"]
        if strengths:
            block.append("**Strengths:**")
            block += [f"- {f.text}" for f in strengths]
            block.append("")
        if weaknesses:
            block.append("**Recommendations:**")
            block += [f"- {f.text}" for f in weaknesses]
            block.append("")
        if notes:
            block.append("**Notes:**")
            block += [f"- {f.text}" for f in notes]
            block.append("")
        summary_text = (summary_text or "") + "\n".join(block).rstrip() + "\n"

    # AAA-50: MEASURED cost = vertex_generate calls + ADK agent model turns,
    # both priced with the same gemini-3-flash-preview helper. No estimate.
    vx = get_usage()
    in_tok = vx["prompt"] + adk_in
    # output = candidates + thoughts (thinking billed at output rate)
    out_tok = vx["candidates"] + vx["thoughts"] + adk_out
    audit_cost_usd = round(
        in_tok * _IN_PM / 1_000_000 + out_tok * _OUT_PM / 1_000_000, 6
    )
    audit_token_counts = {"in": in_tok, "out": out_tok}

    # AAA-42 (Sub-step 1 + 1b): pop the transient raw HTML from the
    # active_crawl (the promotion-gated winner — rendered if promoted, else
    # httpx) so AAA-42 measures whichever HTML Discovery itself trusts.
    # Also pop from the other two state dicts so the transient never lands
    # in any persisted field.
    _rendered = st.get("rendered_crawl")
    _active = st.get("active_crawl") or st.get("crawl") or {}
    raw_html_for_aaa42 = (_active or {}).pop("_raw_html_transient", "")
    (st.get("crawl") or {}).pop("_raw_html_transient", None)
    (st.get("rendered_crawl") or {}).pop("_raw_html_transient", None)
    render_method_used = (
        "playwright_escalation"
        if (_rendered is not None and _active is _rendered)
        else "httpx"
    )

    out = AuditOutput(
        url=url,
        grounding_confidence=gc,
        eeat_signals=st.get("eeat_signals") or {},
        # AAA-116 (2026-05-26): default fallback switched from "other"
        # (AAA-55 11-value enum) → "other_or_unknown" (AAA-81 v3 27-leaf
        # safety bucket). state["page_type"] is no longer set by entities
        # tool — classify_multi_dim (called below before write_audit) is
        # the sole source and overwrites this default on success. On
        # multi-dim failure, the fallback persists.
        page_type=st.get("page_type") or "other_or_unknown",
        page_type_model_version=st.get("page_type_model_version"),
        audit_kg_calls=kg_usage.get("calls", 0),
        audit_kg_cost_usd=kg_usage.get("cost_usd", 0.0),
        eeat_findings_count=eeat_findings_count,
        audit_cost_usd=audit_cost_usd,
        audit_token_counts=audit_token_counts,
        audit_metadata=AuditMetadata(
            tools_called=tools_called,
            playwright_escalated="crawl_with_playwright_tool" in tools_called,
            duration_seconds=duration,
            cost_usd_estimate=audit_cost_usd,  # now MEASURED, not estimated
            errors=errors,
        ),
        site_profile=st.get("site_profile") or {},
        crawl=st.get("crawl") or {},
        rendered_crawl=st.get("rendered_crawl"),
        target_keywords=st.get("keywords") or {},
        entities=st.get("entities") or {},
        pagespeed=st.get("pagespeed") or {},
        indexing=st.get("indexing") or {},
        summary_markdown=summary_text,
    )

    # AAA-179 Sub-step 2 — post-crawl language-mismatch flag (defense-in-depth).
    # If the requested locale and the DETECTED page language disagree (the site
    # forced a different language despite the requested Accept-Language — e.g. a
    # geo/IP redirect, or the requested-locale variant doesn't exist), record a
    # schema-additive flag (crawl.i18n.locale_mismatch) so the report can surface
    # it. We keep deriving on what was fetched (best available) — never silently.
    if not corpus_mode:
        try:
            from crawler.crawler import get_requested_locale, _norm_locale
            req_loc = get_requested_locale()
            det_loc = _norm_locale((out.site_profile or {}).get("language"))
            if req_loc and det_loc and req_loc != det_loc:
                cr = out.crawl if isinstance(out.crawl, dict) else {}
                i18n = cr.get("i18n") if isinstance(cr.get("i18n"), dict) else {}
                tech = cr.get("technical") if isinstance(cr.get("technical"), dict) else {}
                i18n["locale_mismatch"] = {
                    "requested": req_loc,
                    "detected": det_loc,
                    "final_url": cr.get("url") or url,
                    "redirect_chain": tech.get("redirect_chain"),
                }
                cr["i18n"] = i18n
                out.crawl = cr
                print(f"  AAA-179 locale_mismatch: requested={req_loc} "
                      f"detected={det_loc} final_url={cr.get('url') or url}")
        except Exception as _e:  # noqa: BLE001 — flag is best-effort, never break the audit
            print(f"  AAA-179 locale_mismatch check skipped: {type(_e).__name__}: {_e}")

    if not corpus_mode:  # AAA-75 DROP step(s): W4-W9
        # AAA-80: Google AI-Mode query fan-out for the primary target keyword.
        # Serial placement (write_audit's enrichments are currently sequential,
        # so async-parallel here is a follow-up — adds ~8s to wall-time but
        # keeps Sub-step 1 surgical). Skip-finding contract: errors -> [] / 0.0.
        tk = st.get("keywords") or {}
        if isinstance(tk, dict):
            primary_kw = tk.get("primary_keyword") or ""
        elif isinstance(tk, list) and tk:  # forward-compat: AAA-76 list[dict]
            first = tk[0]
            primary_kw = (
                first.get("keyword") if isinstance(first, dict) else str(first)
            ) or ""
        else:
            primary_kw = ""
        fan_out, fan_out_cost = (
            await detect_query_fan_out(primary_kw) if primary_kw else ([], 0.0)
        )
        out.query_fan_out = fan_out
        out.audit_fan_out_cost_usd = fan_out_cost

        # AAA-84 Sub-step 1 — Option A: side-by-side per-keyword classification.
        # target_keywords (the heterogeneous dict) stays byte-unchanged;
        # target_keywords_classified is the new sorted list. Skip-finding:
        # errors -> [] / 0.0. Cost isolated via _USAGE delta in classify_keywords
        # itself (AAA-53 separation — audit_cost_usd above is already frozen).
        tk_dict = st.get("keywords") or {}
        if isinstance(tk_dict, dict) and tk_dict:
            classified, kw_cost = await classify_keywords_with_l2(
                tk_dict, summary_text
            )
        else:
            classified, kw_cost = [], 0.0
        out.target_keywords_classified = classified
        out.audit_keyword_classify_cost_usd = kw_cost

        # AAA-76 Sub-step 2 — DataForSEO volume enrichment (Path A: all 11
        # keywords, ~15% fill expected; null = legitimate "no volume" signal).
        # Merges 5 volume fields INTO the classified items (Option alpha);
        # other AAA-84 fields untouched. Skip-finding: errors -> [] / 0.0.
        volume_cost = 0.0
        kw_strings = [c["keyword"] for c in classified if c.get("keyword")]
        if kw_strings:
            sp = st.get("site_profile") or {}
            lang = str(sp.get("language") or "").strip().lower()[:2]
            lang = lang if lang in ("hu", "en") else "en"
            vol_data, volume_cost = await fetch_keywords_volume(
                kw_strings, language_code=lang,
                location_code=resolve_location_code(lang),
            )
            vol_map = {v.get("keyword"): v for v in (vol_data or [])
                       if v.get("keyword")}
            for c in classified:
                v = vol_map.get(c.get("keyword"))
                if v:
                    c["search_volume_monthly"] = v.get("search_volume")
                    c["trend_12m"] = v.get("monthly_searches")
                    c["cpc_usd"] = v.get("cpc")
                    c["competition"] = v.get("competition")
                    c["competition_index"] = v.get("competition_index")
        out.audit_keywords_volume_cost_usd = volume_cost

        # AAA-85 Sub-step 2 — AI Overview trigger detection (Option C:
        # schema-additive, primary keyword only). Skip-finding: errors ->
        # (None, 0.0). Cost SEPARATE (audit_ai_overview_cost_usd, AAA-53).
        # AAA-137: capture the full AIO object (markdown + cited_sources +
        # client_cited) from the same live call; derive the legacy boolean.
        ai_obj, ai_cost = None, 0.0
        primary_kw_classified = (
            classified[0].get("keyword") if classified else None
        )
        if primary_kw_classified:
            sp2 = st.get("site_profile") or {}
            lang2 = str(sp2.get("language") or "").strip().lower()[:2]
            lang2 = lang2 if lang2 in ("hu", "en") else "en"
            ai_obj, ai_cost = await check_ai_overview_async(
                primary_kw_classified, language_code=lang2,
                location_code=resolve_location_code(lang2),
                client_url=url,
            )
        out.ai_overview = ai_obj
        out.ai_overview_triggered = (ai_obj.get("present") if ai_obj else None)
        out.audit_ai_overview_cost_usd = ai_cost

        # AAA-86 Sub-step 1 — ChatGPT 5.4 citation + fan-out (one OpenAI
        # Responses API call; fulfils AAA-80 Sub-step 1c). Primary keyword
        # only. Skip-finding: errors -> (None, 0.0). Cost SEPARATE (AAA-53).
        chatgpt_resp, chatgpt_cost = None, 0.0
        if primary_kw_classified:
            chatgpt_resp, chatgpt_cost = await extract_chatgpt_response(
                primary_kw_classified, url
            )
        out.chatgpt_query_response = chatgpt_resp
        out.audit_chatgpt_cost_usd = chatgpt_cost

        # AAA-95 — classify every fan-out query (AAA-80 Google-grounded +
        # AAA-86 ChatGPT) into a US11663201B2 variant_type. Schema-additive:
        # query_fan_out + chatgpt_query_response.fan_out_queries untouched.
        # Skip-finding: per-query errors -> variant_type=None, batch continues.
        fan_out_combined = [
            {"query": q, "source": "google_grounded"}
            for q in (fan_out or [])
        ] + [
            {"query": q, "source": "chatgpt"}
            for q in ((chatgpt_resp or {}).get("fan_out_queries") or [])
        ]
        fan_out_enriched, fan_out_enrich_cost = [], 0.0
        if primary_kw_classified and fan_out_combined:
            fan_out_enriched, fan_out_enrich_cost = (
                await classify_fan_out_variants(
                    primary_kw_classified, fan_out_combined
                )
            )
        out.fan_out_enriched = fan_out_enriched
        out.audit_fan_out_enrichment_cost_usd = fan_out_enrich_cost

    # AAA-42 Sub-step 1 — agent-friendliness raw-HTML measurement (no LLM,
    # selectolax-only, <2s, $0). Uses the transient raw HTML popped above
    # (never archived). Skip-finding: errors degrade only failed dimensions.
    out.agent_friendly_measurements = measure_agent_friendliness(
        raw_html_for_aaa42
    )
    out.render_method_used = render_method_used

    # AAA-89 Sub-step 1 — CrUX field data from PSI mobile response.
    # Extract first, THEN strip the raw blocks from out.pagespeed so the
    # archive doesn't carry the duplicate (the parsed form is in
    # crux_field_data). Skip-finding: invalid response -> _error set.
    _ps_mobile = (out.pagespeed or {}).get("mobile") or {}
    out.crux_field_data = extract_crux_from_psi_response(_ps_mobile)
    for _key in ("mobile", "desktop"):
        _ps = (out.pagespeed or {}).get(_key) or {}
        if isinstance(_ps, dict):
            _ps.pop("loadingExperience", None)
            _ps.pop("originLoadingExperience", None)

    if not corpus_mode:  # AAA-75 DROP step(s): W12
        # AAA-42 Sub-step 1b — pre-write snapshot so the measurement is
        # preserved even if write_audit fails (e.g. vercel's documented
        # Firestore 1 MiB overflow). Best-effort; never raises.
        try:
            from urllib.parse import urlparse as _urlparse
            _snap_dom = _urlparse(url).netloc or "site"
            OUT_DIR.mkdir(exist_ok=True)
            (OUT_DIR / f"_pre_write_{_snap_dom}.json").write_text(
                json.dumps(out.model_dump(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    if not corpus_mode:  # AAA-75 DROP step(s): W13
        # AAA-95 Sub-step 2.1 — coverage classification, directly after the
        # variant_type tagging. In-place enrichment (adds coverage+suggestion
        # to each fan_out_enriched entry). Skip-finding per query. Cost SEPARATE.
        cov_cost = 0.0
        if primary_kw_classified and fan_out_enriched:
            body_text = (
                ((st.get("crawl") or {}).get("main_content") or {}).get("text")
                or ""
            )
            fan_out_enriched, cov_cost = await analyze_fan_out_coverage(
                target_keyword=primary_kw_classified,
                fan_out_enriched=fan_out_enriched,
                landing_page_summary=summary_text,
                landing_page_body=body_text,
            )
            out.fan_out_enriched = fan_out_enriched
        out.audit_fan_out_coverage_cost_usd = cov_cost

    # AAA-77 v2 + AAA-81 v3 + AAA-113 — multi-dimensional Discovery
    # classification, single multi-field Gemini call. Coordinated ship of
    # 3 tickets. Skip-finding: errors -> all-None + _error captured in the
    # session log (the field-level Nones are honest absence). Cost SEPARATE
    # (audit_multi_dim_classify_cost_usd, AAA-53 — never folded into
    # audit_cost_usd). Inserted BEFORE write_audit so the new fields are
    # persisted on first write (no backfill needed).
    from page_analysis.multi_dim_classify import classify_multi_dim
    _md, _md_cost = await classify_multi_dim(
        crawl=st.get("crawl") or {},
        site_profile=st.get("site_profile") or {},
        summary_text=summary_text or "",
    )
    if _md.get("page_type"):
        # Overwrite AAA-55's legacy page_type ONLY when the multi-dim call
        # succeeded — on failure keep the AAA-55 value as a fallback (it's
        # also a non-empty string by AAA-55's bias-to-"other" contract).
        out.page_type = _md["page_type"]
        out.page_type_model_version = (
            _md.get("_model_version") or out.page_type_model_version
        )
    out.page_type_parent_intent_group = _md.get("page_type_parent_intent_group")
    out.business_model = _md.get("business_model")
    out.topic_domain = _md.get("topic_domain")
    out.locality = _md.get("locality")
    out.audience_relationship_primary = _md.get("audience_relationship_primary")
    out.audience_relationship_secondary = _md.get(
        "audience_relationship_secondary"
    )
    out.audience_confidence = _md.get("audience_confidence")
    out.audit_multi_dim_classify_cost_usd = _md_cost

    # AAA-123 Sub-step 1 — Phase 2 raw-HTML structural + 2 MB cutoff +
    # rendering-mode measurements. Pure-Python, no LLM, no DataForSEO, $0.
    # Consumes the same `raw_html_for_aaa42` transient as AAA-42 (already
    # popped from session state above). MUST run AFTER multi_dim_classify
    # so we have page_type for the Schema.org expected-types mapping.
    # Skip-finding per sub-tree (semantic_structure / google_2mb_cutoff /
    # rendering_mode each carry their own _error on independent failure).
    try:
        from page_analysis.phase2_html import run_phase2_measurements
        _audit_lang_for_p2 = (st.get("site_profile") or {}).get("language") or "en"
        # crawl_result-shaped dict for the orchestrator. Headers byte
        # count is approximate from selectolax-via-AAA-42 path; we don't
        # carry the live HTTP response headers through to audit() today,
        # so we surface 0 (acceptable per AAA-123 S0 deviation #2 —
        # off by ~30-100 B, invisible at 2 MB scale).
        out.phase2_html_measurements = await run_phase2_measurements(
            crawl_result={
                "_raw_html_transient": raw_html_for_aaa42,
                "response_headers_bytes_estimate": 0,
            },
            page_type=out.page_type,
            audit_language=_audit_lang_for_p2,
        )
    except Exception as e:  # noqa: BLE001 — never fail the audit on Phase 2
        out.phase2_html_measurements = {
            "_error": f"{type(e).__name__}: {e}"
        }

    # AAA-158 Sub-step 1 — deterministic ($0) title + meta-description SERP
    # measurement (pixel length + truncation + quality signals). Pure-Python,
    # no LLM/network. Runs late so crawl.meta, headings.h1, brand_context AND
    # target_keywords are all populated in `out` (part-2 quality signals gate
    # on those inputs and skip cleanly when absent). Skip-finding: never raises.
    try:
        from page_analysis.title_meta import measure_title_meta
        out.title_meta_measurements = measure_title_meta(out.model_dump())
    except Exception as e:  # noqa: BLE001 — never fail the audit on this measurement
        out.title_meta_measurements = {"_error": f"{type(e).__name__}: {e}"}

    # AAA-173 — deterministic placeholder / content-QA-leak detector ($0, no LLM).
    # Scans crawl.main_content.text + visible_text + heading_tree for unfinished-
    # content markers; raises a page-level flag on any HARD/NAME hit. Runs late so
    # crawl text + phase2 heading_tree are populated. Skip-finding: never raises.
    try:
        from page_analysis.placeholder_detector import detect_placeholder_leaks
        out.content_qa_leak = detect_placeholder_leaks(out.model_dump())
    except Exception as e:  # noqa: BLE001 — never fail the audit on this measurement
        out.content_qa_leak = {"_error": f"{type(e).__name__}: {e}"}

    # AAA-124 Sub-step 1 (Option E) — per-aspect page evaluation. ONE Gemini
    # 3.5 Flash holistic (V3) call producing 7 per-aspect findings. MUST run
    # AFTER multi_dim_classify (needs page_type/business_model/audience for
    # context) AND AFTER phase2_html_measurements (needs the AAA-123 ground
    # truth for the preventive anchor). Cost SEPARATE (audit_aspect_eval_cost_usd,
    # AAA-53). Skip-finding: evaluate_aspects never raises — returns (None|err
    # dict, 0.0) on failure; the audit + write_audit continue regardless.
    try:
        from page_analysis.aspect_evaluator import evaluate_aspects
        _ae_input = out.model_dump()
        _ae_input["url"] = url  # url is a separate arg, not on the model
        _ae_input["summary"] = summary_text or ""
        _aspect_evals, _ae_cost = evaluate_aspects(_ae_input)
        out.aaa124_aspect_evaluations = _aspect_evals
        out.audit_aspect_eval_cost_usd = _ae_cost
    except Exception as e:  # noqa: BLE001 — defensive; evaluate_aspects is
        # already skip-finding, this is belt-and-suspenders
        out.aaa124_aspect_evaluations = {"_meta": {"error": f"{type(e).__name__}: {e}"}}
        out.audit_aspect_eval_cost_usd = 0.0

    # AAA-170 Sub-step 1 — client E-E-A-T scorer. ONE gemini-3.5-flash call
    # scoring the CLIENT page on the 4 E-E-A-T dimensions, grounded on the
    # already-measured eeat_signals (AAA-56) + KG/entities + phase2 (AAA-123) +
    # aspect_evaluations (AAA-124). MUST run AFTER aspect eval (consumes its
    # schema_entity finding) and BEFORE write_audit. CLIENT-ONLY (competitors
    # deferred → RG4). Cost SEPARATE (audit_eeat_score_cost_usd, AAA-53).
    # Skip-finding: score_eeat never raises — _error in _meta, audit continues.
    try:
        from page_analysis.eeat_score import score_eeat
        # AAA-172: query-anchored. For a competitor (corpus_mode), the RE workflow
        # threads in the CLIENT's anchor keyword so client + competitors score on
        # the SAME query. For the client (eeat_anchor_keyword=None), score_eeat
        # falls back to the client's own primary_keyword (which IS the anchor).
        _eeat, _eeat_cost = score_eeat(out.model_dump(),
                                       anchor_keyword=eeat_anchor_keyword)
        out.eeat_score = _eeat
        out.audit_eeat_score_cost_usd = _eeat_cost
    except Exception as e:  # noqa: BLE001 — belt-and-suspenders; score_eeat is
        # already skip-finding
        out.eeat_score = {"client": None, "competitors": [],
                          "_meta": {"error": f"{type(e).__name__}: {e}"}}
        out.audit_eeat_score_cost_usd = 0.0

    # AAA-61: archive the full audit (source of truth) — critical write.
    # AAA-31 S2: audit_id (the dispatcher job id) is used as the archive key
    # when supplied so job_id == archive_id; else write_audit mints a uuid4.
    audit_id = await write_audit(out, url, corpus_mode=corpus_mode,
                                 audit_id=audit_id)
    print(f"  Audit archived: {audit_id}")

    # AAA-64: surface audit_id so callers (RE flow) can wire memory
    # retrieval / self-exclusion. Non-breaking extra key; standalone
    # main() ignores it.
    data = out.model_dump()
    data["audit_id"] = audit_id
    return data


async def main() -> None:
    urls = sys.argv[1:] or URLS
    OUT_DIR.mkdir(exist_ok=True)
    for url in urls:
        print("=" * 78)
        print(f"Auditing {url}...")
        data = await audit(url)
        meta = data["audit_metadata"]
        print(f"  tools called      : {meta['tools_called']}")
        print(f"  playwright escal. : {meta['playwright_escalated']}")
        print(f"  duration (s)      : {meta['duration_seconds']}")
        print(f"  cost MEASURED ($) : {data['audit_cost_usd']}  "
              f"tokens in/out={data['audit_token_counts']}")
        if meta["errors"]:
            print(f"  errors            : {meta['errors']}")
        sm = data["summary_markdown"] or "(no summary produced)"
        print(f"  summary (300c)    : {sm[:300].replace(chr(10), ' ')}")

        domain = urlparse(url).netloc or "site"
        path = OUT_DIR / f"{domain}.json"
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  saved             : {path}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
