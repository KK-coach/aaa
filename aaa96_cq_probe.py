"""AAA-96 Phase 0 — Content Quality rubric variance probe. 5 sites × 5 repeats,
gemini-3-flash-preview @ global, temp=0, thinking_level=LOW, structured JSON.
PROBE ONLY."""
import asyncio, json, statistics
from collections import Counter, defaultdict
from google import genai
from google.genai import types
from google.cloud import firestore_v1 as firestore
from site_profile.gemini_analyzer import _resolve_project, MODEL

SITES = {
  "agrobook(ecom/HU)":   "e8128e08-e144-4d98-99f8-3800ac6d30d4",
  "kk.coach(b2b_svc)":   "62281b45-94fe-409e-81de-2eb5ba41494e",
  "theverge(news)":      "f0416968-e494-4f32-86d6-171df356d98d",
  "aboutyou(category)":  "3f16256f",
  "taxually(b2b_saas)":  "222bd523-0726-4aba-97ca-15c1b486ecf2",
}
M = 5
CRITERIA = ["comprehensiveness","intent_match","clarity","value_add",
            "eeat_substance","freshness_specificity"]
ENUM = ["yes","partial","no"]
PTS = {"yes":2,"partial":1,"no":0}

def _crit(): return {"type":"OBJECT","properties":{
    "verdict":{"type":"STRING","enum":ENUM},"reason":{"type":"STRING"}},
    "required":["verdict","reason"]}
SCHEMA = {"type":"OBJECT","properties":{c:_crit() for c in CRITERIA},"required":CRITERIA}

def band(s):
    return "Strong" if s>=0.75 else ("Adequate" if s>=0.4 else "Weak")

def prompt(page_type, bm, intent, char_count, text):
    return f"""You are grading the CONTENT QUALITY of one webpage on 6 criteria. For each, return
verdict yes/partial/no + a 1-line reason that MUST reference the actual content below.

PAGE CONTEXT: page_type={page_type} | business_model={bm} | search_intent={intent}
TRUE total main-content length: {char_count} chars.

CRITERIA:
1. comprehensiveness — depth vs thin (treat low char-count as a floor signal, not the whole story)
2. intent_match — does the content answer the classified search_intent ({intent})?
3. clarity — clear, structured, scannable?
4. value_add — unique value vs generic/commodity boilerplate?
5. eeat_substance — does the TEXT itself show expertise/experience (not just markup)?
6. freshness_specificity — current/specific vs vague/dated?

MAIN CONTENT (may be truncated):
---
{text}
---
Return ONLY structured JSON (all 6 criteria). Ground every reason in the content above."""

async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    client=genai.Client(vertexai=True, project=_resolve_project(), location="global")
    cfg=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json",
        response_schema=SCHEMA, thinking_config=types.ThinkingConfig(thinking_level="LOW"))
    OFF_IN=0.50/1e6; OFF_OUT=3.00/1e6
    total_cost=0.0
    results={}  # site -> list of M parsed dicts
    for label,aid in SITES.items():
        if len(aid)<36:
            async for s in db.collection("audits").stream():
                if s.id.startswith(aid): aid=s.id; break
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        mc=(ao.get("crawl") or {}).get("main_content") or {}
        text=(mc.get("text") or mc.get("content") or "")
        cc=len(text); text=text[:8000]
        intent=(ao.get("target_keywords") or {}).get("intent")
        p=prompt(ao.get("page_type"), ao.get("business_model"), intent, cc, text)
        runs=[]
        for i in range(M):
            r=await client.aio.models.generate_content(model=MODEL, contents=p, config=cfg)
            um=r.usage_metadata
            itok=getattr(um,"prompt_token_count",0) or 0
            otok=(getattr(um,"candidates_token_count",0) or 0)+(getattr(um,"thoughts_token_count",0) or 0)
            total_cost+=itok*OFF_IN+otok*OFF_OUT
            runs.append(json.loads(r.text))
        results[label]=runs
    # ---- analysis ----
    print(f"{'SITE':20s} | "+" ".join(f"{c[:9]:9s}" for c in CRITERIA)+" | band(s) | subσ")
    crit_flips=Counter()
    overall_band_stable=0
    for label,runs in results.items():
        flips=[]
        for c in CRITERIA:
            verds=[r[c]["verdict"] for r in runs]
            nd=len(set(verds))
            flips.append(nd)
            if nd>1: crit_flips[c]+=1
        subs=[sum(PTS[r[c]["verdict"]] for c in CRITERIA)/12 for r in runs]
        bands=[band(s) for s in subs]
        band_stable = len(set(bands))==1
        overall_band_stable += band_stable
        sigma=statistics.pstdev(subs)
        flipmark=" ".join(("OK " if f==1 else f"{f}! ").ljust(9) for f in flips)
        print(f"{label:20s} | {flipmark} | {'STABLE:'+bands[0] if band_stable else 'FLIP:'+'/'.join(sorted(set(bands)))} | {sigma:.3f}")
    print(f"\nband-stable sites: {overall_band_stable}/{len(SITES)}")
    print(f"per-criterion flip count (sites with >1 verdict across {M} repeats):")
    for c in CRITERIA:
        print(f"   {c:24s} {crit_flips[c]}/{len(SITES)} sites flipped")
    noisiest=sorted(CRITERIA, key=lambda c:-crit_flips[c])[:3]
    print(f"noisiest: {[(c,crit_flips[c]) for c in noisiest if crit_flips[c]>0] or 'NONE — all stable'}")
    print(f"\nTOTAL COST ({len(SITES)*M} calls): ${total_cost:.6f}")
    json.dump(results, open("aaa96_cq_out.json","w",encoding="utf-8"), ensure_ascii=False)

asyncio.run(main())
