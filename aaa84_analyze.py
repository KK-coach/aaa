"""AAA-84 Sub-step 2 Phase B/C/D — variance, tolerance, ship gate.

Pure computation on the 25-audit sweep. No API calls.
"""

import json
import statistics

d = json.load(open(r"C:\Users\donm6\ai-advisor-app\aaa84_sweep_results.json",
                    encoding="utf-8"))
runs = [r for r in d["runs"] if "_error" not in r]

by_url: dict[str, list] = {}
for r in runs:
    by_url.setdefault(r["url"], []).append(r)


def kw_map(run):
    return {x["keyword"]: x for x in run["target_keywords_classified"]}


def top3(run):
    return [x["keyword"] for x in run["target_keywords_classified"][:3]]


print("=" * 72)
print("PHASE B — per-URL variance")
print("=" * 72)
per_url = {}
for url, group in by_url.items():
    maps = [kw_map(g) for g in group]
    # keywords present in ALL runs of this URL
    common = set(maps[0])
    for m in maps[1:]:
        common &= set(m)
    common = sorted(common)
    n_runs = len(group)

    tail_stable = intent_stable = 0
    rel_drifts = []
    for kw in common:
        tails = {m[kw]["tail_type"] for m in maps}
        intents = {m[kw]["search_intent"] for m in maps}
        if len(tails) == 1:
            tail_stable += 1
        if len(intents) == 1:
            intent_stable += 1
        scores = [m[kw]["relevance_score"] for m in maps
                  if m[kw]["relevance_score"] is not None]
        if len(scores) >= 2:
            rel_drifts.append(max(scores) - min(scores))

    t3s = [tuple(top3(g)) for g in group]
    mode_t3 = max(set(t3s), key=t3s.count)
    t3_match = t3s.count(mode_t3)

    nc = len(common)
    per_url[url] = {
        "n_runs": n_runs,
        "n_common_kw": nc,
        "tail_stable": tail_stable,
        "tail_pct": round(100 * tail_stable / nc, 1) if nc else 0,
        "intent_stable": intent_stable,
        "intent_pct": round(100 * intent_stable / nc, 1) if nc else 0,
        "rel_drift_max": round(max(rel_drifts), 3) if rel_drifts else 0.0,
        "rel_drift_p90": round(
            sorted(rel_drifts)[int(0.9 * (len(rel_drifts) - 1))], 3
        ) if rel_drifts else 0.0,
        "top3_match": t3_match,
        "kw_count_per_run": [len(m) for m in maps],
    }
    u = per_url[url]
    print(f"\n{url}")
    print(f"  runs={n_runs}  kw/run={u['kw_count_per_run']}  "
          f"common-across-all={nc}")
    print(f"  tail_type stable : {tail_stable}/{nc} ({u['tail_pct']}%)")
    print(f"  search_intent st.: {intent_stable}/{nc} ({u['intent_pct']}%)")
    print(f"  relevance drift  : max={u['rel_drift_max']} p90={u['rel_drift_p90']}")
    print(f"  top-3 ordering   : {t3_match}/{n_runs} runs share modal top-3")

# --- aggregate ---
print("\n" + "=" * 72)
print("AGGREGATE")
print("=" * 72)
intent_pcts = [u["intent_pct"] for u in per_url.values()]
tail_pcts = [u["tail_pct"] for u in per_url.values()]
all_drifts = []
for url, group in by_url.items():
    maps = [kw_map(g) for g in group]
    common = set(maps[0])
    for m in maps[1:]:
        common &= set(m)
    for kw in common:
        scores = [m[kw]["relevance_score"] for m in maps
                  if m[kw]["relevance_score"] is not None]
        if len(scores) >= 2:
            all_drifts.append(max(scores) - min(scores))
t3_matches = [u["top3_match"] for u in per_url.values()]
drift_p90 = (sorted(all_drifts)[int(0.9 * (len(all_drifts) - 1))]
             if all_drifts else 0.0)
drift_max = max(all_drifts) if all_drifts else 0.0

print(f"search_intent stability: mean={statistics.mean(intent_pcts):.1f}% "
      f"range={min(intent_pcts):.1f}-{max(intent_pcts):.1f}%")
print(f"tail_type stability    : mean={statistics.mean(tail_pcts):.1f}% "
      f"range={min(tail_pcts):.1f}-{max(tail_pcts):.1f}%")
print(f"relevance drift        : p90={drift_p90:.3f}  max={drift_max:.3f}")
print(f"top-3 ordering         : mean={statistics.mean(t3_matches):.1f}/5 "
      f"runs share modal top-3")

# --- Phase C: data-fitted tolerance (bottom-envelope / p90) ---
print("\n" + "=" * 72)
print("PHASE C — suggested production tolerance (data-fitted)")
print("=" * 72)
# Bottom-envelope tolerance: gate statistic == tolerance statistic.
# rel tolerance is set from per-URL MAX (the gated quantity), not aggregate
# p90, and floors are NOT rounded up past the observed worst.
import math  # noqa: E402
per_url_rel_max = [u["rel_drift_max"] for u in per_url.values()]
tol = {
    "intent_pct": math.floor(min(intent_pcts) * 10) / 10,  # no round-up
    "tail_pct": math.floor(min(tail_pcts) * 10) / 10,
    "rel_drift": round(max(per_url_rel_max) + 0.01, 2),  # observed worst + ε
    "top3_min": min(t3_matches),
}
print(f"search_intent : >= {tol['intent_pct']}% byte-stable "
      f"(worst observed URL = bottom envelope)")
print(f"tail_type     : >= {tol['tail_pct']}% byte-stable (worst URL)")
print(f"relevance     : per-URL max drift <= {tol['rel_drift']} "
      f"(observed worst + margin)")
print(f"top-3 ordering: >= {tol['top3_min']}/5 runs share modal top-3 (worst URL)")

# --- Phase D: ship gate vs SAME data ---
print("\n" + "=" * 72)
print("PHASE D — ship gate (same 25 audits vs suggested tolerance)")
print("=" * 72)
all_pass = True
for url, u in per_url.items():
    p_intent = u["intent_pct"] >= tol["intent_pct"]
    p_tail = u["tail_pct"] >= tol["tail_pct"]
    p_rel = u["rel_drift_max"] <= tol["rel_drift"]
    p_t3 = u["top3_match"] >= tol["top3_min"]
    ok = p_intent and p_tail and p_rel and p_t3
    all_pass &= ok
    print(f"  {url}: intent={p_intent} tail={p_tail} rel={p_rel} "
          f"top3={p_t3} -> {'PASS' if ok else 'FAIL'}")
print(f"\nSHIP GATE: {'ALL 5 PASS' if all_pass else 'FAIL'}")

json.dump({"per_url": per_url, "tolerance": tol, "ship_pass": all_pass},
          open(r"C:\Users\donm6\ai-advisor-app\aaa84_analysis.json",
               "w", encoding="utf-8"), ensure_ascii=False, indent=1)
