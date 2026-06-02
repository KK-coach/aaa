"""AAA-42 Sub-step 2 — ship-gate analysis on the sweep results."""

import json
import time
from collections import defaultdict

import httpx

from memory.firestore_archive import read_audit_sync
from page_analysis.agent_friendly import measure_agent_friendliness

d = json.load(open(r"C:\Users\donm6\ai-advisor-app\aaa42_s2_results.json",
                    encoding="utf-8"))
res = [r for r in d["results"] if "_error" not in r]
fails = [r for r in d["results"] if "_error" in r]

print(f"=== (A) SWEEP SUCCESS ===")
print(f"n_done={d['n_done']} n_fail={d['n_fail']} wall={d['wall_s']}s")
by_url = defaultdict(list)
for r in res:
    by_url[r["url"]].append(r)
for url, group in by_url.items():
    print(f"  {url:42s} runs={len(group)}/5")
for r in fails:
    print(f"  FAIL {r['url']} run{r['run']}: {r['_error'][:120]}")

# Flatten an agent_friendly dict into comparable scalar/tuple cells.
def flatten(afm: dict) -> dict:
    if not afm:
        return {}
    return {
        "semantic_html.button_count": afm["semantic_html"]["button_count"],
        "semantic_html.div_onclick_count": afm["semantic_html"]["div_onclick_count"],
        "semantic_html.has_div_onclick_antipattern": afm["semantic_html"]["has_div_onclick_antipattern"],
        "landmarks.count": afm["landmarks"]["count"],
        "landmarks.present": tuple(afm["landmarks"]["present"]),
        "heading.h1_count": afm["heading"]["h1_count"],
        "heading.total_headings": afm["heading"]["total_headings"],
        "heading.level_skips": afm["heading"]["level_skips"],
        "forms.input_count": afm["forms"]["input_count"],
        "forms.label_coverage": afm["forms"]["label_coverage"],
        "images.img_count": afm["images"]["img_count"],
        "images.alt_count": afm["images"]["alt_count"],
        "aria.interactive_count": afm["aria"]["interactive_count"],
        "aria.with_aria_count": afm["aria"]["with_aria_count"],
        "schema_actions": tuple(afm.get("schema_actions") or []),
        "_error": afm.get("_error"),
    }


print("\n=== (B) PER-URL × PER-DIMENSION STABILITY ===")
drift_records = []
for url, group in by_url.items():
    group = sorted(group, key=lambda r: r["run"])
    flats = [flatten(r["agent_friendly"]) for r in group]
    dims = list(flats[0]) if flats else []
    print(f"\n## {url}  ({len(group)} runs)")
    print(f"| Dimension | " + " | ".join(f"R{r['run']}" for r in group) + " | Stable? |")
    for dim in dims:
        vals = [f.get(dim) for f in flats]
        stable = len(set(vals)) == 1
        if not stable:
            drift_records.append((url, dim, vals))
        flag = "✅" if stable else "❌"
        cells = " | ".join(str(v)[:24] for v in vals)
        print(f"| {dim} | {cells} | {flag} |")

print("\n=== (C) render_method_used UNIFORMITY ===")
method_drift = []
for url, group in by_url.items():
    methods = [r["render_method_used"] for r in group]
    uniform = len(set(methods)) == 1
    print(f"  {url:42s} -> {dict((m, methods.count(m)) for m in set(methods))} "
          f"{'✅' if uniform else '❌'}")
    if not uniform:
        method_drift.append((url, methods))

# (D) Latency profile — standalone, post-hoc
print("\n=== (D) LATENCY PROFILE (standalone, post-hoc) ===")
H = {"User-Agent": "Mozilla/5.0 (compatible; AAA-42-latency/1.0)"}
lat_per_url = {}
with httpx.Client(headers=H, timeout=30.0, follow_redirects=True) as c:
    for url in by_url:
        try:
            r = c.get(url)
            r.raise_for_status()
            lats = []
            for _ in range(5):
                t0 = time.perf_counter()
                measure_agent_friendliness(r.text)
                lats.append((time.perf_counter() - t0) * 1000)
            lat_per_url[url] = lats
            print(f"  {url:42s} min={min(lats):.1f}ms max={max(lats):.1f}ms "
                  f"mean={sum(lats)/len(lats):.1f}ms")
        except Exception as e:  # noqa: BLE001
            print(f"  {url:42s} LATENCY-FETCH-FAIL: {e}")

# (E) _raw_html_transient leak audit on archived docs
print("\n=== (E) _raw_html_transient LEAK AUDIT (25 archives × 2 fields) ===")
total_leaks = 0
for r in res:
    aid = r["audit_id"]
    if not aid:
        continue
    arch = read_audit_sync(aid)
    if not arch:
        continue
    ao = arch.get("audit_output") or {}
    cr_leak = "_raw_html_transient" in (ao.get("crawl") or {})
    rc_leak = "_raw_html_transient" in (ao.get("rendered_crawl") or {})
    if cr_leak or rc_leak:
        total_leaks += 1
        print(f"  LEAK {r['url']} run{r['run']}: "
              f"crawl={cr_leak} rendered={rc_leak}")
print(f"  total leaks: {total_leaks} / {len(res)}")

# (G) Summary
print("\n=== SHIP GATE SUMMARY ===")
print(f"  drift records: {len(drift_records)}")
for url, dim, vals in drift_records:
    print(f"    {url} {dim}: {vals}")
print(f"  method drift: {len(method_drift)}")
print(f"  leaks: {total_leaks}")
print(f"  audits failed: {len(fails)}")
