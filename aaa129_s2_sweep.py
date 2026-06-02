"""AAA-129 S2 — stability sweep + quality surface. NO code edits.
Part A: evaluate_aspects 5x on agrobook/kk.coach/theverge.
Part B: + aboutyou (1 run) for the full quality surface."""
import asyncio, json, re, statistics
from google.cloud import firestore_v1 as firestore
from page_analysis.aspect_evaluator import evaluate_aspects, ASPECTS
from page_analysis.aspect_edu_templates import EDU_TEMPLATES

CANARIES = {
 "agrobook.hu":  ("aa1aa86e-c27d-4d39-8e27-4ab4a1d656ee", None),
 "kk.coach":     ("54f5619c-6404-48a3-b51f-a1a8d2f410c3", None),
 "theverge":     ("f0416968-e494-4f32-86d6-171df356d98d", None),
 "aboutyou/c/noi":("3f16256f", "aaa129_s0_slot3_phase2.json"),
}
N_PARTA = 5

NEG = ["lack","missing","absence","absent","zero","without","critical","gap",
       "fails","weak","poor","not present","disrupt","limit","unusual"]
POS = ["excellent","single h1","well-structured","well-defined","solid","strong",
       "clear","perfect","robust","successfully","clean","ideal","lightweight"]

def n_sent(t): return len(re.findall(r"[.!?](?:\s|$)", t or ""))
def pol(t):
    tl=(t or "").lower()
    return sum(tl.count(w) for w in POS), sum(tl.count(w) for w in NEG)
def step1(t):
    m=re.search(r"1\.\s*(.+?)(?:\s*2\.|\Z)", (t or ""), re.S)
    return (m.group(1).strip()[:80] if m else "(no step1)")

async def load(db, aid, p2file):
    if len(aid)<36:
        async for s in db.collection("audits").stream():
            if s.id.startswith(aid): aid=s.id; break
    ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
    if p2file:
        ovr=json.load(open(p2file,encoding="utf-8"))
        ao["phase2_html_measurements"]=ovr.get("phase2_html_measurements")
    return ao

async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    store={}
    # Part A: 5x for first 3; Part B aboutyou: 1x
    for site,(aid,p2) in CANARIES.items():
        ao=await load(db,aid,p2); ao["url"]=f"https://{site}"
        runs = N_PARTA if site!="aboutyou/c/noi" else 1
        store[site]={"runs":[]}
        for i in range(runs):
            res,cost=evaluate_aspects(ao)
            store[site]["runs"].append({"result":res,"cost":cost})
            print(f"  {site} run{i+1}: cost=${cost:.6f} err={(res.get('_meta') or {}).get('error')}")
    json.dump(store, open("aaa129_s2_sweep_out.json","w",encoding="utf-8"), ensure_ascii=False)

    # template byte-identical assert across ALL runs
    tpl_ok=True
    for site,d in store.items():
        for run in d["runs"]:
            for asp in ASPECTS:
                ev=run["result"][asp]
                if ev["educational_context"]!=EDU_TEMPLATES[asp]["text"] or ev["educational_context_template_id"]!=EDU_TEMPLATES[asp]["template_id"]:
                    tpl_ok=False
    print(f"\n[WI-SCOPE] educational_context byte-identical across all runs: {tpl_ok}")

    # Part A stability table
    print("\n=== PART A STABILITY (5 runs) ===")
    tot_cost=0.0
    for site in ["agrobook.hu","kk.coach","theverge"]:
        runs=store[site]["runs"]
        print(f"\n### {site}")
        for asp in ASPECTS:
            evs=[r["result"][asp] for r in runs]
            confs=[e["confidence_0_1"] for e in evs]
            sents=[n_sent(e["structured_finding"]) for e in evs]
            inlock=all(3<=s<=6 for s in sents)
            pols=[pol(e["structured_finding"]) for e in evs]
            # dominant polarity per run: +1 pos, -1 neg, 0 tie
            signs=[(1 if p>n else (-1 if n>p else 0)) for p,n in pols]
            nonzero=[s for s in signs if s!=0]
            flip = len(set(nonzero))>1  # both +1 and -1 present
            steps=[step1(e["recommendation"]) for e in evs]
            print(f"  {asp:24s} conf μ={statistics.mean(confs):.2f} σ={statistics.pstdev(confs):.3f} range=[{min(confs)},{max(confs)}] | sent={sents} inlock={'Y' if inlock else 'N'} | pol_signs={signs} flip={'Y!!' if flip else 'N'}")
        for r in runs: tot_cost+=r["cost"]
    # aboutyou cost
    for r in store["aboutyou/c/noi"]["runs"]: tot_cost+=r["cost"]
    print(f"\n=== COST LEDGER (official) total {15}+1 runs = ${tot_cost:.6f} ===")
    for site,d in store.items():
        cs=[r["cost"] for r in d["runs"]]
        print(f"  {site:15s} n={len(cs)} sum=${sum(cs):.6f} mean=${sum(cs)/len(cs):.6f}")

    # capture the 5 findings + step1 for substantive review (heading_semantics — clearest)
    print("\n=== SUBSTANTIVE: heading_semantics 5-run findings (+ step1) ===")
    for site in ["agrobook.hu","kk.coach","theverge"]:
        print(f"\n{site}:")
        for i,r in enumerate(store[site]["runs"]):
            ev=r["result"]["heading_semantics"]
            print(f"  r{i+1}: {ev['structured_finding'][:150]}")
            print(f"       step1: {step1(ev['recommendation'])}")

asyncio.run(main())
