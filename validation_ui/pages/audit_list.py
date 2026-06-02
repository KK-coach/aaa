"""AAA-67 Sub-step 2 — audit list page (read-only browse)."""

import streamlit as st

from memory.firestore_archive import list_audits_sync

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
st.caption(f"{len(audits)} audit(s)")

hdr = st.columns([3, 2, 2, 2, 2, 1])
for c, label in zip(
    hdr, ["URL", "Date", "Industry", "Page type", "Status", ""]
):
    c.markdown(f"**{label}**")

for audit in audits:
    cols = st.columns([3, 2, 2, 2, 2, 1])
    cols[0].write(audit["audit_url"])
    cols[1].write((audit["audit_date"] or "")[:10])
    cols[2].write(audit["industry_llm"] or "—")
    cols[3].write(audit["page_type"] or "—")
    if audit["validated_at"]:
        if audit["overall_acceptance"] == "anomaly":
            cols[4].write("⚠️ Anomaly")
        else:
            cols[4].write("✅ Validated")
    else:
        cols[4].write("⏳ Pending")
    if cols[5].button("Open", key=f"open_{audit['audit_id']}"):
        st.session_state["selected_audit_id"] = audit["audit_id"]
        st.switch_page("pages/audit_detail.py")
