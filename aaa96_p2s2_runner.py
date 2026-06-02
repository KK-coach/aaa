import asyncio, json
from datetime import datetime, timezone
from google.cloud import firestore_v1 as firestore
from report.cq_eval import evaluate_content_quality
from report.report_model import build_report_model
from report.narrative import generate_narrative
SITES={"agrobook":"e8128e08-e144-4d98-99f8-3800ac6d30d4","kk.coach":"62281b45-94fe-409e-81de-2eb5ba41494e",
  "theverge":"f0416968-e494-4f32-86d6-171df356d98d","aboutyou":"3f16256f","taxually":"222bd523-0726-4aba-97ca-15c1b486ecf2"}
async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    gen=datetime.now(timezone.utc).isoformat()
    total=0.0; dumps={}
    summary=[]
    for label,aid in SITES.items():
        if len(aid)<36:
            async for s in db.collection("audits").stream():
                if s.id.startswith(aid): aid=s.id; break
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        ao["_audit_id"]=aid
        cq=evaluate_content_quality(ao); total+=cq.get("cost_usd") or 0.0
        rm=build_report_model(ao, cq_result=cq, generated_at=gen)
        nar=generate_narrative(rm, ao); total+=(nar.get("_meta") or {}).get("cost_usd") or 0.0
        dumps[label]=(rm,nar)
        summary.append((label, rm["overall_score"], rm["overall_band"], rm["priority_fix"]["finding_code"] if rm["priority_fix"] else None, nar))
        print(f"{'='*74}\n{label}  overall={rm['overall_score']} {rm['overall_band']}  nar_cost=${(nar.get('_meta') or {}).get('cost_usd'):.6f}")
        print(f"  HERO: {nar.get('hero_verdict')}")
        print(f"  EXEC: {nar.get('exec_summary')}")
        print(f"  PRIORITY_WHY ({rm['priority_fix']['finding_code'] if rm['priority_fix'] else None}): {nar.get('priority_fix_why')}")
    print(f"\nTOTAL cost (5× CQ + 5× narrative): ${total:.6f}")
    # full taxually dump
    rm,nar=dumps["taxually"]
    print(f"\n{'#'*74}\nFULL NARRATIVE JSON — taxually\n{'#'*74}")
    nar_clean={k:v for k,v in nar.items()}
    print(json.dumps(nar_clean, indent=2, ensure_ascii=False))
    # grounding aid: print taxually report_model numbers for cross-check
    print(f"\n--- taxually report_model figures (for groundedness cross-check) ---")
    print(f"overall={rm['overall_score']} band={rm['overall_band']}")
    for p in rm['pillars']:
        print(f"  {p['id']:20s} sub={p['sub_score']} band={p['band']} findings={[f['code'] for f in p['findings']]}")
    print(f"  priority_fix={rm['priority_fix']}")
    print(f"  quick_wins={[q['code'] for q in rm['quick_wins']]}  flags={rm['flags']}  competitor_avail={rm['competitor']['available']}")
asyncio.run(main())
