import pandas as pd
import streamlit as st

from core import config, db, notify, plates, ui
from core.auth import require_login

st.set_page_config(page_title="Vehicle Registry", page_icon="🚗", layout="wide")
officer = require_login()
is_admin = officer["role"] == "admin"
st.title("🚗 Vehicle Registry")
st.caption("Owner details are personal data. Mobile numbers are masked unless you are an admin.")

vehicles = db.list_vehicles()
q = st.text_input("Search by plate or owner")
if q:
    qn = plates.normalize(q)
    vehicles = [v for v in vehicles
                if (qn and qn in v["plate_norm"]) or q.lower() in v["owner_name"].lower()]

if vehicles:
    df = pd.DataFrame([{
        "Plate": v["plate_display"], "Owner": v["owner_name"], "Type": v["vehicle_type"],
        "Mobile": v["mobile"] if is_admin else notify.mask_mobile(v["mobile"]),
    } for v in vehicles])
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No vehicles found.")

st.divider()
st.subheader("Add or update a vehicle")
with st.form("vehicle_form", clear_on_submit=True):
    plate = st.text_input("Number plate")
    name = st.text_input("Owner name")
    vtype = st.selectbox("Vehicle type", ["Bike", "Scooty", "Car", "Auto", "Truck", "Other"])
    vid = st.text_input("Vehicle ID (optional)")
    mobile = st.text_input("Mobile (10 digits)")
    photo = st.file_uploader("Owner photo (optional)", type=["jpg", "jpeg", "png"])
    if st.form_submit_button("Save", type="primary"):
        pv = plates.check_plate(plate)
        if not pv.valid:
            st.error(f"Plate problem: {pv.message}")
        elif not name.strip():
            st.error("Owner name is required")
        elif not notify.normalize_mobile(mobile):
            st.error("Enter a valid 10-digit Indian mobile number")
        else:
            photo_name = ""
            if photo is not None:
                config.ensure_dirs()
                photo_name = f"{pv.normalized}.{photo.name.rsplit('.', 1)[-1].lower()}"
                (config.DRIVER_DIR / photo_name).write_bytes(photo.getvalue())
            db.upsert_vehicle(pv.normalized, pv.display, name.strip(), vtype, vid.strip(),
                              mobile.strip(), photo_name, by=officer["username"])
            st.success(f"Saved {pv.display}")
            st.rerun()

if is_admin and vehicles:
    st.divider()
    st.subheader("Delete a vehicle")
    target = st.selectbox("Vehicle", [v["plate_norm"] for v in db.list_vehicles()])
    if st.button("🗑️ Delete"):
        db.delete_vehicle(target, officer["username"])
        st.rerun()
