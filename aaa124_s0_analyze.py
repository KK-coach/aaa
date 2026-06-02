"""AAA-124 Sub-step 0 — Post-probe analysis: (D.1) + (D.2) + hallucination
audit + variant comparison.
"""
import asyncio
import json
import statistics
from collections import defaultdict
from pathlib import Path

from google.cloud import firestore_v1 as firestore


# Aspects + indices (kept identical to probe script)
ASPECTS = ["macro_structure", "heading_semantics", "above_the_fold",
           "micro_semantics", "inline_link_semantics", "forms_conversion_points",
           "schema_entity"]
INDICES = ["technical_semantic_index", "ux_conversion_index",
            "ai_geo_readability_index"]

# (D.1) expected JUSTIFIED-weight patterns (cross-canary)
D1_PATTERNS = [
    ("schema_entity",   "C1", "C3", "ProductPage > BlogPost (schema_org page-type-specific)"),
    ("forms_conversion_points", "C4", "C1", "LandingPage b2b_saas > ProductPage ecommerce (form quality for b2b funnel)"),
    ("above_the_fold",  "C2", "C3", "ServicePage B2B > BlogPost B2C (LocalBusiness+NAP locality, NOTE: C2 lost local axis — degraded test)"),
    ("schema_entity",   "C2", "C3", "ServicePage B2B > BlogPost B2C (E-E-A-T entity-density audience proxy)"),
]

# (D.2) sub-dimensions that SHOULD be uniformly-weighted across all 4 canaries
# (NEM justified per AAA-124 comment 12176)
D2_UNIFORM_ASPECTS = ["heading_semantics", "micro_semantics",
                      "inline_link_semantics"]


# Canonical aspect→owning-index mapping for V2 extraction
# (aspect appears in multiple indices' per_aspect_evaluations; the owning
# index is the one whose composite this aspect contributes to per the AAA-124
# spec — see INDEX_TO_ASPECTS at top of probe file).
_ASPECT_OWNING_INDEX = {
    "macro_structure": "technical_semantic_index",
    "heading_semantics": "technical_semantic_index",   # also in ai_geo, but technical is primary
    "micro_semantics": "technical_semantic_index",     # also in ai_geo
    "schema_entity": "technical_semantic_index",       # also in ai_geo
    "above_the_fold": "ux_conversion_index",
    "inline_link_semantics": "ux_conversion_index",
    "forms_conversion_points": "ux_conversion_index",
}


def extract_aspect_evals_per_canary_per_variant(out: dict) -> dict:
    """Returns: {slot: {variant: {aspect: aspect_eval_dict_or_None}}}.

    For V2, an aspect is extracted from its OWNING index's
    per_aspect_evaluations — NOT the first-seen, because each V2 index call
    emits all 7 aspects, but aspects not owned by that index get weight=0.0
    with "not in this index" justification (structural artifact, not real
    weighting judgment)."""
    res = defaultdict(lambda: defaultdict(dict))
    for slot, r in (out.get("results") or {}).items():
        runs = r.get("runs") or {}
        # V1 — each aspect is its own call
        for asp in ASPECTS:
            ev = ((runs.get("V1") or {}).get(asp) or {}).get("parsed")
            res[slot]["V1"][asp] = ev
        # V2 — extract from owning index
        for asp in ASPECTS:
            owning = _ASPECT_OWNING_INDEX[asp]
            inner = ((runs.get("V2") or {}).get(owning) or {}).get("parsed") or {}
            ev = (inner.get("per_aspect_evaluations") or {}).get(asp)
            res[slot]["V2"][asp] = ev
        # V3 — single call has per_aspect_evaluations
        v3_parsed = (runs.get("V3") or {}).get("parsed") or {}
        for asp, ev in (v3_parsed.get("per_aspect_evaluations") or {}).items():
            res[slot]["V3"][asp] = ev
    return res


def detective_recheck(out: dict) -> dict:
    """Cross-check structured_claims against ground truth, with corrected GT.
    Returns: {variant: {claim_count, contradict_count, null_count}}"""
    summary = {v: {"claim_count": 0, "contradict_count": 0,
                   "null_count": 0, "contradictions": []}
               for v in ("V1", "V2", "V3")}
    pair_keys = [
        ("h1_count_claimed", "h1_count"),
        ("alt_coverage_pct_claimed", "alt_coverage_pct"),
        ("has_main_claimed", "has_main"),
        ("schema_actions_count_claimed", "schema_actions_count"),
        ("exceeds_2mb_claimed", "exceeds_2mb"),
    ]
    for slot, r in (out.get("results") or {}).items():
        gt = r.get("ground_truth") or {}
        runs = r.get("runs") or {}

        # V1 collect
        v1 = runs.get("V1") or {}
        for asp, call in v1.items():
            parsed = call.get("parsed") or {}
            claims = parsed.get("structured_claims") or {}
            for ck, gk in pair_keys:
                c = claims.get(ck)
                g = gt.get(gk)
                if c is None:
                    summary["V1"]["null_count"] += 1
                    continue
                summary["V1"]["claim_count"] += 1
                if g is None:
                    continue
                if isinstance(c, (int, float)) and isinstance(g, (int, float)):
                    tol = max(1, abs(g) * 0.10)
                    if abs(c - g) > tol:
                        summary["V1"]["contradict_count"] += 1
                        summary["V1"]["contradictions"].append(
                            f"{slot}/V1/{asp} {ck}={c} vs gt.{gk}={g}")
                elif c != g:
                    summary["V1"]["contradict_count"] += 1
                    summary["V1"]["contradictions"].append(
                        f"{slot}/V1/{asp} {ck}={c!r} vs gt.{gk}={g!r}")

        # V2 collect (per index)
        v2 = runs.get("V2") or {}
        for idx, call in v2.items():
            parsed = call.get("parsed") or {}
            for asp, ev in (parsed.get("per_aspect_evaluations") or {}).items():
                claims = (ev or {}).get("structured_claims") or {}
                for ck, gk in pair_keys:
                    c = claims.get(ck)
                    g = gt.get(gk)
                    if c is None:
                        summary["V2"]["null_count"] += 1
                        continue
                    summary["V2"]["claim_count"] += 1
                    if g is None:
                        continue
                    if isinstance(c, (int, float)) and isinstance(g, (int, float)):
                        tol = max(1, abs(g) * 0.10)
                        if abs(c - g) > tol:
                            summary["V2"]["contradict_count"] += 1
                            summary["V2"]["contradictions"].append(
                                f"{slot}/V2/{idx}/{asp} {ck}={c} vs gt.{gk}={g}")
                    elif c != g:
                        summary["V2"]["contradict_count"] += 1
                        summary["V2"]["contradictions"].append(
                            f"{slot}/V2/{idx}/{asp} {ck}={c!r} vs gt.{gk}={g!r}")

        # V3 collect
        v3 = (runs.get("V3") or {}).get("parsed") or {}
        for asp, ev in (v3.get("per_aspect_evaluations") or {}).items():
            claims = (ev or {}).get("structured_claims") or {}
            for ck, gk in pair_keys:
                c = claims.get(ck)
                g = gt.get(gk)
                if c is None:
                    summary["V3"]["null_count"] += 1
                    continue
                summary["V3"]["claim_count"] += 1
                if g is None:
                    continue
                if isinstance(c, (int, float)) and isinstance(g, (int, float)):
                    tol = max(1, abs(g) * 0.10)
                    if abs(c - g) > tol:
                        summary["V3"]["contradict_count"] += 1
                        summary["V3"]["contradictions"].append(
                            f"{slot}/V3/{asp} {ck}={c} vs gt.{gk}={g}")
                elif c != g:
                    summary["V3"]["contradict_count"] += 1
                    summary["V3"]["contradictions"].append(
                        f"{slot}/V3/{asp} {ck}={c!r} vs gt.{gk}={g!r}")

    return summary


def cost_latency_table(out: dict) -> list[dict]:
    """Per canary × variant: total cost, total latency, structural completeness."""
    rows = []
    for slot, r in (out.get("results") or {}).items():
        runs = r.get("runs") or {}
        # V1
        v1 = runs.get("V1") or {}
        cost1 = sum((c.get("cost_usd") or 0) for c in v1.values())
        lat1 = sum((c.get("latency_s") or 0) for c in v1.values())
        # 7 aspects expected
        v1_complete = sum(1 for c in v1.values() if c.get("ok")) == 7

        # V2
        v2 = runs.get("V2") or {}
        cost2 = sum((c.get("cost_usd") or 0) for c in v2.values())
        lat2 = sum((c.get("latency_s") or 0) for c in v2.values())
        v2_complete = sum(1 for c in v2.values() if c.get("ok")) == 3
        # Aspect coverage from V2 (deduplicated across indices)
        v2_aspects_seen = set()
        for idx_call in v2.values():
            parsed = idx_call.get("parsed") or {}
            for asp in (parsed.get("per_aspect_evaluations") or {}).keys():
                v2_aspects_seen.add(asp)

        # V3
        v3 = runs.get("V3") or {}
        cost3 = v3.get("cost_usd") or 0
        lat3 = v3.get("latency_s") or 0
        v3_complete = v3.get("ok", False)
        v3_parsed = v3.get("parsed") or {}
        v3_aspects_seen = set((v3_parsed.get("per_aspect_evaluations") or {}).keys())
        v3_has_3_indices = all(idx in v3_parsed for idx in INDICES)

        rows.append({
            "slot": slot, "url": r.get("url"),
            "page_type": r.get("page_type"), "bm": r.get("business_model"),
            "loc": r.get("locality"), "aud": r.get("audience"),
            "V1_cost": cost1, "V1_lat": lat1, "V1_complete_7of7": v1_complete,
            "V2_cost": cost2, "V2_lat": lat2, "V2_complete_3of3": v2_complete,
            "V2_aspect_coverage": len(v2_aspects_seen),
            "V3_cost": cost3, "V3_lat": lat3, "V3_complete": v3_complete,
            "V3_aspect_coverage": len(v3_aspects_seen),
            "V3_has_3_indices": v3_has_3_indices,
        })
    return rows


def d1_check(per: dict) -> list[dict]:
    """For each expected JUSTIFIED pattern, compute cross-canary weight diff."""
    res = []
    for asp, high_slot, low_slot, descr in D1_PATTERNS:
        out_row = {"sub_dim": asp, "high": high_slot, "low": low_slot,
                   "descr": descr, "per_variant": {}}
        for v in ("V1", "V2", "V3"):
            high_ev = (per.get(high_slot) or {}).get(v, {}).get(asp)
            low_ev = (per.get(low_slot) or {}).get(v, {}).get(asp)
            high_w = (high_ev or {}).get("weight_in_context_0_1")
            low_w = (low_ev or {}).get("weight_in_context_0_1")
            if high_w is None or low_w is None:
                verdict = "MISSING_DATA"
                delta = None
            else:
                delta = round(high_w - low_w, 3)
                verdict = "PASS" if delta > 0 else "FAIL"
            out_row["per_variant"][v] = {
                "high_weight": high_w, "low_weight": low_w,
                "delta": delta, "verdict": verdict,
            }
        res.append(out_row)
    return res


def d2_check(per: dict) -> list[dict]:
    """For each NEM-justified sub-dim, weights SHOULD be uniform across slots.
    Compute stdev — high stdev = halt-trigger."""
    res = []
    for asp in D2_UNIFORM_ASPECTS:
        out_row = {"sub_dim": asp, "per_variant": {}}
        for v in ("V1", "V2", "V3"):
            weights = {}
            for slot in ("C1", "C2", "C3", "C4"):
                ev = (per.get(slot) or {}).get(v, {}).get(asp)
                w = (ev or {}).get("weight_in_context_0_1")
                weights[slot] = w
            wlist = [w for w in weights.values() if w is not None]
            if len(wlist) < 2:
                stdev = None
                verdict = "MISSING_DATA"
            else:
                stdev = round(statistics.pstdev(wlist), 3)
                verdict = "UNIFORM" if stdev < 0.10 else "DRIFT"
            out_row["per_variant"][v] = {
                "weights_per_slot": weights, "stdev": stdev,
                "min": min(wlist) if wlist else None,
                "max": max(wlist) if wlist else None,
                "verdict": verdict,
            }
        res.append(out_row)
    return res


async def get_audit_costs():
    """Query Firestore for the 4 Sub-step 0 audit costs."""
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",
                                database="ai-advisor-app")
    audit_ids = [
        ("C1 emag", "5dfb38aa-7e2c-45ea-b570-4f6bb81c39af"),
        ("C2 lab.coop", "b6e1a446-f19a-4c80-9389-7adfbd01da73"),
        ("C3 fallback theverge", "f0416968-e494-4f32-86d6-171df356d98d"),
        ("C3 primary blog.google", "f3257657-f30e-4426-ae61-8f4e60c6c171"),
    ]
    total = 0.0
    print("\n--- Discovery audit costs ---")
    for label, aid in audit_ids:
        doc = await db.collection("audits").document(aid).get()
        d = doc.to_dict() or {}
        ao = d.get("audit_output") or {}
        # Cost is summed across multiple fields — typical naming
        cost_keys = [
            "audit_total_cost_usd", "audit_cost_usd",
            "audit_embedding_cost_usd", "audit_industry_cost_usd",
            "audit_translation_cost_usd",
            "audit_multi_dim_classify_cost_usd",
            "audit_keyword_classify_cost_usd",
        ]
        c = 0
        for k in cost_keys:
            if k in d:
                c += d.get(k) or 0
            if k in ao:
                c += ao.get(k) or 0
        # Also look for site_profile / pagespeed / entity costs nested
        sp = ao.get("site_profile") or {}
        for k in ("cost_usd", "_cost_usd"):
            if k in sp:
                c += sp.get(k) or 0
        print(f"  {label:30s} ${c:.4f}")
        total += c
    print(f"  {'TOTAL':30s} ${total:.4f}")
    return total


def main():
    out = json.loads(Path("aaa124_s0_probe_out.json").read_text(encoding="utf-8"))

    # 1) cost+latency
    rows = cost_latency_table(out)
    print("\n=== Variant comparison table ===")
    print(f"{'slot':4s} {'pt':18s} {'V1$':>8s} {'V1s':>6s} {'V2$':>8s} {'V2s':>6s} {'V3$':>8s} {'V3s':>6s} V1c V2c V3c V3idx")
    for r in rows:
        print(f"{r['slot']:4s} {r['page_type']:18s} "
              f"${r['V1_cost']:.5f} {r['V1_lat']:5.1f}s "
              f"${r['V2_cost']:.5f} {r['V2_lat']:5.1f}s "
              f"${r['V3_cost']:.5f} {r['V3_lat']:5.1f}s "
              f"{int(r['V1_complete_7of7'])}/7 "
              f"{r['V2_aspect_coverage']}/7 "
              f"{r['V3_aspect_coverage']}/7 "
              f"{int(r['V3_has_3_indices'])}/3")

    # 2) Detective recheck
    det = detective_recheck(out)
    print("\n=== Detective hallucination (against corrected GT) ===")
    for v in ("V1", "V2", "V3"):
        s = det[v]
        total_attempted = s["claim_count"] + s["null_count"]
        print(f"  {v}: claims={s['claim_count']}  null={s['null_count']}  "
              f"contradictions={s['contradict_count']} "
              f"(rate: {100*s['contradict_count']/max(1,s['claim_count']):.1f}% of non-null)")
        for c in s["contradictions"]:
            print(f"    - {c}")

    # 3) per-aspect extraction
    per = extract_aspect_evals_per_canary_per_variant(out)

    # 4) D1
    print("\n=== (D.1) JUSTIFIED weight cross-canary check ===")
    d1 = d1_check(per)
    for row in d1:
        print(f"  {row['sub_dim']}: {row['high']} > {row['low']}  "
              f"[{row['descr']}]")
        for v, sub in row["per_variant"].items():
            print(f"    {v}: high={sub['high_weight']!r} low={sub['low_weight']!r} "
                  f"delta={sub['delta']} -> {sub['verdict']}")

    # 5) D2
    print("\n=== (D.2) NON-JUSTIFIED uniformity check ===")
    d2 = d2_check(per)
    for row in d2:
        print(f"  {row['sub_dim']}: should be UNIFORM across C1-C4")
        for v, sub in row["per_variant"].items():
            print(f"    {v}: weights={sub['weights_per_slot']}  "
                  f"stdev={sub['stdev']}  range=[{sub['min']}..{sub['max']}]  "
                  f"-> {sub['verdict']}")

    # 6) Discovery audit costs
    audit_cost = asyncio.run(get_audit_costs())

    # 7) Aggregate cost summary
    gemini_v1_total = sum(r["V1_cost"] for r in rows)
    gemini_v2_total = sum(r["V2_cost"] for r in rows)
    gemini_v3_total = sum(r["V3_cost"] for r in rows)
    gemini_total = gemini_v1_total + gemini_v2_total + gemini_v3_total
    sunk_v1_broken = 0.0831  # cost of the first broken run
    grand_total = audit_cost + gemini_total + sunk_v1_broken
    print(f"\n=== Cost ledger ===")
    print(f"  Discovery audits (4)       : ${audit_cost:.4f}")
    print(f"  Gemini probe v2 (correct)  : ${gemini_total:.4f}")
    print(f"    V1 (28 calls)            : ${gemini_v1_total:.4f}")
    print(f"    V2 (12 calls)            : ${gemini_v2_total:.4f}")
    print(f"    V3 (4 calls)             : ${gemini_v3_total:.4f}")
    print(f"  Sunk cost v1 (broken)      : ${sunk_v1_broken:.4f}")
    print(f"  GRAND TOTAL                : ${grand_total:.4f}  (ceiling $1.20)")

    # 8) Write structured analysis output
    Path("aaa124_s0_analysis.json").write_text(json.dumps({
        "variant_table": rows, "detective": det,
        "d1_check": d1, "d2_check": d2,
        "audit_cost": audit_cost,
        "gemini_total": gemini_total,
        "sunk_v1_broken": sunk_v1_broken,
        "grand_total": grand_total,
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("\nWrote aaa124_s0_analysis.json")


if __name__ == "__main__":
    main()
