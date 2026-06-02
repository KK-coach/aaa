"""AAA-136 probe: quoted exact-URL indexed detection + 4-variant canonicalization.
PROBE ONLY — does NOT modify the tool. agrobook.hu + kk.coach + wikipedia control."""
import asyncio, re
import httpx
from selectolax.parser import HTMLParser
from reverse_engineering_agent.tools import _run_serp

def norm(u: str) -> str:
    """drop scheme + leading www + trailing slash + STRIP query string (srsltid)."""
    s = (u or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    s = s.split("?", 1)[0].split("#", 1)[0]
    return s.rstrip("/")

def variants(domain: str):
    return [f"http://{domain}", f"https://{domain}",
            f"http://www.{domain}", f"https://www.{domain}"]

def resolve(url: str):
    """httpx follow-redirects → (status_chain, final_url, direct_live_200, canonical)."""
    try:
        with httpx.Client(follow_redirects=True, timeout=25,
                          headers={"User-Agent": "AAA-136-probe/0"}) as c:
            r = c.get(url)
        chain = [resp.status_code for resp in r.history] + [r.status_code]
        final = str(r.url)
        direct = (len(r.history) == 0 and r.status_code == 200)
        canon = None
        if r.status_code == 200 and r.text:
            node = HTMLParser(r.text).css_first('link[rel="canonical"]')
            canon = node.attributes.get("href") if node else None
        return chain, final, direct, canon
    except Exception as e:
        return [f"ERR:{type(e).__name__}"], None, False, None

async def quoted_indexed(variant_url: str, location: str, lang: str):
    q = f'"{variant_url}"'  # QUOTED exact-URL phrase search
    s = await _run_serp(q, location, lang, depth=10)
    cost = float(s.get("cost_usd") or 0.0)
    if s.get("error"):
        return {"query": q, "first_url": None, "match": "unknown", "position": None, "cost": 0.0, "err": s.get("error")}
    org = s.get("organic_results") or []
    first = org[0] if org else None
    first_url = first.get("url") if first else None
    match = bool(first_url and norm(first_url) == norm(variant_url))
    return {"query": q, "first_url": first_url,
            "match": match, "position": (first.get("position") if first else None),
            "n_organic": len(org), "cost": cost}

async def probe_site(domain: str, lang: str, location: str):
    print(f"\n{'#'*72}\n# {domain}  (lang={lang}, location={location})\n{'#'*72}")
    rows = {}; canons = []
    total = 0.0
    for v in variants(domain):
        chain, final, direct, canon = resolve(v)
        qi = await quoted_indexed(v, location, lang)
        total += qi["cost"]
        if canon: canons.append(canon)
        rows[v] = dict(chain=chain, final=final, direct=direct, qi=qi)
        print(f"\n  VARIANT {v}")
        print(f"    redirect chain: {chain}  final={final}  direct_live_200={direct}")
        print(f"    quoted SERP {qi['query']}: first_result={qi['first_url']}")
        print(f"      normalize-equals variant? {qi['match']}  position={qi['position']}  n_organic={qi.get('n_organic')}")
    canon_val = next((c for c in canons if c), None)
    live = [v for v,d in rows.items() if d["direct"]]
    indexed = [v for v,d in rows.items() if d["qi"]["match"] is True]
    print(f"\n  --- AGGREGATE {domain} ---")
    print(f"    rel=canonical: {canon_val}")
    print(f"    direct-live(200) variants: {live}")
    print(f"    indexed-via-quoted variants: {indexed}")
    print(f"    duplication signal (>1 distinct variant indexed): {len(indexed) > 1}")
    cm = (canon_val and indexed and norm(canon_val) not in {norm(v) for v in indexed})
    print(f"    canonical-mismatch (rel=canonical not among indexed): {bool(cm)}")
    print(f"    site cost: ${total:.6f}")
    return total

async def main():
    t = 0.0
    t += await probe_site("agrobook.hu", "hu", "Hungary")
    t += await probe_site("kk.coach", "en", "United States")
    # wikipedia deep-article quoted-exact control
    print(f"\n{'#'*72}\n# CONTROL: wikipedia deep article (quoted exact)\n{'#'*72}")
    qi = await quoted_indexed("https://en.wikipedia.org/wiki/Search_engine_optimization", "United States", "en")
    t += qi["cost"]
    print(f"  quoted {qi['query']}: first={qi['first_url']} match={qi['match']} pos={qi['position']} cost=${qi['cost']}")
    print(f"\nTOTAL PROBE COST: ${t:.6f}")

asyncio.run(main())
