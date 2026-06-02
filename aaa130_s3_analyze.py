"""AAA-130 S3 — analyze 18 in-vivo audits for language-contract reliability."""
import asyncio, json
from google.cloud import firestore_v1 as firestore
from page_analysis.language_detect import is_genuine_target_language

AUDITS = {
 ("ctrl","agrobook","r1"):"aa1aa86e-c27d-4d39-8e27-4ab4a1d656ee",
 ("ctrl","agrobook","r2"):"fff32f3e-f720-41ee-af79-7b72b372b2db",
 ("ctrl","agrobook","r3"):"730a31cb-0fe0-481a-851c-5b52c84a7610",
 ("ctrl","kk.coach","r1"):"54f5619c-6404-48a3-b51f-a1a8d2f410c3",
 ("ctrl","kk.coach","r2"):"190c0472-db2d-4852-9057-a81a2813f738",
 ("ctrl","kk.coach","r3"):"791f686a-bbee-4bbd-8b30-c47cc608d987",
 ("ctrl","aboutyou","r1"):"07428dde-2b46-4dda-93d5-632e67c091d3",
 ("ctrl","aboutyou","r2"):"93e20012-b731-4e19-b5cb-4f134d226dd1",
 ("ctrl","aboutyou","r3"):"23645774-d5ab-4216-a44a-07364e2d051b",
 ("treat","agrobook","r1"):"ed27c3be-378e-4400-b84b-afe920687c20",
 ("treat","agrobook","r2"):"34f8b97a-40e5-4d0d-8dd4-277161a14ced",
 ("treat","agrobook","r3"):"7bb86da5-cb6b-4ab8-8870-bd1a7465b3ad",
 ("treat","kk.coach","r1"):"3e509620-35bd-4d62-a2d8-dc9b8e918e0e",
 ("treat","kk.coach","r2"):"0f1bfeca-64e5-4d29-b5ea-e53074b628d0",
 ("treat","kk.coach","r3"):"a88c9696-e73c-4b3e-89e7-dc4c102b4d33",
 ("treat","aboutyou","r1"):"9d531649-17cb-4280-951d-693b8e5b5c78",
 ("treat","aboutyou","r2"):"efbee096-62fa-43ce-a9b1-4b9bb5fdba11",
 ("treat","aboutyou","r3"):"2fe4d86b-ed71-48fa-b852-09930c96952e",
}

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    rows=[]
    agg={"ctrl":{"hu_ok":0,"n":0,"silent_fail":0,"guard_fired":0,"flagged_fail":0,"attempts":[]},
         "treat":{"hu_ok":0,"n":0,"silent_fail":0,"guard_fired":0,"flagged_fail":0,"attempts":[]}}
    print(f"{'arm':5s} {'site':9s} {'run':3s} | {'md_EN':6s} {'en==md':7s} {'hu_gen':7s} {'reason':11s} | en_fail tr_fail attempts cost")
    for (arm,site,run),aid in AUDITS.items():
        d=(await db.collection("audits").document(aid).get()).to_dict() or {}
        ao=d.get("audit_output") or {}
        md=ao.get("summary_markdown") or ""
        tr=ao.get("summary_translations") or {}
        en=tr.get("en") or ""; hu=tr.get("hu")
        md_en=is_genuine_target_language(md,"en")["is_genuine"]
        en_eq=(en.strip()==md.strip())
        hu_chk=is_genuine_target_language(hu,"hu",source_text=md) if hu else None
        hu_gen=(hu_chk["is_genuine"] if hu_chk else None)
        reason=(hu_chk["reason"] if hu_chk else "OMITTED")
        en_fail=ao.get("_en_canonical_failed",False)
        tr_fail=ao.get("_translation_failed",False)
        att=ao.get("_hu_translate_attempts")
        cost=ao.get("audit_translation_cost_usd")
        a=agg[arm]; a["n"]+=1
        if hu is not None and hu_gen: a["hu_ok"]+=1
        # silent corruption = hu present, NOT genuine, and NO _translation_failed
        if hu is not None and not hu_gen and not tr_fail: a["silent_fail"]+=1
        if tr_fail: a["flagged_fail"]+=1
        if isinstance(att,int): a["attempts"].append(att)
        # guard fired (real agent non-EN emission): can't see directly, but if md_en True AND _en_canonical_failed False we can't tell;
        # proxy: _en_canonical_failed True means guard fired+failed; guard fired+succeeded is invisible unless we stored it.
        print(f"{arm:5s} {site:9s} {run:3s} | {str(md_en):6s} {str(en_eq):7s} {str(hu_gen):7s} {reason:11s} | {str(en_fail):7s} {str(tr_fail):7s} {str(att):8s} {cost}")
    print("\n=== AGGREGATE ===")
    for arm in ("ctrl","treat"):
        a=agg[arm]
        from collections import Counter
        print(f"{arm}: HU-genuine {a['hu_ok']}/{a['n']} ({100*a['hu_ok']/a['n']:.0f}%)  silent_corruption={a['silent_fail']}  flagged_fail(_translation_failed)={a['flagged_fail']}  attempt_dist={dict(Counter(a['attempts']))}")

asyncio.run(main())
