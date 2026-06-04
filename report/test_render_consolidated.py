# -*- coding: utf-8 -*-
"""AAA-161 / RG1-S3 — unit tests for the consolidated render's DETERMINISTIC
parts ($0: input-completeness guard, render-view projection, prompt assembly).
The live Gemini call is NOT tested here. Run: pytest report/test_render_consolidated.py
"""
import json
import os

import pytest

from report.fact_base import build_fact_base
from report.decide import build_decisions
from report.render_consolidated import (
    assert_inputs_complete, build_render_view, assemble_render_prompt,
    estimate_tokens, _filter_landmarks,
)

_FX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(_FX, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def tx():
    ao = _load("taxually_013a2853.json")
    fb = build_fact_base(ao)
    return fb, build_decisions(fb)


def test_inputs_complete_passes(tx):
    fb, dec = tx
    assert_inputs_complete(fb, dec)  # must not raise


def test_inputs_incomplete_raises():
    with pytest.raises(ValueError):
        assert_inputs_complete({"classification": {}, "target": {},
                                "competition": {}, "ai_visibility": {},
                                "technical": {}}, {})


def test_render_view_strips_not_measured(tx):
    """No not_measured FACT reaches the fact-projection of the view (the
    decisions block intentionally keeps guard text + provenance labels for the
    model, so it is excluded from this scan)."""
    fb, dec = tx
    v = build_render_view(fb, dec)
    facts_only = {k: v[k] for k in
                  ("subject", "onpage", "ai_visibility", "technical", "competition")}
    blob = json.dumps(facts_only)
    assert "entity_lists" not in blob          # competitor entity lists excluded
    assert "not_measured" not in blob          # no not_measured fact in projection


def test_render_view_humanizes_page_kinds(tx):
    fb, dec = tx
    v = build_render_view(fb, dec)
    kinds = {e["page_kind"] for e in v["competition"]["serp_top10"]}
    assert "company homepage" in kinds         # business_homepage -> humanized
    assert "business_homepage" not in kinds     # raw code must not appear


def test_homepage_landmark_guard_filter(tx):
    fb, dec = tx
    v = build_render_view(fb, dec)
    ml = v["onpage"]["missing_landmarks"]
    assert "article" not in ml and "aside" not in ml   # guard-denied on homepage
    # filter helper directly
    assert _filter_landmarks(["article", "aside", "header"], "homepage") == ["header"]
    assert _filter_landmarks(["article"], "blog_article") == ["article"]


def test_competitors_count_schema_only(tx):
    """Competitor entries carry counts/schema, never entity name lists."""
    fb, dec = tx
    v = build_render_view(fb, dec)
    for c in v["competition"]["competitors"]:
        assert "entity_counts" in c and "schema_types" in c
        assert "entity_lists" not in c


def test_prompt_assembles_and_has_rules(tx):
    fb, dec = tx
    p = assemble_render_prompt(fb, dec)
    for marker in ("HARD RULES", "OFF-PAGE HEDGE", "RECOMMENDATION GUARDS",
                   "## §1 — Where you stand", "[DATA"):
        assert marker in p
    est = estimate_tokens(p)
    assert est["est_input_tokens"] > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
