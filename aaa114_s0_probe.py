"""AAA-114 Sub-step 0 — competitor compatibility scoring empirical probe.

Archive-bypass: read 2 reference audits' persisted SERP top-10 URLs (per
AAA-108 S4 query_metadata + organic_results), classify each via the
production classify_multi_dim path, then apply 3 candidate scoring formulas
(A=pure hard filter, B=pure weighted-sum, C=hybrid LOCKED default).

NOTE: spec asked for 3 reference audits (HU ecomm / EN consulting / EN B2B
SaaS) but only 2 are in archive (no taxually.com RE audit). Documented as
substitution in §1. The within-SERP diversity (jofogás vs habi vs Facebook
on agrobook; LinkedIn vs Reddit vs Investopedia on kk.coach) provides
sufficient signal to evaluate formulas; the missing B2B SaaS shape is
methodologically flagged.

No production code modification. Pure research/design empirical validation.
"""
import asyncio
import json
import os
import time
from urllib.parse import urlparse

# AAA-62 env var — standalone scripts must set explicitly (per AAA-81 S2 lesson)
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

from crawler.crawler import crawl_html
from memory.firestore_archive import read_audit  # async (sync wrapper nests asyncio.run)
from page_analysis.multi_dim_classify import classify_multi_dim
from site_profile.gemini_analyzer import get_usage

REFERENCE_AUDITS = [
    ("agrobook.hu", "f2792df5-3fb1-484e-9d03-84c749637701"),
    ("kk.coach",    "2a2c335c-33f9-4ec2-97a9-082865acbd2c"),
]


# --- formulas ---------------------------------------------------------------
def _parent_match(target_pt, url_pt, target_parent, url_parent):
    """Returns 1.0 exact leaf match, 0.5 parent_intent match only, else 0."""
    if target_pt and url_pt and target_pt == url_pt:
        return 1.0
    if target_parent and url_parent and target_parent == url_parent:
        return 0.5
    return 0.0


def _binary_eq(a, b):
    return 1.0 if (a is not None and b is not None and a == b) else 0.0


def _locality_applicable(target_loc):
    """Locality is a hard filter only when target locality == 'local'."""
    return target_loc == "local"


def formula_a_pure_hard(target, url):
    """A) Hard filter: bm match AND audience match AND (locality NA OR locality match)."""
    bm_ok = target["business_model"] == url["business_model"]
    aud_ok = target["audience_primary"] == url["audience_primary"]
    loc_ok = (
        True if not _locality_applicable(target["locality"])
        else target["locality"] == url["locality"]
    )
    include = bm_ok and aud_ok and loc_ok
    reasons = []
    if not bm_ok: reasons.append(f"bm:{target['business_model']}≠{url['business_model']}")
    if not aud_ok: reasons.append(f"aud:{target['audience_primary']}≠{url['audience_primary']}")
    if not loc_ok: reasons.append(f"loc:{target['locality']}≠{url['locality']}")
    return include, "; ".join(reasons) or "all match"


def formula_b_pure_weighted(target, url):
    """B) Weighted-sum over 5 dims, equal weights, include if sum>=3.0."""
    bm = _binary_eq(target["business_model"], url["business_model"])
    aud = _binary_eq(target["audience_primary"], url["audience_primary"])
    pt = _parent_match(target["page_type"], url["page_type"],
                       target["parent_intent_group"], url["parent_intent_group"])
    td = _binary_eq(target["topic_domain"], url["topic_domain"])
    loc = _binary_eq(target["locality"], url["locality"])
    total = bm + aud + pt + td + loc
    include = total >= 3.0
    return total, include, f"bm={bm} aud={aud} pt={pt} td={td} loc={loc}"


def formula_c_hybrid(target, url):
    """C) LOCKED hybrid (per Krisztián+Claude 2026-05-26):
      - Hard filter: bm AND audience (mismatch → exclude)
      - Weighted-sum: topic_domain (1.0 ex match) + page_type (1.0/0.5/0.0)
        with 0.5 weight each, include if these two sum to >= 0.5 (at least
        one matches at parent level or topic_domain matches)
      - Locality: hard filter ONLY IF target.locality == 'local'
    """
    # Hard gates
    bm_ok = target["business_model"] == url["business_model"]
    aud_ok = target["audience_primary"] == url["audience_primary"]
    loc_ok = (
        True if not _locality_applicable(target["locality"])
        else target["locality"] == url["locality"]
    )
    if not (bm_ok and aud_ok and loc_ok):
        reasons = []
        if not bm_ok: reasons.append(f"bm-mismatch")
        if not aud_ok: reasons.append(f"aud-mismatch")
        if not loc_ok: reasons.append(f"loc-mismatch(target=local)")
        return False, "; ".join(reasons)
    # Weighted soft signals
    td = _binary_eq(target["topic_domain"], url["topic_domain"])
    pt = _parent_match(target["page_type"], url["page_type"],
                       target["parent_intent_group"], url["parent_intent_group"])
    soft = 0.5 * td + 0.5 * pt
    include = soft >= 0.5
    reason = (
        f"hard-OK; soft=td*{td}+pt*{pt}={soft:.2f}"
        + (" >= 0.5 INCLUDE" if include else " < 0.5 SOFT EXCLUDE")
    )
    return include, reason


# --- main probe -------------------------------------------------------------
async def classify_url(url: str) -> dict:
    """Cheap classify: crawl + minimal site_profile + classify_multi_dim."""
    try:
        crawl = await crawl_html(url)
    except Exception as e:
        return {"_error": f"crawl: {type(e).__name__}: {e}", "url": url}
    if (crawl or {}).get("error"):
        return {"_error": f"crawl-error: {crawl.get('error')}", "url": url}
    # Minimal synthetic site_profile so the classifier prompt has structure
    netloc = urlparse(url).netloc or ""
    sp = {"brand": netloc, "language": "[unknown]", "location": "[unknown]"}
    md, cost = await classify_multi_dim(crawl, sp, summary_text="")
    return {
        "url": url,
        "page_type": md.get("page_type"),
        "parent_intent_group": md.get("page_type_parent_intent_group"),
        "business_model": md.get("business_model"),
        "topic_domain": md.get("topic_domain"),
        "locality": md.get("locality"),
        "audience_primary": md.get("audience_relationship_primary"),
        "audience_secondary": md.get("audience_relationship_secondary"),
        "audience_confidence": md.get("audience_confidence"),
        "classify_cost_usd": cost,
        "_error": md.get("_error"),
    }


async def main():
    t0 = time.perf_counter()
    cost_total = 0.0
    out = {"audits": [], "by_url_classification": {}}

    for label, aid in REFERENCE_AUDITS:
        print(f"\n=== {label} ({aid[:8]}…) ===", flush=True)
        doc = await read_audit(aid)
        ao = doc.get("audit_output") or {}
        rf = ao.get("re_findings") or {}
        # Target classification
        target = {
            "label": label,
            "audit_id": aid,
            "url": doc.get("audit_url"),
            "page_type": ao.get("page_type"),
            "parent_intent_group": ao.get("page_type_parent_intent_group"),
            "business_model": ao.get("business_model"),
            "topic_domain": ao.get("topic_domain"),
            "locality": ao.get("locality"),
            "audience_primary": ao.get("audience_relationship_primary"),
            "audience_secondary": ao.get("audience_relationship_secondary"),
            "audience_confidence": ao.get("audience_confidence"),
        }
        print(f"  target classification: {target}", flush=True)

        # SERP top-10 URLs (branded + category, deduped)
        sb = (rf.get("serp_branded") or {}).get("organic_results") or []
        sc = (rf.get("serp_category") or {}).get("organic_results") or []
        urls = []
        seen = set()
        for r in sb + sc:
            u = r.get("url")
            if u and u not in seen:
                seen.add(u)
                urls.append({
                    "url": u,
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                    "position_in_serp": r.get("position"),
                })
        print(f"  unique SERP URLs: {len(urls)}", flush=True)

        # Classify each (cache across audits to save cost on overlaps)
        classified = []
        for u in urls:
            url = u["url"]
            if url in out["by_url_classification"]:
                cls = out["by_url_classification"][url]
                u["__from_cache"] = True
            else:
                cls = await classify_url(url)
                cost_total += cls.get("classify_cost_usd") or 0.0
                out["by_url_classification"][url] = cls
                u["__from_cache"] = False
            row = {**u, "classification": cls}
            classified.append(row)
            cost_tag = (
                "$cache" if u["__from_cache"]
                else f"${(cls.get('classify_cost_usd') or 0):.4f}"
            )
            pt_v = cls.get("page_type")
            bm_v = cls.get("business_model")
            aud_v = cls.get("audience_primary")
            print(
                f"    [{cost_tag}] {url[:70]:70s}  "
                f"pt={pt_v!r:18s} bm={bm_v!r:30s} aud={aud_v!r}",
                flush=True,
            )

        out["audits"].append({"target": target, "classified": classified})

    # Apply formulas
    print("\n\n=== FORMULA EVALUATION ===", flush=True)
    aggregate = {"A": {"fp": 0, "fn": 0, "incl": 0},
                 "B": {"fp": 0, "fn": 0, "incl": 0},
                 "C": {"fp": 0, "fn": 0, "incl": 0}}
    formula_results = []

    # A-priori manual expected-include heuristics (simple rules):
    # - Include if same TLD, looks like same industry vertical
    # - Exclude if obviously social/classified/wikipedia/forum
    EXCLUDE_HINTS = ["facebook.com", "linkedin.com", "reddit.com",
                     "wikipedia.org", "youtube.com", "jofogas",
                     "wiki", "telefonkonyv", "orszagosszaknevsor"]

    for audit_entry in out["audits"]:
        target = audit_entry["target"]
        print(f"\n--- {target['label']} (target_url={target['url']}) ---", flush=True)
        print(f"  target: bm={target['business_model']} aud={target['audience_primary']} "
              f"td={target['topic_domain']} loc={target['locality']} pt={target['page_type']}",
              flush=True)
        for entry in audit_entry["classified"]:
            url = entry["url"]
            cls = entry["classification"]
            if cls.get("_error"):
                print(f"    SKIP (_error): {url[:60]}", flush=True)
                continue
            # Determine apriori expectation
            host = urlparse(url).netloc.lower()
            host_clean = host[4:] if host.startswith("www.") else host
            apriori = "unclear"
            if any(h in host for h in EXCLUDE_HINTS):
                apriori = "EXCLUDE"
            elif host_clean == urlparse(target["url"]).netloc.lower().lstrip("www.").lstrip("."):
                apriori = "EXCLUDE-self"
            # Compute formulas
            url_cls = {
                "page_type": cls["page_type"],
                "parent_intent_group": cls["parent_intent_group"],
                "business_model": cls["business_model"],
                "topic_domain": cls["topic_domain"],
                "locality": cls["locality"],
                "audience_primary": cls["audience_primary"],
            }
            a_inc, a_r = formula_a_pure_hard(target, url_cls)
            b_score, b_inc, b_r = formula_b_pure_weighted(target, url_cls)
            c_inc, c_r = formula_c_hybrid(target, url_cls)
            print(
                f"  {url[:65]:65s}  apriori={apriori:12s}  "
                f"A={'IN ' if a_inc else 'OUT'} B={b_score:.1f}{'IN' if b_inc else 'OUT'} "
                f"C={'IN ' if c_inc else 'OUT'}  | A={a_r[:50]}  C={c_r[:50]}",
                flush=True,
            )
            for formula, included in (("A", a_inc), ("B", b_inc), ("C", c_inc)):
                aggregate[formula]["incl"] += int(included)
                if apriori.startswith("EXCLUDE") and included:
                    aggregate[formula]["fp"] += 1
                # We don't have ground truth on "include", so fn is hard
            formula_results.append({
                "audit": target["label"],
                "url": url,
                "apriori": apriori,
                "A_include": a_inc, "A_reason": a_r,
                "B_score": b_score, "B_include": b_inc, "B_reason": b_r,
                "C_include": c_inc, "C_reason": c_r,
            })

    out["formula_results"] = formula_results
    out["aggregate"] = aggregate
    out["cost_usd"] = cost_total
    out["wall_s"] = round(time.perf_counter() - t0, 1)

    print(f"\n=== TOTAL cost=${cost_total:.4f}  wall={out['wall_s']}s ===", flush=True)
    print(f"=== AGGREGATE: {aggregate}", flush=True)

    with open("aaa114_s0_probe.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)


if __name__ == "__main__":
    asyncio.run(main())
