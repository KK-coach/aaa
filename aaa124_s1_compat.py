"""AAA-124 S1 schema-additive backward-compat verification."""
import asyncio
from google.cloud import firestore_v1 as firestore
from discovery_agent.output_schema import AuditOutput

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",
                                database="ai-advisor-app")
    # A pre-AAA-124 legacy entry (vercel.com archived 18c133f2, pre-AAA-123 even)
    doc = await db.collection("audits").document("18c133f2").get()
    # 18c133f2 is a prefix; need full scan
    if not doc.exists:
        async for snap in db.collection("audits").stream():
            if snap.id.startswith("18c133f2"):
                doc = snap
                break
    d = doc.to_dict() or {}
    ao = d.get("audit_output") or {}
    print(f"legacy doc id: {doc.id}")
    print(f"  has aaa124_aspect_evaluations key: {'aaa124_aspect_evaluations' in ao}")
    print(f"  has audit_aspect_eval_cost_usd key: {'audit_aspect_eval_cost_usd' in ao}")
    # Parse through the model
    try:
        parsed = AuditOutput(**ao)
        print(f"  AuditOutput parse: PASS")
        print(f"  aaa124_aspect_evaluations default: {parsed.aaa124_aspect_evaluations}")
        print(f"  audit_aspect_eval_cost_usd default: {parsed.audit_aspect_eval_cost_usd}")
    except Exception as e:
        print(f"  AuditOutput parse: FAIL {type(e).__name__}: {e}")

asyncio.run(main())
