# -*- coding: utf-8 -*-
"""AAA-161 / RG1-S2 — unit tests for the decide pass. Fixture-driven (read-only
canary archives), Firestore-independent. Run: pytest report/test_decide.py
"""
import json
import os

import pytest

from report.fact_base import build_fact_base, MEASURED, ABSENT, NOT_MEASURED
from report.decide import (
    build_decisions, decide_anchor, _SEV_RANK, DECISIONS_VERSION,
)

_FX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(_FX, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def tx():
    ao = _load("taxually_013a2853.json")
    return build_decisions(build_fact_base(ao))


@pytest.fixture(scope="module")
def kk():
    ao = _load("kkcoach_67762118.json")
    return build_decisions(build_fact_base(ao))


def test_version(tx):
    assert tx["meta"]["schema_version"] == DECISIONS_VERSION
    assert set(tx.keys()) == {"meta", "anchor", "target_stance",
                              "ranked_findings", "recommendation_guards",
                              "diagnosis_inputs"}


# --- (1) anchor ------------------------------------------------------------
def test_taxually_anchor_is_avalara_not_wikipedia(tx):
    a = tx["anchor"]
    assert a["provenance"] == MEASURED
    assert "avalara" in (a["value"]["url"] or "")
    assert a["value"]["serp_position"] == 1
    assert a["selection_basis"] == "serp_rank"
    assert "wikipedia" not in (a["value"]["url"] or "")


def test_kkcoach_anchor_is_top_serp_real_competitor(kk):
    a = kk["anchor"]
    assert a["provenance"] == MEASURED
    assert a["value"]["serp_position"] == 1  # chrisraulf #1 via serp_category


def test_anchor_absent_when_no_real_competitor():
    fb = {"competition": {"competitors": []}, "target": {"intent": {"value": None}}}
    a = decide_anchor(fb)
    assert a["provenance"] == ABSENT and a["selection_basis"] == "no_real_competitor"


# --- (2) target_stance -----------------------------------------------------
def test_taxually_good_fit_no_flipflop(tx):
    ts = tx["target_stance"]
    # homepage appears in SERP (no dominant dedicated type) -> good_fit, no rec
    assert ts["verdict"] == "good_fit"
    assert ts["dedicated_page_recommendation"] is False


def test_kkcoach_page_type_mismatch_additive(kk):
    ts = kk["target_stance"]
    # SERP dominated by business_blog_or_article (8/9) vs homepage target
    assert ts["verdict"] == "page_type_mismatch"
    assert ts["dedicated_page_recommendation"] is True
    assert ts["serp_dominant_type"] == "business_blog_or_article"
    assert "homepage" in ts["honesty_note"].lower()
    assert "not measured" in ts["honesty_note"].lower() or "not measure" in ts["honesty_note"].lower()


# --- (3) ranked_findings ---------------------------------------------------
def test_schema_never_high(tx, kk):
    for d in (tx, kk):
        for f in d["ranked_findings"]:
            if f["category"] == "schema":
                assert _SEV_RANK[f["impact_severity"]] <= _SEV_RANK["medium"]


def test_heading_findings_not_ranking_critical(tx, kk):
    for d in (tx, kk):
        for f in d["ranked_findings"]:
            if f["category"] == "structure_accessibility":
                assert f["impact_severity"] == "low"


def test_findings_sorted_desc(tx):
    sev = [_SEV_RANK[f["impact_severity"]] for f in tx["ranked_findings"]]
    assert sev == sorted(sev, reverse=True)


def test_not_measured_excluded_from_findings(kk):
    # kk.coach AI overview client_cited is not_measured -> NO 'not cited' finding
    for f in kk["ranked_findings"]:
        assert "not cited in the google ai overview" not in f["finding"].lower()


def test_redirect_finding_kept_when_present(tx):
    # taxually has a real redirect chain (taxually.com -> www.taxually.com)
    cats = [f for f in tx["ranked_findings"] if "redirect" in f["finding"].lower()]
    assert cats and cats[0]["category"] == "technical"


# --- (4) recommendation_guards --------------------------------------------
def test_taxually_guards_saas(tx):
    g = tx["recommendation_guards"]
    assert "SoftwareApplication" in g["allow"] and "Offer" in g["allow"]
    assert "local_seo" in g["deny"]                 # locality global
    assert g["flags"]["schema_profile"] == "saas"


def test_kkcoach_guards_service_no_local_no_product(kk):
    g = kk["recommendation_guards"]
    assert "Person" in g["allow"] and "Service" in g["allow"]
    assert "Product" in g["deny"] and "LocalBusiness" in g["deny"]
    assert "local_seo" in g["deny"]
    assert g["flags"]["schema_profile"] == "service"


def test_fabrication_and_competitor_entity_guards(tx, kk):
    for d in (tx, kk):
        f = d["recommendation_guards"]["flags"]
        assert "fabrication_guard" in f and "competitor_entity_guard" in f


# --- (5) diagnosis_inputs --------------------------------------------------
def test_kkcoach_aio_excluded_from_diagnosis(kk):
    di = kk["diagnosis_inputs"]
    assert "ai_overview_client_cited" in di["excluded_not_measured"]
    assert all(rf["key"] != "ai_overview_client_cited" for rf in di["ranked_facts"])
    assert di["offpage_unmeasured"] is True


def test_taxually_aio_included_as_absent(tx):
    di = tx["diagnosis_inputs"]
    aio = [rf for rf in di["ranked_facts"] if rf["key"] == "ai_overview_client_cited"]
    assert aio and aio[0]["provenance"] == ABSENT


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
