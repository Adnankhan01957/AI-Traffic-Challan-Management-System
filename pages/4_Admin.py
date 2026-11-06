import pandas as pd
import streamlit as st

from core import db
from core.auth import require_login

st.set_page_config(page_title="Admin", page_icon="⚙️", layout="wide")
officer = require_login(admin_only=True)
st.title("⚙️ Admin")

st.subheader("Fine schedule")
st.caption("Set these to match the official Telangana fine schedule. "
           "Changes apply to new challans only.")
fines = pd.DataFrame(db.list_fines())
edited = st.data_editor(fines, hide_index=True, disabled=["violation"],
                        use_container_width=True, key="fines_editor")
if st.button("💾 Save fines"):
    for _, row in edited.iterrows():
        db.update_fine(row["violation"], int(row["fine"]), str(row["section"] or ""),
                       officer["username"])
    st.success("Fines updated")

st.divider()
st.subheader("Officers")
st.dataframe(pd.DataFrame(db.list_officers()), hide_index=True, use_container_width=True)

with st.form("new_officer", clear_on_submit=True):
    st.markdown("**Add officer**")
    c1, c2 = st.columns(2)
    username = c1.text_input("Username")
    full_name = c2.text_input("Full name")
    badge = c1.text_input("Badge number")
    role = c2.selectbox("Role", ["officer", "admin"])
    pw = st.text_input("Temporary password (min 8 characters)", type="password")
    if st.form_submit_button("Create officer"):
        try:
            if not username.strip() or not full_name.strip():
                raise ValueError("Username and full name are required")
            db.create_officer(username, full_name, badge, role, pw, officer["username"])
            st.success(f"Created {username}")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

st.markdown("**Change a password / deactivate an officer**")
names = [o["username"] for o in db.list_officers()]
who = st.selectbox("Officer", names)
new_pw = st.text_input("New password (min 8 characters)", type="password", key="newpw")
c1, c2 = st.columns(2)
if c1.button("Set password"):
    try:
        db.set_password(who, new_pw, officer["username"])
        st.success("Password changed")
    except ValueError as exc:
        st.error(str(exc))
if c2.button("Deactivate officer", disabled=(who == officer["username"])):
    db.set_officer_active(who, False, officer["username"])
    st.rerun()
