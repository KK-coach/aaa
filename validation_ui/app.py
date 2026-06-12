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
# AAA-204 S3b — central credential gate covering EVERY page (Statisztikák,
# Beállítások, all Validáció pages). Credentials come from the runtime env
# (ADMIN_AUTH_USER + ADMIN_AUTH_PASS; the password is a Secret Manager secret
# on Cloud Run — NEVER in the repo). Fail-closed on Cloud Run: creds missing
# while running as a service (K_SERVICE set) -> hard stop, never open.
# Local dev (no K_SERVICE, no creds) stays open for convenience.
#
# CRITICAL SHAPE: st.navigation MUST run on every script run. If the gate
# st.stop()s before st.navigation, Streamlit falls back to DIRECTORY-based
# multipage routing and serves pages/*.py directly at their URLs — bypassing
# the gate entirely (caught in the S3b cloud canary). Pre-auth we therefore
# still call st.navigation, registering ONLY the login page: the v2 router
# then owns routing and unregistered paths (e.g. /statistics) do not resolve.
# --------------------------------------------------------------------------
def _gate_active() -> bool:
    user = os.environ.get("ADMIN_AUTH_USER", "")
    password = os.environ.get("ADMIN_AUTH_PASS", "")
    if not (user and password):
        if os.environ.get("K_SERVICE"):
            st.error("Auth nincs konfigurálva — a szolgáltatás zárolva.")
            st.stop()
        return False  # local dev without creds: open
    return not st.session_state.get("_aaa_admin_authed")


def _login_page() -> None:
    user = os.environ.get("ADMIN_AUTH_USER", "")
    password = os.environ.get("ADMIN_AUTH_PASS", "")
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


if _gate_active():
    st.navigation([st.Page(_login_page, title="Bejelentkezés", icon="🔒")]).run()
    st.stop()

# AAA-204 S1 — grouped navigation. Existing validation pages unchanged,
# just regrouped under a section header; new Statisztikák + Beállítások.
# S3b: the directory is named views/ (NOT the magic pages/) on purpose —
# a pages/ dir arms Streamlit's directory-based router, which serves page
# scripts directly by URL on a fresh session BEFORE the entrypoint (and its
# auth gate) ever runs. With views/, only st.navigation routes exist.
pages = {
    "Statisztikák": [
        st.Page("views/03_statistics.py", title="Statisztikák", icon="📊"),
    ],
    "Validáció": [
        st.Page("views/audit_list.py", title="Audit list", icon="📋"),
        st.Page("views/audit_detail.py", title="Audit detail", icon="📄"),
        st.Page("views/02_data_explorer.py",
                title="Audit data explorer", icon="🔎"),
    ],
    "Beállítások": [
        st.Page("views/04_settings.py", title="Beállítások", icon="⚙️"),
    ],
}

st.navigation(pages).run()
