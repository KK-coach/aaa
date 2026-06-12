"""AAA-204 S1 — shared projected-scan loader for the Statisztikák page.

One full `select()`-projected scan of the `audits` collection (NEVER full
docs — AAA-103: archive docs run toward the 1 MiB cap; an unprojected
stream moves ~0.5 GB). Field list = the AAA-204 S0 probe inventory.
Cached via st.cache_data(ttl=300) so interactive filtering never re-reads
Firestore. Plus a small `audit_jobs` reader for web-run status counts.

URL normalization for dedup: registrable host, www.-stripped, lowercase
(same rule as success_url_normalized in memory/success_backfill.py).
"""

from urllib.parse import urlparse

import streamlit as st

from memory.firestore_archive import _db

_AUDITS = "audits"
_JOBS = "audit_jobs"

# S0-probed projection — every field the dashboard needs, nothing else.
_SELECT_FIELDS = [
    "audit_id",
    "audit_date",
    "audit_language",
    "audit_url",
    "success_serp_position",
    "success_ai_cited",
    "success_excluded",
    "success_label_version",
    "user_validation.validated_at",
    "user_validation.overall_acceptance",
    "audit_output.url",
    "audit_output.business_model",
    "audit_output.page_type",
    "audit_output.topic_domain",
    "audit_output.locality",
    "audit_output.audience_relationship_primary",
    "audit_output.audit_cost_usd",
    # client-doc discriminator: re_findings presence (projected via small
    # subfields — projecting the whole re_findings would pull megabytes).
    "audit_output.re_findings.competitor_audit_ids",
    "audit_output.re_findings.serp_branded.query_metadata.keyword",
    # report-link gate: artifact reference presence (small dicts).
    "audit_output.customer_report_html_uri_ff.default_lang",
    "audit_output.customer_report_html_uri.default_lang",
]

REPORT_BASE = "https://aaa-web-664356368213.europe-west3.run.app"


def normalize_host(url: str | None) -> str | None:
    """Registrable host: scheme-tolerant, www.-stripped, lowercase."""
    if not url:
        return None
    host = (urlparse(url if "://" in url else "https://" + url).netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _get(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


@st.cache_data(ttl=300, show_spinner="Audit archive scan…")
def load_stats_rows() -> list[dict]:
    """Projected scan -> one flat dict per audit doc (picklable, cacheable)."""
    rows: list[dict] = []
    q = _db().collection(_AUDITS).select(_SELECT_FIELDS)
    for snap in q.stream():
        d = snap.to_dict() or {}
        re_f = _get(d, "audit_output.re_findings")
        cai = _get(d, "audit_output.re_findings.competitor_audit_ids")
        url = _get(d, "audit_output.url") or d.get("audit_url")
        has_report = bool(
            _get(d, "audit_output.customer_report_html_uri_ff.default_lang")
            or _get(d, "audit_output.customer_report_html_uri.default_lang")
        )
        rows.append({
            "audit_id": d.get("audit_id") or snap.id,
            "audit_date": str(d.get("audit_date") or ""),
            "day": str(d.get("audit_date") or "")[:10],
            "language": d.get("audit_language"),
            "url": url,
            "host": normalize_host(url),
            "business_model": _get(d, "audit_output.business_model"),
            "page_type": _get(d, "audit_output.page_type"),
            "topic_domain": _get(d, "audit_output.topic_domain"),
            "locality": _get(d, "audit_output.locality"),
            "audience_relationship_primary": _get(
                d, "audit_output.audience_relationship_primary"),
            "cost_usd": _get(d, "audit_output.audit_cost_usd") or 0.0,
            "success_serp_position": d.get("success_serp_position"),
            "success_ai_cited": d.get("success_ai_cited"),
            "validated": bool(_get(d, "user_validation.validated_at")),
            "is_client": re_f is not None,
            "competitor_audit_ids": list(cai.values()) if isinstance(cai, dict) else [],
            "report_url": (
                "%s/report/%s?lang=en" % (REPORT_BASE, d.get("audit_id") or snap.id)
                if has_report else None
            ),
        })
    return rows


@st.cache_data(ttl=300, show_spinner=False)
def load_job_status_counts() -> dict:
    """audit_jobs (web-submitted runs) -> {status: count}."""
    counts: dict[str, int] = {}
    for snap in _db().collection(_JOBS).select(["status"]).stream():
        s = (snap.to_dict() or {}).get("status") or "(unknown)"
        counts[s] = counts.get(s, 0) + 1
    return counts
