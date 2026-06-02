import asyncio, json
from google.cloud import firestore_v1 as firestore
IDS={'taxually':'013a2853-2e51-4c41-a201-a781f7f6aa67','agrobook':'93707b41-db62-4313-8c9a-2812aa99ecc5','kk.coach':'67762118-df49-41d1-865d-81e9c6ad9d30'}
def P(x): return json.dumps(x, ensure_ascii=False)
async def main():
    db=firestore.AsyncClient(project='project-7d6eedd4-adff-46ae-8fc',database='ai-advisor-app')
    for label,aid in IDS.items():
        d=(await db.collection('audits').document(aid).get()).to_dict() or {}
        ao=d.get('audit_output') or {}
        rf=ao.get('re_findings') or {}
        print(f'\n################## {label} ({aid[:8]}) ##################')
        # GATE
        sb=rf.get('serp_branded') or {}; sc=rf.get('serp_category') or {}
        comp=rf.get('comparison') or {}
        print(f'[GATE] re_findings present={bool(rf)} completed={rf.get(\"re_workflow_completed\")} serps_identical={rf.get(\"serps_identical\")}')
        print(f'   serp_branded.organic={len(sb.get(\"organic_results\") or [])} serp_category.organic={len(sc.get(\"organic_results\") or [])} comparison_keys={sorted(comp.keys())}')
        print(f'   competitor_audits={ {k[:30]:v[:20] for k,v in (rf.get(\"competitor_audits\") or {}).items()} }')
        # §2
        print('[§2]', P({k:ao.get(k) for k in ['page_type','page_type_parent_intent_group','business_model','topic_domain','locality','audience_relationship_primary','audience_relationship_secondary','audience_confidence']}))
        sp=ao.get('site_profile') or {}; ent=ao.get('entities') or {}; ee=ao.get('eeat_signals') or {}
        print('   brand:', sp.get('brand'),'| eeat named_people:', ee.get('named_people'),'| brand_mentions:', ee.get('brand_mentions'),'| social:', ee.get('social_proof_links'))
        print('   entities: orgs', len(ent.get('organizations') or []),'people',ent.get('people'),'products',len(ent.get('products') or []),'places',len(ent.get('places') or []))
        tk=ao.get('target_keywords') or {}
        print('   category_keyword:', tk.get('category_keyword'),'| topic_cluster:', tk.get('topic_cluster'))
        # §3
        tkc=ao.get('target_keywords_classified') or []
        filled=sum(1 for c in tkc if c.get('search_volume_monthly') is not None)
        print(f'[§3] primary={tk.get(\"primary_keyword\")!r} classified={len(tkc)} vol_filled={filled}')
        for c in tkc[:3]:
            print(f'   - {c.get(\"keyword\")!r} tail={c.get(\"tail_type\")} intent={c.get(\"search_intent\")}/{c.get(\"search_intent_l2\")} relev={c.get(\"relevance_score\")} vol={c.get(\"search_volume_monthly\")}')
        sfa=ao.get('serp_fit_analysis') or []
        print(f'   serp_fit_analysis len={len(sfa)}:', [(s.get('keyword_role'),s.get('target_type'),s.get('target_type_fit'),s.get('keyword_recommendation_trigger')) for s in sfa])
        crs=rf.get('client_ranking_status') or {}
        print('   client_ranking_status:', {k:(v or {}).get('found_in_top_10') for k,v in crs.items()}, {k:(v or {}).get('position') for k,v in crs.items()})
        # §4
        v2=ao.get('selected_competitors_v2') or []
        sel=[c for c in v2 if c.get('selected')]
        print(f'[§4] selected_competitors_v2: {len(sel)} selected / {len(v2)} cand | hard_fail={sum(1 for c in v2 if not c.get(\"hard_filter_pass\"))}')
        for c in sorted(sel,key=lambda x:x.get('selection_rank') or 99)[:6]:
            print(f'   rank{c.get(\"selection_rank\")} {c.get(\"keyword_role\")} {c.get(\"url\")[:48]} type={c.get(\"serp_type\")} pos={c.get(\"position\")} soft={c.get(\"soft_score\")} kw={c.get(\"keyword\")!r}')
        # §5
        dt=comp.get('dimension_table')
        print('[§5] dimension_table keys:', sorted(dt.keys()) if isinstance(dt,dict) else type(dt).__name__)
        if isinstance(dt,dict):
            for k,v in list(dt.items())[:6]: print(f'   {k}: client={ (v or {}).get(\"client\") } vs best={ (v or {}).get(\"competitor_best\") } gap={str((v or {}).get(\"gap\"))[:60]}')
        pat=comp.get('patterns') or []
        print(f'   patterns: {len(pat)}', [(p.get('finding'),p.get('severity')) for p in pat][:5])
        # §6
        qfo=ao.get('query_fan_out'); fe=ao.get('fan_out_enriched') or []
        print('[§6] query_fan_out:', qfo, '| fan_out_enriched:', [(e.get('variant_type'),e.get('coverage'),e.get('source')) for e in fe])
        aio=ao.get('ai_overview')
        if aio: print(f'   ai_overview present={aio.get(\"present\")} async={aio.get(\"asynchronous\")} client_cited={aio.get(\"client_cited\")} cited_n={len(aio.get(\"cited_sources\") or [])} md_len={len(aio.get(\"markdown\") or \"\")} note={aio.get(\"note\")}')
        else: print('   ai_overview: ABSENT')
        cg=ao.get('chatgpt_query_response') or {}
        print(f'   chatgpt: target_cited={cg.get(\"target_site_cited\")} citations_n={len(cg.get(\"citations\") or [])} resp_len={len(cg.get(\"response_text\") or \"\")} cost={ao.get(\"audit_chatgpt_cost_usd\")}')
        # §7/§8 aspects
        ae=ao.get('aaa124_aspect_evaluations') or {}
        from_aspects={a:(ae.get(a) or {}).get('confidence_0_1') for a in ['macro_structure','heading_semantics','above_the_fold','micro_semantics','inline_link_semantics','forms_conversion_points','schema_entity'] if a in ae}
        print('[§7/§8] aaa124_aspect_evaluations present:', bool(ae and any(a in ae for a in ['macro_structure'])),'| aspect confidences:', from_aspects)
        print('   aggregate_evaluation present:', 'aggregate_evaluation' in ao, '| 3-index scores: ABSENT (Option E)' )
        afm=ao.get('agent_friendly_measurements') or {}
        print('   agent_friendly: heading', afm.get('heading'),'forms', afm.get('forms'),'images', afm.get('images'),'aria', afm.get('aria'))
        p2=ao.get('phase2_html_measurements') or {}
        ss=p2.get('semantic_structure') or {}; rm=p2.get('rendering_mode') or {}; cut=p2.get('google_2mb_cutoff') or {}
        print('   phase2: heading_tree_count', ss.get('heading_tree_count'),'heading_tree_recommended?', 'heading_tree_recommended' in ss, '| is_csr', rm.get('is_csr_likely'),'spa', rm.get('spa_frameworks_detected'),'exceeds_2mb', cut.get('exceeds_2mb_cutoff'))
        # §10
        idx=ao.get('indexing') or {}
        tech=(ao.get('crawl') or {}).get('technical') or {}
        ps=ao.get('pagespeed') or {}
        crux=((ao.get('crux_field_data') or {}).get('origin_level') or {}).get('metrics') or {}
        print('[§10] indexing.method', idx.get('method'),'indexed', idx.get('indexed'),'canonical_indexed', idx.get('canonical_indexed'))
        print('   canonical', (tech.get('canonical') or {}).get('value'),'| redirect_chain', tech.get('redirect_chain'),'| https', tech.get('https'))
        print('   pagespeed mobile/desktop perf:
