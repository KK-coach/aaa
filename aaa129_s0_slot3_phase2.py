"""AAA-129 S0 — slot3 aboutyou.hu/c/noi phase2 live-compute (pre-AAA-123 archive)."""
import asyncio, json, time
import httpx
from page_analysis.phase2_html import run_phase2_measurements

async def main():
    url = "https://www.aboutyou.hu/c/noi"
    with httpx.Client(follow_redirects=True, timeout=30,
                      headers={"User-Agent": "AAA-129-S0-slot3/0"}) as c:
        r = c.get(url)
    hdr_b = sum(len(k.encode())+len(v.encode())+4 for k,v in r.headers.items())
    p2 = await run_phase2_measurements(
        {"_raw_html_transient": r.text, "response_headers_bytes_estimate": hdr_b},
        page_type="category_page", audit_language="hu")
    json.dump({"url": url, "phase2_html_measurements": p2},
              open("aaa129_s0_slot3_phase2.json","w",encoding="utf-8"),
              indent=2, ensure_ascii=False)
    ss = p2["semantic_structure"]; rm = p2["rendering_mode"]
    print(f"aboutyou/c/noi: heading_tree={ss['heading_tree_count']} "
          f"csr={rm['is_csr_likely']} spa={rm['spa_frameworks_detected']} "
          f"raw_bytes={p2['google_2mb_cutoff']['raw_html_bytes_uncompressed']}")

asyncio.run(main())
