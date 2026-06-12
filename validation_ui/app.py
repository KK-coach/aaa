"""AAA-67 Validation UI — admin tool entry point (Streamlit multi-page).

Run from the repo root:
    python -m streamlit run validation_ui/app.py
(Use `python -m streamlit`, not the bare CLI — AAA-66 Area 1 local
`streamlit.exe`/`-ip` pip issue.)
"""

import hmac
import os
import time

import streamlit as st

st.set_page_config(page_title="Validation UI", layout="wide")


# --------------------------------------------------------------------------
# AAA-204 S3b — central credential gate (runs BEFORE st.navigation dispatch,
# so it covers EVERY page: Statisztikák, Beállítások, all Validáció pages).
# Credentials come from the runtime env (ADMIN_AUTH_USER + ADMIN_AUTH_PASS;
# the password is a Secret Manager secret on Cloud Run — NEVER in the repo).
# Fail-closed on Cloud Run: if creds are missing while running as a Cloud Run
# service (K_SERVICE set), the app hard-stops instead of serving open.
# Local dev (no K_SERVICE, no creds) stays open for convenience.
# --------------------------------------------------------------------------
def _auth_gate() -> None:
    user = os.environ.get("ADMIN_AUTH_USER", "")
    password = os.environ.get("ADMIN_AUTH_PASS", "")
    if not (user and password):
        if os.environ.get("K_SERVICE"):
            st.error("Auth nincs konfigurálva — a szolgáltatás zárolva.")
            st.stop()
        return  # local dev without creds: open
    if st.session_state.get("_aaa_admin_authed"):
        return
    st.title("AAA admin — bejelentkezés")
    with st.form("aaa_admin_login"):
        u = st.text_input("Felhasználónév")
        p = st.text_input("Jelszó", type="password")
        submitted = st.form_submit_button("Belépés")
    if submitted:
        ok = hmac.compare_digest(u.encode(), user.encode()) and \
            hmac.compare_digest(p.encode(), password.encode())
        if ok:
            st.session_state["_aaa_admin_authed"] = True
            st.rerun()
        time.sleep(1.0)  # blunt brute force
        st.error("Hibás felhasználónév vagy jelszó.")
    st.stop()  # nothing below (navigation/pages/data) renders unauthenticated


_auth_gate()

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
