"""AAA-130 S2 canary — exercise _build_translations contract on prod model
(gemini-3-flash-preview), 2 deterministic real inputs:
  aboutyou: HU markdown (control f138c42b) -> EN-canonical guard must fire
  kk.coach: EN markdown (control d108a4b6) -> normal path
"""
import asyncio, json
from google.cloud import firestore_v1 as firestore
from memory.firestore_archive import _build_translations
from page_analysis.language_detect import is_genuine_target_language
from site_profile.gemini_analyzer import get_usage, reset_usage, MODEL

async def fetch_md(db, aid):
    ao = ((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output") or {}
    return ao.get("summary_markdown") or ""

async def run_one(label, md):
    reset_usage()
    en_in = is_genuine_target_language(md, "en")
    print(f"\n{'='*72}\n{label}  (model={MODEL})\n{'='*72}")
    print(f"  INPUT summary_markdown: len={len(md)} genuine_EN={en_in['is_genuine']} density={en_in['density']:.2f}")
    translations, cost, md_en, flags = await _build_translations(md)
    # post-contract checks
    en_out = is_genuine_target_language(md_en, "en")
    hu = translations.get("hu")
    hu_chk = is_genuine_target_language(hu, "hu", source_text=md_en) if hu else None
    print(f"  -> summary_markdown_en: len={len(md_en)} genuine_EN={en_out['is_genuine']} density={en_out['density']:.2f}")
    print(f"  -> ['en'] == md_en: {translations.get('en','').strip()==md_en.strip()}")
    if hu:
        print(f"  -> ['hu']: present len={len(hu)} genuine_HU={hu_chk['is_genuine']} density={hu_chk['density']:.2f} reason={hu_chk['reason']}")
    else:
        print(f"  -> ['hu']: OMITTED")
    print(f"  -> flags: { {k:v for k,v in flags.items()} }")
    print(f"  -> hu_translate_attempts: {flags.get('_hu_translate_attempts')}")
    print(f"  -> added translate cost: ${cost:.6f}")
    return cost

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    ay_md = await fetch_md(db, "f138c42b-9705-435a-a192-d39f4ec10950")  # HU markdown (EN-canonical broken)
    kk_md = await fetch_md(db, "d108a4b6-5e2a-4bb7-a207-e4e452ec0398")  # EN markdown (normal)
    c1 = await run_one("aboutyou.hu (EN-canonical-broken prod case)", ay_md)
    c2 = await run_one("kk.coach (normal HU-site EN summary)", kk_md)
    print(f"\nTOTAL added cost across 2 canaries: ${c1+c2:.6f}")

asyncio.run(main())

async def force_guard():
    """Decisive EN-canonical-guard test: feed a GENUINE HU text as
    summary_markdown -> guard must re-translate to EN."""
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    ao = ((await db.collection("audits").document("693a5326-570f-4074-9899-cd9057f51b88").get()).to_dict() or {}).get("audit_output") or {}
    hu_md = (ao.get("summary_translations") or {}).get("hu") or ""  # genuine Hungarian
    await run_one("FORCED: genuine-HU markdown (EN-canonical guard must fire)", hu_md)

asyncio.run(force_guard())
