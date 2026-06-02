"""Reverse Engineering Agent (AAA-20).

ARCHITECTURE NOTE on the sub-agent pattern: ADK's AgentTool copies parent
state into the child and forwards the child's state_delta back - BUT the
Discovery Agent writes the SAME flat state keys (crawl, site_profile, ...)
every run, so auditing client + 3 competitors through one AgentTool would
overwrite each prior audit, and AgentTool only returns the child's final
markdown (our Discovery deliberately keeps structured data in state). So
`discovery_agent_tool` is a FunctionTool that runs the REAL discovery_agent
via a nested runner and harvests its full session state, namespacing each
audit per-URL. This reuses 100% of Discovery logic with zero duplication.
"""

from __future__ import annotations

import os

from site_profile.gemini_analyzer import MODEL, _resolve_project

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
_proj = _resolve_project()
if _proj and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = _proj
# Hard-set the location — gemini-3-flash-preview only exists in 'global'.
# Override any pre-existing env var to prevent silent 404 from polluted
# shells/CI/deployment (AAA-62; surfaced in AAA-61 S1 smoke first-run).
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
assert os.environ.get("GOOGLE_CLOUD_LOCATION") == "global", (
    f"GOOGLE_CLOUD_LOCATION must be 'global' for gemini-3-flash-preview, "
    f"got: {os.environ.get('GOOGLE_CLOUD_LOCATION')!r}"
)

from google.adk.agents import Agent  # noqa: E402

from reverse_engineering_agent.tools import ALL_TOOLS  # noqa: E402

REVERSE_ENGINEERING_SYSTEM_PROMPT = """\
CRITICAL - PROVENANCE CONSTRAINT:
Every named entity (product, technology, framework, brand, person, place,
organization) you mention in your output MUST appear verbatim in the provided
source content above - which includes the main article content, brand
metadata (JSON-LD entities, meta tags, Twitter/OG tags, footer, address),
schema types, and the site profile fields.

If a named entity does not appear in any of these sources, do one of the
following:
1. Omit it entirely, OR
2. Refer to it generically (e.g., "their deployment platform" instead of
   "Next.js", "the founder" instead of an invented name).

Do not pattern-match from domain names, brand initials, or general industry
knowledge. If you cannot identify something specifically from the provided
sources, that absence is itself useful information for the audit - surface it
as "not identifiable from public-facing content" rather than guessing.

You are an expert SEO/GEO competitor analysis agent. Analyze a client URL by
comparing it against the top-ranking competitors for its primary keyword.

WORKFLOW
1. Call `discovery_agent_tool` with role="client", target_country="" (unless
   the user explicitly provided one) on the client URL.
2. Check the returned serp_strategy / needs_user_confirmation:
   - If serp_strategy == "needs_user_confirmation" AND the user did NOT
     provide a target country: STOP and return a short message asking the
     user for the target country. Do NOT call any paid tools.
   - Otherwise note target_country, target_language, primary_keyword AND
     category_keyword from the client result.
2b. FIRST analysis tool (before any SERP/paid tool): call
   `memory_read_similar_cases_tool` (pass query_summary="" and
   current_audit_id="" — it self-fills from session state; top_k=3). The
   client audit has just been archived; this returns the top-3 similar
   PRIOR audits (self-excluded automatically). Each has audit_id,
   audit_url, brand, industry_llm, page_type, audit_date, similarity_score
   (lower = more similar) and the full English audit_summary. Look for
   recurring issues, industry-specific findings, and successful
   recommendations from similar prior audits to inform later synthesis.
   IMPORTANT (Phase-1 small memory): if similarity_score values are high
   (e.g. > 0.40) or the industries do not match, the priors are only
   weakly related — say so honestly in synthesis ("Prior memory contained
   no closely-matching audits in this industry yet") rather than
   fabricating patterns from poor matches. If results are empty or
   _error is set, proceed WITHOUT prior knowledge and do NOT invent
   patterns from missing data.
3. Call `dataforseo_serp_query_tool` with primary_keyword=<primary>,
   category_keyword=<category>, location=target_country,
   language=target_language. (It runs BOTH SERPs, auto-skipping the second
   if branded == category.)
4. Call `select_competitor_urls_tool` with the client_url. It returns
   branded_competitors AND category_competitors and sets the CATEGORY
   competitors as the deep-audit set.
5. Call `audit_all_competitors_tool` ONCE (no args — reads state).
   It audits ALL category competitor URLs in PARALLEL internally via
   asyncio.gather (AAA-88 Sub-step 2). Wall-clock = slowest competitor,
   NOT sum of all three. Failed competitors are recorded as crawl errors
   and the batch continues. (Do NOT call `discovery_agent_tool` for
   competitors anymore — the batch tool replaces those 3 sequential
   calls. Branded competitors are still reported only, not deep-audited.)
6. Call `compare_audits_tool` (no args - reads state; compares against the
   CATEGORY competitors).
7. Produce the final markdown report covering:
   a. Client identification (brand, target country, primary + category kw)
   b. SERP Landscape - show BOTH the branded query and the category query
      with the client's ranking position in EACH
   c. Gap Analysis - contrast branded vs category ranking explicitly
   d. Dimension comparison vs the category competitors
   e. 3-5 pattern findings (from compare_audits_tool). Where a retrieved
      PRIOR audit (from step 2b) reveals a relevant recurring pattern,
      weave it in naturally (e.g. "Similar SaaS landing pages in prior
      audits also lacked structured pricing data"). NEVER mention
      audit_ids or memory mechanics in the user-facing report. If the
      priors were weak/unrelated, say so honestly instead of forcing a
      pattern.
   f. AI Overview citation analysis - EXPLICITLY say whether the CLIENT is
      cited (check both SERPs)

RULES
- Never skip the SERP query; competitor selection depends on it.
- If a competitor audit fails, document and continue - do not abort.
- Be honest about thin/JS-shell client content.
- Cost discipline: call `discovery_agent_tool` exactly once per URL
  (1 client + up to 3 competitors). Never re-audit.
Start the final summary with: `## Reverse-engineering report for <client_url>`
"""

reverse_engineering_agent = Agent(
    name="reverse_engineering_agent",
    model=MODEL,  # AAA-83 S1: central constant (= "gemini-3-flash-preview")
    description="Compares a client URL against top 3 competitors for a keyword",
    instruction=REVERSE_ENGINEERING_SYSTEM_PROMPT,
    tools=ALL_TOOLS,
)

root_agent = reverse_engineering_agent
