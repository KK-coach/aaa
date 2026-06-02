"""AAA-114 Sub-step 1 pre-flight: 3 synthetic scenarios for the
deterministic Stage 2 filter. Cost: $0 (no LLM calls)."""
import json

from reverse_engineering_agent.competitor_filter import (
    filter_and_rank_competitors,
)


def synth_keyword(label: str, role: str, classifs: list[dict]) -> dict:
    """Build a Stage 1-shaped keyword entry."""
    return {
        "keyword": label,
        "keyword_role": role,
        "serp_top10_classifications": classifs,
        "serp_type_distribution": {},  # not used by Stage 2
        "_error": None,
    }


def c(url, pos, serp_type, relev, title=""):
    return {
        "url": url, "position": pos, "title": title, "snippet": "",
        "serp_type": serp_type, "topic_relevance_score": relev,
        "from_cache": False, "_error": None,
    }


# Scenario 1 — HIGH-CANDIDATE: 20 candidates business-tilted, all >=0.7
SCEN1 = [
    synth_keyword("kw1", "primary", [
        c("https://homepage1.com",  1, "business_homepage", 0.95),
        c("https://homepage2.com",  2, "business_homepage", 0.95),
        c("https://homepage3.com",  3, "business_homepage", 0.90),
        c("https://homepage4.com",  4, "business_homepage", 0.90),
        c("https://homepage5.com",  5, "business_homepage", 0.85),
        c("https://homepage6.com",  6, "business_homepage", 0.85),
        c("https://homepage7.com",  7, "business_homepage", 0.80),
        c("https://homepage8.com",  8, "business_homepage", 0.80),
        c("https://category1.com",  9, "business_category", 0.75),
        c("https://category2.com", 10, "business_category", 0.75),
    ]),
    synth_keyword("kw2", "secondary", [
        c("https://homepage11.com", 1, "business_homepage", 0.95),
        c("https://homepage12.com", 2, "business_homepage", 0.95),
        c("https://homepage13.com", 3, "business_homepage", 0.90),
        c("https://homepage14.com", 4, "business_homepage", 0.85),
        c("https://homepage15.com", 5, "business_homepage", 0.80),
        c("https://homepage16.com", 6, "business_homepage", 0.80),
        c("https://homepage17.com", 7, "business_homepage", 0.75),
        c("https://homepage18.com", 8, "business_homepage", 0.75),
        c("https://category11.com", 9, "business_category", 0.75),
        c("https://category12.com",10, "business_category", 0.70),
    ]),
]

# Scenario 2 — LOW-CANDIDATE: most fail (14 below 0.7 + 4 host-platform), 2 pass
SCEN2 = [
    synth_keyword("kw1", "primary", [
        c("https://low_rel1.com",   1, "business_homepage", 0.5),
        c("https://low_rel2.com",   2, "business_homepage", 0.4),
        c("https://low_rel3.com",   3, "business_category", 0.6),
        c("https://low_rel4.com",   4, "business_blog_or_article", 0.3),
        c("https://low_rel5.com",   5, "business_homepage", 0.5),
        c("https://low_rel6.com",   6, "business_service", 0.2),
        c("https://low_rel7.com",   7, "business_homepage", 0.6),
        # host-platform — fails Hard filter C
        c("https://lkdn.com/co/x",  8, "social_profile_or_page", 0.9),
        c("https://reddit.com/r/x", 9, "forum_or_qa_thread", 0.85),
        # passes everything → 1st passer
        c("https://passer1.com",   10, "business_homepage", 0.85),
    ]),
    synth_keyword("kw2", "secondary", [
        c("https://low_rel8.com",   1, "business_homepage", 0.5),
        c("https://low_rel9.com",   2, "business_homepage", 0.4),
        c("https://low_rel10.com",  3, "business_category", 0.6),
        c("https://low_rel11.com",  4, "business_blog_or_article", 0.5),
        c("https://low_rel12.com",  5, "business_homepage", 0.55),
        c("https://low_rel13.com",  6, "business_service", 0.45),
        c("https://low_rel14.com",  7, "business_homepage", 0.65),
        # host-platform
        c("https://jofogas.hu/x",   8, "marketplace_category", 0.9),
        c("https://wiki.org/x",     9, "wiki_or_reference", 0.8),
        # 2nd passer
        c("https://passer2.com",   10, "business_homepage", 0.90),
    ]),
]

# Scenario 3 — ZERO-CANDIDATE: all fail (below threshold OR host-platform)
SCEN3 = [
    synth_keyword("kw1", "primary", [
        c("https://low1.com",  1, "business_homepage", 0.5),
        c("https://low2.com",  2, "business_homepage", 0.3),
        c("https://low3.com",  3, "business_category", 0.6),
        c("https://low4.com",  4, "business_service", 0.4),
        c("https://low5.com",  5, "business_blog_or_article", 0.65),
        c("https://lkdn.com/x", 6, "social_profile_or_page", 0.95),
        c("https://reddit.com/r/x",7,"forum_or_qa_thread", 0.85),
        c("https://wiki.org/x", 8, "wiki_or_reference", 0.9),
        c("https://yt.com/x",   9, "video_or_audio_listing", 0.85),
        c("https://m.com/p",   10, "marketplace_listing", 0.9),
    ]),
    synth_keyword("kw2", "secondary", [
        c("https://low6.com",  1, "business_homepage", 0.55),
        c("https://low7.com",  2, "business_homepage", 0.4),
        c("https://low8.com",  3, "business_category", 0.6),
        c("https://low9.com",  4, "business_service", 0.5),
        c("https://low10.com", 5, "business_blog_or_article", 0.65),
        c("https://fb.com/x",  6, "social_post", 0.9),
        c("https://dir.com/x", 7, "directory_listing", 0.85),
        c("https://blog.com/x",8, "aggregator_or_personal_blog", 0.9),
        c("https://other.com/x",9,"other_or_unknown", 0.8),
        c("https://news.com/x",10,"news_or_publisher_article", 0.95),  # conditional, target=homepage → excluded
    ]),
]


def run_scenario(label: str, scenario, target_type="business_homepage",
                 expected_pass_count=None, expected_selected=None,
                 expected_no_comparable=None):
    print(f"=== Scenario {label} ===")
    result = filter_and_rank_competitors(
        serp_fit_analysis=scenario,
        audit_target_type=target_type,
        target_locality=None,
        target_locality_tld=None,
    )
    cand = result["selected_competitors_v2"]
    passers = [e for e in cand if e["hard_filter_pass"]]
    selected = [e for e in cand if e["selected"]]
    no_comp = result["no_comparable_competitors_found"]
    print(f"  total candidates audit-trail entries: {len(cand)}")
    print(f"  hard_filter_pass count               : {len(passers)}  (expected ~{expected_pass_count})")
    print(f"  selected count                       : {len(selected)}  (expected {expected_selected})")
    print(f"  no_comparable_competitors_found      : {no_comp}  (expected {expected_no_comparable})")
    fails = []
    if expected_pass_count is not None and len(passers) != expected_pass_count:
        fails.append(f"passer count {len(passers)} != {expected_pass_count}")
    if expected_selected is not None and len(selected) != expected_selected:
        fails.append(f"selected count {len(selected)} != {expected_selected}")
    if expected_no_comparable is not None and no_comp != expected_no_comparable:
        fails.append(f"no_comparable {no_comp} != {expected_no_comparable}")
    # Sanity per-entry
    for e in cand:
        if e["hard_filter_pass"]:
            if e["soft_score"] is None or e["soft_score_breakdown"] is None:
                fails.append(f"passer {e['url']} missing soft_score / breakdown")
            if e["hard_filter_fail_reason"] is not None:
                fails.append(f"passer {e['url']} has fail_reason set")
        else:
            if not e["hard_filter_fail_reason"]:
                fails.append(f"failer {e['url']} missing fail_reason")
            if e["soft_score"] is not None:
                fails.append(f"failer {e['url']} has soft_score set")
            if e["selected"]:
                fails.append(f"failer {e['url']} marked selected")
    selected_sorted = sorted(selected, key=lambda x: x["selection_rank"])
    print(f"  selected (rank order):")
    for s in selected_sorted:
        print(f"    rank {s['selection_rank']}: {s['url']:42s}  "
              f"serp_type={s['serp_type']:25s}  relev={s['topic_relevance_score']}  "
              f"soft={s['soft_score']}  breakdown={s['soft_score_breakdown']}")
    # Sample failer
    sample_failer = next((e for e in cand if not e["hard_filter_pass"]), None)
    if sample_failer:
        print(f"  sample failer: {sample_failer['url']} reason={sample_failer['hard_filter_fail_reason']}")
    print()
    return "PASS" if not fails else "FAIL: " + "; ".join(fails)


# Expected values:
# Scenario 1: 20 candidates × all relev >=0.7 + all business_homepage/business_category → 20 pass
#             top-3: 3 of the homepage entries with relev>=0.8 (8 such in kw1, 6 such in kw2 = 14
#             with soft_score=2.0). Selected count = 3.
# Scenario 2: 14 below-threshold failers + 4 host-platform failers + 2 passers (homepage relev>=0.8)
#             Selected count = 2 (cap=3 graceful)
# Scenario 3: 0 passers (all failures by relev or serp_type), audit_no_comparable=True
print("\n" + "="*80)
print("AAA-114 Sub-step 1 pre-flight dry-run")
print("="*80 + "\n")
r1 = run_scenario("1 HIGH", SCEN1, expected_pass_count=20, expected_selected=3,
                   expected_no_comparable=False)
r2 = run_scenario("2 LOW",  SCEN2, expected_pass_count=2, expected_selected=2,
                   expected_no_comparable=False)
r3 = run_scenario("3 ZERO", SCEN3, expected_pass_count=0, expected_selected=0,
                   expected_no_comparable=True)
print(f"Scenario 1: {r1}")
print(f"Scenario 2: {r2}")
print(f"Scenario 3: {r3}")
all_pass = all(r.startswith("PASS") for r in (r1, r2, r3))
print(f"\nOVERALL: {'PASS' if all_pass else 'FAIL'}")
