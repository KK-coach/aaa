"""Headless mirror of the AAA-129 _render_edu logic from 02_data_explorer.py.
Reproduces the exact control flow (no Streamlit runtime)."""
import json, asyncio
from google.cloud import firestore_v1 as firestore

_ASPECT_ORDER = ["macro_structure","heading_semantics","above_the_fold",
    "micro_semantics","inline_link_semantics","forms_conversion_points","schema_entity"]

def render_edu(ev, log):
    ec = ev.get("educational_context"); tid = ev.get("educational_context_template_id")
    if ec is None: log.append("  📚 (no educational context — pre-AAA-129 audit)"); return
    if not isinstance(ec, dict): log.append(f"  📚 (unexpected shape: {type(ec).__name__})"); return
    log.append("  **📚 Miért fontos:**")
    if "hu" not in ec: log.append("    HU: (nincs)")
    elif not str(ec.get("hu") or "").strip(): log.append("    HU: (üres)")
    else: log.append(f"    HU[md]: {ec['hu'][:70]}...")
    if "en" not in ec: log.append("    EN: (nincs)")
    elif not str(ec.get("en") or "").strip(): log.append("    EN: (üres)")
    else: log.append(f"    EN[expander]: {ec['en'][:70]}...")
    log.append(f"    caption: {('template: '+tid) if tid else '(template_id n/a)'}")

def render_section(ae, label):
    print(f"\n{'='*72}\n{label}\n{'='*72}")
    if ae is None:
        print("  [section caption] Not available (pre-AAA-124 audit)"); return
    if not isinstance(ae, dict):
        print(f"  [error] unexpected shape {type(ae).__name__}"); return
    crashed = False
    for asp in _ASPECT_ORDER:  # explicit list — _meta never iterated
        ev = ae.get(asp)
        if ev is None: print(f"#### {asp}\n  (aspect not populated)"); continue
        if not isinstance(ev, dict): print(f"#### {asp}\n  [error]"); continue
        log = []
        try:
            render_edu(ev, log)
        except Exception as e:
            crashed = True; log.append(f"  CRASH: {type(e).__name__}: {e}")
        edu_ok = (isinstance(ev.get("educational_context"), dict)
                  and ev["educational_context"].get("hu") and ev["educational_context"].get("en"))
        tid = ev.get("educational_context_template_id")
        print(f"#### {asp}  [edu_hu+en={'Y' if edu_ok else 'N'} tid={tid}]")
        for l in log: print(l)
    assert not crashed, "RENDER CRASHED"
    print("  '_meta' iterated as aspect? ", "_meta" in _ASPECT_ORDER)

async def main():
    # PATH 1 — POPULATED (S2 sweep output, has educational_context)
    s = json.load(open("aaa129_s2_sweep_out.json", encoding="utf-8"))
    ae_pop = s["agrobook.hu"]["runs"][0]["result"]
    render_section(ae_pop, "POPULATED PATH — agrobook.hu (S2 sweep run-1, AAA-129 hybrid)")

    # PATH 2 — GRACEFUL (pre-AAA-129 archive entry: aaa124_aspect_evaluations
    # present but WITHOUT educational_context). AAA-124 smoke kk.coach 2a8c0b20.
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    ao = ((await db.collection("audits").document("2a8c0b20-0635-4a67-9868-ff71eb08f721").get()).to_dict() or {}).get("audit_output") or {}
    ae_old = ao.get("aaa124_aspect_evaluations")
    has_edu = isinstance(ae_old, dict) and isinstance(ae_old.get("heading_semantics"), dict) and ("educational_context" in (ae_old.get("heading_semantics") or {}))
    print(f"\n[pre-AAA-129 entry 2a8c0b20: aaa124 present={ae_old is not None}, has educational_context key={has_edu}]")
    render_section(ae_old, "GRACEFUL PATH — kk.coach 2a8c0b20 (pre-AAA-129, no educational_context)")
    print("\nALL RENDER PATHS COMPLETED — NO CRASH")

asyncio.run(main())
