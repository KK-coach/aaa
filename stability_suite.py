"""AAA-22 stability suite: 5 URLs x 3 runs of the Discovery agent.

Serial, identical config. Captures _model_version, category_keyword,
topic_cluster, serp_strategy, token usage (vertex + ADK agent model),
measured USD cost, duration, errors, and a hallucination scan vs source.

Run:  python -m stability_suite
Outputs: stability/<slug>/run-<n>.json + stability/_summary.json
"""

import asyncio
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from google.genai import types

from google.adk.runners import InMemoryRunner

from crawler import crawl_html
from discovery_agent.agent import discovery_agent
from site_profile.gemini_analyzer import MODEL, get_usage, reset_usage

URLS = [
    "https://www.agrobook.hu",
    "https://kk.coach",
    "https://www.aboutyou.hu",
    "https://www.taxually.com",
    "https://vercel.com/products/vercel-platform",
]
RUNS = 3
OUT = Path(__file__).resolve().parent / "stability"

# Verbatim mirror of discovery_agent/test_agent.py's low-grounding warning.
WARNING = (
    "> ⚠️ **AUDIT CONFIDENCE: LOW**\n"
    "> This site delivered limited content to search crawlers at the "
    "time of audit (JS-heavy rendering or thin server-side HTML). The "
    "audit was performed on the content available, but specific "
    "product, technology, or branding claims should be verified "
    "manually. This itself is an SEO/GEO finding: AI assistants and "
    "search bots see what we saw, not the full client-side "
    "experience.\n\n"
)
PRICE_IN_PER_M = 0.50    # USD / 1M input tokens (Gemini 3 Flash)
PRICE_OUT_PER_M = 3.00   # USD / 1M output tokens (incl. thinking)
ABORT = None  # set to a string -> suite stops


def _slug(u: str) -> str:
    p = urlparse(u)
    return (p.netloc + p.path).strip("/").replace("/", "_").replace(".", "-")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower())


def _halluc_candidates(summary: str, source_text: str) -> list[str]:
    """Proper-noun / person-name sequences in summary absent from source."""
    src = _norm(source_text)
    cands = set()
    # 2-4 TitleCase word sequences (orgs, products, people)
    for m in re.findall(r"\b([A-Z][\w.&-]+(?:\s+[A-Z][\w.&-]+){1,3})\b",
                         summary):
        token = m.strip()
        if len(token) < 4:
            continue
        if _norm(token) not in src:
            cands.add(token)
    # obvious "Firstname Lastname" person pattern (Kevin-Kwok class)
    persons = {
        p for p in re.findall(r"\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b", summary)
        if _norm(p) not in src
    }
    out = sorted(cands | persons)
    # Drop generic SEO/audit phrasing that is not a real entity claim.
    stop = ("Audit", "Summary", "Core Web", "Page Speed", "AI Overview",
            "Schema", "Content", "Target", "Brand", "Primary", "Google")
    return [c for c in out if not any(c.startswith(s) for s in stop)]


async def one_run(url: str, run_no: int, source_text: str) -> dict:
    global ABORT
    runner = InMemoryRunner(discovery_agent, app_name="stab")
    session = await runner.session_service.create_session(
        app_name="stab", user_id="s"
    )
    msg = types.Content(role="user",
                        parts=[types.Part(text=f"Audit this URL: {url}")])
    reset_usage()
    adk_in = adk_out = adk_tot = 0
    tools, errors, summary = [], [], ""
    t0 = time.perf_counter()
    try:
        async for ev in runner.run_async(
            user_id="s", session_id=session.id, new_message=msg
        ):
            um = getattr(ev, "usage_metadata", None)
            if um is not None:
                adk_in += getattr(um, "prompt_token_count", 0) or 0
                adk_tot += getattr(um, "total_token_count", 0) or 0
                adk_out += (getattr(um, "candidates_token_count", 0) or 0)
            for fc in (ev.get_function_calls() or []):
                tools.append(fc.name)
            if ev.content and ev.content.parts and ev.content.role == "model":
                txt = "".join(p.text for p in ev.content.parts
                              if getattr(p, "text", None))
                if txt:
                    summary = txt
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")

    dur = round(time.perf_counter() - t0, 1)
    vx = get_usage()
    sess = await runner.session_service.get_session(
        app_name="stab", user_id="s", session_id=session.id
    )
    st = sess.state if sess else {}
    sp = st.get("site_profile") or {}
    kw = st.get("keywords") or {}
    en = st.get("entities") or {}

    mv = {
        "site_profile": sp.get("_model_version"),
        "keywords": kw.get("_model_version"),
        "entities": en.get("_model_version"),
    }
    # ADK output incl. thinking tokens = total - input
    adk_out_eff = max(adk_out, adk_tot - adk_in) if adk_tot else adk_out
    in_tok = vx["prompt"] + adk_in
    out_tok = (vx["total"] - vx["prompt"] if vx["total"] else vx["candidates"]) \
        + adk_out_eff
    cost = round(in_tok * PRICE_IN_PER_M / 1e6
                 + out_tok * PRICE_OUT_PER_M / 1e6, 6)

    halluc = _halluc_candidates(summary, source_text)

    # Mirror test_agent's deterministic warning injection so the baseline
    # measures the SHIPPED artifact (warning iff grounding_confidence==low).
    gc = st.get("grounding_confidence")
    if gc == "low":
        summary = WARNING + (summary or "")
    rec = {
        "url": url, "run": run_no, "duration_s": dur,
        "model_versions": mv,
        "category_keyword": kw.get("category_keyword"),
        "topic_cluster": kw.get("topic_cluster"),
        "serp_strategy": sp.get("serp_strategy"),
        "grounding_confidence": gc,
        "warning_present": WARNING.strip() in (summary or ""),
        "brand": sp.get("brand"),
        "tokens": {"vertex": vx, "adk_in": adk_in, "adk_out_eff": adk_out_eff,
                   "in": in_tok, "out": out_tok},
        "cost_usd": cost,
        "tools": tools,
        "errors": errors,
        "halluc_candidates": halluc,
        "summary_markdown": summary,
    }

    # --- abort checks (deterministic only) ---
    bad_mv = [k for k, v in mv.items() if v not in (None, MODEL)]
    if bad_mv:
        ABORT = f"MODEL DRIFT {url} run{run_no}: {mv}"
    if any(re.search(r"thought signature|INVALID_ARGUMENT|\b400\b", e)
           for e in errors):
        ABORT = f"AGENT ERROR {url} run{run_no}: {errors}"
    return rec


async def main() -> None:
    global ABORT
    OUT.mkdir(exist_ok=True)
    all_recs, src_cache, total_cost = [], {}, 0.0
    for url in URLS:
        cr = await crawl_html(url)
        src_cache[url] = (cr.get("content") or {}).get("visible_text", "") \
            + " " + json.dumps(cr.get("brand_context") or {}, ensure_ascii=False)
        slug = _slug(url)
        (OUT / slug).mkdir(exist_ok=True)
        for n in range(1, RUNS + 1):
            print(f"[{time.strftime('%H:%M:%S')}] {url} run {n}/{RUNS} ...",
                  flush=True)
            rec = await one_run(url, n, src_cache[url])
            (OUT / slug / f"run-{n}.json").write_text(
                json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            all_recs.append(rec)
            total_cost += rec["cost_usd"]
            print(f"   dur={rec['duration_s']}s cost=${rec['cost_usd']:.5f} "
                  f"cat={rec['category_keyword']!r} mv_ok="
                  f"{set(v for v in rec['model_versions'].values() if v)} "
                  f"halluc={len(rec['halluc_candidates'])}", flush=True)
            if ABORT:
                print(f"!!! ABORT: {ABORT}", flush=True)
                break
            if total_cost > 2.0 or (len(all_recs) == 5 and total_cost > 1.0):
                ABORT = f"COST SANITY: ${total_cost:.4f} after {len(all_recs)}"
                print(f"!!! ABORT: {ABORT}", flush=True)
                break
        if ABORT:
            break
        # --- per-URL post-3-run abort checks (AAA-51 re-baseline) ---
        u_recs = [r for r in all_recs if r["url"] == url]
        if len(u_recs) == RUNS:
            for fld in ("category_keyword", "topic_cluster", "serp_strategy"):
                vals = {r[fld] for r in u_recs}
                if len(vals) != 1:
                    ABORT = f"DRIFT {url} {fld}: {[r[fld] for r in u_recs]}"
            is_vercel = "vercel.com" in url
            want_gc = "low" if is_vercel else "high"
            for r in u_recs:
                if r["grounding_confidence"] != want_gc:
                    ABORT = (f"GROUNDING MISMATCH {url} run{r['run']}: "
                             f"{r['grounding_confidence']} (want {want_gc})")
                want_warn = is_vercel
                if r["warning_present"] != want_warn:
                    ABORT = (f"WARNING MISMATCH {url} run{r['run']}: "
                             f"present={r['warning_present']} "
                             f"(want {want_warn})")
            if ABORT:
                print(f"!!! ABORT: {ABORT}", flush=True)
                break
    (OUT / "_summary.json").write_text(
        json.dumps({"records": all_recs, "total_cost_usd": round(total_cost, 5),
                    "aborted": ABORT}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nDONE runs={len(all_recs)} total_cost=${total_cost:.5f} "
          f"aborted={ABORT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
