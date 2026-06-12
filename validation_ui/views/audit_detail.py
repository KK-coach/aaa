"""AAA-67 Sub-step 2 — audit detail page (read-only markdown render).

Scoring widgets / Edit flow are Sub-step 3 — intentionally NOT here.
"""

import streamlit as st

from memory.firestore_archive import read_audit_sync, update_validation_sync

DIMENSIONS = [
    ("schema_markup", "Schema markup (JSON-LD detection)"),
    ("target_keywords", "Target keywords"),
    ("entities", "Entities (named entities)"),
    ("eeat_named_people", "E-E-A-T: Named people (author/expert)"),
    ("eeat_organization", "E-E-A-T: Organization"),
]


def _back_to_list() -> None:
    st.session_state.pop("selected_audit_id", None)
    st.switch_page("views/audit_list.py")

audit_id = st.session_state.get("selected_audit_id")
if not audit_id:
    st.warning("No audit selected. Go back to Audit list.")
    if st.button("← Back to list"):
        st.switch_page("views/audit_list.py")
    st.stop()

archive_doc = read_audit_sync(audit_id)
if not archive_doc:
    st.error(f"Audit {audit_id} not found in archive.")
    if st.button("← Back to list"):
        st.switch_page("views/audit_list.py")
    st.stop()

audit_output = archive_doc.get("audit_output") or {}
meta = archive_doc.get("metadata") or {}
st.title(f"Audit: {archive_doc.get('audit_url')}")

mc = st.columns(4)
mc[0].metric("Industry", meta.get("industry_llm") or "—")
mc[1].metric("Page type", meta.get("page_type") or "—")
mc[2].metric("Audit date", (archive_doc.get("audit_date") or "")[:10])
mc[3].metric("Audit ID", (archive_doc.get("audit_id") or "")[:8] + "...")

st.divider()

summary_en = (
    (audit_output.get("summary_translations") or {}).get("en")
    or audit_output.get("summary_markdown")
    or "_(no summary available)_"
)
st.markdown(summary_en)

st.divider()

# --- AAA-67 Sub-step 3: scoring ---------------------------------------- #
existing_validation = archive_doc.get("user_validation") or {}
is_edit_mode = bool(existing_validation.get("validated_at"))
existing_scores = existing_validation.get("scores") or {}

if is_edit_mode:
    lv = existing_validation.get("validated_at") or ""
    st.info(
        f"✏️ Edit mode — last validated {lv[:10]} as "
        f"{existing_validation.get('overall_acceptance') or 'unknown'}"
    )

st.subheader("Overall assessment")
overall_score = st.slider(
    "Overall audit quality (1-10)", min_value=1, max_value=10,
    value=int(existing_validation.get("overall_score") or 5),
)
overall_notes = st.text_area(
    "Overall notes (optional)",
    value=existing_validation.get("overall_notes") or "",
    height=100,
)

st.subheader("Dimension scores")
dimension_scores = {}
for dim_key, dim_label in DIMENSIONS:
    st.markdown(f"**{dim_label}**")
    c = st.columns([3, 5])
    ex = existing_scores.get(dim_key) or {}
    score_val = c[0].slider(
        f"Score ({dim_key})", min_value=1, max_value=10,
        value=int(ex.get("score") or 5),
        key=f"score_{dim_key}", label_visibility="collapsed",
    )
    notes_val = c[1].text_area(
        f"Notes ({dim_key})", value=ex.get("notes") or "",
        height=80, key=f"notes_{dim_key}",
        label_visibility="collapsed", placeholder="Notes (optional)",
    )
    dimension_scores[dim_key] = {"score": score_val, "notes": notes_val}

st.divider()
b = st.columns([1, 1, 1, 3])

if b[0].button("✅ Submit", type="primary", use_container_width=True):
    ok = update_validation_sync(audit_id, {
        "overall_score": overall_score,
        "overall_notes": overall_notes,
        "overall_acceptance": "kept",
        "scores": dimension_scores,
    })
    if ok:
        st.success("Audit validated and saved.")
        _back_to_list()
    else:
        st.error("Failed to save validation. Check logs.")

if b[1].button("⏭️ Skip", use_container_width=True):
    _back_to_list()

if b[2].button("⚠️ Anomaly", use_container_width=True):
    ok = update_validation_sync(audit_id, {
        "overall_score": None,
        "overall_notes": overall_notes,
        "overall_acceptance": "anomaly",
        "scores": {},
    })
    if ok:
        st.warning("Audit marked as anomaly.")
        _back_to_list()
    else:
        st.error("Failed to mark as anomaly. Check logs.")

if st.button("← Back to list"):
    _back_to_list()
