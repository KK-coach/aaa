"""AAA-96 Phase 0 — CQ discrimination re-sweep: page_type-relative rubric +
known-bad controls. gemini-3-flash-preview @ global, temp=0, thinking LOW. PROBE."""
import asyncio, json, statistics
from collections import Counter
from google import genai
from google.genai import types
from google.cloud import firestore_v1 as firestore
from site_profile.gemini_analyzer import _resolve_project, MODEL

GOOD = {
  "agrobook(homepage/ecom)":  "e8128e08-e144-4d98-99f8-3800ac6d30d4",
  "kk.coach(homepage/b2bsvc)":"62281b45-94fe-409e-81de-2eb5ba41494e",
  "theverge(news_article)":   "f0416968-e494-4f32-86d6-171df356d98d",
  "aboutyou(category)":       "3f16256f",
  "taxually(homepage/b2bsaas)":"222bd523-0726-4aba-97ca-15c1b486ecf2",
}
# Known-bad/thin CONTROLS — paired to same page_type as a good counterpart.
CONTROLS = {
  "CTRL thin-homepage": dict(page_type="homepage", business_model="b2b_service",
    search_intent="commercial", text=(
      "Welcome to our website. We offer great products and services for all your needs. "
      "Our team is dedicated to quality and customer satisfaction. Contact us today to "
      "learn more. We look forward to working with you.")),
  "CTRL thin-news": dict(page_type="news_article", business_model="publisher_or_media",
    search_intent="informational", text=(
      "A new event happened recently. Many people were involved and it was important. "
      "Experts say it could have an impact. More details may follow. Stay tuned for updates.")),
  "CTRL keyword-stuffed": dict(page_type="homepage", business_model="ecommerce",
    search_intent="transactional", text=(
      "Cheap shoes buy shoes online. Best shoes cheap shoes. Shoes for sale buy shoes now. "
      "Discount shoes cheap shoes online shoes. Shoes shoes shoes best price shoes buy shoes "
      "cheapest shoes online shoes store shoes deal shoes offer shoes today shoes.")),
}
M=3
CRIT=["comprehensiveness","intent_match","clarity","value_add","eeat_substance","freshness_specificity"]
ENUM=["yes","partial","no"]; PTS={"yes":2,"partial":1,"no":0}
def _c(): return {"type":"OBJECT","properties":{"verdict":{"type":"STRING","enum":ENUM},"reason":{"type":"STRING"}},"required":["verdict","reason"]}
SCHEMA={"type":"OBJECT","properties":{c:_c() for c in CRIT},"required":CRIT}
def band(s): return "Strong" if s>=0.75 else ("Adequate" if s>=0.4 else "Weak")

def prompt(pt,bm,intent,cc,text):
    return f"""You are grading CONTENT QUALITY of one webpage on 6 criteria. verdict yes/partial/no + a
1-line reason grounded in the actual content.

PAGE CONTEXT: page_type={pt} | business_model={bm} | search_intent={intent} | main_content_length={cc} chars

KEY RULE — judge RELATIVE TO page_type expectations: does this page cover what a page of THIS page_type
should? A homepage is NOT expected to be a deep article (don't penalize it for brevity if it does its job);
a thin news_article or a generic/empty homepage IS a problem. Char-count is context interpreted relative
to page_type, not an absolute floor.

CRITERIA:
1. comprehensiveness — does it cover what THIS page_type should (relative, not absolute depth)?
2. intent_match — answers the classified search_intent ({intent})?
3. clarity — clear, structured, scannable?
4. value_add — unique value vs generic/commodity/keyword-stuffed boilerplate?
5. eeat_substance — does the TEXT show expertise/experience appropriate to THIS page_type?
6. freshness_specificity — specific/current vs vague/dated, relative to page_type?

MAIN CONTENT (may be truncated):
---
{text}
---
Return ONLY structured JSON (all 6). Ground every reason in the content above."""

async def grade(client,cfg,pt,bm,intent,cc,text):
    p=prompt(pt,bm,intent,cc,text[:8000])
    runs=[];cost=0.0
    for _ in range(M):
        r=await client.aio.models.generate_content(model=MODEL,contents=p,config=cfg)
        um=r.usage_metadata
        cost+=(getattr(um,"prompt_token_count",0)or 0)*0.5/1e6+((getattr(um,"candidates_token_count",0)or 0)+(getattr(um,"thoughts_token_count",0)or 0))*3.0/1e6
        runs.append(json.loads(r.text))
    return runs,cost

async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    client=genai.Client(vertexai=True,project=_resolve_project(),location="global")
    cfg=types.GenerateContentConfig(temperature=0.0,response_mime_type="application/json",
        response_schema=SCHEMA,thinking_config=types.ThinkingConfig(thinking_level="LOW"))
    total=0.0; out={}
    # good
    for label,aid in GOOD.items():
        if len(aid)<36:
            async for s in db.collection("audits").stream():
                if s.id.startswith(aid): aid=s.id; break
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        mc=(ao.get("crawl") or {}).get("main_content") or {}
        text=mc.get("text") or mc.get("content") or ""
        runs,c=await grade(client,cfg,ao.get("page_type"),ao.get("business_model"),(ao.get("target_keywords") or {}).get("intent"),len(text),text)
        total+=c; out[label]=("GOOD",runs)
    # controls
    for label,d in CONTROLS.items():
        runs,c=await grade(client,cfg,d["page_type"],d["business_model"],d["search_intent"],len(d["text"]),d["text"])
        total+=c; out[label]=("CTRL",runs)
    # report
    print(f"{'ITEM':28s} {'kind':5s} | sub-score | band(s)          | per-criterion (run0)")
    for label,(kind,runs) in out.items():
        subs=[sum(PTS[r[c]["verdict"]] for c in CRIT)/12 for r in runs]
        bands=[band(s) for s in subs]
        bstr= bands[0] if len(set(bands))==1 else "FLIP:"+"/".join(sorted(set(bands)))
        v0="  ".join(f"{c[:4]}:{runs[0][c]['verdict'][:1]}" for c in CRIT)
        print(f"{label:28s} {kind:5s} | {min(subs):.2f}-{max(subs):.2f} | {bstr:16s} | {v0}")
    # control criterion detail
    print("\n--- control per-criterion verdict spread (M=3) ---")
    for label,(kind,runs) in out.items():
        if kind!="CTRL": continue
        print(f"  {label}:")
        for c in CRIT:
            vs=[r[c]["verdict"] for r in runs]
            print(f"     {c:24s} {dict(Counter(vs))}")
    goods=[band(sum(PTS[runs[0][c]['verdict']] for c in CRIT)/12) for k,(kind,runs) in out.items() if kind=="GOOD"]
    ctrls=[band(sum(PTS[runs[0][c]['verdict']] for c in CRIT)/12) for k,(kind,runs) in out.items() if kind=="CTRL"]
    print(f"\nGOOD bands: {goods}")
    print(f"CTRL bands: {ctrls}")
    print(f"\nTOTAL COST ({len(out)*M} calls): ${total:.6f}")
    json.dump({k:v[1] for k,v in out.items()},open("aaa96_cq_discrim_out.json","w",encoding="utf-8"),ensure_ascii=False)

asyncio.run(main())
