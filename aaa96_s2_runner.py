import asyncio, json
from collections import Counter
from google.cloud import firestore_v1 as firestore
from report.report_model import build_report_model, SEVERITY_SCORE, EFFORT_BY_CODE, EFFORT_LABEL
SITES={"agrobook":"e8128e08-e144-4d98-99f8-3800ac6d30d4","kk.coach":"62281b45-94fe-409e-81de-2eb5ba41494e",
  "theverge":"f0416968-e494-4f32-86d6-171df356d98d","aboutyou":"3f16256f","taxually":"222bd523-0726-4aba-97ca-15c1b486ecf2"}
async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    for label,aid in SITES.items():
        if len(aid)<36:
            async for s in db.collection("audits").stream():
                if s.id.startswith(aid): aid=s.id; break
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        m=build_report_model(ao)
        f=m["pillars"]["findability"]
        print(f"\n{'='*74}\n{label} ({aid[:8]})  OVERALL {m['overall_score']} {m['overall_band']}\n{'='*74}")
        print(f"  Findability={f['sub_score']}  indexed={f['detail'].get('indexed')} not_confirmed={f['detail'].get('indexing_not_confirmed')}")
        sev=Counter(x['severity'] for x in m['findings'])
        print(f"  findings: {len(m['findings'])} total  {dict(sev)}")
        for x in m['findings']:
            print(f"     [{x['severity']:8s}] {x['pillar']:18s} {x['code']:26s} {x['default_title']}")
        print(f"  TOP-3 QUICK WINS:")
        for q in m['quick_wins']:
            print(f"     score={q['quick_win_score']:.3f} impact={q['impact']} effort={q['effort_label']}({q['effort_weight']}) <- [{q['severity']}] {q['code']} ({q['pillar']})")
        print(f"  FLAGS: {[k for k,v in m['flags'].items() if v] or 'none'}")
    print(f"\n--- SEVERITY rubric: {SEVERITY_SCORE}")
    print(f"--- EFFORT_BY_CODE: {json.dumps(EFFORT_BY_CODE)}")
asyncio.run(main())
