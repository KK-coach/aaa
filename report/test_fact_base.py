# -*- coding: utf-8 -*-
"""AAA-161 / RG1-S1 — unit tests for the fact_base mapper + provenance resolvers.

Fixture-driven (report/fixtures/*.json captured read-only from the two canary
archives) so tests are NOT Firestore-dependent. Run: pytest report/test_fact_base.py
"""
import json
import os

import pytest

from report.fact_base import (
    build_fact_base, SCHEMA_VERSION,
    MEASURED, ABSENT, NOT_MEASURED,
    r_count, r_list, r_client_cited, r_ranking,
)

_FX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(_FX, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def taxually():
    return build_fact_base(_load("taxually_013a2853.json"))


@pytest.fixture(scope="module")
def kkcoach():
    return build_fact_base(_load("kkcoach_67762118.json"))


# --- structure / schema_version -------------------------------------------
def test_top_level_sections(taxually):
    assert set(taxually.keys()) == {
        "meta", "classification", "target", "onpage",
        "ai_visibility", "technical", "competition"}
    assert taxually["meta"]["schema_version"] == SCHEMA_VERSION


def test_every_leaf_has_wrapper(taxually):
    """Spot: a sample of leaves all carry value/provenance/source."""
    leaves = [
        taxually["classification"]["topic_domain"],
        taxually["onpage"]["forms"]["input_count"],
        taxually["ai_visibility"]["ai_overview_client_cited"],
        taxually["technical"]["https"],
    ]
    for lf in leaves:
        assert set(lf.keys()) == {"value", "provenance", "source"}
        assert lf["provenance"] in (MEASURED, ABSENT, NOT_MEASURED)


# --- the critical spot-checks from the spec --------------------------------
def test_taxually_client_cited_absent(taxually):
    """taxually: AI Overview evaluated, client NOT cited → absent."""
    f = taxually["ai_visibility"]["ai_overview_client_cited"]
    assert f["value"] is False and f["provenance"] == ABSENT


def test_kkcoach_client_cited_not_measured(kkcoach):
    """kk.coach: client_cited is None → not_measured (NOT absent)."""
    f = kkcoach["ai_visibility"]["ai_overview_client_cited"]
    assert f["value"] is None and f["provenance"] == NOT_MEASURED


def test_competitor_entity_lists_always_not_measured(taxually):
    comps = taxually["competition"]["competitors"]
    assert comps, "expected competitors in taxually canary"
    for c in comps:
        assert c["entity_lists"]["provenance"] == NOT_MEASURED
        assert c["entity_lists"]["value"] is None


def test_competitor_schema_types_measured_for_ok_discovery(taxually):
    """Successfully-discovered competitor (anchor) → schema_types measured."""
    anchor = next((c for c in taxually["competition"]["competitors"]
                   if c["is_anchor"]), None)
    assert anchor is not None
    assert anchor["discovery_status"]["value"] == "ok"
    assert anchor["schema_types"]["provenance"] == MEASURED
    assert isinstance(anchor["schema_types"]["value"], list) and anchor["schema_types"]["value"]


def test_failed_competitor_is_not_measured(taxually):
    """taxually wikipedia competitor Discovery failed → counts/types not_measured."""
    failed = [c for c in taxually["competition"]["competitors"]
              if c["discovery_status"]["value"] == "failed"]
    assert failed, "expected the failed wikipedia competitor"
    for c in failed:
        assert c["schema_types"]["provenance"] == NOT_MEASURED
        assert c["entity_counts"]["provenance"] == NOT_MEASURED


def test_heading_tree_preserved_with_order(taxually):
    """Heading fa carries order (position) + depth (level) + zone, intact."""
    tree = taxually["onpage"]["headings"]["tree"]
    assert tree["provenance"] == MEASURED
    items = tree["value"]
    assert len(items) >= 3
    for it in items[:5]:
        assert {"level", "position", "zone", "text"} <= set(it.keys())
    positions = [it["position"] for it in items]
    assert positions == sorted(positions), "heading order must be preserved"


def test_aria_measured_zero_vs_absent(taxually):
    """ARIA: non-zero interactive → measured; a real zero → absent."""
    aria = taxually["onpage"]["aria"]
    ic = aria["interactive_count"]
    assert ic["provenance"] == MEASURED and ic["value"] > 0
    # semantic_html.button_count==0 maps via structure? buttons not in fact_base;
    # validate the measured-zero contract directly on the resolver instead:
    assert r_count({"x": {"n": 0}}, "x", "n")["provenance"] == ABSENT


# --- forms reconciliation: phase2 canonical (incl. hidden) -----------------
def test_forms_input_count_is_phase2_canonical(taxually):
    f = taxually["onpage"]["forms"]["input_count"]
    assert f["source"].startswith("phase2_html_measurements")
    assert f["value"] == 21  # phase2 counts ALL non-CMP inputs (incl hidden)
    lc = taxually["onpage"]["forms"]["label_coverage"]
    assert lc["source"].startswith("agent_friendly_measurements")


def test_schema_types_from_phase2(taxually):
    s = taxually["onpage"]["schema"]["types_found"]
    assert s["source"].endswith("found_schemas")
    assert s["provenance"] == MEASURED


# --- resolver unit behaviour ----------------------------------------------
def test_r_count_rules():
    assert r_count({"a": 5}, "a")["provenance"] == MEASURED
    assert r_count({"a": 0}, "a")["provenance"] == ABSENT
    assert r_count({}, "a")["provenance"] == NOT_MEASURED
    assert r_count({"a": 0}, "a", error_subtree={"_error": "x"})["provenance"] == NOT_MEASURED


def test_r_list_rules():
    assert r_list({"a": [1]}, "a")["provenance"] == MEASURED
    assert r_list({"a": []}, "a")["provenance"] == ABSENT
    assert r_list({}, "a")["provenance"] == NOT_MEASURED
    assert r_list({"a": []}, "a", error_subtree={"_error": "x"})["provenance"] == NOT_MEASURED


def test_r_client_cited_rules():
    assert r_client_cited({"c": True}, "c")["provenance"] == MEASURED
    assert r_client_cited({"c": False}, "c")["provenance"] == ABSENT
    assert r_client_cited({"c": None}, "c")["provenance"] == NOT_MEASURED
    assert r_client_cited({}, "c")["provenance"] == NOT_MEASURED


def test_r_ranking_found_flag_disambiguates_none_position():
    ao = {"re_findings": {"client_ranking_status": {"branded": {
        "position": None, "found_in_top_10": False, "ranking_severity": "outside_top_10"}}}}
    f = r_ranking(ao, "branded")
    assert f["provenance"] == ABSENT and f["value"]["position"] is None
    ao2 = {"re_findings": {"client_ranking_status": {"branded": {
        "position": 3, "found_in_top_10": True}}}}
    assert r_ranking(ao2, "branded")["provenance"] == MEASURED


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
