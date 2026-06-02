"""Post-process the 3 existing reverse-eng JSON outputs (no re-auditing).

For each file:
  1. compute client_ranking_status from serp_result.organic_urls
  2. re-apply the new entity-based competitor exclusion and DOCUMENT what
     the selection WOULD have been (does not re-audit)
  3. regenerate summary_markdown with a SERP Landscape section + ranking

Run:  python -m reverse_engineering_agent.postprocess
"""

import json
import re
from pathlib import Path

from reverse_engineering_agent.ranking import (
    compute_client_ranking_status,
    render_serp_landscape,
    select_competitors,
)

OUT_DIR = Path(__file__).resolve().parent / "test_outputs"
FILES = ["www.agrobook.hu.json", "www.taxually.com.json", "vercel.com.json"]


# Section headers appear in 3 forms across agent runs:
#   "### Title", "### 1. Title", "**a. Title**"
_HDR = re.compile(
    r"^\s*(?:#{2,4}\s*(?:\d+\.\s*)?(?P<h>.+?)\s*|"
    r"\*\*\s*(?:[a-z]\.\s*)?(?P<b>[^*]+?)\s*\*\*)\s*$"
)


def _split_sections(md: str) -> list[tuple[str, str]]:
    """Return [(title, body), ...]. Leading 'report for' H2 is dropped."""
    sections: list[tuple[str, list[str]]] = []
    cur_title, cur_body = None, []
    for line in (md or "").splitlines():
        m = _HDR.match(line)
        title = (m.group("h") or m.group("b")) if m else None
        if title is not None:
            if cur_title is not None:
                sections.append((cur_title, cur_body))
            cur_title, cur_body = title.strip(), []
        else:
            if cur_title is None:
                cur_title, cur_body = "_preamble", []
            cur_body.append(line)
    if cur_title is not None:
        sections.append((cur_title, cur_body))
    return [(t, "\n".join(b).strip()) for t, b in sections]


def _classify(title: str) -> str:
    t = title.lower()
    if "report for" in t or t == "_preamble":
        return "drop"
    if "client identification" in t or "client overview" in t:
        return "drop"          # replaced by the new structured block
    if "serp landscape" in t:
        return "drop"          # replaced by the new structured block
    if "ai overview" in t:
        return "ai"
    if any(k in t for k in ("recommend", "strategic", "next step",
                            "action plan")):
        return "reco"
    return "comparison"        # dimension / pattern / comparison / fallback


def _merge_summary(d: dict, ident: str, landscape: str) -> str:
    source = d.get("summary_markdown_original") or d.get(
        "summary_markdown", ""
    )
    comparison, ai, reco = [], [], []
    for title, body in _split_sections(source):
        if not body:
            continue
        bucket = _classify(title)
        if bucket == "comparison":
            comparison.append(f"_{title}_\n\n{body}")
        elif bucket == "ai":
            ai.append(body)
        elif bucket == "reco":
            reco.append(body)

    parts = [
        ident.rstrip(),
        landscape.rstrip(),
        "---\n\n### Competitor Comparison & Pattern Findings\n\n"
        + ("\n\n".join(comparison) if comparison
           else "_No comparison data was produced by the agent._"),
    ]
    if ai:
        parts.append("### AI Overview Analysis\n\n" + "\n\n".join(ai))
    if reco:
        parts.append("### Strategic Recommendations\n\n" + "\n\n".join(reco))
    return "\n\n".join(parts) + "\n"


def process(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    client_url = d["client_url"]
    serp = d.get("serp_result") or {}
    organic = serp.get("organic_urls", []) or []
    sp = (d.get("client_audit") or {}).get("site_profile") or {}
    main_entities = sp.get("main_entities") or []

    ranking = compute_client_ranking_status(client_url, organic)
    d["client_ranking_status"] = ranking

    original_comp = d.get("competitor_urls") or []
    resel = select_competitors(client_url, serp, main_entities)
    d["competitor_reselection"] = {
        "original_competitors": original_comp,
        "entity_aware_competitors": resel["competitor_urls"],
        "exclusions": resel["exclusions"],
        "main_entities_used": main_entities,
        "changed": resel["competitor_urls"] != original_comp,
        "note": (
            "Entity-based exclusion applied to the SAME cached SERP. "
            "Competitors NOT re-audited."
        ),
    }

    landscape = render_serp_landscape(
        d.get("primary_keyword", ""), client_url, serp, ranking
    )
    ident = (
        f"## Reverse-engineering report for {client_url}\n\n"
        f"### Client Identification\n"
        f"- Brand: {sp.get('brand')}\n"
        f"- Target country: {d.get('target_country')}\n"
        f"- Primary keyword: {d.get('primary_keyword')}"
    )
    # Preserve the genuine agent output once; always merge from it.
    if "summary_markdown_original" not in d:
        d["summary_markdown_original"] = d.get("summary_markdown", "")
    d["summary_markdown"] = _merge_summary(d, ident, landscape)

    path.write_text(
        json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return d


def main() -> None:
    for fname in FILES:
        p = OUT_DIR / fname
        if not p.exists():
            print(f"SKIP (missing): {fname}")
            continue
        d = process(p)
        rk = d["client_ranking_status"]
        rs = d["competitor_reselection"]
        print("=" * 74)
        print(fname)
        print(f"  client_ranking : found={rk['found_in_top_10']} "
              f"pos={rk['position']} severity={rk['ranking_severity']}")
        print(f"  original comps : {rs['original_competitors']}")
        print(f"  entity-aware   : {rs['entity_aware_competitors']}")
        print(f"  changed        : {rs['changed']}")
        for ex in rs["exclusions"]:
            print(f"    excluded: {ex['url']}  <-  {ex['reason']}")
    print("\nDone. summary_markdown regenerated (original kept as "
          "summary_markdown_original).")


if __name__ == "__main__":
    main()
