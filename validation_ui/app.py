"""AAA-67 Validation UI — admin tool entry point (Streamlit multi-page).

Run from the repo root:
    python -m streamlit run validation_ui/app.py
(Use `python -m streamlit`, not the bare CLI — AAA-66 Area 1 local
`streamlit.exe`/`-ip` pip issue.)
"""

import streamlit as st

st.set_page_config(page_title="Validation UI", layout="wide")

# AAA-204 S1 — grouped navigation. Existing validation pages unchanged,
# just regrouped under a section header; new Statisztikák + Beállítások.
pages = {
    "Statisztikák": [
        st.Page("pages/03_statistics.py", title="Statisztikák", icon="📊"),
    ],
    "Validáció": [
        st.Page("pages/audit_list.py", title="Audit list", icon="📋"),
        st.Page("pages/audit_detail.py", title="Audit detail", icon="📄"),
        st.Page("pages/02_data_explorer.py",
                title="Audit data explorer", icon="🔎"),
    ],
    "Beállítások": [
        st.Page("pages/04_settings.py", title="Beállítások", icon="⚙️"),
    ],
}

st.navigation(pages).run()
