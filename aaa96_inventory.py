"""AAA-96 prep — ground-truth audit_output dimension inventory (read-only)."""
import asyncio, json
from google.cloud import firestore_v1 as firestore

def classify(v):
    if v is None: return "null", "None"
    if isinstance(v, bool): return "populated", "bool"
    if isinstance(v, (int, float)): return "populated", type(v).__name__
    if isinstance(v, str):
        if not v.strip(): return "empty", "str"
        return "populated", f"str({len(v)}c)"
    if isinstance(v, dict):
        if not v: return "empty", "dict{}"
        # stub heuristic
        if v.get("note") and "stub" in str(v.get("note")).lower(): return "stub", "dict"
        if v.get("_error"): return "error", "dict"
        return "populated", f"dict[{len(v)}k]"
    if isinstance(v, list):
        if not v: return "empty", "list[]"
        inner = "dict" if isinstance(v[0], dict) else type(v[0]).__name__
        return "populated", f"list[{len(v)}×{inner}]"
    return "populated", type(v).__name__

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    # agrobook e8128e08 (post-AAA-136). Check for re_findings; if absent, note.
    doc = (await db.collection("audits").document("e8128e08-e144-4d98-99f8-3800ac6d30d4").get()).to_dict() or {}
    print("=== TOP-LEVEL DOC KEYS (archive wrapper) ===")
    for k in sorted(doc): 
        st,ty = classify(doc[k]); print(f"  {k:32s} {st:10s} {ty}")
    ao = doc.get("audit_output") or {}
    print(f"\n=== audit_output: {len(ao)} keys ===")
    for k in sorted(ao):
        st, ty = classify(ao[k])
        print(f"  {k:42s} {st:10s} {ty}")
    # nested drill for key composite dims
    print("\n=== NESTED DRILL ===")
    def drill(path, v, depth=0):
        if isinstance(v, dict):
            for kk in sorted(v):
                st,ty=classify(v[kk]); print(f"  {path}.{kk:38s} {st:10s} {ty}")
    for key in ["site_profile","keywords","target_keywords","indexing","agent_friendly_measurements",
                "phase2_html_measurements","pagespeed","eeat_signals","re_findings","aaa124_aspect_evaluations"]:
        if key in ao:
            print(f"\n-- {key} --")
            drill(key, ao[key])
    # aspects sub-shape
    ae = ao.get("aaa124_aspect_evaluations") or {}
    if ae:
        asp = next((a for a in ae if a!="_meta"), None)
        if asp: print(f"\n-- aaa124_aspect_evaluations.{asp} (per-aspect shape) --");
        if asp:
            for kk in sorted(ae[asp]): 
                st,ty=classify(ae[asp][kk]); print(f"     {kk:30s} {st:10s} {ty}")
    # indexing.variants[0]
    iv = (ao.get("indexing") or {}).get("variants") or []
    if iv:
        print("\n-- indexing.variants[] item shape --")
        for kk in sorted(iv[0]): 
            st,ty=classify(iv[0][kk]); print(f"     {kk:30s} {st:10s} {ty}")
    # target_keywords_classified[0]
    tkc = ao.get("target_keywords_classified") or []
    if tkc:
        print("\n-- target_keywords_classified[] item shape --")
        for kk in sorted(tkc[0]):
            st,ty=classify(tkc[0][kk]); print(f"     {kk:30s} {st:10s} {ty}")
    print(f"\nre_findings present? {ao.get('re_findings') is not None}")

asyncio.run(main())
