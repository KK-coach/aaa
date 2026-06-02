"""AAA-118 Sub-step 2.2 pre-flight dry-run.

3 synthetic scenarios verify verdict bands + conditional LLM call:
  1) HIGH fit  → no LLM call
  2) PARTIAL   → no LLM call
  3) LOW       → 3-5 alternative-keyword suggestions via Gemini

Cost target: ~$0.005 (one LLM call only, scenario 3).
"""
import asyncio
import os
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

from page_analysis.serp_fit_classify import (
    AlternativeKeywordSuggestions, compute_target_type_fit,
    enrich_with_verdicts, map_target_type,
)


def synth_classifications(distrib: dict[str, int], relev: float = 1.0,
                          title_prefix: str = "Title for") -> list[dict]:
    """Build a synthetic serp_top10_classifications list from a distribution."""
    out = []
    pos = 1
    for stype, n in distrib.items():
        for i in range(n):
            out.append({
                "url": f"https://example.com/{stype}-{i}",
                "position": pos,
                "title": f"{title_prefix} {stype} #{i+1}",
                "snippet": "...",
                "serp_type": stype,
                "topic_relevance_score": relev,
                "from_cache": False,
                "_error": None,
            })
            pos += 1
    return out


SCENARIOS = [
    {
        "label": "HIGH",
        "distribution": {"business_homepage": 6, "business_category": 2,
                         "marketplace_listing": 1, "business_blog_or_article": 1},
        "expected_verdict": "high",
        "expected_llm_fire": False,
    },
    {
        "label": "PARTIAL",
        "distribution": {"business_blog_or_article": 5, "business_homepage": 1,
                         "marketplace_listing": 2, "news_or_publisher_article": 2},
        "expected_verdict": "partial",
        "expected_llm_fire": False,
    },
    {
        "label": "LOW",
        "distribution": {"business_blog_or_article": 7,
                         "news_or_publisher_article": 2, "forum_or_qa_thread": 1},
        "expected_verdict": "low",
        "expected_llm_fire": True,
    },
]


async def main():
    # First — quick mapping sanity check on a few page_type → SERP type
    print("=== map_target_type sanity ===")
    for pt, expected in [
        ("homepage", "business_homepage"),
        ("product_page", "business_product"),
        ("news_article", "news_or_publisher_article"),
        ("error_or_redirect_page", "other_or_unknown"),
        ("UNKNOWN_FALLTHROUGH", "other_or_unknown"),
        (None, "other_or_unknown"),
    ]:
        got = map_target_type(pt, None)
        print(f"  {pt!r:35s} → {got!r}  ({'PASS' if got == expected else 'FAIL'})")
    print()

    # Build synthetic serp_fit_analysis list (3 entries, one per scenario)
    target_type = "business_homepage"
    sfa_input = []
    for sc in SCENARIOS:
        sfa_input.append({
            "keyword": f"synthetic-{sc['label'].lower()}-keyword",
            "keyword_role": "primary" if sc["label"] == "HIGH" else "secondary",
            "serp_top10_classifications": synth_classifications(sc["distribution"]),
            "serp_type_distribution": dict(sc["distribution"]),
            "_error": None,
        })

    # Per-scenario standalone verdict check (no LLM)
    print("=== compute_target_type_fit() per scenario ===")
    all_correct = True
    for sc, entry in zip(SCENARIOS, sfa_input):
        verdict, top3, dist = compute_target_type_fit(
            target_type, entry["serp_top10_classifications"]
        )
        ok = verdict == sc["expected_verdict"]
        if not ok:
            all_correct = False
        print(f"  [{sc['label']:8s}] verdict={verdict!r:10s}  expected={sc['expected_verdict']!r:10s}  "
              f"top3={top3}  total={sum(dist.values())}  {'PASS' if ok else 'FAIL'}")

    # Now run enrich_with_verdicts which should fire LLM only for scenario 3
    print("\n=== enrich_with_verdicts() integration ===")
    enriched, extra_cost = await enrich_with_verdicts(
        sfa_input,
        target_type=target_type,
        target_topic_domain="Technology & Computing",
        target_topic_cluster="Cloud infrastructure platforms",
        target_category_keyword="cloud hosting platform",
        audit_language="en",
    )
    print(f"  alternative-keyword LLM cost: ${extra_cost:.6f}")

    # Verify LLM fired only for scenario 3
    print()
    for sc, entry in zip(SCENARIOS, enriched):
        sug = entry.get("alternative_keyword_suggestions") or []
        rsn = entry.get("alternative_keyword_reasoning")
        trigger = entry.get("keyword_recommendation_trigger")
        llm_fired = bool(sug) or bool(rsn)
        ok_trigger = trigger == sc["expected_llm_fire"]
        ok_fire = llm_fired == sc["expected_llm_fire"]
        print(f"  [{sc['label']:8s}] verdict={entry['target_type_fit']!r:10s}  "
              f"trigger={trigger}  suggestions={len(sug)}  "
              f"{'PASS' if (ok_trigger and ok_fire) else 'FAIL'}")
        if llm_fired:
            try:
                # Pydantic validate the alt-kw payload
                AlternativeKeywordSuggestions.model_validate(
                    {"suggestions": sug, "reasoning": rsn or ""}
                )
                print(f"      Pydantic-valid (3-5 suggestions, non-empty reasoning)")
            except Exception as e:
                print(f"      Pydantic INVALID: {e}")
                all_correct = False
            print(f"      reasoning: {(rsn or '')[:200]}")
            print(f"      suggestions: {sug}")

    print()
    print(f"=== TOTAL cost: ${extra_cost:.6f} (target <$0.005 for scenario 3 LLM) ===")
    print(f"=== ALL CHECKS: {'PASS' if all_correct else 'FAIL'} ===")


if __name__ == "__main__":
    asyncio.run(main())
