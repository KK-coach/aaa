"""AAA-83 S2.5 — 3-way diff: S2-control(3-preview) vs S2-old-treat(3.5 pre-recalib) vs S2.5-new-treat(3.5+recalib)."""
import asyncio
from google.cloud import firestore_v1 as firestore

_HU_D = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")
_PN = ["Csávoly","Agrobook.hu Kft.","Agrobook","Kft.","Mezőgazdasági","ügynökség",
       "Taxually","Vercel","AboutYou","About You","Krisztián","Kiss","ABOUT YOU"]
_HU_FW = [" és "," az "," egy "," hogy "," nem "," való "," amely "," ezen ",
          " mely "," ahol "," által "," lehet "," kell "," márk"," felism"]

def prose_lang(t):
    t = t or ""
    body = t
    for pn in _PN: body = body.replace(pn,"")
    d = sum(1 for c in body if c in _HU_D)
    fw = sum(1 for w in _HU_FW if w in t.lower())
    return ("HU" if (d>=12 or fw>=4) else "EN"), d, fw

# (label, control, old_treat, new_treat)
TRIPLES = [
    ("agrobook.hu", "693a5326-570f-4074-9899-cd9057f51b88","2d5a73f1-f0d0-48b9-a953-4e923c588168","50167055-da98-4978-bf41-7c15361d7f68"),
    ("kk.coach",    "d108a4b6-5e2a-4bb7-a207-e4e452ec0398","8beb0d5e-17c4-497d-8a4c-f28e763cd3ff","8866504b-75b9-43dc-87d8-36bf823a33c6"),
    ("aboutyou.hu", "f138c42b-9705-435a-a192-d39f4ec10950","c370318d-42fc-4d29-b941-18192662aedf","90d6dad6-388c-4ee3-b24f-7c6fe9571d40"),
    ("taxually.com","222bd523-0726-4aba-97ca-15c1b486ecf2","f9caa770-7a63-413e-bc3e-e6bcb7389bb7","335e98bc-dad3-4660-afdf-142e3c87058c"),
    ("vercel/plat", "049bb71e-76a3-4334-a287-8fddffb09621","af213372-736d-46a6-b295-5481d9a01cec","2a83f713-92c1-4545-9a4c-4484ed7dbaa6"),
]

async def get(db, aid):
    return ((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}

def hu_verdict(ao):
    md = ao.get("summary_markdown") or ""
    hu = (ao.get("summary_translations") or {}).get("hu") or ""
    lang, d, fw = prose_lang(hu)
    verbatim = (hu.strip() == md.strip() and len(hu) > 50)  # EN passthrough check
    return lang, d, fw, len(hu), verbatim

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    print(f"{'URL':13s} | {'HU gate C / oldT / newT':40s} | core categorical newT vs C | kw n_class C/oldT/newT")
    for label, cid, oid, nid in TRIPLES:
        c, o, n = await get(db,cid), await get(db,oid), await get(db,nid)
        cl = hu_verdict(c); ol = hu_verdict(o); nl = hu_verdict(n)
        def fmt(v): return f"{v[0]}{'(VERBATIM-EN)' if v[4] else ''}/{v[3]}c"
        # core categorical newT vs control
        cats = ["page_type","business_model","topic_domain","locality","audience_relationship_primary"]
        changed = [f for f in cats if c.get(f)!=n.get(f)]
        catstat = "5/5 STABLE" if not changed else f"CHANGED:{changed}"
        # kw n_classified
        def nk(ao): return len(ao.get("target_keywords_classified") or [])
        print(f"\n{label}")
        print(f"  HU gate:  C={fmt(cl)}   oldT={fmt(ol)}   newT={fmt(nl)}")
        print(f"  core categorical (newT vs C): {catstat}")
        print(f"  kw n_classified: C={nk(c)} oldT={nk(o)} newT={nk(n)}")
        # summary_markdown lang
        cml=prose_lang(c.get('summary_markdown') or '')[0]; nml=prose_lang(n.get('summary_markdown') or '')[0]
        print(f"  summary_markdown lang: C={cml} newT={nml}")

asyncio.run(main())
