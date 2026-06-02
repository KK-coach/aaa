import asyncio, json
from collections import Counter
from datetime import datetime, timezone
from google.cloud import firestore_v1 as firestore
from report.report_model import build_report_model, persist_report_model, ASPECT_FINDING_THRESHOLD
SITES={"agrobook":"e8128e08-e144-4d98-99f8-3800ac6d30d4","kk.coach":"62281b45-94fe-409e-81de-2eb5ba41494e",
  "theverge":"f0416968-e494-4f32-86d6-171df356d98d","aboutyou":"3f16256f","taxually":"222bd523-0726-4aba-97ca-15c1b486ecf2"}
async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    gen=datetime.now(timezone.utc).isoformat()
    print(f"ASPECT_FINDING_THRESHOLD={ASPECT_FINDING_THRESHOLD}\n")
    full_dump=None
    for label,aid in SITES.items():
        if len(aid)<36:
            async for s in db.collection("audits").stream():
                if s.id.startswith(aid): aid=s.id; break
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        ao["_audit_id"]=aid
        rm=build_report_model(ao, generated_at=gen)
        nf=sum(len(p["findings"]) for p in rm["pillars"])
        sev=Counter(f["severity"] for p in rm["pillars"] for f in p["findings"])
        pf=rm["priority_fix"]
        qw=[f"{q['code']}({q['quick_win_score']})" for q in rm["quick_wins"]]
        print(f"{'='*72}\n{label} ({aid[:8]})  overall={rm['overall_score']} {rm['overall_band']}")
        print(f"  findings={nf} {dict(sev)}  | competitor.available={rm['competitor']['available']}")
        print(f"  quick_wins: {qw}")
        print(f"  priority_fix: {pf['finding_code']} [{pf['severity']}] impact={pf['impact']} ({pf['pillar']}) — {pf['title']}")
        coincides = pf['finding_code'] in [q['code'] for q in rm['quick_wins']]
        print(f"     coincides with a quick_win? {coincides}")
        print(f"  flags: {rm['flags']}")
        if label=="aboutyou": full_dump=rm
    # dry-run persist on aboutyou
    print(f"\n{'#'*72}\nDRY-RUN PERSIST (aboutyou)\n{'#'*72}")
    pr=persist_report_model(full_dump)
    print(json.dumps(pr, indent=2))
    print(f"\n{'#'*72}\nFULL report_model — aboutyou (pretty JSON)\n{'#'*72}")
    print(json.dumps(full_dump, indent=2, ensure_ascii=False, default=str))
asyncio.run(main())
