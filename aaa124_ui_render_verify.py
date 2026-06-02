"""Headless render verification — mirrors 02_data_explorer.py AAA-124 logic
EXACTLY, dumping the rendered text for review + proving _meta skip + None handling."""
import asyncio
from google.cloud import firestore_v1 as firestore

_ASPECT_ORDER = [
    "macro_structure", "heading_semantics", "above_the_fold",
    "micro_semantics", "inline_link_semantics", "forms_conversion_points",
    "schema_entity",
]

def _conf_badge(c):
    if not isinstance(c, (int, float)): return "❔ —"
    if c >= 0.85: return f"🟢 {c:.2f}"
    if c >= 0.6:  return f"🟡 {c:.2f}"
    return f"🔴 {c:.2f}"

def render(ao, label):
    print(f"\n{'='*78}\nRENDER: {label}\n{'='*78}")
    _ae = ao.get("aaa124_aspect_evaluations")
    _ae_cost = ao.get("audit_aspect_eval_cost_usd")
    if _ae is None:
        print("[caption] Not available (pre-AAA-124 audit) — aaa124_aspect_evaluations not populated.")
        return
    if not isinstance(_ae, dict):
        print(f"[error] unexpected shape: {type(_ae).__name__}")
        return
    _meta = _ae.get("_meta") or {}
    if _meta.get("error"):
        print(f"[warning] skip-finding error: {_meta.get('error')}")
    _cost_str = f"${_ae_cost:.6f}" if isinstance(_ae_cost,(int,float)) else "—"
    print(f"[caption] Cost: {_cost_str} | model: {_meta.get('model_id')} | "
          f"latency: {_meta.get('latency_s')}s | tokens in/out: "
          f"{_meta.get('input_tokens')}/{_meta.get('output_tokens')}")
    # prove _meta skip: iterate explicit list only
    iterated = []
    _any = False
    for _asp in _ASPECT_ORDER:
        _ev = _ae.get(_asp)
        iterated.append(_asp)
        if _ev is None:
            print(f"\n#### {_asp}\n(aspect not populated)")
            continue
        _any = True
        print(f"\n**{_asp}** (confidence: {_ev.get('confidence_0_1')})  badge={_conf_badge(_ev.get('confidence_0_1'))}")
        print(f"- Finding: {_ev.get('structured_finding')}")
        print(f"- Justification: {_ev.get('justification')}")
        print(f"- Recommendation: {_ev.get('recommendation')}")
    # confirm _meta NOT in iterated set, and any extra dict keys
    print(f"\n[iteration check] iterated aspects = {iterated}")
    print(f"[iteration check] '_meta' in iterated list? {'_meta' in iterated}  (must be False)")
    extra = [k for k in _ae.keys() if k not in _ASPECT_ORDER]
    print(f"[iteration check] dict keys NOT rendered as aspects = {extra}  (expect ['_meta'])")

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    for label, aid in [
        ("kk.coach", "2a8c0b20-0635-4a67-9868-ff71eb08f721"),
        ("agrobook.hu", "b4908500-7728-4290-b320-eb030ba2179a"),
    ]:
        doc = await db.collection("audits").document(aid).get()
        render((doc.to_dict() or {}).get("audit_output") or {}, f"{label} ({aid[:8]})")
    # legacy None-handling
    legacy = None
    async for snap in db.collection("audits").stream():
        if snap.id.startswith("18c133f2"):
            legacy = snap; break
    render((legacy.to_dict() or {}).get("audit_output") or {}, "vercel.com 18c133f2 (LEGACY None-handling)")

asyncio.run(main())
