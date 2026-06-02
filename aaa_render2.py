import asyncio, json
from google import genai
from google.genai import types
from google.cloud import firestore_v1 as firestore
from site_profile.gemini_analyzer import _resolve_project, compute_call_cost_usd
from discovery_agent.tools import _select_canonical

MODEL = "gemini-3.5-flash"
AID = "013a2853-2e51-4c41-a201-a781f7f6aa67"

SECTIONS = [
 ("§1", "Valóság-pillanatkép", "Foglald össze 3-5 mondatban az oldal jelenlegi helyzetét a CONTEXT tényei alapján: indexelt-e, megjelenik-e az AI Overview / ChatGPT válaszokban, benne van-e a Google top 10-ben a fő kulcsszóra. NE adj pontszámot vagy minősítést. Csak a tényeket mondd ki és magyarázd el, miért fontosak egy döntéshozónak."),
 ("§2", "Azonosítás és kontextus", "Magyarázd el közérthetően, milyen típusú oldal ez (page_type), milyen üzleti modell, téma, célközönség (B2B/B2C), milyen földrajzi fókusz, mi a márka. Használd a multi-dim és brand/entitás adatokat."),
 ("§3", "Kulcsszavak és keresési szándék", "Mutasd be az elsődleges kulcsszót és a fő osztályozott kulcsszavakat (tail_type, search_intent, relevancia, keresési volumen ahol van). Mondd ki az AAA-118 SERP-illeszkedés verdiktjét és hogy az oldal benne van-e a top 10-ben. Magyarázd, mit jelent a 'top 10-en kívül'."),
 ("§4", "Versenytársak", "Sorold fel a kiválasztott versenytársakat és magyarázd, miért ők (SERP-pozíció, típus-egyezés). Közérthetően."),
 ("§5", "Összehasonlítás a legjobbakkal", "A comparison dimension_table alapján dimenziónként: kliens vs legjobb versenytárs + a hiány. Sorold a megnevezett mintázatokat (patterns) súlyossággal. Ne találj ki új számokat."),
 ("§6", "AI-láthatóság", "Magyarázd el a fan-out lekérdezéseket és lefedettséget; az AI Overview tényt (megjelent-e, hány forrást idéz, a kliens köztük van-e); a ChatGPT idézettséget. Mondd ki tényszerűen és magyarázd, miért számít."),
 ("§7", "Tartalomminőség", "Tartalomhossz kliens vs legjobb versenytárs, entitás-gazdagság, E-E-A-T jelek (megnevezett szerzők, márkaemlítések, social). Csak a megadott tényekből. Ne adj minőség-pontszámot."),
 ("§8", "Szemantikus felépítés", "AAA-42 mérések (címsorok, űrlapok, képek alt, ARIA), AAA-123 phase2 (renderelés, 2MB), és az aspektus-megfigyelések leíró jelleggel. Ne alkoss új pontszámot; a meglévő megfigyeléseket fordítsd közérthetőre."),
 ("§9", "Hajtás feletti terület és űrlapok", "Az above_the_fold megfigyelés és a konverziós pontok (űrlap-címke lefedettség, interaktív elemek). Közérthetően."),
 ("§10", "Technikai állapot", "Indexeltség és kanonikus URL (a megadott canonical_indexed-et használd), átirányítási lánc, HTTPS, PageSpeed mobil/asztali, CrUX. Magyarázd, mit jelentenek a mobil teljesítmény-számok."),
 ("§11", "Összegzés és következő lépések", "A CONTEXT tényeiből vezetett, prioritized, konkrét következő lépések listája a hiányokra. Csak a megadott tényekre alapozz. Nincs pontszám."),
 ("§12", "Módszertan", "Röviden, közérthetően: mit mértünk (Discovery + versenytárs-elemzés + AI-láthatóság), milyen forrásokból, mikor készült."),
]

SYS = ("Te egy SEO/AEO jelentes-szovegiro vagy. KIZAROLAG a megadott CONTEXT adataira tamaszkodj — "
 "semmit ne talalj ki, ne becsulj, ne adj hozza pontszamot, minositest vagy ertekiteletet azon tul, "
 "amit az adat kimond. A tenyeket (pl. 'nincs a top 10-ben', 'az AI Overview nem idezi az oldalt') "
 "mondd ki es magyarazd el, miert fontosak. Kozertheto uzleti magyar nyelven irj, marketingesnek ES "
 "vezetonek is erthetoen; a szakzsargont roviden magyarazd. Markdown szekciot adj vissza ## cimmel.")


def build_ctx(ao, rf, canonical_indexed):
    sp = ao.get("site_profile") or {}; ee = ao.get("eeat_signals") or {}; ent = ao.get("entities") or {}
    tk = ao.get("target_keywords") or {}; tkc = ao.get("target_keywords_classified") or []
    sfa = ao.get("serp_fit_analysis") or []; v2 = [c for c in (ao.get("selected_competitors_v2") or []) if c.get("selected")]
    comp = rf.get("comparison") or {}; crs = rf.get("client_ranking_status") or {}
    fe = ao.get("fan_out_enriched") or []; aio = ao.get("ai_overview") or {}; cg = ao.get("chatgpt_query_response") or {}
    afm = ao.get("agent_friendly_measurements") or {}; p2 = ao.get("phase2_html_measurements") or {}
    ae = ao.get("aaa124_aspect_evaluations") or {}; idx = ao.get("indexing") or {}; tech = (ao.get("crawl") or {}).get("technical") or {}
    ps = ao.get("pagespeed") or {}; crux = ((ao.get("crux_field_data") or {}).get("origin_level") or {}).get("metrics") or {}
    dt = comp.get("dimension_table") or {}
    return {
      "identity": {"url": ao.get("url"), "page_type": ao.get("page_type"), "parent_intent": ao.get("page_type_parent_intent_group"),
        "business_model": ao.get("business_model"), "topic_domain": ao.get("topic_domain"), "locality": ao.get("locality"),
        "audience": ao.get("audience_relationship_primary"), "audience_confidence": ao.get("audience_confidence"),
        "brand": sp.get("brand"), "named_people": ee.get("named_people"), "brand_mentions": ee.get("brand_mentions"),
        "social_proof_links": ee.get("social_proof_links"), "entities_orgs": ent.get("organizations"), "entities_products": ent.get("products")},
      "keywords": {"primary": tk.get("primary_keyword"), "category": tk.get("category_keyword"), "topic_cluster": tk.get("topic_cluster"),
        "classified": [{"kw": c.get("keyword"), "tail": c.get("tail_type"), "intent": c.get("search_intent"), "intent_l2": c.get("search_intent_l2"),
          "relevance": c.get("relevance_score"), "volume": c.get("search_volume_monthly")} for c in tkc],
        "serp_fit": [{"role": s.get("keyword_role"), "target_type": s.get("target_type"), "fit": s.get("target_type_fit"),
          "rec_trigger": s.get("keyword_recommendation_trigger"), "alt_keywords": s.get("alternative_keyword_suggestions")} for s in sfa],
        "client_ranking": {k: {"in_top10": (v or {}).get("found_in_top_10"), "position": (v or {}).get("position")} for k, v in crs.items()}},
      "competitors": [{"url": c.get("url"), "role": c.get("keyword_role"), "serp_type": c.get("serp_type"), "position": c.get("position"),
        "soft_score": c.get("soft_score"), "keyword": c.get("keyword")} for c in v2],
      "comparison": {"dimension_table": dt, "patterns": comp.get("patterns")},
      "ai_visibility": {"query_fan_out": ao.get("query_fan_out"),
        "fan_out_enriched": [{"q": e.get("query"), "variant": e.get("variant_type"), "coverage": e.get("coverage"), "source": e.get("source")} for e in fe],
        "ai_overview": {"present": aio.get("present"), "asynchronous": aio.get("asynchronous"), "client_cited": aio.get("client_cited"),
          "cited_sources_count": len(aio.get("cited_sources") or []), "cited_sources_sample": [c.get("url") for c in (aio.get("cited_sources") or [])[:9]],
          "markdown_length": len(aio.get("markdown") or "")},
        "chatgpt": {"target_site_cited": cg.get("target_site_cited"), "citations_count": len(cg.get("citations") or []),
          "citations_sample": [c.get("url") for c in (cg.get("citations") or [])[:3]], "query": cg.get("query")}},
      "content_quality": {"content_length_dim": dt.get("content_depth"), "entity_richness": dt.get("entity_richness_orgs"),
        "named_people": ee.get("named_people"), "brand_mentions": ee.get("brand_mentions"), "social": ee.get("social_proof_links")},
      "semantic": {"agent_friendly": {"heading": afm.get("heading"), "forms": afm.get("forms"), "images": afm.get("images"), "aria": afm.get("aria")},
        "phase2": {"heading_tree_count": (p2.get("semantic_structure") or {}).get("heading_tree_count"),
          "is_csr_likely": (p2.get("rendering_mode") or {}).get("is_csr_likely"), "exceeds_2mb": (p2.get("google_2mb_cutoff") or {}).get("exceeds_2mb_cutoff")},
        "aspect_findings": {a: (ae.get(a) or {}).get("structured_finding") for a in ["macro_structure", "heading_semantics", "micro_semantics", "schema_entity", "inline_link_semantics"] if a in ae}},
      "ux": {"above_the_fold_finding": (ae.get("above_the_fold") or {}).get("structured_finding"),
        "forms_finding": (ae.get("forms_conversion_points") or {}).get("structured_finding"), "forms_measure": afm.get("forms")},
      "technical": {"indexed": idx.get("indexed"), "canonical_indexed": canonical_indexed, "rel_canonical": idx.get("rel_canonical"),
        "redirect_chain": tech.get("redirect_chain"), "https": tech.get("https"),
        "pagespeed_mobile": (ps.get("mobile") or {}).get("scores", {}).get("performance"),
        "pagespeed_desktop": (ps.get("desktop") or {}).get("scores", {}).get("performance"),
        "crux": {m: (crux.get(m) or {}).get("category") for m in ["lcp", "cls", "inp"]}},
      "meta": {"audit_date": ao.get("_audit_date"), "models": ["gemini-3-flash-preview", "gemini-3.5-flash"],
        "components": ["Discovery audit", "versenytars reverse-engineering", "AI-lathatosag (AI Overview + ChatGPT + fan-out)", "technikai meresek"]},
    }


async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    d = (await db.collection("audits").document(AID).get()).to_dict() or {}
    ao = d.get("audit_output") or {}; ao["_audit_date"] = d.get("audit_date")
    rf = ao.get("re_findings") or {}; idx = ao.get("indexing") or {}
    indexed_variants = [v for v in (idx.get("variants") or []) if v.get("indexed") is True]
    canonical_indexed, _mm = _select_canonical(indexed_variants, idx.get("rel_canonical"))
    print("re-derived canonical_indexed: %s (OLD persisted: %s)" % (canonical_indexed, idx.get("canonical_indexed")))
    ctx = build_ctx(ao, rf, canonical_indexed)
    ctx_text = "AUDIT CONTEXT (JSON, az EGYETLEN tenyforras):\n" + json.dumps(ctx, ensure_ascii=False)
    client = genai.Client(vertexai=True, project=_resolve_project(), location="global")
    ctx_tok = client.models.count_tokens(model=MODEL, contents=ctx_text).total_tokens
    print("context tokens: %d" % ctx_tok)

    cache_name = None; cache_mode = "implicit"
    try:
        cache = client.caches.create(model=MODEL, config=types.CreateCachedContentConfig(
            system_instruction=SYS, contents=[ctx_text], ttl="1200s"))
        cache_name = cache.name; cache_mode = "explicit"
        um = getattr(cache, "usage_metadata", None)
        print("explicit cache OK: %s | cached tokens: %s" % (cache_name, getattr(um, "total_token_count", None) if um else "n/a"))
    except Exception as e:
        print("explicit cache FAILED (%s: %s) -> implicit prefix mode" % (type(e).__name__, str(e)[:140]))

    results = []; total_cost = 0.0
    for num, title, instr in SECTIONS:
        prompt = "Ird meg a(z) %s — %s szekciot magyarul. %s" % (num, title, instr)
        if cache_mode == "explicit":
            cfg = types.GenerateContentConfig(cached_content=cache_name, temperature=0.3,
                thinking_config=types.ThinkingConfig(thinking_level="LOW"))
            contents = prompt
        else:
            cfg = types.GenerateContentConfig(system_instruction=SYS, temperature=0.3,
                thinking_config=types.ThinkingConfig(thinking_level="LOW"))
            contents = ctx_text + "\n\n---\n" + prompt
        r = client.models.generate_content(model=MODEL, contents=contents, config=cfg)
        um = r.usage_metadata
        itok = getattr(um, "prompt_token_count", 0) or 0
        otok = (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
        ctok = getattr(um, "cached_content_token_count", 0) or 0
        cost = round(compute_call_cost_usd(MODEL, itok, otok), 6)
        total_cost += cost
        results.append((num, title, r.text, itok, otok, ctok, cost))
        print("  %s in=%d out=%d cached=%d $%.5f" % (num, itok, otok, ctok, cost))

    print("\n##########  RENDERED REPORT (HU)  ##########")
    for num, title, text, *_ in results:
        print("\n" + (text or "").strip())
    print("\n##########  STATS  ##########")
    print("cache_mode: %s | context tokens: %d" % (cache_mode, ctx_tok))
    for n, t, _x, it, ot, ct, c in results:
        print("  %s in=%d cached=%d out=%d $%.5f" % (n, it, ct, ot, c))
    in_tot = sum(r[3] for r in results); cached_sum = sum(r[5] for r in results); out_tot = sum(r[4] for r in results)
    print("TOTAL Gemini cost: $%.5f" % total_cost)
    print("aggregate input=%d cached=%d output=%d | cache-hit ratio=%.1f%%" % (in_tot, cached_sum, out_tot, 100 * cached_sum / max(1, in_tot)))
    if cache_name:
        try:
            client.caches.delete(name=cache_name); print("cache deleted")
        except Exception:
            pass

asyncio.run(main())
