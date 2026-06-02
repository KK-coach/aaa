"""AAA-124 Sub-step 0 — C4 vercel.com phase2_html_measurements live-compute.

vercel.com archive entry 18c133f2 is pre-AAA-123-ship: phase2 field is None.
Strategy (β): live-fetch raw HTML and run page_analysis.phase2_html standalone
to populate the Block 10 Réteg 1 ground-truth for the C4 input payload.
"""
import asyncio
import json
import time
import httpx
from page_analysis.phase2_html import run_phase2_measurements


async def main():
    url = "https://vercel.com"
    t0 = time.perf_counter()
    with httpx.Client(follow_redirects=True, timeout=30,
                      headers={"User-Agent": "AAA-124-S0-c4/0"}) as c:
        r = c.get(url)
    fetch_s = round(time.perf_counter() - t0, 3)
    hdr_b = sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) + 4
                for k, v in r.headers.items())
    body = r.text
    body_b = len(r.content)
    print(f"vercel.com fetch: {fetch_s}s body={body_b}B headers~{hdr_b}B")

    p2 = await run_phase2_measurements(
        {"_raw_html_transient": body, "response_headers_bytes_estimate": hdr_b},
        page_type="homepage", audit_language="en",
    )
    out = {
        "url": url,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "body_bytes": body_b,
        "header_bytes_est": hdr_b,
        "phase2_html_measurements": p2,
    }
    with open("aaa124_s0_c4_vercel_phase2.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"wrote aaa124_s0_c4_vercel_phase2.json")
    print(f"  heading_tree_count: {p2['semantic_structure']['heading_tree_count']}")
    print(f"  raw_html_bytes: {p2['google_2mb_cutoff']['raw_html_bytes_uncompressed']}")
    print(f"  exceeds_2mb: {p2['google_2mb_cutoff']['exceeds_2mb_cutoff']}")
    print(f"  is_csr_likely: {p2['rendering_mode']['is_csr_likely']}")
    print(f"  spa_frameworks: {p2['rendering_mode']['spa_frameworks_detected']}")


asyncio.run(main())
