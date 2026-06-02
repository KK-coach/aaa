"""AAA-95 Sub-step 2.2 — coverage stability analysis. Pure computation."""

import json
import statistics
from collections import Counter, defaultdict

d = json.load(open(r"C:\Users\donm6\ai-advisor-app\aaa95_s22_sweep_results.json",
                    encoding="utf-8"))
res = [r for r in d["results"] if "_error" not in r]
fails = [r for r in d["results"] if "_error" in r]

# --- 1. meta ---
flakes = [r for r in res if not r["eeat"] or r["tk_keys"] == 0]
total_entries = sum(len(r["enriched"]) for r in res)
cov_errors = sum(1 for r in res for e in r["enriched"] if e["cov_error"])
cov_costs = [r["cov_cost"] or 0.0 for r in res]
cov_sorted = sorted(cov_costs)
durs = [r["duration_s"] or 0.0 for r in res if r.get("duration_s")]
print("=== 1. SWEEP META ===")
print(f"completed {len(res)} / failed {len(fails)} / wall {d['wall_s']}s")
print(f"thin-crawl flakes: {len(flakes)} "
      f"({[(r['url'].split('/')[-1] or r['url'], r['run']) for r in flakes]})")
print(f"total fan_out_enriched entries: {total_entries}")
print(f"coverage classification errors: {cov_errors}")
print(f"coverage cost: mean=${statistics.mean(cov_costs):.5f} "
      f"median=${statistics.median(cov_costs):.5f} "
      f"p90=${cov_sorted[int(0.9*(len(cov_sorted)-1))]:.5f} "
      f"max=${max(cov_costs):.5f} total=${sum(cov_costs):.5f}")
env = [(r['audit_cost'] or 0) + (r['enrich_cost'] or 0) + (r['cov_cost'] or 0)
       for r in res]
print(f"per-audit cost envelope (audit+enrich+coverage) mean=${statistics.mean(env):.5f}")
if durs:
    print(f"per-audit duration mean={statistics.mean(durs):.0f}s")

# --- 2. coverage tier frequency ---
print("\n=== 2. COVERAGE TIER FREQUENCY ===")
freq = Counter()
by_url_src = defaultdict(Counter)
for r in res:
    for e in r["enriched"]:
        c = e["coverage"]
        freq[c] += 1
        by_url_src[(r["url"], e["source"])][c] += 1
tot = sum(freq.values()) or 1
for tier in ("covered", "partial", "missing", "off_topic", "n_a", None):
    print(f"  {str(tier):10s} {freq.get(tier,0):4d}  {100*freq.get(tier,0)/tot:.1f}%")

# --- 3 + 4. upstream variability + coverage byte-stability ---
print("\n=== 3+4. PER URL x SOURCE ===")
print("| url | source | runs | uniq_q | shared_q | upstream_stab | "
      "coverage_consistency |")
by_url = defaultdict(list)
for r in res:
    by_url[r["url"]].append(r)
agg_cov_ok = agg_cov_tot = 0
disagreements = []
for url, group in by_url.items():
    for src in ("google_grounded", "chatgpt"):
        qv = defaultdict(list)   # query -> [coverage per run]
        qruns = defaultdict(int)
        for r in group:
            for e in r["enriched"]:
                if e["source"] == src:
                    qv[e["query"]].append(e["coverage"])
                    qruns[e["query"]] += 1
        uniq = sum(1 for q, runs in qruns.items() if runs == 1)
        shared = [q for q, runs in qruns.items() if runs >= 2]
        # upstream stability: shared / distinct
        distinct = len(qv)
        up_stab = (100 * len(shared) / distinct) if distinct else 0
        cov_ok = sum(1 for q in shared if len(set(qv[q])) == 1)
        agg_cov_ok += cov_ok
        agg_cov_tot += len(shared)
        for q in shared:
            if len(set(qv[q])) > 1:
                disagreements.append((url, src, q, qv[q]))
        cc = (f"{100*cov_ok/len(shared):.0f}% ({cov_ok}/{len(shared)})"
              if shared else "n/a")
        print(f"| {url.split('//')[-1][:24]} | {src} | {len(group)} | "
              f"{uniq} | {len(shared)} | {up_stab:.0f}% | {cc} |")

print(f"\nAGGREGATE coverage byte-stability: {agg_cov_ok}/{agg_cov_tot} = "
      f"{100*agg_cov_ok/max(1,agg_cov_tot):.1f}%")

# --- 5. disagreements ---
print("\n=== 5. COVERAGE DISAGREEMENTS ===")
for url, src, q, covs in disagreements:
    print(f"  {url.split('//')[-1][:22]} | {src} | {q[:46]!r} -> {covs}")
if not disagreements:
    print("  (none)")

json.dump({"meta": {"completed": len(res), "failed": len(fails),
                    "flakes": len(flakes), "cov_errors": cov_errors,
                    "total_entries": total_entries,
                    "cov_cost_total": round(sum(cov_costs), 5)},
           "tier_freq": dict(freq),
           "coverage_byte_stability_pct": round(
               100*agg_cov_ok/max(1, agg_cov_tot), 1),
           "shared_q_total": agg_cov_tot,
           "disagreements": len(disagreements)},
          open(r"C:\Users\donm6\ai-advisor-app\aaa95_substep_22_aggregate.json",
               "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved aaa95_substep_22_aggregate.json")
