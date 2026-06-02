"""AAA-124 S1 smoke verification + preventive hallucination cross-check."""
import asyncio, json
from google.cloud import firestore_v1 as firestore
from page_analysis.aspect_evaluator import AAA124AspectEvaluations, ASPECTS

AUDITS = {
    "kk.coach": "2a8c0b20-0635-4a67-9868-ff71eb08f721",
    "agrobook.hu": "b4908500-7728-4290-b320-eb030ba2179a",
}

def gt_extract(afm, p2):
    h = afm.get("heading") or {}
    img = afm.get("images") or {}
    lm = afm.get("landmarks") or {}
    sa = afm.get("schema_actions")
    cut = (p2 or {}).get("google_2mb_cutoff") or {}
    ic = img.get("img_count") or 0
    alt = round(100.0*(img.get("alt_count") or 0)/ic,1) if ic else None
    return {
        "h1_count": h.get("h1_count"),
        "total_headings": h.get("total_headings"),
        "alt_coverage_pct": alt,
        "has_main": "main" in (lm.get("present") or []),
        "schema_actions_count": len(sa) if isinstance(sa,list) else None,
        "exceeds_2mb": cut.get("exceeds_2mb_cutoff"),
    }

def halluc_check(result, gt):
    """Scan all finding/justification/recommendation text for numeric claims
    that contradict ground truth. Simple heuristic: look for explicit numbers
    near keywords."""
    import re
    warnings = []
    blob = json.dumps({a: result.get(a) for a in ASPECTS if a in result}).lower()
    # H1 count claim check: phrases like "N h1" / "h1 count of N" / "N <h1>"
    if gt.get("h1_count") is not None:
        for m in re.finditer(r'(\d+)\s*(?:h1|<h1>|h1 element)', blob):
            claimed = int(m.group(1))
            if abs(claimed - gt["h1_count"]) > max(1, gt["h1_count"]*0.1):
                warnings.append(f"h1 claim {claimed} vs gt {gt['h1_count']}")
    # exceeds_2mb contradiction
    if gt.get("exceeds_2mb") is False and ("exceeds 2mb" in blob or "over 2mb" in blob or "exceeds the 2mb" in blob):
        warnings.append("claims exceeds_2mb but gt=False")
    return warnings

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",
                                database="ai-advisor-app")
    for label, aid in AUDITS.items():
        doc = await db.collection("audits").document(aid).get()
        d = doc.to_dict() or {}
        ao = d.get("audit_output") or {}
        ae = ao.get("aaa124_aspect_evaluations")
        cost = ao.get("audit_aspect_eval_cost_usd")
        print(f"\n===== {label} ({aid[:8]}) =====")
        print(f"  schema_version: {d.get('schema_version')}")
        print(f"  aaa124_aspect_evaluations present: {ae is not None}")
        print(f"  audit_aspect_eval_cost_usd: {cost}")
        if not ae:
            print("  MISSING — FAIL")
            continue
        meta = ae.get("_meta") or {}
        print(f"  _meta: error={meta.get('error')} latency={meta.get('latency_s')}s "
              f"in_tok={meta.get('input_tokens')} out_tok={meta.get('output_tokens')}")
        present = [a for a in ASPECTS if a in ae]
        print(f"  aspects present: {len(present)}/7")
        # Pydantic re-validate
        try:
            AAA124AspectEvaluations(**{a: ae[a] for a in ASPECTS})
            print(f"  Pydantic validation: PASS")
        except Exception as e:
            print(f"  Pydantic validation: FAIL {e}")
        confs = {a: ae[a]['confidence_0_1'] for a in present}
        print(f"  confidences: {confs}")
        print(f"  min confidence: {min(confs.values())}  (halt if <0.5)")
        # halluc check
        gt = gt_extract(ao.get("agent_friendly_measurements") or {},
                        ao.get("phase2_html_measurements") or {})
        print(f"  ground_truth: {gt}")
        w = halluc_check(ae, gt)
        print(f"  hallucination warnings: {len(w)} {w}")
        # 1 most actionable + 1 most insightful example
        print(f"  EXAMPLE schema_entity.recommendation: {ae['schema_entity']['recommendation'][:200]}")
        print(f"  EXAMPLE heading_semantics.finding: {ae['heading_semantics']['structured_finding'][:200]}")

asyncio.run(main())
