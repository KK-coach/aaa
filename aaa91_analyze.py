"""AAA-91 Sub-step 2 Phase B/C — L2 variance analysis. Pure computation."""

import json
import statistics
from collections import Counter, defaultdict

d = json.load(open(r"C:\Users\donm6\ai-advisor-app\aaa91_sweep_results.json",
                    encoding="utf-8"))
runs = [r for r in d["results"] if "_error" not in r]

INDUSTRY = {
    "https://www.agrobook.hu": "agri e-commerce",
    "https://kk.coach": "consulting",
    "https://www.aboutyou.hu": "fashion e-commerce",
    "https://www.taxually.com": "B2B SaaS",
    "https://vercel.com/products/vercel-platform": "dev platform",
}


def tier(pct: float) -> str:
    if pct > 95:
        return "TRUSTWORTHY"
    if pct >= 75:
        return "MOSTLY STABLE"
    if pct >= 50:
        return "BEST-EFFORT"
    return "DIRECTIONAL"


by_url = defaultdict(list)
for r in runs:
    by_url[r["url"]].append(r)

print(f"sweep: {len(runs)} ok audits, kw_cost ${d.get('total_kw_cost')}")
print("=" * 78)

per_url = {}
per_l1_l2 = defaultdict(lambda: [0, 0])  # l1 -> [l2_stable, total]
for url, group in by_url.items():
    maps = [{c["keyword"]: (c["l1"], c["l2"]) for c in g["classified"]}
            for g in group]
    common = set(maps[0])
    for m in maps[1:]:
        common &= set(m)
    common = sorted(common)

    l1_stable = l2_raw = 0
    l2_cond_vals = []
    for kw in common:
        l1s = [m[kw][0] for m in maps]
        l2s = [m[kw][1] for m in maps]
        if len(set(l1s)) == 1:
            l1_stable += 1
        if len(set(l2s)) == 1:
            l2_raw += 1
        # conditional: within the modal-L1 subset, is L2 constant?
        modal_l1 = Counter(l1s).most_common(1)[0][0]
        sub_l2 = [l2s[i] for i in range(len(l1s)) if l1s[i] == modal_l1]
        if len(sub_l2) >= 2:
            l2_cond_vals.append(1 if len(set(sub_l2)) == 1 else 0)
            per_l1_l2[modal_l1][1] += 1
            if len(set(sub_l2)) == 1:
                per_l1_l2[modal_l1][0] += 1

    nc = len(common) or 1
    per_url[url] = {
        "industry": INDUSTRY.get(url, "?"),
        "runs": len(group),
        "n_kw": len(common),
        "l1_pct": round(100 * l1_stable / nc, 1),
        "l2_raw_pct": round(100 * l2_raw / nc, 1),
        "l2_cond_pct": round(
            100 * sum(l2_cond_vals) / len(l2_cond_vals), 1
        ) if l2_cond_vals else None,
    }

print("| URL | Industry | runs | n_kw | L1 byte-stab | L2 raw | "
      "L2 conditional |")
print("|---|---|---|---|---|---|---|")
for url, u in per_url.items():
    print(f"| {url.split('//')[-1][:28]} | {u['industry']} | {u['runs']} "
          f"| {u['n_kw']} | {u['l1_pct']}% | {u['l2_raw_pct']}% "
          f"| {u['l2_cond_pct']}% |")

l1s = [u["l1_pct"] for u in per_url.values()]
l2raws = [u["l2_raw_pct"] for u in per_url.values()]
l2conds = [u["l2_cond_pct"] for u in per_url.values()
           if u["l2_cond_pct"] is not None]
print("\nAGGREGATE")
print(f"  L1 byte-stability : mean {statistics.mean(l1s):.1f}% "
      f"range {min(l1s)}-{max(l1s)}%")
print(f"  L2 raw            : mean {statistics.mean(l2raws):.1f}% "
      f"range {min(l2raws)}-{max(l2raws)}%")
if l2conds:
    m = statistics.mean(l2conds)
    print(f"  L2 CONDITIONAL    : mean {m:.1f}% "
          f"range {min(l2conds)}-{max(l2conds)}%  -> tier: {tier(m)}")

print("\nPER-L1 L2 conditional stability (the session-11 insight):")
for l1, (st, tot) in sorted(per_l1_l2.items()):
    if tot:
        print(f"  {l1:15s} L2-stable {st}/{tot} = "
              f"{100 * st / tot:.0f}%")
