"""AAA-107 Sub-step 1 — categorized 14-group audit explorer (read-only).

Replaces Sub-step 0's raw `st.json(audit_output)` dump with a structured
14-group view. Each field renders as a collapsed `st.expander` containing
`st.json(value)`. Per-field skip-finding: missing/None values render
"(mező nem található)" inside the expander rather than crashing the group.

Markdown rendering of the AI summaries is intentionally NOT here —
Sub-step 2 scope. Group 12 is a placeholder.
"""

import streamlit as st

from memory.firestore_archive import list_audits_sync, read_audit_sync

st.title("Audit data explorer")

try:
    audits = list_audits_sync(sort_by="audit_date", descending=True)
except Exception as e:  # noqa: BLE001 — skip-finding UI variant
    st.error(f"Failed to load archive list: {type(e).__name__}: {e}")
    st.stop()

if not audits:
    st.warning("No audits in archive.")
    st.stop()


def _label(a: dict) -> str:
    date = (a.get("audit_date") or "")[:10]
    return f"{a.get('audit_url') or '(no url)'} | {a.get('audit_id')} | {date}"


choices = {_label(a): a["audit_id"] for a in audits}
picked = st.selectbox(
    f"Select an audit ({len(audits)} total, recent first)",
    options=list(choices),
)
audit_id = choices[picked]

try:
    archive = read_audit_sync(audit_id)
except Exception as e:  # noqa: BLE001
    st.error(f"Failed to load audit {audit_id}: {type(e).__name__}: {e}")
    st.stop()
if not archive:
    st.error(f"Audit {audit_id} not found in archive.")
    st.stop()

ao = archive.get("audit_output") or {}


# ---------- helpers ----------
def _render_value(value) -> None:
    """Type-aware render: dicts/lists -> st.json (structured), None ->
    skip-finding caption, scalars (str/int/float/bool/anything else) ->
    st.write. Fixes Sub-step 1/2 bug where st.json('https://...') tried to
    parse a plain string as JSON content."""
    if isinstance(value, (dict, list)):
        st.json(value)
    elif value is None:
        st.caption("(None)")
    else:
        # str, int, float, bool, anything else scalar
        st.write(value)


def _expander(label: str, value):
    """Collapsed expander with type-aware rendering."""
    with st.expander(label):
        try:
            _render_value(value)
        except Exception as e:  # noqa: BLE001 — never crash a group
            st.error(f"render failed: {type(e).__name__}: {e}")


# Crawl-dict subkeys explicitly broken out (same list reused for
# rendered_crawl). Any subkey not in this list folds into "(other)".
_CRAWL_SUBKEYS = [
    "meta", "technical", "schema_markup", "headings", "links", "images",
    "javascript_indicators", "googlebot_index_limit", "i18n",
    "main_content", "content", "brand_context",
]


def _render_crawl_subtree(d) -> None:
    if not isinstance(d, dict):
        st.caption("(crawl subtree missing or invalid)")
        return
    for k in _CRAWL_SUBKEYS:
        _expander(k, d.get(k))
    leftover = {k: v for k, v in d.items() if k not in _CRAWL_SUBKEYS}
    if leftover:
        _expander("(other)", leftover)


# ---------- 1. Identity / routing ----------
st.subheader("1. Identity / routing")
_expander("url", ao.get("url"))

# ---------- 2. Crawler — raw HTML ----------
st.subheader("2. Crawler — raw HTML")
_render_crawl_subtree(ao.get("crawl") or {})

# ---------- 3. Crawler — rendered ----------
st.subheader("3. Crawler — rendered")
rmu = ao.get("render_method_used")
st.caption(f"render_method_used: {rmu}")
rc = ao.get("rendered_crawl")
if rc is None:
    st.caption(f"no Playwright escalation (render_method_used: {rmu})")
else:
    _render_crawl_subtree(rc)

# ---------- 4. Site profile ----------
st.subheader("4. Site profile")
_expander("site_profile", ao.get("site_profile"))
_expander("target_keywords", ao.get("target_keywords"))
_expander("entities", ao.get("entities"))

# ---------- 🔎 Indexing / Canonicalization (AAA-136) ----------
# audit_output.indexing has THREE historical shapes; detect + render each
# without crashing:
#   1. NEW quoted_url_serp  -> full 4-variant matrix + canonical/dup badges
#   2. serp_site_query (superseded site: era) -> flat fields + note
#   3. old stub / missing   -> placeholder
st.subheader("🔎 Indexing / Canonicalization (AAA-136)")


def _indexed_badge(v) -> str:
    """Overall indexed badge: True green / False red / else grey unknown."""
    if v is True:
        return "🟢 Indexed"
    if v is False:
        return "🔴 Not indexed"
    return "⚪ Unknown"


def _md_cell(v) -> str:
    """Markdown-table cell: stringify, escape pipes, None -> em-dash."""
    if v is None:
        return "—"
    return str(v).replace("|", "\\|")


def _render_indexing(idx) -> None:
    if not isinstance(idx, dict) or not idx:
        st.caption("(no indexing data — pre-AAA-136 audit)")
        return
    method = idx.get("method")

    # Shape 3 — old stub / unrecognized (no method we know).
    if method not in ("quoted_url_serp", "serp_site_query"):
        if idx.get("note") or set(idx.keys()) <= {"indexed", "note", "url"}:
            st.caption("(no indexing data — pre-AAA-136 audit)")
        else:
            st.caption("(unrecognized indexing shape — raw below)")
            _render_value(idx)
        return

    # Shape 2 — superseded site: method.
    if method == "serp_site_query":
        st.markdown(f"**Status:** {_indexed_badge(idx.get('indexed'))}")
        st.caption(
            f"query: `{idx.get('query')}`  |  matched_url: "
            f"`{idx.get('matched_url') or '—'}`  |  position: "
            f"{idx.get('position')}"
        )
        st.caption(
            f"method: `{idx.get('method')}`  |  cost: "
            f"${idx.get('cost_usd') or 0:.6f}"
        )
        st.caption("(superseded site: method — pre-AAA-136 refinement)")
        return

    # Shape 1 — NEW quoted_url_serp.
    st.markdown(f"**Status:** {_indexed_badge(idx.get('indexed'))}")
    ci, rc = idx.get("canonical_indexed"), idx.get("rel_canonical")
    line = (
        f"**canonical_indexed:** `{ci or '—'}`  &nbsp;|&nbsp;  "
        f"**rel_canonical:** `{rc or '—'}`"
    )
    if idx.get("canonical_mismatch"):
        line += "  &nbsp; 🟠 **canonical mismatch**"
    st.markdown(line)
    st.caption(
        "canonical_indexed is a variant-identity (compared normalized, not a "
        "byte-exact URL)."
    )
    if idx.get("duplication_signal"):
        st.markdown(
            "🟠 **duplication** — >1 live variant independently indexed"
        )

    variants = idx.get("variants") or []
    if variants:
        cols = ["url", "status_chain", "final_url", "live_200",
                "indexed", "first_result_url", "position"]
        header = "| " + " | ".join(cols) + " |"
        sep = "|" + "|".join(["---"] * len(cols)) + "|"
        body = "\n".join(
            "| " + " | ".join(_md_cell(v.get(c)) for c in cols) + " |"
            for v in variants
        )
        st.markdown(f"{header}\n{sep}\n{body}")
    else:
        st.caption("(no variants)")
    st.caption(
        f"method: `{idx.get('method')}`  |  cost: "
        f"${idx.get('cost_usd') or 0:.6f}"
    )


_render_indexing(ao.get("indexing"))

# ---------- 5. Page classification ----------
st.subheader("5. Page classification")
_expander("page_type", ao.get("page_type"))
_expander("page_type_model_version", ao.get("page_type_model_version"))

# ---------- 6. Keywords + intent ----------
st.subheader("6. Keywords + intent")
_expander("target_keywords_classified", ao.get("target_keywords_classified"))

# ---------- 7. AI visibility ----------
st.subheader("7. AI visibility")
_expander("ai_overview_triggered", ao.get("ai_overview_triggered"))
_expander("chatgpt_query_response", ao.get("chatgpt_query_response"))
_expander("query_fan_out", ao.get("query_fan_out"))
_expander("fan_out_enriched", ao.get("fan_out_enriched"))

# ---------- Predicted competitors (LLM pre-SERP hunch) ----------
# Sits between Group 7 and Group 8 intentionally — no numeric prefix so the
# existing 1–14 group labels stay intact. Backed by
# audit_output.target_keywords.category_competitors_likely (a Discovery LLM
# hunch from page content, BEFORE any DataForSEO SERP call). The real
# SERP-based competitor data is intermediate-only today (AAA-108 finding) —
# this panel ships pending AAA-108 production persistence.
st.subheader("🎯 Predicted competitors (LLM pre-SERP hunch)")
st.caption(
    "Ez a Discovery agent oldal-tartalmából tippelt konkurens-domain / "
    "-brand lista, "
    "mielőtt bármilyen SERP query lefutott volna. A valós SERP-based "
    "konkurens-adat (DataForSEO top-10 + selected RE targets) az AAA-108 "
    "ship után lesz elérhető."
)
_predicted = (ao.get("target_keywords") or {}).get(
    "category_competitors_likely"
)
if _predicted is None or (isinstance(_predicted, list) and len(_predicted) == 0):
    st.caption("(no LLM-predicted competitors for this audit)")
elif isinstance(_predicted, list):
    st.markdown("\n".join(f"- `{d}`" for d in _predicted))
else:
    st.error(
        "unexpected shape for category_competitors_likely: "
        f"{type(_predicted).__name__} (expected list[str])"
    )

# ---------- RE findings (workflow-based, post-AAA-108) ----------
# Sits between "Predicted competitors" (LLM pre-SERP hunch) and Group 8.
# Backed by audit_output.re_findings — populated ONLY when the full RE
# workflow ran end-to-end (client Discovery + SERP × 2 + competitor
# Discovery × N + Gemini comparison + post-workflow persist_re_findings()
# attach). Stand-alone Discovery audits have re_findings is None and get
# the gating caption — no expanders rendered.
st.subheader("🔬 RE findings (workflow-based, post-AAA-108)")

_rf = ao.get("re_findings")
if _rf is None:
    st.caption(
        "(this audit was stand-alone Discovery — no RE workflow ran. "
        "Only audits that went through the full RE workflow have "
        "re_findings populated.)"
    )
elif isinstance(_rf, dict):
    _serp_cost = _rf.get("audit_re_serp_cost_usd") or 0.0
    _comp_cost = _rf.get("audit_re_comparison_cost_usd") or 0.0
    st.caption(
        f"RE workflow completed: {_rf.get('re_workflow_completed')} | "
        f"SERPs identical: {_rf.get('serps_identical')} | "
        f"Total RE cost: ${(_serp_cost + _comp_cost):.4f}"
    )

    # ----- 🔍 Query context panel (Sub-step 3.5, AAA-108 S4 surface) -----
    # Rendered directly (NOT in an expander) — most-frequently-needed
    # forensic context for understanding all RE findings below. Backed by
    # audit_output.re_findings.serp_{branded,category}.query_metadata
    # (AAA-108 Sub-step 4); falls back gracefully on pre-S4 entries.
    _serp_b = _rf.get("serp_branded") or {}
    _serp_c = _rf.get("serp_category") or {}
    _qm_b = _serp_b.get("query_metadata")
    _qm_c = _serp_c.get("query_metadata")
    _locale_strategy = _serp_b.get("serp_locale_strategy")
    _serps_identical_val = _rf.get("serps_identical")

    def _fmt_query_line(label: str, qm) -> str:
        """One bullet for a (branded|category) query. Three skip-finding
        outcomes: missing query_metadata entirely (pre-S4 entry), missing
        individual field (rendered as '(empty)'), populated (rendered)."""
        if qm is None:
            return (
                f"- **{label}:** _(metadata not captured — pre-AAA-108 "
                f"Sub-step 4 entry)_"
            )
        kw = qm.get("keyword") or "(empty)"
        loc = qm.get("location_name") or "(empty)"
        lang = qm.get("language_code") or "(empty)"
        return (
            f"- **{label}:** `{kw}`  \n"
            f"  Locale: `{loc}` / `{lang}`"
        )

    _qc_lines = ["**🔍 Query context**", ""]
    _qc_lines.append(_fmt_query_line("Branded query", _qm_b))
    _qc_lines.append(_fmt_query_line("Category query", _qm_c))
    if _serps_identical_val is not None:
        _qc_lines.append(f"- **SERPs identical:** `{_serps_identical_val}`")
    if _locale_strategy:
        _qc_lines.append(f"- **Locale strategy:** `{_locale_strategy}`")
    st.markdown("\n".join(_qc_lines))

    def _re_expander(label: str, value) -> None:
        """Skip-finding expander for re_findings sub-keys: explicit
        '(no data)' caption when a sub-key is None mid-flow."""
        with st.expander(label):
            if value is None:
                st.caption("(no data)")
            else:
                try:
                    _render_value(value)
                except Exception as e:  # noqa: BLE001 — never crash group
                    st.error(f"render failed: {type(e).__name__}: {e}")

    _re_expander("serp_branded", _rf.get("serp_branded"))
    _re_expander("serp_category", _rf.get("serp_category"))
    _re_expander("selected_competitors", _rf.get("selected_competitors"))
    _re_expander("client_ranking_status", _rf.get("client_ranking_status"))
    _re_expander("competitor_audits", _rf.get("competitor_audits"))
    _re_expander("comparison", _rf.get("comparison"))
    _re_expander("memory_retrieval", _rf.get("memory_retrieval"))
    # Expander 8 — combined cost summary (scalars; markdown table for clarity).
    with st.expander("RE costs"):
        st.markdown(
            f"- `audit_re_serp_cost_usd`       : **${_serp_cost:.6f}**\n"
            f"- `audit_re_comparison_cost_usd` : **${_comp_cost:.6f}**\n"
            f"- **Total RE cost**              : **${(_serp_cost + _comp_cost):.6f}**\n"
            f"\n_AAA-53 separation: these costs are NOT folded into "
            f"`audit_cost_usd` (Discovery's main cost field)._"
        )
else:
    st.error(
        "unexpected shape for re_findings: "
        f"{type(_rf).__name__} (expected dict or None)"
    )

# ---------- 8. Agent-friendliness ----------
st.subheader("8. Agent-friendliness")
_expander(
    "agent_friendly_measurements", ao.get("agent_friendly_measurements")
)

# ---------- 🎨 Per-aspect evaluations (AAA-124 Sub-step 1) ----------
# Sits after Group 8 (Agent-friendliness) — AAA-124 builds on the same AAA-42
# `agent_friendly_measurements` + AAA-123 `phase2_html_measurements` ground
# truth. Backed by audit_output.aaa124_aspect_evaluations (7 aspects, each:
# structured_finding + confidence_0_1 + justification + recommendation, plus
# the AAA-129 hybrid layer: educational_context {hu,en} +
# educational_context_template_id — code-injected, rendered as "📚 Miért fontos"
# before the Gemini Finding so the template→finding seam is visible).
# Underscore-prefixed `_meta` is NOT an 8th aspect — iterated via the explicit
# _ASPECT_ORDER list, never via dict.keys(), so `_meta` is structurally
# skipped (same precedent as _raw_html_transient / _error).
st.subheader("🎨 Per-aspect evaluations (AAA-124)")

_ASPECT_ORDER = [
    "macro_structure", "heading_semantics", "above_the_fold",
    "micro_semantics", "inline_link_semantics", "forms_conversion_points",
    "schema_entity",
]
_ae = ao.get("aaa124_aspect_evaluations")
_ae_cost = ao.get("audit_aspect_eval_cost_usd")


def _conf_badge(c) -> str:
    """Confidence indicator badge. Thresholds: >=0.85 green, >=0.6 amber,
    else red; non-numeric -> unknown."""
    if not isinstance(c, (int, float)):
        return "❔ —"
    if c >= 0.85:
        return f"🟢 {c:.2f}"
    if c >= 0.6:
        return f"🟡 {c:.2f}"
    return f"🔴 {c:.2f}"


def _render_edu(ev: dict) -> None:
    """AAA-129 hybrid 'Miért fontos' (why-it-matters) educational block — the
    code-injected, audit-independent template layer (NOT Gemini-generated).
    Rendered BEFORE the Gemini Finding so the seam (template why → Gemini what)
    is visible. Forward-only graceful: pre-AAA-129 aspects have no edu keys."""
    ec = ev.get("educational_context")
    tid = ev.get("educational_context_template_id")
    if ec is None:
        st.caption("📚 (no educational context — pre-AAA-129 audit)")
        return
    if not isinstance(ec, dict):
        st.caption(
            f"📚 (unexpected educational_context shape: {type(ec).__name__})"
        )
        return
    st.markdown("**📚 Miért fontos:**")
    # HU primary (rendered inline as markdown)
    if "hu" not in ec:
        st.caption("HU: (nincs)")
    elif not str(ec.get("hu") or "").strip():
        st.caption("HU: (üres)")
    else:
        st.markdown(ec["hu"])
    # EN secondary (collapsible, labeled)
    if "en" not in ec:
        st.caption("EN: (nincs)")
    elif not str(ec.get("en") or "").strip():
        st.caption("EN: (üres)")
    else:
        with st.expander("EN"):
            st.markdown(ec["en"])
    st.caption(f"template: {tid}" if tid else "(template_id n/a)")


if _ae is None:
    st.caption(
        "Not available (pre-AAA-124 audit) — `aaa124_aspect_evaluations` "
        "was not populated for this archive entry."
    )
elif not isinstance(_ae, dict):
    st.error(
        "unexpected shape for aaa124_aspect_evaluations: "
        f"{type(_ae).__name__} (expected dict or None)"
    )
else:
    _meta = _ae.get("_meta") or {}
    if _meta.get("error"):
        st.warning(
            f"⚠️ aspect evaluation skip-finding error: {_meta.get('error')}"
        )
    _cost_str = (
        f"${_ae_cost:.6f}" if isinstance(_ae_cost, (int, float)) else "—"
    )
    st.caption(
        f"Cost: **{_cost_str}** (`audit_aspect_eval_cost_usd`, AAA-53 separate) "
        f"| model: `{_meta.get('model_id') or '—'}` "
        f"| latency: {_meta.get('latency_s') or '—'}s "
        f"| tokens in/out: {_meta.get('input_tokens') or '—'}/"
        f"{_meta.get('output_tokens') or '—'}"
    )

    _any = False
    for _asp in _ASPECT_ORDER:  # explicit list — _meta never iterated
        _ev = _ae.get(_asp)
        if _ev is None:
            st.markdown(f"#### {_asp}")
            st.caption("(aspect not populated)")
            continue
        if not isinstance(_ev, dict):
            st.markdown(f"#### {_asp}")
            st.error(f"unexpected aspect shape: {type(_ev).__name__}")
            continue
        _any = True
        st.markdown(f"#### {_asp} &nbsp; {_conf_badge(_ev.get('confidence_0_1'))}")
        _render_edu(_ev)  # AAA-129 📚 'Miért fontos' (template) — before Finding
        st.markdown(f"**Finding:** {_ev.get('structured_finding') or '_(none)_'}")
        st.markdown(
            f"**💡 Recommendation:** {_ev.get('recommendation') or '_(none)_'}"
        )
        with st.expander("Justification"):
            st.markdown(_ev.get("justification") or "_(none)_")
        st.divider()
    if not _any:
        st.caption(
            "(no aspects populated — only `_meta` present, likely a "
            "skip-finding error entry)"
        )

# ---------- 9. Performance ----------
st.subheader("9. Performance")
ps = ao.get("pagespeed") or {}
_expander("pagespeed.mobile", ps.get("mobile"))
_expander("pagespeed.desktop", ps.get("desktop"))
_expander("crux_field_data", ao.get("crux_field_data"))

# ---------- 10. E-E-A-T ----------
st.subheader("10. E-E-A-T")
_expander("eeat_signals", ao.get("eeat_signals"))
_expander("eeat_findings_count", ao.get("eeat_findings_count"))

# ---------- 11. Grounding ----------
st.subheader("11. Grounding")
_expander("grounding_confidence", ao.get("grounding_confidence"))

# ---------- 12. AI summaries (kiemelt markdown) ----------
st.subheader("12. AI summaries (kiemelt markdown)")
st.caption("9 AI-generated text fields below. Each expandable.")


def _dot_get(root, path: str):
    """Resolve a dotted path against nested dicts. Returns None if any
    intermediate step is missing or not a dict."""
    cur = root
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _md_expander(label: str, value) -> None:
    """Collapsed expander with st.markdown — skip-finding on missing/empty."""
    with st.expander(label):
        if value is None:
            st.caption("(mező nem található)")
            return
        if isinstance(value, str) and value == "":
            st.caption("(üres)")
            return
        try:
            st.markdown(value)
        except Exception as e:  # noqa: BLE001 — never crash a group
            st.error(f"render failed: {type(e).__name__}: {e}")


_AI_TEXT_PATHS = [
    "summary_markdown",
    "summary_translations.en",
    "summary_translations.hu",
    "site_profile.reasoning",
    "entities.reasoning",
    "target_keywords.reasoning",
    "target_keywords.gap_interpretation",
    "chatgpt_query_response.response_text",
]
for _path in _AI_TEXT_PATHS:
    _md_expander(_path, _dot_get(ao, _path))

# Field 9 — fan_out_enriched[*].suggestion (per-item list)
with st.expander("fan_out_enriched[*].suggestion (per-item)"):
    _fan_out = ao.get("fan_out_enriched") or []
    if not isinstance(_fan_out, list):
        st.caption("(fan_out_enriched not a list)")
    else:
        _shown = 0
        for _entry in _fan_out:
            if not isinstance(_entry, dict):
                continue
            _sug = _entry.get("suggestion")
            if _sug is None or (isinstance(_sug, str) and _sug == ""):
                continue
            if _shown > 0:
                st.divider()
            st.markdown(f"**Query:** {_entry.get('query')}")
            try:
                st.markdown(_sug)
            except Exception as e:  # noqa: BLE001
                st.error(f"render failed: {type(e).__name__}: {e}")
            _shown += 1
        if _shown == 0:
            st.caption(
                "(no suggestions populated — all entries covered or off_topic)"
            )

# ---------- 13. Cost / token ----------
st.subheader("13. Cost / token")
_expander("audit_cost_usd", ao.get("audit_cost_usd"))
_expander("audit_token_counts", ao.get("audit_token_counts"))
_expander("audit_metadata", ao.get("audit_metadata"))
# Auto-discover audit_* cost/calls/count fields not already claimed by
# the explicit Cost/token entries above or by the Memory group (14).
_CLAIMED_AUDIT_KEYS = {
    "audit_cost_usd", "audit_token_counts", "audit_metadata",
    "audit_memory_retrieval_calls", "audit_memory_retrieval_cost_usd",
    # AAA-124: rendered co-located in the per-aspect evaluations section above.
    "audit_aspect_eval_cost_usd",
}
_auto_discovered = [
    k for k in sorted(ao)
    if k.startswith("audit_") and k not in _CLAIMED_AUDIT_KEYS
]
for k in _auto_discovered:
    _expander(k, ao.get(k))

# ---------- 14. Memory ----------
st.subheader("14. Memory")
_expander(
    "audit_memory_retrieval_calls",
    ao.get("audit_memory_retrieval_calls"),
)
_expander(
    "audit_memory_retrieval_cost_usd",
    ao.get("audit_memory_retrieval_cost_usd"),
)
_expander("embedding_metadata", ao.get("embedding_metadata"))
