"""AAA-129 S1 WI-8 canary: run shipped evaluate_aspects on 2 stored audits.
agrobook.hu (0 heading bad case) + kk.coach (45 heading good case)."""
import asyncio, json, re
from google.cloud import firestore_v1 as firestore
from page_analysis.aspect_evaluator import evaluate_aspects, ASPECTS
from page_analysis.aspect_edu_templates import EDU_TEMPLATES

# freshest full-ground-truth control audits from AAA-130 S3
SRC = {"agrobook.hu": "aa1aa86e-c27d-4d39-8e27-4ab4a1d656ee",
       "kk.coach":    "54f5619c-6404-48a3-b51f-a1a8d2f410c3"}

# WI-6 over-reach tokens: ungrounded perf/framework advice (no perf GT fed)
OVERREACH = ["crux", "lcp", "cls", "core web vitals", "largest contentful",
             "cumulative layout", "next.js", "nextjs", "react", "time to first byte", "ttfb"]
# redundancy markers: generic "why it matters" prose duplicating the template
REDUNDANCY = ["matters because", "search engines use", "it is important because",
              "azért fontos", "azért számít"]

def scan(txt, toks):
    t = (txt or "").lower()
    return [k for k in toks if k in t]

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    for site, aid in SRC.items():
        ao = ((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        ao["url"] = f"https://{site}"
        h = (ao.get("agent_friendly_measurements") or {}).get("heading") or {}
        print(f"\n{'='*78}\n{site}  (audit {aid[:8]}, h1={h.get('h1_count')} total_headings={h.get('total_headings')})\n{'='*78}")
        result, cost = evaluate_aspects(ao)
        meta = result.get("_meta") or {}
        if meta.get("error"):
            print(f"  ERROR: {meta['error']}"); continue
        print(f"  cost=${cost:.6f}  in={meta['input_tokens']} out={meta['output_tokens']} lat={meta['latency_s']}s model={meta['model_id']}")
        all_overreach = []
        for asp in ASPECTS:
            ev = result[asp]
            sf, ju, rc = ev["structured_finding"], ev["justification"], ev["recommendation"]
            tid = ev.get("educational_context_template_id")
            ec = ev.get("educational_context") or {}
            tid_ok = (tid == EDU_TEMPLATES[asp]["template_id"])
            ec_ok = (ec == EDU_TEMPLATES[asp]["text"])  # injected verbatim
            over = scan(sf, OVERREACH) + scan(ju, OVERREACH) + scan(rc, OVERREACH)
            redun = scan(sf, REDUNDANCY) + scan(ju, REDUNDANCY)
            all_overreach += over
            n_sent = sf.count(". ") + sf.count(".\n") + (1 if sf.strip().endswith(".") else 0)
            step = bool(re.search(r"\b1\.\s", rc))
            print(f"\n  --- {asp}  conf={ev['confidence_0_1']} | template_id={tid} (match={tid_ok}, edu_injected_verbatim={ec_ok})")
            print(f"      finding ({len(sf)}c, ~{n_sent} sent): {sf}")
            print(f"      justification: {ju[:240]}{'...' if len(ju)>240 else ''}")
            print(f"      recommendation (step-numbered={step}): {rc[:300]}{'...' if len(rc)>300 else ''}")
            verdict = "OK"
            if not tid_ok or not ec_ok: verdict = "TEMPLATE-INJECT-FAIL"
            elif over: verdict = f"OVERREACH:{over}"
            elif redun: verdict = f"REDUNDANCY-FLAG:{redun}"
            print(f"      coherence verdict: {verdict}")
        print(f"\n  >>> {site} over-reach tokens across all aspects: {sorted(set(all_overreach)) or 'NONE (WI-6 holds)'}")

asyncio.run(main())
