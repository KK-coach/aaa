"""The 7 existing modules wrapped as ADK FunctionTools.

Design: large payloads (crawl results, profiles) are NOT shuttled back
through the LLM. Each tool stores its full result in ``tool_context.state``
and returns a SMALL summary to the model so it can reason cheaply about
what to do next. The test harness reconstructs the full AuditOutput from
session state afterwards.

State keys: crawl, rendered_crawl, active_crawl, site_profile, keywords,
entities, pagespeed, indexing, _cost, _tools.
"""

from __future__ import annotations

import asyncio
import re

from google.adk.tools import FunctionTool, ToolContext

from crawler import crawl_html
from crawler.crawler import parse_rendered_html
from playwright_poc.render import render_url
from site_profile import analyze_site_profile
from page_analysis import extract_entities, extract_target_keywords
from page_analysis._gemini import compute_grounding_confidence, select_body
# AAA-116 Sub-step 1 — legacy classify_page_type DEPRECATED 2026-05-26.
# Kept on disk but no longer imported here. AAA-81 v3 multi_dim_classify
# is the sole page_type source of truth.
# from page_analysis.classify_page import classify_page_type  # noqa: ERA001
from pagespeed.client import get_pagespeed_score

def _bump(ctx: ToolContext, tool: str) -> None:
    """Track which tools ran. Cost is measured from real usage_metadata
    at the audit boundary (AAA-50) - no per-call estimate constant."""
    state = ctx.state
    state["_tools"] = (state.get("_tools") or []) + [tool]


def _mc(crawl: dict) -> dict:
    return (crawl or {}).get("main_content") or {}


async def crawl_html_tool(url: str, tool_context: ToolContext) -> dict:
    """Fetch a URL with a fast HTTP crawler (no JavaScript). ALWAYS call this
    first. Returns technical/content/schema signals and whether a Playwright
    re-crawl is recommended.

    Args:
        url: The absolute URL to crawl.
    """
    result = await crawl_html(url)
    tool_context.state["crawl"] = result
    tool_context.state["active_crawl"] = result
    _bump(tool_context, "crawl_html")

    if result.get("error"):
        return {"error": result["error"], "error_type": result.get("error_type")}

    mc = _mc(result)
    spa = (result.get("javascript_indicators") or {}).get("spa_indicators", [])
    escalate = (
        mc.get("extraction_method") == "fallback_full_body"
        or (mc.get("confidence") or 1.0) < 0.5
        or bool(spa)
    )
    return {
        "status_code": result.get("status_code"),
        "main_content_method": mc.get("extraction_method"),
        "main_content_confidence": mc.get("confidence"),
        "main_content_words": mc.get("words"),
        "spa_indicators": spa,
        "playwright_escalation_recommended": escalate,
    }


async def crawl_with_playwright_tool(url: str, tool_context: ToolContext) -> dict:
    """Re-crawl a URL with a real headless browser (executes JavaScript), then
    parse the rendered DOM into the SAME schema as crawl_html. Call this when
    crawl_html recommends escalation (fallback_full_body / low confidence /
    SPA) or when a later tool reports [CONTENT LIMITED].

    Args:
        url: The absolute URL to render and re-crawl.
    """
    rendered = await render_url(url)
    if rendered.get("error"):
        _bump(tool_context, "crawl_with_playwright")
        return {"error": rendered["error"],
                "error_type": rendered.get("error_type")}

    parsed = parse_rendered_html(
        url,
        rendered.get("rendered_html", ""),
        rendered.get("status_code", 200),
        rendered.get("render_time_ms", 0),
    )
    tool_context.state["rendered_crawl"] = parsed
    _bump(tool_context, "crawl_with_playwright")

    active_mc = _mc(tool_context.state.get("active_crawl") or {})
    new_mc = _mc(parsed)
    old_conf = active_mc.get("confidence") or 0
    new_conf = new_mc.get("confidence") or 0
    old_words = active_mc.get("words") or 0
    new_words = new_mc.get("words") or 0

    # Only replace the HTTP crawl if the rendered DOM is genuinely better:
    # higher confidence, OR a tie on confidence but strictly more content.
    # This blocks the Vercel case where a bot-blocked / pre-RSC-streaming
    # shell renders at equal confidence but FEWER words.
    rendered_better = new_conf > old_conf
    rendered_tie_but_more_content = (
        new_conf == old_conf and new_words > old_words
    )
    promoted = (not parsed.get("error")) and (
        rendered_better or rendered_tie_but_more_content
    )
    if promoted:
        tool_context.state["active_crawl"] = parsed
    else:
        print(
            f"[discovery_agent] Rendered crawl NOT promoted: confidence "
            f"{new_conf}=={old_conf} but words {new_words}<{old_words} "
            f"(keeping HTTP crawl as active_crawl for {url})"
            if new_conf == old_conf
            else (
                f"[discovery_agent] Rendered crawl NOT promoted: confidence "
                f"{new_conf}<{old_conf}, words {new_words} vs {old_words} "
                f"(keeping HTTP crawl as active_crawl for {url})"
            )
        )

    return {
        "rendered_main_content_method": _mc(parsed).get("extraction_method"),
        "rendered_main_content_confidence": _mc(parsed).get("confidence"),
        "rendered_main_content_words": _mc(parsed).get("words"),
        "promoted_to_active": promoted,
        "error": parsed.get("error"),
    }


async def analyze_site_profile_tool(tool_context: ToolContext) -> dict:
    """Determine SITE-level profile (brand, industry, target country/language,
    audience) from the most recent crawl. Call AFTER crawl_html (and after
    Playwright escalation if it happened).
    """
    crawl = tool_context.state.get("active_crawl") or tool_context.state.get(
        "crawl"
    )
    if not crawl:
        return {"error": "no crawl in state - call crawl_html first"}
    profile = await analyze_site_profile(crawl)
    tool_context.state["site_profile"] = profile
    _bump(tool_context, "analyze_site_profile")
    # AAA-51: grounding confidence from the content actually synthesized.
    gc = compute_grounding_confidence(crawl)
    tool_context.state["grounding_confidence"] = gc
    # Surface the real identity signals so the agent's final synthesis uses
    # the actual owner/author name instead of pattern-completing initials.
    bc = crawl.get("brand_context") or {}
    return {
        "brand": profile.get("brand"),
        "industry": profile.get("industry"),
        "location": profile.get("location"),
        "language": profile.get("language"),
        "audience": profile.get("audience"),
        "needs_user_confirmation": profile.get("needs_user_confirmation"),
        "main_entities": profile.get("main_entities", []),
        "brand_context": {
            "json_ld_entities": bc.get("json_ld_entities", []),
            "meta_author": bc.get("meta_author"),
            "og_site_name": bc.get("og_site_name"),
            "twitter_creator": bc.get("twitter_creator"),
            "footer_text": (bc.get("footer_text") or "")[:300],
        },
        "grounding_confidence": gc,
        "error": profile.get("error"),
    }


async def extract_target_keywords_tool(tool_context: ToolContext) -> dict:
    """Extract the keywords/topics this page targets. Requires crawl_html and
    analyze_site_profile to have run first.
    """
    crawl = tool_context.state.get("active_crawl")
    profile = tool_context.state.get("site_profile")
    if not crawl or not profile:
        return {"error": "need crawl + site_profile first"}
    kw = await extract_target_keywords(crawl, profile)
    tool_context.state["keywords"] = kw
    _bump(tool_context, "extract_target_keywords")
    reasoning = kw.get("reasoning", "") or ""
    return {
        "primary_keyword": kw.get("primary_keyword"),
        "category_keyword": kw.get("category_keyword"),
        "topic_cluster": kw.get("topic_cluster"),
        "intent": kw.get("intent"),
        "estimated_difficulty": kw.get("estimated_difficulty"),
        "keyword_gap_severity": kw.get("keyword_gap_severity"),
        "gap_interpretation": kw.get("gap_interpretation"),
        # capped to keep the agent context lean
        "secondary_keywords": (kw.get("secondary_keywords") or [])[:5],
        "long_tail_keywords": (kw.get("long_tail_keywords") or [])[:5],
        "content_limited": "[CONTENT LIMITED" in reasoning,
        "_model_version": kw.get("_model_version"),
    }


_SOCIAL_RE = re.compile(
    r"https?://(?:www\.)?(?:linkedin\.com|twitter\.com|x\.com|facebook\.com|"
    r"instagram\.com|youtube\.com|github\.com)/[^\s\"'<>)]+",
    re.I,
)


def _norm_name(s: str) -> str:
    """'@Krisztian__Kiss' / 'Krisztian__Kiss' -> 'Krisztian Kiss'."""
    s = (s or "").strip()
    if s.startswith("@"):
        s = s[1:]
    s = re.sub(r"_+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _dedup(values) -> list[str]:
    """Case-insensitive dedup preserving first-seen display form."""
    out, seen = [], set()
    for v in values:
        if not isinstance(v, str):
            continue
        disp = _norm_name(v)
        key = disp.casefold()
        if disp and key not in seen:
            seen.add(key)
            out.append(disp)
    return out


def _jsonld_by_type(crawl: dict, want: str) -> list[str]:
    bc = (crawl or {}).get("brand_context") or {}
    names = []
    for e in bc.get("json_ld_entities") or []:
        if isinstance(e, dict) and str(e.get("type", "")).lower() == want:
            n = e.get("name")
            if isinstance(n, str) and n.strip():
                names.append(n.strip())
    return names


def _collect_eeat_signals(crawl: dict, profile: dict, ent: dict) -> dict:
    bc = (crawl or {}).get("brand_context") or {}
    profile = profile or {}
    ent = ent or {}

    brand_mentions = _dedup(
        [profile.get("brand"), bc.get("og_site_name")]
        + _jsonld_by_type(crawl, "organization")
    )

    # Authoritative people sources (union). main_entities only CORROBORATES
    # an already-found person (prevents pulling 'GA4'/brand as a person).
    people_sources = (
        list(ent.get("people") or [])
        + _jsonld_by_type(crawl, "person")
        + ([bc["meta_author"]] if bc.get("meta_author") else [])
        + ([bc["twitter_creator"]] if bc.get("twitter_creator") else [])
    )
    named_people = _dedup(people_sources)
    people_keys = {p.casefold() for p in named_people}
    for me in profile.get("main_entities") or []:
        if isinstance(me, str) and _norm_name(me).casefold() in people_keys:
            pass  # already represented; corroboration only, no new entry

    # social proof: schema sameAs + twitter handle + footer social URLs
    same_as = []
    for e in bc.get("json_ld_entities") or []:
        sa = e.get("sameAs") if isinstance(e, dict) else None
        if isinstance(sa, str):
            same_as.append(sa)
        elif isinstance(sa, list):
            same_as += [x for x in sa if isinstance(x, str)]
    footer_links = _SOCIAL_RE.findall(bc.get("footer_text") or "")
    tw = bc.get("twitter_creator")
    social = []
    seen_s = set()
    for s in same_as + ([tw] if tw else []) + footer_links:
        if isinstance(s, str) and s.strip() and s.lower() not in seen_s:
            seen_s.add(s.lower())
            social.append(s.strip())

    return {
        "brand_mentions": brand_mentions,
        "named_people": named_people,
        "social_proof_links": social,
    }


async def extract_entities_tool(tool_context: ToolContext) -> dict:
    """Extract page-level named entities (products, orgs, people, places,
    technologies, concepts). Requires crawl_html and analyze_site_profile.
    """
    crawl = tool_context.state.get("active_crawl")
    profile = tool_context.state.get("site_profile")
    if not crawl or not profile:
        return {"error": "need crawl + site_profile first"}
    ent = await extract_entities(crawl, profile)
    tool_context.state["entities"] = ent
    _bump(tool_context, "extract_entities")
    cats = ("products", "organizations", "people", "places", "technologies",
            "concepts")
    reasoning = ent.get("reasoning", "") or ""
    # AAA-48: counts for ALL 6 (empty count is a signal, e.g. people=0 ->
    # no named author/E-E-A-T gap); names sample only for non-empty cats,
    # capped at 5 in the upstream model's own priority (insertion) order.
    sample = {
        c: ent.get(c, [])[:5]
        for c in cats
        if isinstance(ent.get(c), list) and ent.get(c)
    }
    eeat_signals = _collect_eeat_signals(crawl, profile, ent)
    # AAA-116 (Sub-step 1, 2026-05-26): AAA-55 classify_page_type DEPRECATED.
    # The legacy 11-value taxonomy classifier ran here and wrote state[
    # "page_type"]. Empirical evidence (AAA-81 S1+S2: 45/45 = 100% multi-dim
    # success on diverse leaves) cleared this for clean removal. The new
    # source of truth is classify_multi_dim (called in
    # discovery_agent/test_agent.py::audit AFTER write_audit's AuditOutput
    # construction) which emits AAA-81 v3's 27-leaf taxonomy and overwrites
    # `out.page_type`. On multi-dim failure, the default falls back to
    # "other_or_unknown" (AAA-81 v3 safety bucket; see test_agent.py).
    # The legacy classify_page_type function and PAGE_TYPES constant remain
    # in page_analysis/classify_page.py (unused, not deleted per AAA-116
    # surgical-removal scope).
    tool_context.state["eeat_signals"] = eeat_signals
    return {
        "entity_counts": {c: len(ent.get(c, []) or []) for c in cats},
        "entities_sample": sample,
        "eeat_signals": eeat_signals,
        "content_limited": "[CONTENT LIMITED" in reasoning,
        "_model_version": ent.get("_model_version"),
    }


async def pagespeed_score_tool(url: str, tool_context: ToolContext) -> dict:
    """Get Google PageSpeed Insights for BOTH mobile and desktop (run
    concurrently). Returns category scores + Core Web Vitals.

    Args:
        url: The absolute URL to measure.
    """
    mobile, desktop = await asyncio.gather(
        get_pagespeed_score(url, "mobile"),
        get_pagespeed_score(url, "desktop"),
    )
    combined = {"mobile": mobile, "desktop": desktop}
    tool_context.state["pagespeed"] = combined
    _bump(tool_context, "pagespeed_score")

    def _scores(r: dict) -> dict:
        return {} if r.get("error") else r.get("scores", {})

    return {
        "mobile_scores": _scores(mobile),
        "desktop_scores": _scores(desktop),
        "mobile_error": mobile.get("error"),
        "desktop_error": desktop.get("error"),
    }


# AAA-136 — indexing / canonicalization via QUOTED exact-URL SERP detection.
# The `site:` operator was unreliable (false-negative on the agrobook homepage
# — domain indexed but exact homepage absent from site: top-10). Replaced with
# a quoted exact-URL phrase search per the 4 scheme×host variants; a variant is
# indexed iff the FIRST organic result normalize-equals it. Locale maps the
# audit language to the SERP country-name + ISO code expected by
# reverse_engineering_agent.tools._run_serp. Mirrors keywords_volume map.
_INDEXING_LOCATION_NAME = {"hu": "Hungary", "en": "United States"}


def _normalize_url_for_match(u: str) -> str:
    """Normalize a URL for indexed-match comparison: drop scheme + leading www.
    + trailing slash + STRIP query string (incl. Google's `?srsltid=` tracking)
    and fragment; lowercase. So http⇄https / www / trailing-slash / tracking-
    param variants all compare equal (AAA-136 matching rule)."""
    s = (u or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    s = s.split("?", 1)[0].split("#", 1)[0]
    return s.rstrip("/")


def _canonical_key(u: str) -> str:
    """AAA-138: scheme/www-PRESERVING key for canonical comparison. Unlike
    _normalize_url_for_match (which collapses scheme+www for indexed-membership),
    this KEEPS scheme and www — strips only the query (incl. `srsltid`),
    fragment, and trailing slash, lowercased. So https://www.x.com/ and
    http://x.com compare as DIFFERENT (a real http↔https / www↔apex split must
    surface), while https://www.x.com/?srsltid=… == https://www.x.com."""
    s = (u or "").strip().lower()
    s = s.split("?", 1)[0].split("#", 1)[0]
    return s.rstrip("/")


def _select_canonical(indexed_variants: list[dict],
                      rel_canonical: str | None) -> "tuple[str | None, bool]":
    """AAA-138: pick canonical_indexed + compute canonical_mismatch (pure, so
    it is unit-testable without a live SERP).

    Order: (1) the live_200=True indexed variant (direct-200 non-redirecting
    endpoint = the true canonical); (2) the indexed variant whose scheme/www-
    PRESERVED key matches rel_canonical; (3) first indexed. mismatch = rel
    present AND its PRESERVED key != canonical_indexed's preserved key."""
    if not indexed_variants:
        return None, False
    rc_key = _canonical_key(rel_canonical) if rel_canonical else None
    canonical_indexed = (
        next((x["url"] for x in indexed_variants if x.get("live_200")), None)
        or next((x["url"] for x in indexed_variants
                 if rc_key and _canonical_key(x["url"]) == rc_key), None)
        or indexed_variants[0]["url"]
    )
    mismatch = bool(
        rel_canonical and canonical_indexed
        and _canonical_key(rel_canonical) != _canonical_key(canonical_indexed)
    )
    return canonical_indexed, mismatch


def _url_variants(url: str) -> list[str]:
    """The 4 scheme×host variants of `url`, path PRESERVED (works for deep
    pages, not just homepages): http/https × bare-domain/www. Ordered
    [http://bare, https://bare, http://www, https://www]."""
    from urllib.parse import urlparse

    p = urlparse(url if "://" in (url or "") else f"https://{url or ''}")
    host = (p.netloc or "").lower()
    bare = host[4:] if host.startswith("www.") else host
    tail = p.path or ""
    if p.query:
        tail += f"?{p.query}"
    return [
        f"http://{bare}{tail}",
        f"https://{bare}{tail}",
        f"http://www.{bare}{tail}",
        f"https://www.{bare}{tail}",
    ]


def _head_resolve(variant: str) -> tuple[list, str | None, bool]:
    """Light HTTP HEAD (follow redirects) -> (status_chain, final_url,
    live_200). HEAD blocked/unavailable -> (["unknown"], None, False), never
    raises (skip-finding). $0 — no body fetched."""
    try:
        import httpx

        with httpx.Client(follow_redirects=True, timeout=15,
                          headers={"User-Agent": "AAA-136-indexing/0"}) as c:
            r = c.head(variant)
        chain = [resp.status_code for resp in r.history] + [r.status_code]
        return chain, str(r.url), (len(r.history) == 0 and r.status_code == 200)
    except Exception as e:  # noqa: BLE001 — skip-finding
        logger.info("indexing HEAD failed for %s: %s", variant, e)
        return ["unknown"], None, False


async def check_indexing_status_tool(url: str, tool_context: ToolContext) -> dict:
    """AAA-136: indexing + canonicalization via quoted exact-URL SERP detection.

    Builds the 4 scheme×host variants of `url` (path preserved). For the audited
    variant, redirect/canonical are REUSED from state["crawl"] (0 re-fetch); the
    other 3 get a light HEAD. Each variant gets one quoted exact-URL Google SERP
    query — indexed iff result #1 normalize-equals the variant. Aggregates into
    audit_output.indexing. Skip-finding: SERP failure -> indexed "unknown",
    cost 0, _error; the audit continues.

    Args:
        url: The absolute URL whose index status is checked (full path used).
    """
    # Deferred import — RE tools import discovery_agent at module load, so a
    # top-level import here would be circular.
    from reverse_engineering_agent.tools import _run_serp

    sp = tool_context.state.get("site_profile") or {}
    lang = str(sp.get("language") or "").strip().lower()[:2]
    lang = lang if lang in ("hu", "en") else "en"
    location = _INDEXING_LOCATION_NAME.get(lang, "United States")

    crawl = tool_context.state.get("crawl") or {}
    rel_canonical = (
        ((crawl.get("technical") or {}).get("canonical") or {}).get("value")
    )
    crawl_final = crawl.get("url")
    crawl_redirects = (crawl.get("technical") or {}).get("redirect_chain") or []
    crawl_status = crawl.get("status_code")
    # Audited-variant dispatch uses an EXACT key (scheme+host+path, trailing-
    # slash/fragment-tolerant) — NOT _normalize_url_for_match, which drops
    # scheme+www and would match ALL 4 variants, collapsing their per-variant
    # redirect resolution onto the audited one. Only the true audited variant
    # reuses state["crawl"]; the other 3 get a real HEAD.
    def _exact_key(u: str) -> str:
        s = (u or "").strip().lower().split("#", 1)[0]
        return s.rstrip("/")

    audited_key = _exact_key(url)

    # AAA-151: also query the redirect-resolved / canonical URL. Google indexes
    # the canonical of a redirecting request URL (e.g. /hu/ 301-> /hu/index-hu/),
    # so the 4 request-URL variants alone miss it. Append the canonical target
    # (rel_canonical, else the crawl's resolved final URL) when it is distinct
    # from the 4 variants. For non-redirect / self-canonical URLs it dedupes to
    # an existing variant -> NO extra query, NO behaviour change.
    query_urls = list(_url_variants(url))
    canonical_target = rel_canonical or crawl_final
    if canonical_target and _exact_key(canonical_target) not in {
        _exact_key(x) for x in query_urls
    }:
        query_urls.append(canonical_target)

    variants_out: list[dict] = []
    any_error = None
    total_cost = 0.0

    for v in query_urls:
        # --- redirect/final resolution ---
        if _exact_key(v) == audited_key:
            # REUSE state["crawl"] for the audited variant — 0 extra fetch.
            status_chain = [crawl_status] if crawl_status else ["reused"]
            final_url = crawl_final
            live_200 = (
                len(crawl_redirects) <= 1 and crawl_status == 200
                and _exact_key(crawl_final) == audited_key
            )
        else:
            status_chain, final_url, live_200 = await asyncio.to_thread(
                _head_resolve, v
            )

        # --- quoted exact-URL indexed check ---
        serp = await _run_serp(f'"{v}"', location, lang, depth=10)
        if serp.get("error"):
            any_error = serp.get("error")
            indexed_v, first_url, position = None, None, None  # unknown
        else:
            total_cost += float(serp.get("cost_usd") or 0.0)
            org = serp.get("organic_results") or []
            first = org[0] if org else None
            first_url = first.get("url") if first else None
            # AAA-151: a variant is indexed if SERP result #1 normalize-equals
            # the queried URL OR its resolved final_url OR rel_canonical (the
            # URL Google actually indexed for a redirecting request URL). For a
            # non-redirect self-canonical URL the accept set collapses to {v},
            # so this is identical to the previous exact-match behaviour.
            accept = {
                _normalize_url_for_match(x)
                for x in (v, final_url, rel_canonical) if x
            }
            indexed_v = bool(
                first_url and _normalize_url_for_match(first_url) in accept
            )
            position = first.get("position") if (first and indexed_v) else None

        variants_out.append({
            "url": v,
            "status_chain": status_chain,
            "final_url": final_url,
            "live_200": live_200,
            "indexed": indexed_v,
            "first_result_url": first_url,
            "position": position,
        })

    # --- aggregate ---
    indexed_variants = [x for x in variants_out if x["indexed"] is True]
    any_known = any(x["indexed"] is not None for x in variants_out)
    if indexed_variants:
        site_indexed: bool | str = True
    elif any_known:
        site_indexed = False
    else:
        site_indexed = "unknown"  # every variant's SERP errored

    # AAA-138: canonical_indexed leads with the live_200 endpoint (true
    # canonical), then rel_canonical match via the scheme/www-PRESERVING key,
    # then first-indexed; canonical_mismatch uses the PRESERVING key so a real
    # http<->https / www<->apex split surfaces. (Indexed-membership above still
    # uses the collapsing _normalize_url_for_match — correct there.)
    canonical_indexed, canonical_mismatch = _select_canonical(
        indexed_variants, rel_canonical)

    # duplication: >1 distinct live(200,non-redirect) variant independently indexed
    duplication_signal = sum(
        1 for x in indexed_variants if x["live_200"]
    ) > 1

    result = {
        "requested_url": url,
        "method": "quoted_url_serp",
        "variants": variants_out,
        "indexed": site_indexed,
        "canonical_indexed": canonical_indexed,
        "rel_canonical": rel_canonical,
        "duplication_signal": duplication_signal,
        "canonical_mismatch": canonical_mismatch,
        "cost_usd": round(total_cost, 6) if site_indexed != "unknown" else 0.0,
    }
    if any_error:
        result["_error"] = any_error
    tool_context.state["indexing"] = result
    _bump(tool_context, "check_indexing_status")
    return result


# --- ADK FunctionTool wrappers ---
crawl_html_ft = FunctionTool(crawl_html_tool)
crawl_with_playwright_ft = FunctionTool(crawl_with_playwright_tool)
analyze_site_profile_ft = FunctionTool(analyze_site_profile_tool)
extract_target_keywords_ft = FunctionTool(extract_target_keywords_tool)
extract_entities_ft = FunctionTool(extract_entities_tool)
pagespeed_score_ft = FunctionTool(pagespeed_score_tool)
check_indexing_status_ft = FunctionTool(check_indexing_status_tool)

ALL_TOOLS = [
    crawl_html_ft,
    crawl_with_playwright_ft,
    analyze_site_profile_ft,
    extract_target_keywords_ft,
    extract_entities_ft,
    pagespeed_score_ft,
    check_indexing_status_ft,
]
