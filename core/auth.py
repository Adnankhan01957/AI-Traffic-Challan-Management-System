"""Officer login for Streamlit pages."""
import time

import streamlit as st

from core import db


@st.cache_resource
def _init_once():
    db.init_db()
    return True


@st.cache_data(ttl=60)
def _default_pw_in_use() -> bool:
    return db.default_admin_password_in_use()


def _login_form():
    st.title("🚦 Traffic Challan Assistant")
    st.caption("Authorised officers only")
    fails = st.session_state.get("login_fails", 0)
    locked_until = st.session_state.get("locked_until", 0)
    if time.time() < locked_until:
        st.error(f"Too many failed attempts. Try again in {int(locked_until - time.time())} seconds.")
        return
    with st.form("login"):
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        go = st.form_submit_button("Log in", type="primary")
    if go:
        officer = db.verify_login(user, pw)
        if officer:
            st.session_state["officer"] = officer
            st.session_state["login_fails"] = 0
            st.rerun()
        fails += 1
        st.session_state["login_fails"] = fails
        if fails >= 5:
            st.session_state["locked_until"] = time.time() + 60
            st.session_state["login_fails"] = 0
        st.error("Invalid username or password")


def require_login(admin_only: bool = False) -> dict:
    _init_once()
    officer = st.session_state.get("officer")
    if not officer:
        _login_form()
        st.stop()
    if admin_only and officer["role"] != "admin":
        st.error("This page is for administrators only.")
        st.stop()
    with st.sidebar:
        st.markdown(f"**{officer['full_name']}**  \nBadge: {officer['badge_no'] or '-'}  \nRole: {officer['role']}")
        if st.button("Log out"):
            st.session_state.pop("officer", None)
            st.rerun()
        if officer["role"] == "admin" and _default_pw_in_use():
            st.warning("The default admin password is still in use. Change it in the Admin page.")
    return officer
