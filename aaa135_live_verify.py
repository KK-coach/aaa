"""AAA-135 live re-run: real DataForSEO Keywords Data call on theverge's
classified keyword set (previously errored on the apostrophe keyword)."""
import asyncio
from google.cloud import firestore_v1 as firestore
from page_analysis.keywords_volume import (
    fetch_keywords_volume, resolve_location_code, _sanitize_keyword,
)

async def main():
    db=firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",database="ai-advisor-app")
    ao=((await db.collection("audits").document("f0416968-e494-4f32-86d6-171df356d98d").get()).to_dict() or {}).get("audit_output") or {}
    classified=ao.get("target_keywords_classified") or []
    kws=[c["keyword"] for c in classified if c.get("keyword")]
    print(f"theverge classified keywords ({len(kws)}):")
    bad=0
    for k in kws:
        san=_sanitize_keyword(k)
        changed = (san != k)
        flag = "SKIP" if san is None else ("SANITIZED" if changed else "")
        if any(c in k for c in ",'’“”!@%^()={};~`<>?\|"): bad+=1
        print(f"   {flag:9s} {k!r} -> {san!r}")
    print(f"\n   ({bad} keyword(s) contained previously-interfering chars)")
    lang=(ao.get("site_profile") or {}).get("language") or ao.get("audit_language") or "en"
    print(f"\nLIVE CALL: lang={lang} location={resolve_location_code(lang)} ...")
    vol,cost=await fetch_keywords_volume(kws, language_code=lang, location_code=resolve_location_code(lang))
    print(f"  returned {len(vol)} result(s), cost=${cost:.6f}")
    # confirm canonical restored (join works): any returned keyword present in canonical set?
    canon_set=set(kws)
    restored=[v.get("keyword") for v in vol if v.get("keyword") in canon_set]
    print(f"  results whose keyword matches a CANONICAL kw (join works): {len(restored)}/{len(vol)}")
    # show a few with volume
    withvol=[v for v in vol if v.get("search_volume") is not None]
    print(f"  results WITH non-null search_volume: {len(withvol)}")
    for v in vol[:6]:
        print(f"     {v.get('keyword')!r}: vol={v.get('search_volume')}")

asyncio.run(main())
