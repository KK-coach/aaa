import asyncio, json
from datetime import datetime, timezone
from google.cloud import firestore_v1 as firestore
from report.cq_eval import evaluate_content_quality
from report.report_model import build_report_model
SITES={"agrobook":"e8128e08-e144-4d98-99f8-3800ac6d30d4","kk.coach":"62281b45-94fe-409e-81de-2eb5ba41494e",
  "theverge":"f0416968-e494-4f32-86d6-171df356d98d","aboutyou":"3f16256f","taxually":"222bd523-0726-4aba-97ca-15c1b486ecf2"}
async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    gen=datetime.now(timezone.utc).isoformat()
    total_cost=0.0
    for label,aid in SITES.items():
        if len(aid)<36:
            async for s in db.collection("audits").stream():
                if s.id.startswith(aid): aid=s.id; break
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        ao["_audit_id"]=aid
        # old (CQ pending) for contrast
        old=build_report_model(ao, cq_result=None, generated_at=gen)
        # CQ eval
        cq=evaluate_content_quality(ao)
        total_cost+=cq.get("cost_usd") or 0.0
        new=build_report_model(ao, cq_result=cq, generated_at=gen)
        cqp=new["pillars"][1]  # content_quality
        print(f"{'='*74}\n{label} ({aid[:8]})  main_content_chars={cq['main_content_chars']}")
        if cq.get("_error"):
            print(f"  CQ ERROR: {cq['_error']}  -> cq_status={new['meta']['cq_status']}")
        else:
            print(f"  CQ band={cq['band']} sub_score_0_1={cq['sub_score_0_1']} -> pillar {cqp['sub_score']}/100 cost=${cq['cost_usd']:.6f}")
            print(f"  criteria: "+", ".join(f"{c['name']}={c['verdict']}" for c in cq['criteria']))
        print(f"  OVERALL: old(/75 CQ-pending)={old['overall_score']} {old['overall_band']}  ->  NEW(/{new['meta']['present_weight_total']})={new['overall_score']} {new['overall_band']}  [cq_status={new['meta']['cq_status']}]")
        cqf=[f for f in (new['pillars'][1]['findings']) ]
        print(f"  CQ findings: {[(f['code'],f['severity']) for f in cqf] or 'none'}")
        print(f"  priority_fix={new['priority_fix']['finding_code'] if new['priority_fix'] else None}  quick_wins={[q['code'] for q in new['quick_wins']]}")
    print(f"\nTOTAL CQ cost (5 calls): ${total_cost:.6f}")
asyncio.run(main())
