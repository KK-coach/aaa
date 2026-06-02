"""AAA-83 S2 — control vs treatment per-step diff."""
import asyncio, re
from google.cloud import firestore_v1 as firestore

_HU_D = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")
_PN = ["Csávoly","Agrobook.hu Kft.","Agrobook","Kft.","Mezőgazdasági","ügynökség",
       "Taxually","Vercel","AboutYou","About You","Krisztián","Kiss"]
_HU_FW = [" és "," az "," egy "," hogy "," nem "," való "," amely "," ezen ",
          " mely "," ahol "," által "," lehet "," kell "," ők "]

def prose_lang(t):
    t = t or ""
    body = t
    for pn in _PN: body = body.replace(pn, "")
    d_body = sum(1 for c in body if c in _HU_D)
    hu_fw = sum(1 for w in _HU_FW if w in t.lower())
    return ("HU" if (d_body >= 12 or hu_fw >= 4) else "EN"), d_body, hu_fw

PAIRS = [
    ("agrobook.hu",  "693a5326-570f-4074-9899-cd9057f51b88", "2d5a73f1-f0d0-48b9-a953-4e923c588168"),
    ("kk.coach",     "d108a4b6-5e2a-4bb7-a207-e4e452ec0398", "8beb0d5e-17c4-497d-8a4c-f28e763cd3ff"),
    ("aboutyou.hu",  "f138c42b-9705-435a-a192-d39f4ec10950", "c370318d-42fc-4d29-b941-18192662aedf"),
    ("taxually.com", "222bd523-0726-4aba-97ca-15c1b486ecf2", "f9caa770-7a63-413e-bc3e-e6bcb7389bb7"),
    ("vercel/platform","049bb71e-76a3-4334-a287-8fddffb09621","af213372-736d-46a6-b295-5481d9a01cec"),
]

def kwc(ao):
    tk = ao.get("target_keywords") or {}
    kc = ao.get("target_keywords_classified") or []
    first = kc[0] if kc else {}
    return {
        "primary": (ao.get("keywords") or {}).get("primary_keyword") or tk.get("primary_keyword"),
        "category": (ao.get("keywords") or {}).get("category_keyword") or tk.get("category_keyword"),
        "n_classified": len(kc),
        "first_kw": first.get("keyword"),
        "first_intent": first.get("search_intent"),
        "first_tail": first.get("tail_type"),
    }

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    for label, cid, tid in PAIRS:
        c = ((await db.collection("audits").document(cid).get()).to_dict() or {})
        t = ((await db.collection("audits").document(tid).get()).to_dict() or {})
        cao, tao = c.get("audit_output") or {}, t.get("audit_output") or {}
        print(f"\n{'='*78}\n{label}   C={cid[:8]}  T={tid[:8]}\n{'='*78}")
        # multi-dim
        for f in ["page_type","business_model","topic_domain","locality","audience_relationship_primary"]:
            cv, tv = cao.get(f), tao.get(f)
            flag = "" if cv==tv else "  <<< CHANGED"
            print(f"  md.{f:28s} C={str(cv):22s} T={str(tv):22s}{flag}")
        # keyword classify
        ck, tk = kwc(cao), kwc(tao)
        for k in ck:
            flag = "" if ck[k]==tk[k] else "  <<< CHANGED"
            print(f"  kw.{k:28s} C={str(ck[k])[:22]:22s} T={str(tk[k])[:22]:22s}{flag}")
        # summary_markdown
        csm, tsm = cao.get("summary_markdown") or "", tao.get("summary_markdown") or ""
        cl, _, _ = prose_lang(csm); tl, _, _ = prose_lang(tsm)
        print(f"  summary_markdown lang        C={cl} ({len(csm)}c)   T={tl} ({len(tsm)}c)" + ("" if cl==tl else "  <<< LANG CHANGED"))
        # summary_translations.hu
        chu = (cao.get("summary_translations") or {}).get("hu") or ""
        thu = (tao.get("summary_translations") or {}).get("hu") or ""
        chl, cd, cf = prose_lang(chu); thl, td, tf = prose_lang(thu)
        print(f"  summary_tr[hu] genuine-HU?   C={chl}(d={cd},fw={cf},{len(chu)}c)  T={thl}(d={td},fw={tf},{len(thu)}c)" + ("" if (chl=='HU' and thl=='HU') else "  <<< HU GATE"))
        # serp_fit presence
        print(f"  serp_fit present             C={cao.get('serp_fit_analysis') is not None}  T={tao.get('serp_fit_analysis') is not None}")
        # aspect_eval present (late-stage completion proxy)
        cae = cao.get("aaa124_aspect_evaluations"); tae = tao.get("aaa124_aspect_evaluations")
        from page_analysis.aspect_evaluator import ASPECTS
        cok = bool(cae) and all(a in cae for a in ASPECTS)
        tok = bool(tae) and all(a in tae for a in ASPECTS)
        print(f"  aspect_eval 7/7 (completion)  C={cok}  T={tok}" + ("" if tok else "  <<< TREATMENT INCOMPLETE"))

asyncio.run(main())
