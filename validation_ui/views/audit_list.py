"""AAA-67 Sub-step 2 — audit list page (read-only browse).

AAA-205: industry + page_type + webshop filters above the table, webshop
column derived from audit_output.business_model (ecommerce -> igen, other
-> nem, missing pre-AAA-113 -> "(not classified)"). The "(not classified)"
bucket is explicitly selectable — no doc is silently excluded. Filters
combine with AND. No new classification runs — display/filter only.
"""

import streamlit as st

from memory.firestore_archive import list_audits_sync

NOT_CLASSIFIED = "(not classified)"

st.title("Audit list")

filter_choice = st.radio(
    "Filter",
    options=["All", "Unvalidated", "Validated"],
    horizontal=True,
)
filter_validated = {
    "All": None, "Unvalidated": False, "Validated": True
}[filter_choice]

audits = list_audits_sync(filter_validated=filter_validated)


def _webshop(a: dict) -> str:
    bm = a.get("business_model")
    if bm is None:
        return NOT_CLASSIFIED
    return "igen" if bm == "ecommerce" else "nem"


def _bucket(value) -> str:
    return value if value is not None else NOT_CLASSIFIED


# AAA-205 — filters (options = distinct values present in the corpus)
fc1, fc2, fc3 = st.columns(3)
f_industry = fc1.multiselect(
    "Industry", sorted({_bucket(a.get("industry_llm")) for a in audits}))
f_page_type = fc2.multiselect(
    "Page type", sorted({_bucket(a.get("page_type")) for a in audits}))
f_webshop = fc3.multiselect(
    "Webshop", ["igen", "nem", NOT_CLASSIFIED])

if f_industry:
    audits = [a for a in audits if _bucket(a.get("industry_llm")) in f_industry]
if f_page_type:
    audits = [a for a in audits if _bucket(a.get("page_type")) in f_page_type]
if f_webshop:
    audits = [a for a in audits if _webshop(a) in f_webshop]

st.caption(f"{len(audits)} audit(s)")

hdr = st.columns([3, 2, 2, 2, 1, 2, 1])
for c, label in zip(
    hdr, ["URL", "Date", "Industry", "Page type", "Webshop", "Status", ""]
):
    c.markdown(f"**{label}**")

for audit in audits:
    cols = st.columns([3, 2, 2, 2, 1, 2, 1])
    cols[0].write(audit["audit_url"])
    cols[1].write((audit["audit_date"] or "")[:10])
    cols[2].write(audit["industry_llm"] or "—")
    cols[3].write(audit["page_type"] or "—")
    cols[4].write(_webshop(audit))
    if audit["validated_at"]:
        if audit["overall_acceptance"] == "anomaly":
            cols[5].write("⚠️ Anomaly")
        else:
            cols[5].write("✅ Validated")
    else:
        cols[5].write("⏳ Pending")
    if cols[6].button("Open", key=f"open_{audit['audit_id']}"):
        st.session_state["selected_audit_id"] = audit["audit_id"]
        st.switch_page("views/audit_detail.py")
