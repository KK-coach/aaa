"""AAA-96 Part B — cache economics probe. Builds narrative context slice from
e8128e08, counts tokens (free count_tokens), computes 3 cost scenarios."""
import asyncio, json
from google import genai
from google.cloud import firestore_v1 as firestore
from site_profile.gemini_analyzer import _resolve_project, MODEL

# narrative-relevant slice: what a report writer needs; EXCLUDE bulky raw.
KEEP_TOP = ["url","page_type","page_type_parent_intent_group","business_model",
  "topic_domain","locality","audience_relationship_primary","audience_relationship_secondary",
  "indexing","agent_friendly_measurements","phase2_html_measurements","pagespeed",
  "crux_field_data","eeat_signals","eeat_findings_count","grounding_confidence",
  "ai_overview_triggered","summary_markdown","summary_translations"]

def slim(ao):
    s={}
    for k in KEEP_TOP:
        if k in ao: s[k]=ao[k]
    # target_keywords: drop nothing big; keep core
    tk=ao.get("target_keywords") or {}
    s["target_keywords"]={k:tk.get(k) for k in ("primary_keyword","category_keyword","topic_cluster","intent","keyword_gap_severity","gap_interpretation","secondary_keywords","long_tail_keywords")}
    # classified: drop trend_12m (12-pt arrays), keep scalars
    s["target_keywords_classified"]=[{k:c.get(k) for k in ("keyword","search_intent","tail_type","relevance_score","search_volume_monthly","competition","competition_index")} for c in (ao.get("target_keywords_classified") or [])]
    # aspect evals: keep findings/just/rec, DROP educational_context (static template) + _meta
    ae=ao.get("aaa124_aspect_evaluations") or {}
    s["aaa124_aspect_evaluations"]={a:{k:v.get(k) for k in ("structured_finding","justification","recommendation","confidence_0_1")} for a,v in ae.items() if a!="_meta"}
    return s

async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    ao=((await db.collection("audits").document("e8128e08-e144-4d98-99f8-3800ac6d30d4").get()).to_dict() or {}).get("audit_output") or {}
    ctx=slim(ao)
    ctx_json=json.dumps(ctx, ensure_ascii=False)
    print(f"slim context chars: {len(ctx_json)}")
    client=genai.Client(vertexai=True, project=_resolve_project(), location="global")
    ct=client.models.count_tokens(model=MODEL, contents=ctx_json)
    C=ct.total_tokens
    print(f"slim context TOKENS (count_tokens, {MODEL}): {C}")
    # also full audit_output for contrast
    full=json.dumps(ao, ensure_ascii=False)
    cf=client.models.count_tokens(model=MODEL, contents=full).total_tokens
    print(f"FULL audit_output tokens (for contrast): {cf}  (chars {len(full)})")

    # ---- scenario cost math ----
    N=8                      # sections
    P=200                    # per-section instruction/prompt overhead (fresh) tokens
    O=350                    # per-section output tokens
    RIN=0.50/1e6; ROUT=3.00/1e6   # gemini-3-flash-preview official (codebase MODEL_PRICING)
    R_CACHED=0.125/1e6       # ASSUMED cached-input = 25% of input (VERIFY)
    STORE=1.00/1e6           # ASSUMED $1.00 /1M tokens /hour storage (VERIFY); 1hr TTL
    print(f"\nParams: N={N} sections, C={C} ctx tok, P={P} prompt/sec, O={O} out/sec")
    print(f"Rates: in ${RIN*1e6}/M out ${ROUT*1e6}/M  cached-in ${R_CACHED*1e6}/M(assumed) store ${STORE*1e6}/M/hr(assumed)")
    # (a) cached context
    a_cache_write=C*RIN                    # cache creation billed at input rate (assumed)
    a_store=C*STORE                        # 1 hour storage
    a_calls=N*(C*R_CACHED + P*RIN + O*ROUT)
    a=a_cache_write+a_store+a_calls
    # (b) no cache, resend each time
    b=N*(C*RIN + P*RIN + O*ROUT)
    # (c) one big call: context once + all-section output
    c=(C+P)*RIN + (N*O)*ROUT
    print(f"\n(a) cached  : write {a_cache_write*100:.4f}c + store {a_store*100:.4f}c + 8 calls {a_calls*100:.4f}c = ${a:.6f}")
    print(f"(b) no-cache: 8×(C+P in + O out)                       = ${b:.6f}")
    print(f"(c) one-call: (C+P) in + 8O out                        = ${c:.6f}")
    print(f"\nratios: a/c={a/c:.2f}x  b/c={b/c:.2f}x  b/a={b/a:.2f}x")

asyncio.run(main())
