"""Decisive EN-canonical-guard test: genuine-HU text as summary_markdown."""
import asyncio
from google.cloud import firestore_v1 as firestore
from memory.firestore_archive import _build_translations
from page_analysis.language_detect import is_genuine_target_language
from site_profile.gemini_analyzer import MODEL

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    ao = ((await db.collection("audits").document("693a5326-570f-4074-9899-cd9057f51b88").get()).to_dict() or {}).get("audit_output") or {}
    hu_md = (ao.get("summary_translations") or {}).get("hu") or ""  # genuine Hungarian
    en_in = is_genuine_target_language(hu_md, "en")
    hu_in = is_genuine_target_language(hu_md, "hu")
    print(f"FORCED guard test (model={MODEL})")
    print(f"  INPUT md: len={len(hu_md)} genuine_EN={en_in['is_genuine']}(d={en_in['density']:.2f}) genuine_HU={hu_in['is_genuine']}(d={hu_in['density']:.2f})")
    translations, cost, md_en, flags = await _build_translations(hu_md)
    en_out = is_genuine_target_language(md_en, "en")
    hu = translations.get("hu")
    hu_chk = is_genuine_target_language(hu, "hu", source_text=md_en) if hu else None
    print(f"  -> guard fired & md overwritten to EN: {md_en.strip()!=hu_md.strip()}")
    print(f"  -> summary_markdown_en genuine_EN={en_out['is_genuine']} density={en_out['density']:.2f}")
    print(f"  -> ['en']==md_en: {translations.get('en','').strip()==md_en.strip()}")
    print(f"  -> ['hu'] genuine_HU={hu_chk['is_genuine'] if hu_chk else None} reason={hu_chk['reason'] if hu_chk else 'OMITTED'}")
    print(f"  -> flags: { {k:v for k,v in flags.items()} }")
    print(f"  -> added cost: ${cost:.6f}  (EN re-translate + HU translate)")
    print(f"  -> md_en head: {md_en[:90]!r}")

asyncio.run(main())
