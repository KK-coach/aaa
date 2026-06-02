"""AAA-129 Sub-step 0 — verbosity probe + educational_context distillation.

THROWAWAY exploration. Bases on AAA-124 aspect_evaluator.py V3 prompt, extends
verbosity ~5×, adds an `educational_context` field per aspect (page-independent
"why this matters" — Sub-step 1 distillation candidate). Raises max_lengths.

Cost computed with OFFICIAL Gemini 3.5 Flash pricing ($1.50/1M in, $9.00/1M out)
AND the AAA-124 module's rates ($0.50/$3.00) for discrepancy verification.

4 canaries (V3 1-holistic each):
  slot1 agrobook b4908500 (0 heading — bad case)
  slot2 kk.coach 2a8c0b20 (45 heading, 1 H1 — good case)
  slot3 aboutyou/c/noi 3f16256f (category, 1 heading) — phase2 live-computed
  slot4 theverge f0416968 (news_article, 36 heading)
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from google import genai
from google.genai import types
from google.cloud import firestore_v1 as firestore

from site_profile.gemini_analyzer import _resolve_project
from page_analysis.aspect_evaluator import _ground_truth_block, ASPECTS, _ASPECT_FOCUS

MODEL = "gemini-3.5-flash"
LOCATION = "global"
# OFFICIAL pricing (AAA-129 spec)
OFF_IN = 1.50 / 1_000_000
OFF_OUT = 9.00 / 1_000_000
# AAA-124 module's (suspected too-low) rates
MOD_IN = 0.50 / 1_000_000
MOD_OUT = 3.00 / 1_000_000

CANARIES = [
    ("slot1_agrobook", "b4908500-7728-4290-b320-eb030ba2179a", None, "hu"),
    ("slot2_kkcoach",  "2a8c0b20-0635-4a67-9868-ff71eb08f721", None, "en"),
    ("slot3_aboutyou", "3f16256f", "aaa129_s0_slot3_phase2.json", "hu"),
    ("slot4_theverge", "f0416968-e494-4f32-86d6-171df356d98d", None, "en"),
]


def _verbose_schema() -> dict:
    aspect = {
        "type": "OBJECT",
        "properties": {
            "structured_finding": {"type": "STRING"},
            "confidence_0_1": {"type": "NUMBER"},
            "justification": {"type": "STRING"},
            "recommendation": {"type": "STRING"},
            "educational_context": {"type": "STRING"},
        },
        "required": ["structured_finding", "confidence_0_1", "justification",
                     "recommendation", "educational_context"],
    }
    return {"type": "OBJECT",
            "properties": {asp: aspect for asp in ASPECTS},
            "required": list(ASPECTS)}


def _build_verbose_prompt(ao: dict) -> str:
    url = ao.get("url") or ao.get("client_url") or "(unknown)"
    page_type = ao.get("page_type")
    business_model = ao.get("business_model")
    locality = ao.get("locality")
    audience = ao.get("audience_relationship_primary")
    topic_domain = ao.get("topic_domain")
    sp = ao.get("site_profile") or {}
    brand = sp.get("brand_name") or sp.get("brand")
    summary = ao.get("summary") or ao.get("audit_summary") or ""
    if summary and len(summary) > 1500:
        summary = summary[:1500] + "...[truncated]"
    gt = _ground_truth_block(ao)
    focus_lines = "\n".join(f"  - {a}: {_ASPECT_FOCUS[a]}" for a in ASPECTS)

    return f"""\
You are an SEO/AEO (Answer-Engine-Optimization) audit expert evaluating ONE webpage's
per-aspect performance for a customer-facing audit report. Produce a THOROUGH,
customer-facing-depth evaluation for each of 7 aspects.

PAGE CONTEXT:
  url: {url}
  page_type: {page_type}
  business_model: {business_model}
  locality: {locality}
  audience: {audience}
  topic_domain: {topic_domain}
  brand: {brand}

DISCOVERY NARRATIVE (LLM-generated page overview, truncated):
{summary}

{gt}

THE 7 ASPECTS TO EVALUATE:
{focus_lines}

For EACH aspect emit:
  - structured_finding: a DETAILED (3-6 sentence) factual observation about THIS page's
    performance on this aspect. Ground every claim in the measurements + page context.
    Aim for ~5× the depth of a terse one-line finding — but every sentence must add
    information, NOT filler or repetition.
  - confidence_0_1: your own confidence (0.0-1.0) given the available evidence.
  - justification: rich reasoning that explains WHY you reached this finding, grounding
    it in the page data and the specific measurements.
  - recommendation: a STEP-BY-STEP, concrete, customer-actionable plan. Number the
    steps. Be specific to THIS page (cite its measured values, brand, keywords).
  - educational_context: explain WHY this aspect matters for SEO/AEO IN GENERAL
    (page-INDEPENDENT — do NOT reference this specific page's values). Write in plain
    business language understandable to a non-SEO-expert. This is reusable teaching
    material, so keep it generic to the aspect, not to this page.

RULES:
  - Do NOT contradict the GROUND-TRUTH MEASUREMENTS. They are authoritative.
  - structured_finding / justification / recommendation are PAGE-SPECIFIC.
  - educational_context is PAGE-INDEPENDENT (generic teaching about the aspect).
  - Calibrate page-specific findings to the page_type / business_model / audience.

Return ONLY structured JSON matching the required schema (all 7 aspects).
"""


_client = None
def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=_resolve_project(),
                               location=LOCATION)
    return _client


# Preventive hallucination cross-check (numeric claims vs ground truth)
def _gt_nums(ao):
    afm = ao.get("agent_friendly_measurements") or {}
    p2 = ao.get("phase2_html_measurements") or {}
    h = afm.get("heading") or {}
    img = afm.get("images") or {}
    ic = img.get("img_count") or 0
    return {
        "h1_count": h.get("h1_count"),
        "total_headings": h.get("total_headings"),
        "alt_pct": round(100.0*(img.get("alt_count") or 0)/ic,1) if ic else None,
        "exceeds_2mb": (p2.get("google_2mb_cutoff") or {}).get("exceeds_2mb_cutoff"),
    }


def _halluc_scan(result, gt):
    import re
    warns = []
    blob = json.dumps({a: result.get(a) for a in ASPECTS if a in result}).lower()
    if gt.get("h1_count") is not None:
        for m in re.finditer(r'(\d+)\s*(?:h1\b|<h1>|h1 element|h1 tag)', blob):
            claimed = int(m.group(1))
            if abs(claimed - gt["h1_count"]) > max(1, gt["h1_count"]*0.1):
                warns.append(f"h1 claim {claimed} vs gt {gt['h1_count']}")
    if gt.get("total_headings") is not None:
        for m in re.finditer(r'(?:total of |)(\d+)\s*headings', blob):
            claimed = int(m.group(1))
            if abs(claimed - gt["total_headings"]) > max(1, gt["total_headings"]*0.1):
                warns.append(f"total_headings claim {claimed} vs gt {gt['total_headings']}")
    if gt.get("exceeds_2mb") is False and ("exceeds 2mb" in blob or "exceeds the 2mb" in blob or "over 2mb" in blob or "exceeds 2 mb" in blob):
        warns.append("claims exceeds_2mb but gt=False")
    return list(set(warns))


async def load_ao(db, prefix, phase2_file):
    doc = await db.collection("audits").document(prefix).get()
    if not doc.exists:
        async for snap in db.collection("audits").stream():
            if snap.id.startswith(prefix):
                doc = snap; break
    ao = (doc.to_dict() or {}).get("audit_output") or {}
    ao["_audit_id"] = doc.id
    if phase2_file and Path(phase2_file).exists():
        ovr = json.loads(Path(phase2_file).read_text(encoding="utf-8"))
        ao["phase2_html_measurements"] = ovr.get("phase2_html_measurements")
    return ao


async def main():
    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",
                                database="ai-advisor-app")
    out = {}
    for label, prefix, p2file, lang in CANARIES:
        ao = await load_ao(db, prefix, p2file)
        gt = _gt_nums(ao)
        print(f"\n=== {label} {ao['_audit_id'][:8]} pt={ao.get('page_type')} gt={gt} ===")
        prompt = _build_verbose_prompt(ao)
        t0 = time.perf_counter()
        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0, response_mime_type="application/json",
                response_schema=_verbose_schema()))
        lat = round(time.perf_counter()-t0, 3)
        um = resp.usage_metadata
        itok = getattr(um, "prompt_token_count", 0) or 0
        otok = getattr(um, "candidates_token_count", 0) or 0
        cost_off = round(itok*OFF_IN + otok*OFF_OUT, 6)
        cost_mod = round(itok*MOD_IN + otok*MOD_OUT, 6)
        parsed = json.loads(resp.text)
        warns = _halluc_scan(parsed, gt)
        # char-length per aspect for verbosity metric
        lens = {a: {k: len(str((parsed.get(a) or {}).get(k) or ""))
                    for k in ("structured_finding","justification","recommendation","educational_context")}
                for a in ASPECTS}
        out[label] = {
            "audit_id": ao["_audit_id"], "url": ao.get("url") or ao.get("client_url"),
            "page_type": ao.get("page_type"), "gt": gt,
            "in_tok": itok, "out_tok": otok, "latency_s": lat,
            "cost_official": cost_off, "cost_module_rates": cost_mod,
            "hallucinations": warns, "result": parsed, "char_lens": lens,
        }
        print(f"  in={itok} out={otok} lat={lat}s cost_official=${cost_off:.6f} "
              f"cost_module=${cost_mod:.6f} halluc={len(warns)} {warns}")
        # avg char lengths
        avg_sf = sum(lens[a]["structured_finding"] for a in ASPECTS)//7
        avg_ec = sum(lens[a]["educational_context"] for a in ASPECTS)//7
        print(f"  avg structured_finding={avg_sf}c  avg educational_context={avg_ec}c")

    Path("aaa129_s0_probe_out.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    tot_off = sum(v["cost_official"] for v in out.values())
    tot_mod = sum(v["cost_module_rates"] for v in out.values())
    print(f"\nTOTAL cost_official=${tot_off:.6f}  cost_module=${tot_mod:.6f}  "
          f"ratio={tot_off/tot_mod:.2f}x")
    print("wrote aaa129_s0_probe_out.json")


if __name__ == "__main__":
    asyncio.run(main())
