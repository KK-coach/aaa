import asyncio
from google.cloud import firestore_v1 as firestore
from discovery_agent.tools import _select_canonical, _canonical_key
IDS = {"taxually": "013a2853-2e51-4c41-a201-a781f7f6aa67",
       "agrobook": "93707b41-db62-4313-8c9a-2812aa99ecc5",
       "kk.coach": "67762118-df49-41d1-865d-81e9c6ad9d30"}
EXPECT = {"taxually": "https://www.taxually.com", "agrobook": "https://www.agrobook.hu", "kk.coach": "https://kk.coach"}

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc", database="ai-advisor-app")
    print("=== re-derive from persisted indexing.variants (fixed _select_canonical) ===")
    allok = True
    for label, aid in IDS.items():
        idx = ((await db.collection("audits").document(aid).get()).to_dict() or {}).get("audit_output", {}).get("indexing") or {}
        variants = idx.get("variants") or []
        rel = idx.get("rel_canonical")
        indexed = [v for v in variants if v.get("indexed") is True]
        ci, mm = _select_canonical(indexed, rel)
        ok = (ci == EXPECT[label] and mm is False)
        allok = allok and ok
        live = [v["url"] for v in indexed if v.get("live_200")]
        print("%-9s OLD=%s -> NEW=%s mismatch=%s rel=%s live_200=%s [%s]" % (
            label, idx.get("canonical_indexed"), ci, mm, rel, live, "OK" if ok else "FAIL"))
    print("\n3-canary verdict: %s" % ("ALL OK" if allok else "FAIL"))
    print("\n=== synthetic split tests ===")
    syn = [{"url": "https://www.taxually.com", "indexed": True, "live_200": True},
           {"url": "http://taxually.com", "indexed": True, "live_200": False}]
    ci, mm = _select_canonical(syn, "https://taxually.com")
    print("  www<->apex split: rel=https://taxually.com live=https://www.taxually.com -> ci=%s mismatch=%s [%s]" % (ci, mm, "OK" if mm is True else "FAIL"))
    syn2 = [{"url": "http://example.com", "indexed": True, "live_200": True}]
    ci2, mm2 = _select_canonical(syn2, "https://example.com")
    print("  http<->https split: rel=https://example.com live=http://example.com -> ci=%s mismatch=%s [%s]" % (ci2, mm2, "OK" if mm2 is True else "FAIL"))
    syn3 = [{"url": "https://www.x.com", "indexed": True, "live_200": True}]
    ci3, mm3 = _select_canonical(syn3, "https://www.x.com/?srsltid=abc")
    print("  no-split (query/slash only): rel=...?srsltid live=https://www.x.com -> ci=%s mismatch=%s [%s]" % (ci3, mm3, "OK" if mm3 is False else "FAIL"))
    print("\n  _canonical_key (preserves scheme/www; strips query/slash):")
    for u in ["https://www.taxually.com/", "https://www.taxually.com/?srsltid=x", "http://taxually.com"]:
        print("     %-42s -> %s" % (u, _canonical_key(u)))

asyncio.run(main())
