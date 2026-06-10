"""Test the Reverse Engineering Agent.

Run from project root:
  python -m reverse_engineering_agent.test_agent                 # 3 URLs
  python -m reverse_engineering_agent.test_agent https://kk.coach # one URL
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from google.genai import types

from google.adk.runners import InMemoryRunner

from reverse_engineering_agent.agent import reverse_engineering_agent
from reverse_engineering_agent.output_schema import ReverseEngineeringOutput
from reverse_engineering_agent.ranking import render_dual_landscape
from reverse_engineering_agent.postprocess import _split_sections, _classify
from reverse_engineering_agent.tools import persist_re_findings

URLS = [
    "https://www.agrobook.hu",
    "https://www.taxually.com",
    "https://vercel.com/products/vercel-platform",
]
OUT_DIR = Path(__file__).resolve().parent / "test_outputs"
OUT_DIR.mkdir(exist_ok=True)  # at import time, so shell log redirect works
PER_URL_TIMEOUT = 1500  # 25 min ceiling (4 Discovery audits + SERP + compare)


async def run_one(url: str, audit_id: str | None = None,
                  locale: str | None = "hu") -> dict:
    # AAA-31 S2: when the dispatcher supplies an audit_id (the Cloud Tasks job
    # id), thread it into the CLIENT archive so job_id == archive_id. The RE
    # agent calls discovery_agent_tool(role="client") -> _run_discovery_archived,
    # which consumes this forced id once. None => legacy uuid4 (tests unchanged).
    from reverse_engineering_agent.tools import set_client_audit_id
    set_client_audit_id(audit_id)

    # AAA-179: hard-set the crawl Accept-Language from the audit's requested
    # locale (deterministic; never an ambient en-US default). Covers the client
    # + competitor crawls (httpx) and the Playwright escalation for this run.
    from crawler.crawler import set_requested_locale
    set_requested_locale(locale)

    runner = InMemoryRunner(reverse_engineering_agent, app_name="re")
    session = await runner.session_service.create_session(
        app_name="re", user_id="tester"
    )
    msg = types.Content(
        role="user",
        parts=[types.Part(text=f"Reverse-engineer this client URL: {url}")],
    )
    summary, tools_called = "", []
    start = time.perf_counter()

    async def _consume():
        nonlocal summary
        async for ev in runner.run_async(
            user_id="tester", session_id=session.id, new_message=msg
        ):
            for fc in (ev.get_function_calls() or []):
                tools_called.append(fc.name)
            if ev.content and ev.content.parts and ev.content.role == "model":
                t = "".join(p.text for p in ev.content.parts
                            if getattr(p, "text", None))
                if t:
                    summary = t

    timed_out = False
    try:
        await asyncio.wait_for(_consume(), timeout=PER_URL_TIMEOUT)
    except asyncio.TimeoutError:
        timed_out = True

    dur = round(time.perf_counter() - start, 1)
    sess = await runner.session_service.get_session(
        app_name="re", user_id="tester", session_id=session.id
    )
    st = sess.state if sess else {}

    # AAA-146 Sub-step 1 Part 2: enforce the mandatory SERP step. The LLM RE
    # agent occasionally skips emitting dataforseo_serp_query_tool, producing
    # silent 0 competitors (empty query_metadata = _run_serp never ran). If the
    # SERP didn't run, deterministically execute the SERP->select->audit chain
    # from state (keyword + client locale) so an agent skip can't yield a silent
    # empty result. Runs BEFORE persist so re_findings reflect the enforced set.
    serp_ran = bool((st.get("serp_result_branded") or {}).get("query_metadata"))
    serp_enforcement = "not_needed"
    if not serp_ran:
        from reverse_engineering_agent.tools import _enforce_serp_chain
        try:
            serp_enforcement = await _enforce_serp_chain(st)
        except Exception as e:  # noqa: BLE001 — never crash the harness on enforcement
            serp_enforcement = f"error: {type(e).__name__}: {e}"

    # AAA-108 Sub-step 2: persist the assembled re_findings sub-tree onto
    # the CLIENT audit's archived doc (which was written at workflow step 1
    # by _run_discovery_archived). Backfill-pattern dotted-path update —
    # touches only audit_output.re_findings + updated_at. Non-critical on
    # the test path: failure is logged, doesn't kill the harness.
    audit_id_for_re = st.get("current_audit_id") or ""
    re_persist_status = "skipped (no audit_id)"
    if audit_id_for_re:
        try:
            await persist_re_findings(audit_id_for_re, st)
            re_persist_status = "ok"
        except Exception as e:  # noqa: BLE001 — test path tolerates failure
            re_persist_status = f"error: {type(e).__name__}: {e}"

    # AAA-161 Gate 1 — wire the RG1 fact-first data layer (ADDITIVE; no render
    # change). Builds + persists audit_output.fact_base (fact_base_v3) +
    # audit_output.decisions (decisions_v1). MUST run AFTER persist_re_findings
    # (fact_base reads re_findings.competition + eeat_score). Pure/$0/no LLM.
    fact_base_status = "skipped (no audit_id or re_persist not ok)"
    if audit_id_for_re and re_persist_status == "ok":
        from memory.firestore_archive import attach_fact_base_decisions
        fbd = await attach_fact_base_decisions(audit_id_for_re)
        fact_base_status = ("ok" if fbd.get("ok")
                            else f"skip-finding: {fbd.get('_error')}")

    # AAA-202 Gate 3 — success-peer comparison verdict (§9 source). Deterministic
    # pipeline step: AFTER fact_base (prompt input), BEFORE the report render.
    # Skip-finding: never raises; <3 peers → honest note; 0/error → §9 omitted.
    peer_verdict_status = "skipped (no audit_id or re_persist not ok)"
    if audit_id_for_re and re_persist_status == "ok":
        from memory.firestore_archive import attach_peer_verdict
        pv = await attach_peer_verdict(audit_id_for_re)
        peer_verdict_status = (
            "ok (cost=$%.5f%s)" % (pv.get("cost", 0.0),
                                   ", note=%s" % pv["note"] if pv.get("note") else "")
            if pv.get("ok") else "skip-finding: %s" % pv.get("_error")
        )

    # AAA-96 ship — end-of-pipeline customer-facing bilingual render. Runs only
    # after re_findings is persisted (the comparison sections depend on it).
    # Skip-finding: attach_customer_summary never raises; failure -> _error in
    # the status string + a persisted _customer_summary_failed flag, audit intact.
    customer_summary_status = "skipped (no audit_id or re_persist not ok)"
    cs = None
    if audit_id_for_re and re_persist_status == "ok":
        from memory.firestore_archive import attach_customer_summary
        cs = await attach_customer_summary(audit_id_for_re)
        customer_summary_status = (
            f"ok (cost=${cs.get('cost', 0.0):.5f})" if cs.get("ok")
            else f"skip-finding: {cs.get('_error')}"
        )

    # AAA-145 ship — render the customer-facing HTML report(s) to GCS + write the
    # customer_report_html_uri reference. Runs only after the summary translations
    # are attached (they are the render source). Skip-finding: never raises; the
    # HTML is regenerable from the archived audit_output (archive-first).
    customer_report_html_status = "skipped (no summary attached)"
    if audit_id_for_re and isinstance(cs, dict) and cs.get("ok"):
        from memory.firestore_archive import attach_customer_report_html
        ch = await attach_customer_report_html(audit_id_for_re)
        customer_report_html_status = (
            "ok (%d objs)" % len(ch.get("objects") or {}) if ch.get("ok")
            else "skip-finding: %s" % ch.get("_error")
        )

    audits = st.get("audits") or {}
    client_url = st.get("client_url") or url
    comp_urls = st.get("competitor_urls") or []
    ck = audits.get(client_url, {}).get("keywords", {})
    sp = audits.get(client_url, {}).get("site_profile", {})
    serp_b = st.get("serp_result_branded") or {}
    serp_c = st.get("serp_result_category") or {}
    rank_b = st.get("client_ranking_status_branded") or {}
    rank_c = st.get("client_ranking_status_category") or {}
    identical = st.get("serps_identical", False)
    primary_kw = ck.get("primary_keyword") or ""
    category_kw = ck.get("category_keyword") or ""

    # Deterministic Client Identification + dual SERP Landscape + Gap, then
    # the agent's own comparison / AI-Overview narrative (deduped).
    ident = (
        f"## Reverse-engineering report for {url}\n\n"
        f"### Client Identification\n"
        f"- Brand: {sp.get('brand')}\n"
        f"- Target country: {sp.get('location')}\n"
        f"- Branded primary keyword: {primary_kw}\n"
        f"- Category keyword: {category_kw}"
    )
    dual = render_dual_landscape(
        primary_kw, category_kw, client_url, serp_b, serp_c, rank_b, rank_c,
        identical, st.get("branded_competitors") or [],
        st.get("category_competitors") or [],
    )
    kept = []
    for title, body in _split_sections(summary):
        if body and _classify(title) in ("comparison", "ai", "reco"):
            kept.append(f"_{title}_\n\n{body}")
    merged = (
        ident + "\n\n" + dual
        + "\n\n---\n\n### Competitor Comparison & Findings\n\n"
        + ("\n\n".join(kept) if kept else
           "_No comparison narrative produced by the agent._")
    )

    out = ReverseEngineeringOutput(
        client_url=url,
        target_country=sp.get("location") or "",
        primary_keyword=primary_kw,
        category_keyword=category_kw,
        serps_identical=identical,
        serp_result_branded=serp_b,
        serp_result_category=serp_c,
        serp_result=st.get("serp_result") or serp_c,
        branded_competitors=st.get("branded_competitors") or [],
        category_competitors=st.get("category_competitors") or [],
        competitor_urls=comp_urls,
        client_ranking_status_branded=rank_b,
        client_ranking_status_category=rank_c,
        client_ranking_status=rank_c or rank_b,
        client_audit=audits.get(client_url) or {},
        competitor_audits=[audits[u] for u in comp_urls if u in audits],
        comparison=st.get("comparison") or {},
        audit_metadata={
            "tools_called": tools_called,
            "duration_seconds": dur,
            "timed_out": timed_out,
            "discovery_cost_usd": round(
                sum(a.get("_cost", 0.0) for a in audits.values()), 5
            ),
            "serp_cost_usd": round(
                serp_b.get("cost_usd", 0.0)
                + (0.0 if identical else serp_c.get("cost_usd", 0.0)), 5
            ),
            "re_persist_status": re_persist_status,
            "re_persist_audit_id": audit_id_for_re,
            "peer_verdict_status": peer_verdict_status,  # AAA-202 Gate 3
            "customer_summary_status": customer_summary_status,
            "customer_report_html_status": customer_report_html_status,
            "serp_enforcement": serp_enforcement,
        },
        summary_markdown=merged,
        agent_summary_raw=summary,
    )
    return out.model_dump()


async def main():
    urls = sys.argv[1:] or URLS
    OUT_DIR.mkdir(exist_ok=True)
    for url in urls:
        print("=" * 78)
        print(f"[{datetime.now():%H:%M:%S}] Reverse-engineering {url} ...")
        data = await run_one(url)
        m = data["audit_metadata"]
        comp = data["comparison"]
        print(f"  target_country   : {data['target_country']}")
        print(f"  primary_keyword  : {data['primary_keyword']}")
        print(f"  competitor_urls  : {data['competitor_urls']}")
        print(f"  AI Overview      : "
              f"{data['serp_result'].get('ai_overview_present')}")
        print(f"  pattern findings : {len(comp.get('patterns', []))}")
        print(f"  tools called     : {m['tools_called']}")
        print(f"  duration (s)     : {m['duration_seconds']} "
              f"(timed_out={m['timed_out']})")
        dom = urlparse(url).netloc or "site"
        p = OUT_DIR / f"{dom}.json"
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                     encoding="utf-8")
        print(f"  saved            : {p}")


if __name__ == "__main__":
    asyncio.run(main())
