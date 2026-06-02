"""AAA-124 S1 standalone unit test of evaluate_aspects against archived audit."""
import asyncio, json
from google.cloud import firestore_v1 as firestore
from page_analysis.aspect_evaluator import evaluate_aspects, AAA124AspectEvaluations, ASPECTS

async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",
                                database="ai-advisor-app")
    # kk.coach AAA-123 S2 canary — has both AAA-42 + AAA-123 ground truth
    doc = await db.collection("audits").document("806e667c-0eba-4d9a-97a8-9a28c73e28f3").get()
    ao = (doc.to_dict() or {}).get("audit_output") or {}
    ao["url"] = "https://kk.coach"
    print(f"input: page_type={ao.get('page_type')} bm={ao.get('business_model')} "
          f"has_aaa42={ao.get('agent_friendly_measurements') is not None} "
          f"has_phase2={ao.get('phase2_html_measurements') is not None}")
    result, cost = evaluate_aspects(ao)
    print(f"\ncost=${cost:.6f}  meta={result.get('_meta')}")
    err = (result.get('_meta') or {}).get('error')
    if err:
        print(f"ERROR: {err}")
        return
    # Verify 7/7 + Pydantic re-validate
    present = [a for a in ASPECTS if a in result]
    print(f"aspects present: {len(present)}/7")
    confs = {a: result[a]['confidence_0_1'] for a in present}
    print(f"confidences: {confs}")
    print(f"min confidence: {min(confs.values())}")
    # Re-validate
    try:
        AAA124AspectEvaluations(**{a: result[a] for a in ASPECTS})
        print("Pydantic re-validation: PASS")
    except Exception as e:
        print(f"Pydantic re-validation: FAIL {e}")
    # Print 2 example findings
    print("\n--- macro_structure ---")
    print(json.dumps(result['macro_structure'], indent=2, ensure_ascii=False))
    print("\n--- schema_entity ---")
    print(json.dumps(result['schema_entity'], indent=2, ensure_ascii=False))
    # Save for hallucination cross-check
    json.dump({"audit": "kk.coach 806e667c", "ground_truth": {
        "h1": (ao.get('agent_friendly_measurements') or {}).get('heading'),
        "images": (ao.get('agent_friendly_measurements') or {}).get('images'),
        "landmarks": (ao.get('agent_friendly_measurements') or {}).get('landmarks'),
    }, "result": result}, open("aaa124_s1_unit_out.json", "w", encoding="utf-8"),
        indent=2, ensure_ascii=False)
    print("\nwrote aaa124_s1_unit_out.json")

asyncio.run(main())
