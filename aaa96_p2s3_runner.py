import asyncio, json
from datetime import datetime, timezone
from google.cloud import firestore_v1 as firestore
from report.build import build_full_report, persist_report, _weave, _validate_ids
from report.report_model import build_report_model
from report.cq_eval import evaluate_content_quality

SITES={"agrobook":"e8128e08-e144-4d98-99f8-3800ac6d30d4","kk.coach":"62281b45-94fe-409e-81de-2eb5ba41494e",
  "theverge":"f0416968-e494-4f32-86d6-171df356d98d","aboutyou":"3f16256f","taxually":"222bd523-0726-4aba-97ca-15c1b486ecf2"}

async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    gen=datetime.now(timezone.utc).isoformat()
    total=0.0; written=[]; first_doc=None; first_id=None
    for label,aid in SITES.items():
        if len(aid)<36:
            async for s in db.collection("audits").stream():
                if s.id.startswith(aid): aid=s.id; break
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        ao["_audit_id"]=aid
        doc=build_full_report(ao, generated_at=gen)
        meta=doc["meta"]; total+=meta["report_generation_cost_usd"]
        pr=await persist_report(doc, db=db)
        written.append(pr["path"])
        print(f"{label:9s} overall={doc['overall_score']} {doc['overall_band']:10s} "
              f"narr_status={meta['narrative_status']:16s} cost=${meta['report_generation_cost_usd']:.6f} -> {pr['path']} wrote={pr['wrote']}")
        if first_doc is None: first_doc, first_id = doc, aid
    print(f"\nWRITTEN PATHS: {written}")
    print(f"TOTAL cost (5 full reports): ${total:.6f}")

    # round-trip read-back (first site)
    rb=(await db.collection("reports").document(first_id).get()).to_dict() or {}
    print(f"\n=== ROUND-TRIP read-back reports/{first_id[:8]} ===")
    print(f"  keys intact: {sorted(rb.keys())==sorted(first_doc.keys())}")
    print(f"  overall_score match: {rb.get('overall_score')==first_doc['overall_score']}")
    print(f"  hero_verdict present: {bool(rb.get('hero_verdict'))}")
    print(f"  pillars n: {len(rb.get('pillars') or [])}  quick_wins n: {len(rb.get('quick_wins') or [])}")
    print(f"  meta.narrative_status: {rb.get('meta',{}).get('narrative_status')}")

    # top-level key structure
    print(f"\n=== TOP-LEVEL report_doc keys ({first_id[:8]}) ===")
    print(sorted(first_doc.keys()))
    print("  pillar[0] keys:", sorted(first_doc['pillars'][0].keys()))
    print("  quick_win[0] keys:", sorted(first_doc['quick_wins'][0].keys()))
    print("  priority_fix keys:", sorted(first_doc['priority_fix'].keys()))
    print("  competitor keys:", sorted(first_doc['competitor'].keys()))

    # PART 2 synthetic fallback test (no Gemini): drop a pillar id + a quick_win id
    print(f"\n=== SYNTHETIC id-mismatch / fallback test ===")
    ao0=((await db.collection("audits").document(first_id).get()).to_dict() or {}).get("audit_output") or {}
    ao0["_audit_id"]=first_id
    cq=evaluate_content_quality(ao0)  # reuse 1 cq (cheap) for a real rm
    rm=build_report_model(ao0, cq_result=cq, generated_at=gen)
    good_nar={"hero_verdict":"H","exec_summary":"E","priority_fix_why":"P","competitor_teaser":"C","methodology_note":"M",
      "pillars":[{"id":p["id"],"narrative":f"N-{p['id']}"} for p in rm["pillars"]],
      "quick_wins":[{"id":q["code"],"title":f"T-{q['code']}","explanation":"X"} for q in rm["quick_wins"]],
      "_meta":{"cost_usd":0.0,"_error":None}}
    print(f"  full good narrative -> _validate_ids: {_validate_ids(rm, good_nar)} (expect True)")
    broken=json.loads(json.dumps(good_nar))
    dropped_pid=broken["pillars"].pop()["id"]; dropped_qid=broken["quick_wins"].pop()["id"]
    print(f"  dropped pillar id={dropped_pid}, quick_win id={dropped_qid}")
    print(f"  broken narrative -> _validate_ids: {_validate_ids(rm, broken)} (expect False)")
    # build_full_report with injected broken narrator (always returns broken) -> partial_fallback
    doc_fb=build_full_report(ao0, generated_at=gen, _narrate=lambda r,a: broken, _eval_cq=lambda a: cq)
    fb_pillar=next(p for p in doc_fb["pillars"] if p["id"]==dropped_pid)
    fb_qw=next(q for q in doc_fb["quick_wins"] if q["code"]==dropped_qid)
    print(f"  narrative_status: {doc_fb['meta']['narrative_status']} (expect partial_fallback)")
    print(f"  dropped pillar '{dropped_pid}' narrative (fallback): {fb_pillar['narrative']!r}")
    print(f"  dropped quick_win '{dropped_qid}' title (fallback): {fb_qw['title']!r}")
    print(f"  -> fallback filled both, no crash: {bool(fb_pillar['narrative'] and fb_qw['title'])}")
asyncio.run(main())
