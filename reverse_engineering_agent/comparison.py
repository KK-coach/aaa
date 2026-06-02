"""Single Gemini comparison pass over client vs. competitor audits.

We do NOT feed full audit dicts to Gemini (huge, noisy). We extract a
compact per-site dimension row, then ask Gemini for patterns + insights.
"""

from __future__ import annotations

import json

from page_analysis._gemini import generate_json


def _dimensions(audit: dict) -> dict:
    crawl = audit.get("crawl") or {}
    sp = audit.get("site_profile") or {}
    kw = audit.get("keywords") or {}
    ent = audit.get("entities") or {}
    ps = audit.get("pagespeed") or {}
    tech = crawl.get("technical") or {}
    schema = crawl.get("schema_markup") or {}
    mc = crawl.get("main_content") or {}
    imgs = crawl.get("images") or {}
    gl = crawl.get("googlebot_index_limit") or {}

    def _perf(strat: str):
        r = ps.get(strat) or {}
        return None if r.get("error") else (r.get("scores") or {}).get(
            "performance"
        )

    return {
        "url": audit.get("url"),
        "brand": sp.get("brand"),
        "primary_keyword": kw.get("primary_keyword"),
        "intent": kw.get("intent"),
        "https": tech.get("https"),
        "canonical_ok": (tech.get("canonical") or {}).get("self_referencing"),
        "schema_types": schema.get("schema_types_detected", []),
        "schema_count": len(schema.get("schema_types_detected", [])),
        "main_content_words": mc.get("words"),
        "main_content_confidence": mc.get("confidence"),
        "alt_coverage_percent": imgs.get("alt_coverage_percent"),
        "googlebot_risk": gl.get("risk_level"),
        "perf_mobile": _perf("mobile"),
        "perf_desktop": _perf("desktop"),
        "entity_counts": {
            k: len(ent.get(k, []))
            for k in ("products", "organizations", "people", "places",
                      "technologies", "concepts")
        },
        "content_limited": "[CONTENT LIMITED" in (kw.get("reasoning") or ""),
    }


_PROMPT = """\
You are an expert SEO/GEO competitive analyst. Compare the CLIENT site
against COMPETITORS that rank for the same primary keyword.

CLIENT:
{client}

COMPETITORS:
{competitors}

SERP / AI OVERVIEW CONTEXT:
- AI Overview present: {ai_present}
- AI Overview cited URLs: {ai_citations}
- Client URL: {client_url}

Identify what the competitors do that the client does NOT (schema depth,
content length, performance, entity richness, technical health, AI Overview
citation). Be specific and actionable.

Return ONLY valid JSON:
{{
  "dimension_table": {{ "<dimension>": {{ "client": "...", "competitor_best": "...", "gap": "..." }} }},
  "patterns": [
    {{ "finding": "...", "severity": "low|medium|high", "recommendation": "..." }}
  ],
  "ai_overview_summary": "Who got cited, who didn't, and why - especially whether the client is cited."
}}
Provide 3-5 patterns. Be honest if data is thin (e.g. JS-shell client).
"""


async def run_comparison(
    client_audit: dict, competitor_audits: list[dict], serp: dict
) -> dict:
    if not client_audit:
        return {"error": "no client audit available", "patterns": [],
                "dimension_table": {}, "ai_overview_summary": ""}

    client_dim = _dimensions(client_audit)
    comp_dims = [_dimensions(a) for a in competitor_audits]

    prompt = _PROMPT.format(
        client=json.dumps(client_dim, ensure_ascii=False),
        competitors=json.dumps(comp_dims, ensure_ascii=False, indent=1),
        ai_present=serp.get("ai_overview_present"),
        ai_citations=serp.get("ai_overview_citations", []),
        client_url=client_audit.get("url"),
    )
    # Cross-site competitive reasoning -> deeper thinking budget.
    data = await generate_json(prompt, thinking_level="MEDIUM")
    if "_error" in data:
        return {
            "error": f"comparison Gemini call failed: {data['_error']}",
            "dimension_table": {"_raw": {"client": client_dim,
                                         "competitors": comp_dims}},
            "patterns": [],
            "ai_overview_summary": "",
        }
    data.setdefault("dimension_table", {})
    data.setdefault("patterns", [])
    data.setdefault("ai_overview_summary", "")
    data["_raw_dimensions"] = {"client": client_dim, "competitors": comp_dims}
    return data
