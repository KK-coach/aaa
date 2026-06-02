from page_analysis.aspect_edu_templates import EDU_TEMPLATES
from page_analysis.aspect_evaluator import AspectEvaluation, AAA124AspectEvaluations, ASPECTS, _gemini_schema

print("=== WI-1 templates ===")
assert sorted(EDU_TEMPLATES) == sorted(ASPECTS), "template/aspect mismatch"
for a, t in EDU_TEMPLATES.items():
    assert set(t["text"]) == {"hu", "en"}, a
    assert t["template_id"].startswith("edu_") and t["template_id"].endswith("_v1"), a
print("  7/7 aspects, each hu+en + template_id  OK")
print("  macro HU head:", EDU_TEMPLATES["macro_structure"]["text"]["hu"][:55])
assert "„látják" in EDU_TEMPLATES["macro_structure"]["text"]["hu"], "HU curly quote lost"
print("  HU curly-quote preserved  OK")

print("=== WI-3 Gemini emit schema lacks educational_context ===")
props = _gemini_schema()["properties"]["macro_structure"]["properties"]
print("  emit fields:", sorted(props))
assert "educational_context" not in props
print("  educational_context NOT in Gemini schema  OK")

print("=== WI-2 schema validation old/new/full ===")
old = {"structured_finding": "x"*30, "confidence_0_1": 0.9, "justification": "y"*30, "recommendation": "z"*30}
ae_old = AspectEvaluation(**old)
print("  OLD 4-field passes; edu defaults:", ae_old.educational_context, ae_old.educational_context_template_id)
new = dict(old, educational_context={"hu": "a", "en": "b"}, educational_context_template_id="edu_macro_structure_v1")
print("  NEW with edu passes; tid:", AspectEvaluation(**new).educational_context_template_id)
AAA124AspectEvaluations(**{a: dict(old) for a in ASPECTS})
print("  FULL 7-aspect Gemini-shaped passes")
AspectEvaluation(structured_finding="S. "*150, confidence_0_1=0.8, justification="j"*1500, recommendation="1. step. "*100)
print("  long 3-6 sentence finding + step rec fits new maxes  OK")
print("\nALL VALIDATION PASSED")
