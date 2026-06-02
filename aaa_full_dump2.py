import asyncio, json
from google.cloud import firestore_v1 as firestore
IDS = {"taxually": "013a2853-2e51-4c41-a201-a781f7f6aa67",
       "agrobook": "93707b41-db62-4313-8c9a-2812aa99ecc5",
       "kk.coach": "67762118-df49-41d1-865d-81e9c6ad9d30"}
ASP = ["macro_structure", "heading_semantics", "above_the_fold", "micro_semantics",
       "inline_link_semantics", "forms_conversion_points", "schema_entity"]

def P(x): return json.dumps(x, ensure_ascii=False)

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    for label, aid in IDS.items():
        d = (await db.collection("audits").document(aid).get()).to_dict() or {}
        ao = d.get("audit_output") or {}
        rf = ao.get("re_findings") or {}
        sb = rf.get("serp_branded") or {}; sc = rf.get("serp_category") or {}
        comp = rf.get("comparison") or {}
        print("\n################## %s (%s) ##################" % (label, aid[:8]))
        print("[GATE] re_findings=%s completed=%s serps_identical=%s" % (bool(rf), rf.get("re_workflow_completed"), rf.get("serps_identical")))
        print("   serp_branded.organic=%d serp_category.organic=%d comparison_keys=%s" % (len(sb.get("organic_results") or []), len(sc.get("organic_results") or []), sorted(comp.keys())))
        print("   competitor_audits=%s" % ({k[:34]: str(v)[:18] for k, v in (rf.get("competitor_audits") or {}).items()}))
        print("[§2] " + P({k: ao.get(k) for k in ["page_type", "page_type_parent_intent_group", "business_model", "topic_domain", "locality", "audience_relationship_primary", "audience_relationship_secondary", "audience_confidence"]}))
        sp = ao.get("site_profile") or {}; ent = ao.get("entities") or {}; ee = ao.get("eeat_signals") or {}
        print("   brand=%s | named_people=%s brand_mentions=%s social=%s" % (sp.get("brand"), ee.get("named_people"), ee.get("brand_mentions"), ee.get("social_proof_links")))
        print("   entities orgs=%d people=%s products=%d places=%d" % (len(ent.get("organizations") or []), ent.get("people"), len(ent.get("products") or []), len(ent.get("places") or [])))
        tk = ao.get("target_keywords") or {}
        print("   category_keyword=%s | topic_cluster=%s" % (tk.get("category_keyword"), tk.get("topic_cluster")))
        tkc = ao.get("target_keywords_classified") or []
        filled = sum(1 for c in tkc if c.get("search_volume_monthly") is not None)
        print("[§3] primary=%r classified=%d vol_filled=%d" % (tk.get("primary_keyword"), len(tkc), filled))
        for c in tkc[:3]:
            print("   - %r tail=%s intent=%s/%s relev=%s vol=%s" % (c.get("keyword"), c.get("tail_type"), c.get("search_intent"), c.get("search_intent_l2"), c.get("relevance_score"), c.get("search_volume_monthly")))
        sfa = ao.get("serp_fit_analysis") or []
        print("   serp_fit len=%d: %s" % (len(sfa), [(s.get("keyword_role"), s.get("target_type"), s.get("target_type_fit"), s.get("keyword_recommendation_trigger"), s.get("alternative_keyword_suggestions")) for s in sfa]))
        crs = rf.get("client_ranking_status") or {}
        print("   client_ranking found_top10=%s positions=%s" % ({k: (v or {}).get("found_in_top_10") for k, v in crs.items()}, {k: (v or {}).get("position") for k, v in crs.items()}))
        v2 = ao.get("selected_competitors_v2") or []
        sel = [c for c in v2 if c.get("selected")]
        print("[§4] selected=%d / cand=%d | hard_fail=%d" % (len(sel), len(v2), sum(1 for c in v2 if not c.get("hard_filter_pass"))))
        for c in sorted(sel, key=lambda x: x.get("selection_rank") or 99)[:6]:
            print("   rank%s %s %s type=%s pos=%s soft=%s kw=%r" % (c.get("selection_rank"), c.get("keyword_role"), c.get("url")[:46], c.get("serp_type"), c.get("position"), c.get("soft_score"), c.get("keyword")))
        dt = comp.get("dimension_table")
        print("[§5] dimension_table=%s" % (sorted(dt.keys()) if isinstance(dt, dict) else type(dt).__name__))
        if isinstance(dt, dict):
            for k, v in list(dt.items())[:6]:
                v = v or {}
                print("   %s: client=%s best=%s gap=%s" % (k, str(v.get("client"))[:38], str(v.get("competitor_best"))[:38], str(v.get("gap"))[:55]))
        pat = comp.get("patterns") or []
        print("   patterns=%d: %s" % (len(pat), [(p.get("finding"), p.get("severity")) for p in pat][:5]))
        fe = ao.get("fan_out_enriched") or []
        print("[§6] query_fan_out=%s fan_out_enriched=%s" % (ao.get("query_fan_out"), [(e.get("variant_type"), e.get("coverage"), e.get("source")) for e in fe]))
        aio = ao.get("ai_overview")
        if aio:
            print("   ai_overview present=%s async=%s client_cited=%s cited_n=%d md_len=%d note=%s" % (aio.get("present"), aio.get("asynchronous"), aio.get("client_cited"), len(aio.get("cited_sources") or []), len(aio.get("markdown") or ""), aio.get("note")))
        else:
            print("   ai_overview: ABSENT")
        cg = ao.get("chatgpt_query_response") or {}
        print("   chatgpt target_cited=%s citations_n=%d resp_len=%d cost=%s" % (cg.get("target_site_cited"), len(cg.get("citations") or []), len(cg.get("response_text") or ""), ao.get("audit_chatgpt_cost_usd")))
        ae = ao.get("aaa124_aspect_evaluations") or {}
        print("[§7/§8] aaa124 present=%s confidences=%s" % (bool(ae and "macro_structure" in ae), {a: (ae.get(a) or {}).get("confidence_0_1") for a in ASP if a in ae}))
        print("   aggregate_evaluation present=%s | 3-index=ABSENT(OptionE) | AAA-41 commodity=ABSENT" % ("aggregate_evaluation" in ao))
        afm = ao.get("agent_friendly_measurements") or {}
        print("   agent_friendly heading=%s forms=%s images=%s aria=%s" % (afm.get("heading"), afm.get("forms"), afm.get("images"), afm.get("aria")))
        p2 = ao.get("phase2_html_measurements") or {}
        ss = p2.get("semantic_structure") or {}; rm = p2.get("rendering_mode") or {}; cut = p2.get("google_2mb_cutoff") or {}
        print("   phase2 heading_tree_count=%s heading_tree_recommended?=%s is_csr=%s spa=%s exceeds_2mb=%s" % (ss.get("heading_tree_count"), "heading_tree_recommended" in ss, rm.get("is_csr_likely"), rm.get("spa_frameworks_detected"), cut.get("exceeds_2mb_cutoff")))
        print("[§9] above_the_fold finding: %s" % (str((ae.get("above_the_fold") or {}).get("structured_finding"))[:150]))
        print("   forms_conversion finding: %s" % (str((ae.get("forms_conversion_points") or {}).get("structured_finding"))[:130]))
        idx = ao.get("indexing") or {}; tech = (ao.get("crawl") or {}).get("technical") or {}
        ps = ao.get("pagespeed") or {}
        crux = ((ao.get("crux_field_data") or {}).get("origin_level") or {}).get("metrics") or {}
        print("[§10] indexing.method=%s indexed=%s canonical_indexed=%s" % (idx.get("method"), idx.get("indexed"), idx.get("canonical_indexed")))
        print("   canonical=%s redirect_chain=%s https=%s" % ((tech.get("canonical") or {}).get("value"), tech.get("redirect_chain"), tech.get("https")))
        print("   pagespeed mobile=%s desktop=%s | CrUX=%s" % ((ps.get("mobile") or {}).get("scores", {}).get("performance"), (ps.get("desktop") or {}).get("scores", {}).get("performance"), {m: (crux.get(m) or {}).get("category") for m in ["lcp", "cls", "inp"]}))
        costs = {k: v for k, v in ao.items() if k.startswith("audit_") and "cost" in k and isinstance(v, (int, float))}
        costs["re_serp"] = rf.get("audit_re_serp_cost_usd"); costs["re_comparison"] = rf.get("audit_re_comparison_cost_usd")
        tot = sum(v for v in costs.values() if isinstance(v, (int, float)))
        print("[§12] audit_date=%s page_type_model=%s" % (d.get("audit_date"), ao.get("page_type_model_version")))
        print("   costs=%s SUM=$%.4f" % ({k: round(v, 4) for k, v in costs.items() if isinstance(v, (int, float))}, tot))

asyncio.run(main())
