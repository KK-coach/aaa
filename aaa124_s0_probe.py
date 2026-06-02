"""AAA-124 Sub-step 0 — 12-call capability probe (4 canary × 3 variant).

THROWAWAY exploration. NO module commit. NO Discovery integration cascade.

Variants:
  V1 — 7-specific (7 parallel calls, each one aspect)
  V2 — 3-per-index (3 parallel calls, each one index)
  V3 — 1-holistic (1 call, all 3 indices + 7 aspects)

Aspects (per AAA-124 mapping spec):
  macro_structure / heading_semantics / above_the_fold / micro_semantics /
  inline_link_semantics / forms_conversion_points / schema_entity

Indices:
  technical_semantic_index    — macro + heading + micro + schema
  ux_conversion_index         — atf + forms + inline_link
  ai_geo_readability_index    — heading + micro + schema (citability)

Cross-validation:
  Preventív  — prompt-embedded ground-truth (h1_count, alt_coverage, schema_actions...)
  Detective  — programmatic check of structured claims vs AAA-42/AAA-123 ground-truth
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from google import genai
from google.genai import types
from google.cloud import firestore_v1 as firestore

from site_profile.gemini_analyzer import _resolve_project

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("aaa124")

MODEL = "gemini-3.5-flash"
LOCATION = "global"
_RATE_IN = 0.50 / 1_000_000
_RATE_OUT = 3.00 / 1_000_000

# ---------------------------------------------------------------------------
# Canary registry (filled at runtime by canary_map())
# ---------------------------------------------------------------------------
CANARIES = {
    "C1": {"label": "ProductPage/ecommerce/national/B2C",
           "audit_id": None,   # filled post-audit
           "url": None,
           "phase2_override": None},
    "C2": {"label": "ServicePage/agency/local-or-national/B2B",
           "audit_id": None, "url": None, "phase2_override": None},
    "C3": {"label": "BlogPost/content_publisher/global/B2C",
           "audit_id": None, "url": None, "phase2_override": None},
    "C4": {"label": "LandingPage/b2b_saas/global/B2B",
           "audit_id": "18c133f2",   # archived
           "url": "https://vercel.com",
           "phase2_override": "aaa124_s0_c4_vercel_phase2.json"},
}


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------
async def load_audit(db, audit_id_prefix: str) -> dict | None:
    """Find audit doc whose id starts with the given prefix and return its
    full dict. Returns None if not found."""
    coll = db.collection("audits")
    async for snap in coll.stream():
        if snap.id.startswith(audit_id_prefix):
            return {"id": snap.id, **(snap.to_dict() or {})}
    return None


def build_payload(audit_doc: dict, phase2_override: dict | None) -> dict:
    """Build the 10-block input payload from an audit doc. Skip-finding:
    a missing block yields the block key with value None instead of failing."""
    ao = audit_doc.get("audit_output") or {}
    p = {}

    # Block 1: page identity (URL is at audit_output.url; legacy: client_url
    # at top-level audit_url too)
    p["block1_page_identity"] = {
        "client_url": ao.get("url") or ao.get("client_url")
                      or audit_doc.get("audit_url") or audit_doc.get("url"),
        "audit_id": audit_doc.get("id"),
        "language": audit_doc.get("audit_language")
                    or (ao.get("site_profile") or {}).get("language"),
    }
    # Block 2: multi-dim classification
    p["block2_multi_dim"] = {
        "page_type": ao.get("page_type"),
        "business_model": ao.get("business_model"),
        "locality": ao.get("locality"),
        "audience_relationship_primary": ao.get("audience_relationship_primary"),
        "topic_domain": ao.get("topic_domain"),
        "industry": ao.get("industry"),
        "page_funnel_stage": ao.get("page_funnel_stage"),
    }
    # Block 3: brand + entity context
    sp = ao.get("site_profile") or {}
    p["block3_brand_entity"] = {
        "brand_name": sp.get("brand_name"),
        "owner_org": sp.get("owner_organization") or sp.get("owner_org"),
        "named_people": sp.get("named_people") or [],
    }
    # Block 4: topic + keyword context
    p["block4_topic_keywords"] = {
        "category_keyword": (ao.get("keywords") or {}).get("category_keyword"),
        "topic_cluster": ao.get("topic_cluster"),
        "primary_keyword": (ao.get("keywords") or {}).get("primary_keyword"),
        "target_keywords_classified_count": len(
            ao.get("target_keywords_classified") or []),
    }
    # Block 5: AI visibility — typically absent in early audits; skip if so
    p["block5_ai_visibility"] = ao.get("ai_visibility") or None
    # Block 6: competitive landscape — typically absent at Discovery level
    p["block6_competitive_landscape"] = (
        ao.get("re_findings") or ao.get("serp_fit_analysis") or None
    )
    # Block 7: performance signals
    p["block7_performance"] = {
        "pagespeed_mobile_score": (ao.get("pagespeed") or {}).get("mobile_score"),
        "pagespeed_desktop_score": (ao.get("pagespeed") or {}).get("desktop_score"),
        "crux": ao.get("crux") or None,
    }
    # Block 8: Discovery narrative
    p["block8_discovery_narrative"] = (
        ao.get("summary") or ao.get("audit_summary") or None
    )
    # Block 9: raw HTML — typically NOT persisted (transient field). Skip.
    p["block9_raw_html"] = None
    # Block 10: ground truth — AAA-42 + AAA-123
    afm = ao.get("agent_friendly_measurements") or {}
    p2 = ao.get("phase2_html_measurements")
    if p2 is None and phase2_override:
        p2 = phase2_override
    p["block10_ground_truth"] = {
        "aaa42_agent_friendly_measurements": afm or None,
        "aaa123_phase2_html_measurements": p2 or None,
    }
    return p


def _gt_values(payload: dict) -> dict:
    """Single source of truth for ground-truth values; handles AAA-42's actual
    schema (singular `heading`, `images` with alt_count/img_count, landmarks
    present-list, schema_actions LIST-not-dict)."""
    gt = payload.get("block10_ground_truth", {}) or {}
    afm = gt.get("aaa42_agent_friendly_measurements") or {}
    p2 = gt.get("aaa123_phase2_html_measurements") or {}
    h = afm.get("heading") or {}  # singular
    img = afm.get("images") or {}
    lm = afm.get("landmarks") or {}
    sa = afm.get("schema_actions")  # LIST or absent
    ss = (p2 or {}).get("semantic_structure") or {}
    cut = (p2 or {}).get("google_2mb_cutoff") or {}
    rm = (p2 or {}).get("rendering_mode") or {}
    alt_cov = None
    ic = img.get("img_count") or 0
    if ic:
        alt_cov = round(100.0 * (img.get("alt_count") or 0) / ic, 1)
    present = lm.get("present") or []
    has_main = "main" in present if present is not None else None
    schema_count = len(sa) if isinstance(sa, list) else (sa.get("count") if isinstance(sa, dict) else None)
    return {
        "h1_count": h.get("h1_count"),
        "total_headings": h.get("total_headings"),
        "alt_coverage_pct": alt_cov,
        "has_main": has_main,
        "schema_actions_count": schema_count,
        "exceeds_2mb": cut.get("exceeds_2mb_cutoff"),
        "heading_tree_count_phase2": ss.get("heading_tree_count"),
        "raw_html_bytes": cut.get("raw_html_bytes_uncompressed"),
        "is_csr_likely": rm.get("is_csr_likely"),
        "spa_frameworks": rm.get("spa_frameworks_detected"),
        "schema_pagetype_match": (ss.get("schema_pagetype_match") or {}).get("match"),
        "schema_matched_types": (ss.get("schema_pagetype_match") or {}).get("matched_types"),
    }


def _ground_truth_summary(payload: dict) -> str:
    """Tight summary of ground-truth values for prompt embedding (Preventív)."""
    v = _gt_values(payload)
    lines = ["GROUND-TRUTH MEASUREMENTS (do not contradict — these are programmatically measured, authoritative):"]
    lines.append(f"  AAA-42 h1_count={v['h1_count']}  total_headings={v['total_headings']}")
    lines.append(f"  AAA-42 alt_coverage_pct={v['alt_coverage_pct']}")
    lines.append(f"  AAA-42 has_main={v['has_main']}  schema_actions_count={v['schema_actions_count']}")
    lines.append(f"  AAA-123 heading_tree_count={v['heading_tree_count_phase2']}  raw_html_bytes={v['raw_html_bytes']}  exceeds_2mb={v['exceeds_2mb']}")
    lines.append(f"  AAA-123 is_csr_likely={v['is_csr_likely']}  spa_frameworks={v['spa_frameworks']}")
    lines.append(f"  AAA-123 schema_pagetype_match={v['schema_pagetype_match']}  matched_types={v['schema_matched_types']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts + schemas
# ---------------------------------------------------------------------------
_ASPECT_TO_PROMPT_FOCUS = {
    "macro_structure": "the page's macro semantic layout (main/nav/header/footer landmarks, section hierarchy, content-to-chrome ratio)",
    "heading_semantics": "the heading hierarchy (h1 presence/uniqueness, h2-h6 nesting, heading-text quality and topic-coverage)",
    "above_the_fold": "the above-the-fold area (hero content, primary CTA, immediate value proposition for the page_type and audience)",
    "micro_semantics": "the micro semantic richness (inline emphasis em/strong, lists, blockquotes, figures, semantic-vs-presentational markup)",
    "inline_link_semantics": "internal/external link quality (descriptive anchor text, rel attributes, target=_blank safety, internal-link depth)",
    "forms_conversion_points": "conversion-point quality (form fields, CTA placement, lead-gen funnel signals relevant to the business_model)",
    "schema_entity": "structured-data presence and fit (JSON-LD, page_type-specific schema types, entity coverage, KG signals)",
}

_ASPECT_LIST = list(_ASPECT_TO_PROMPT_FOCUS.keys())

_INDEX_TO_ASPECTS = {
    "technical_semantic_index": ["macro_structure", "heading_semantics",
                                  "micro_semantics", "schema_entity"],
    "ux_conversion_index": ["above_the_fold", "forms_conversion_points",
                             "inline_link_semantics"],
    "ai_geo_readability_index": ["heading_semantics", "micro_semantics",
                                  "schema_entity"],
}


def _aspect_schema():
    return {
        "type": "OBJECT",
        "properties": {
            "score_0_100": {"type": "INTEGER"},
            "weight_in_context_0_1": {"type": "NUMBER"},
            "weight_justification": {"type": "STRING"},
            "key_findings": {"type": "ARRAY", "items": {"type": "STRING"}},
            "structured_claims": {
                "type": "OBJECT",
                "properties": {
                    "h1_count_claimed": {"type": "INTEGER", "nullable": True},
                    "alt_coverage_pct_claimed": {"type": "NUMBER", "nullable": True},
                    "has_main_claimed": {"type": "BOOLEAN", "nullable": True},
                    "schema_actions_count_claimed": {"type": "INTEGER", "nullable": True},
                    "exceeds_2mb_claimed": {"type": "BOOLEAN", "nullable": True},
                },
            },
            "confidence_0_1": {"type": "NUMBER"},
        },
        "required": ["score_0_100", "weight_in_context_0_1",
                     "weight_justification", "key_findings",
                     "structured_claims", "confidence_0_1"],
    }


def _v1_schema():
    return _aspect_schema()


def _v2_schema():
    return {
        "type": "OBJECT",
        "properties": {
            "score_0_100": {"type": "INTEGER"},
            "per_aspect_evaluations": {
                "type": "OBJECT",
                "properties": {asp: _aspect_schema() for asp in _ASPECT_LIST},
            },
            "confidence_0_1": {"type": "NUMBER"},
        },
        "required": ["score_0_100", "per_aspect_evaluations", "confidence_0_1"],
    }


def _v3_schema():
    return {
        "type": "OBJECT",
        "properties": {
            "technical_semantic_index": {
                "type": "OBJECT",
                "properties": {"score_0_100": {"type": "INTEGER"},
                               "confidence_0_1": {"type": "NUMBER"}},
            },
            "ux_conversion_index": {
                "type": "OBJECT",
                "properties": {"score_0_100": {"type": "INTEGER"},
                               "confidence_0_1": {"type": "NUMBER"}},
            },
            "ai_geo_readability_index": {
                "type": "OBJECT",
                "properties": {"score_0_100": {"type": "INTEGER"},
                               "confidence_0_1": {"type": "NUMBER"}},
            },
            "per_aspect_evaluations": {
                "type": "OBJECT",
                "properties": {asp: _aspect_schema() for asp in _ASPECT_LIST},
            },
            "overall_summary": {"type": "STRING"},
            "overall_confidence_0_1": {"type": "NUMBER"},
        },
        "required": ["technical_semantic_index", "ux_conversion_index",
                     "ai_geo_readability_index", "per_aspect_evaluations",
                     "overall_summary", "overall_confidence_0_1"],
    }


def _build_prompt(variant: str, focus_or_index: str | None,
                  payload: dict) -> str:
    page_id = payload.get("block1_page_identity") or {}
    mdc = payload.get("block2_multi_dim") or {}
    brand = payload.get("block3_brand_entity") or {}
    kw = payload.get("block4_topic_keywords") or {}
    perf = payload.get("block7_performance") or {}
    nar = payload.get("block8_discovery_narrative") or ""
    if nar and len(nar) > 1500:
        nar = nar[:1500] + "...[truncated]"
    gt = _ground_truth_summary(payload)

    header = f"""\
You are AAA-124's page-context-aware audit grader. Your task is to evaluate the page
on the aspect(s) below, with weighting CALIBRATED TO THE PAGE CONTEXT (page_type,
business_model, locality, audience_relationship).

IMPORTANT WEIGHTING DOCTRINE:
- Some sub-dimensions SHOULD be weighted differently based on page context. Example:
  product-schema fit on a ProductPage > on a BlogPost; LocalBusiness/NAP on a local
  service page > on a global SaaS landing. Use weight_in_context_0_1 to reflect this.
- Other sub-dimensions are UNIVERSAL and MUST be weighted uniformly regardless of
  context. Example: h1-presence, alt-coverage, link-target-blank-safety, ARIA
  coverage, semantic-vs-presentational emphasis. For these, weight_in_context_0_1
  should be ≥ 0.8 in EVERY context.

PAGE CONTEXT (multi-axis):
  client_url: {page_id.get('client_url')}
  language: {page_id.get('language')}
  page_type: {mdc.get('page_type')}
  business_model: {mdc.get('business_model')}
  locality: {mdc.get('locality')}
  audience: {mdc.get('audience_relationship_primary')}
  topic_domain: {mdc.get('topic_domain')}
  industry: {mdc.get('industry')}

BRAND/ENTITY: brand={brand.get('brand_name')}  owner={brand.get('owner_org')}
  named_people_count={len(brand.get('named_people') or [])}

KEYWORD/TOPIC: primary_keyword={kw.get('primary_keyword')!r}
  category_keyword={kw.get('category_keyword')!r}
  topic_cluster={kw.get('topic_cluster')!r}

PERFORMANCE: pagespeed_mobile={perf.get('pagespeed_mobile_score')}
  pagespeed_desktop={perf.get('pagespeed_desktop_score')}

DISCOVERY NARRATIVE (truncated):
{nar}

{gt}

When you populate `structured_claims`, ONLY emit values for fields you would have
direct evidence for from the ground truth above; leave others null. Your
structured_claims will be cross-checked against the ground truth — DO NOT contradict
the measured values.
"""

    if variant == "V1":
        focus = _ASPECT_TO_PROMPT_FOCUS[focus_or_index]
        return header + f"""
TASK (Variant 1 — 7-specific, this call is for ASPECT: {focus_or_index}):
Evaluate {focus}. Score 0-100 (page-context-calibrated quality). State
weight_in_context_0_1 = how heavily THIS aspect should weigh in the final composite
for THIS page_type/business_model/locality/audience. List 2-5 key findings.
Confidence 0-1.

Return ONLY structured JSON.
"""
    elif variant == "V2":
        idx_aspects = _INDEX_TO_ASPECTS[focus_or_index]
        return header + f"""
TASK (Variant 2 — 3-per-index, this call is for INDEX: {focus_or_index}):
Evaluate the page on this composite index. Aspects covered by this index:
{idx_aspects}

For EACH aspect listed, emit a full per-aspect evaluation (score, weight, justification,
findings, structured_claims, confidence). Then emit the composite index score_0_100
(weighted aggregate of the per-aspect scores using your weight_in_context_0_1 values).

Return ONLY structured JSON.
"""
    else:  # V3
        return header + f"""
TASK (Variant 3 — 1-holistic, this single call covers ALL aspects + ALL indices):
For EACH of the 7 aspects [{', '.join(_ASPECT_LIST)}], emit a full per-aspect
evaluation. Then emit the 3 composite indices (technical_semantic_index,
ux_conversion_index, ai_geo_readability_index) as weighted aggregates per the
mapping:
  technical_semantic_index: macro_structure + heading_semantics + micro_semantics + schema_entity
  ux_conversion_index: above_the_fold + forms_conversion_points + inline_link_semantics
  ai_geo_readability_index: heading_semantics + micro_semantics + schema_entity

Provide overall_summary (1-3 sentences) and overall_confidence_0_1.

Return ONLY structured JSON.
"""


# ---------------------------------------------------------------------------
# Gemini caller
# ---------------------------------------------------------------------------
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=_resolve_project(),
                               location=LOCATION)
    return _client


def call_gemini(prompt: str, schema: dict) -> dict:
    t0 = time.perf_counter()
    try:
        resp = _get_client().models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        latency = round(time.perf_counter() - t0, 3)
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = getattr(um, "candidates_token_count", 0) or 0
        cost = round(in_tok * _RATE_IN + out_tok * _RATE_OUT, 8)
        return {
            "ok": True,
            "parsed": json.loads(resp.text),
            "in_tok": in_tok, "out_tok": out_tok,
            "cost_usd": cost, "latency_s": latency,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "latency_s": round(time.perf_counter() - t0, 3),
                "in_tok": 0, "out_tok": 0, "cost_usd": 0.0}


# ---------------------------------------------------------------------------
# Detective hallucination check
# ---------------------------------------------------------------------------
def _gt_extract(payload: dict) -> dict:
    """Extract numerical/boolean ground truths for detective comparison.
    Thin wrapper over _gt_values (single source of truth)."""
    v = _gt_values(payload)
    # The detective check uses these specific keys
    return {
        "h1_count": v["h1_count"],
        "total_headings": v["total_headings"],
        "alt_coverage_pct": v["alt_coverage_pct"],
        "has_main": v["has_main"],
        "schema_actions_count": v["schema_actions_count"],
        "exceeds_2mb": v["exceeds_2mb"],
    }


def detective_check(aspect_eval: dict, gt: dict) -> list[str]:
    """Compare structured_claims against ground truth. Return list of mismatches."""
    claims = (aspect_eval or {}).get("structured_claims") or {}
    mismatches = []
    pairs = [
        ("h1_count_claimed", "h1_count"),
        ("alt_coverage_pct_claimed", "alt_coverage_pct"),
        ("has_main_claimed", "has_main"),
        ("schema_actions_count_claimed", "schema_actions_count"),
        ("exceeds_2mb_claimed", "exceeds_2mb"),
    ]
    for ck, gk in pairs:
        c = claims.get(ck)
        g = gt.get(gk)
        if c is None or g is None:
            continue
        # numeric tolerance: ±10% or ±1
        if isinstance(c, (int, float)) and isinstance(g, (int, float)):
            tol = max(1, abs(g) * 0.10)
            if abs(c - g) > tol:
                mismatches.append(f"{ck}={c} vs gt.{gk}={g} (Δ>{tol:.1f})")
        elif c != g:
            mismatches.append(f"{ck}={c!r} vs gt.{gk}={g!r}")
    return mismatches


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------
async def run_one_canary(slot: str, canary: dict, db) -> dict:
    audit_id = canary["audit_id"]
    print(f"\n=== {slot} ({canary['label']}) audit_id={audit_id} ===")
    audit_doc = await load_audit(db, audit_id)
    if not audit_doc:
        return {"slot": slot, "error": f"audit_id {audit_id} not found"}

    phase2_override = None
    if canary.get("phase2_override"):
        p = Path(canary["phase2_override"])
        if p.exists():
            o = json.loads(p.read_text(encoding="utf-8"))
            phase2_override = o.get("phase2_html_measurements")

    payload = build_payload(audit_doc, phase2_override)
    gt = _gt_extract(payload)
    print(f"  url={payload['block1_page_identity']['client_url']}")
    print(f"  page_type={payload['block2_multi_dim']['page_type']}"
          f"  bm={payload['block2_multi_dim']['business_model']}"
          f"  loc={payload['block2_multi_dim']['locality']}"
          f"  aud={payload['block2_multi_dim']['audience_relationship_primary']}")
    print(f"  ground_truth: {gt}")

    runs = {}

    # V1 — 7-specific calls
    print(f"  V1 (7-specific)...")
    v1 = {}
    for asp in _ASPECT_LIST:
        prompt = _build_prompt("V1", asp, payload)
        res = call_gemini(prompt, _v1_schema())
        if res["ok"]:
            mismatches = detective_check(res["parsed"], gt)
            res["hallucinations"] = mismatches
        v1[asp] = res
        print(f"    {asp}: ok={res['ok']} cost=${res.get('cost_usd', 0):.5f} "
              f"lat={res.get('latency_s', 0)}s "
              f"halluc={len(res.get('hallucinations', []))}")
    runs["V1"] = v1

    # V2 — 3-per-index calls
    print(f"  V2 (3-per-index)...")
    v2 = {}
    for idx in _INDEX_TO_ASPECTS:
        prompt = _build_prompt("V2", idx, payload)
        res = call_gemini(prompt, _v2_schema())
        if res["ok"]:
            mismatches = []
            for asp, ev in (res["parsed"].get("per_aspect_evaluations") or {}).items():
                mismatches += [f"[{asp}] {m}" for m in detective_check(ev, gt)]
            res["hallucinations"] = mismatches
        v2[idx] = res
        print(f"    {idx}: ok={res['ok']} cost=${res.get('cost_usd', 0):.5f} "
              f"lat={res.get('latency_s', 0)}s "
              f"halluc={len(res.get('hallucinations', []))}")
    runs["V2"] = v2

    # V3 — 1-holistic
    print(f"  V3 (1-holistic)...")
    prompt = _build_prompt("V3", None, payload)
    res = call_gemini(prompt, _v3_schema())
    if res["ok"]:
        mismatches = []
        for asp, ev in (res["parsed"].get("per_aspect_evaluations") or {}).items():
            mismatches += [f"[{asp}] {m}" for m in detective_check(ev, gt)]
        res["hallucinations"] = mismatches
    runs["V3"] = res
    print(f"    holistic: ok={res['ok']} cost=${res.get('cost_usd', 0):.5f} "
          f"lat={res.get('latency_s', 0)}s "
          f"halluc={len(res.get('hallucinations', []))}")

    return {"slot": slot, "label": canary["label"], "audit_id": audit_id,
            "url": payload['block1_page_identity']['client_url'],
            "page_type": payload['block2_multi_dim']['page_type'],
            "business_model": payload['block2_multi_dim']['business_model'],
            "locality": payload['block2_multi_dim']['locality'],
            "audience": payload['block2_multi_dim']['audience_relationship_primary'],
            "ground_truth": gt, "runs": runs}


async def main():
    # Read canary mapping populated by orchestrator
    cmap_path = Path("aaa124_s0_canary_map.json")
    if not cmap_path.exists():
        print("HALT: aaa124_s0_canary_map.json missing.")
        return
    cmap = json.loads(cmap_path.read_text(encoding="utf-8"))
    for slot, info in cmap.items():
        if slot in CANARIES:
            CANARIES[slot]["audit_id"] = info["audit_id"]
            CANARIES[slot]["url"] = info["url"]
            if info.get("phase2_override"):
                CANARIES[slot]["phase2_override"] = info["phase2_override"]

    db = firestore.AsyncClient(project="project-7d6eedd4-adff-46ae-8fc",
                                database="ai-advisor-app")

    cost_budget = 1.20
    results = {}
    cumulative_cost = 0.0
    halt_triggered = False

    for slot in ("C1", "C2", "C3", "C4"):
        r = await run_one_canary(slot, CANARIES[slot], db)
        results[slot] = r
        # Track cumulative cost
        runs = r.get("runs") or {}
        for v, inner in runs.items():
            if v == "V3":
                cumulative_cost += inner.get("cost_usd", 0) or 0
            else:
                for k, res in inner.items():
                    cumulative_cost += res.get("cost_usd", 0) or 0
        print(f"  >>> cumulative cost: ${cumulative_cost:.4f}")
        if cumulative_cost > cost_budget:
            print(f"HALT: cost ceiling ${cost_budget} exceeded "
                  f"(${cumulative_cost:.4f})")
            halt_triggered = True
            break

    out = {"results": results, "cumulative_cost_usd": cumulative_cost,
           "halt_triggered": halt_triggered}
    Path("aaa124_s0_probe_out.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    print(f"\nWrote aaa124_s0_probe_out.json (cumulative ${cumulative_cost:.4f})")


if __name__ == "__main__":
    asyncio.run(main())
