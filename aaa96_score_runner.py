"""AAA-96 Sub-step 1 verify runner — score the 5 real audits."""
import asyncio, json
from google.cloud import firestore_v1 as firestore
from report.report_model import (build_report_model, SEM_ASPECTS,
    score_semantic_structure, WEIGHTS)

SITES={"agrobook(homepage/ecom)":"e8128e08-e144-4d98-99f8-3800ac6d30d4",
  "kk.coach(homepage/b2bsvc)":"62281b45-94fe-409e-81de-2eb5ba41494e",
  "theverge(news_article)":"f0416968-e494-4f32-86d6-171df356d98d",
  "aboutyou(category)":"3f16256f",
  "taxually(homepage/b2bsaas)":"222bd523-0726-4aba-97ca-15c1b486ecf2"}

async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    PILL=["findability","content_quality","semantic_structure","technical","ai_visibility","keywords","eeat"]
    print("WEIGHTS:",WEIGHTS,"\n")
    for label,aid in SITES.items():
        if len(aid)<36:
            async for s in db.collection("audits").stream():
                if s.id.startswith(aid): aid=s.id; break
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        m=build_report_model(ao, cq_sub_score=None)  # CQ pending
        print(f"{'='*72}\n{label}  ({aid[:8]})\n{'='*72}")
        print(f"  {'pillar':22s} {'sub':>6s} {'wt':>4s}  detail")
        for p in PILL:
            pd=m["pillars"][p]
            print(f"  {p:22s} {str(pd['sub_score']):>6s} {pd['weight']:>4d}  {json.dumps(pd['detail'],ensure_ascii=False)[:90]}")
        print(f"  -> OVERALL (CQ {m['cq_status']}, renorm /{m['present_weight_total']}): {m['overall_score']}  band={m['overall_band']}")
        # per-aspect grades
        _,grades=score_semantic_structure(ao)
        print(f"  semantic aspect grades (0-1): "+", ".join(f"{k}={v}" for k,v in grades.items()))
        # mock-CQ sanity (band Strong=~0.92*100=92)
        m2=build_report_model(ao, cq_sub_score=92.0)
        print(f"  [sanity] with mock CQ=92 -> overall {m2['overall_score']} band={m2['overall_band']} (renorm /{m2['present_weight_total']})")
        print()

asyncio.run(main())
