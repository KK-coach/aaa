"""Headless mirror of _render_indexing 3-shape handling (no Streamlit runtime)."""
import asyncio
from google.cloud import firestore_v1 as firestore

def indexed_badge(v): return "🟢 Indexed" if v is True else ("🔴 Not indexed" if v is False else "⚪ Unknown")
def md_cell(v): return "—" if v is None else str(v).replace("|","\|")

def render(idx, log):
    if not isinstance(idx, dict) or not idx: log.append("CAPTION: (no indexing data — pre-AAA-136 audit)"); return "STUB/MISSING"
    method=idx.get("method")
    if method not in ("quoted_url_serp","serp_site_query"):
        if idx.get("note") or set(idx.keys())<= {"indexed","note","url"}: log.append("CAPTION: (no indexing data — pre-AAA-136 audit)"); return "STUB"
        log.append("CAPTION: (unrecognized shape — raw)"); return "UNKNOWN"
    if method=="serp_site_query":
        log.append(f"Status: {indexed_badge(idx.get('indexed'))}")
        log.append(f"query={idx.get('query')} matched={idx.get('matched_url')} pos={idx.get('position')}")
        log.append("CAPTION: (superseded site: method — pre-AAA-136 refinement)")
        return "SITE_SUPERSEDED"
    # quoted_url_serp
    log.append(f"Status: {indexed_badge(idx.get('indexed'))}")
    log.append(f"canonical_indexed={idx.get('canonical_indexed')} rel_canonical={idx.get('rel_canonical')} mismatch={idx.get('canonical_mismatch')} dup={idx.get('duplication_signal')}")
    cols=["url","status_chain","final_url","live_200","indexed","first_result_url","position"]
    log.append("| "+" | ".join(cols)+" |")
    for v in (idx.get("variants") or []):
        log.append("| "+" | ".join(md_cell(v.get(c)) for c in cols)+" |")
    log.append(f"CAPTION: method={idx.get('method')} cost=${idx.get('cost_usd') or 0:.6f}")
    return "QUOTED_URL_SERP"

async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    cases=[
      ("NEW quoted_url_serp — agrobook","e8128e08-e144-4d98-99f8-3800ac6d30d4"),
      ("NEW quoted_url_serp — kk.coach","62281b45-94fe-409e-81de-2eb5ba41494e"),
      ("site:-era superseded","700b91dc-3a85-4e89-b65f-c41b9233eead"),
    ]
    for label,aid in cases:
        ao=((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
        log=[]; shape=render(ao.get("indexing"), log)
        print(f"\n{'='*72}\n{label}  ({aid[:8]})  -> shape={shape}\n{'='*72}")
        for l in log: print("  "+l)
    # stub/missing path (synthetic + a real pre-indexing audit if any)
    print(f"\n{'='*72}\nSTUB shape (synthetic)\n{'='*72}")
    log=[]; print("  -> shape=", render({"indexed":"unknown","note":"stub - DataForSEO indexing endpoint not in enabled modules","url":"x"}, log)); 
    for l in log: print("  "+l)
    print(f"\n{'='*72}\nMISSING (None)\n{'='*72}")
    log=[]; print("  -> shape=", render(None, log))
    for l in log: print("  "+l)
    print("\nNO CRASH ON ANY SHAPE")
asyncio.run(main())
