"""Issue Challan - main page."""
import hashlib
from datetime import datetime

import streamlit as st

from core import config, db, detector, challan_pdf, notify, plates, ui
from core.auth import require_login

st.set_page_config(page_title="Traffic Challan Assistant", page_icon="🚦", layout="wide")
officer = require_login()

st.title("🚦 Issue Challan")
st.caption("The AI only suggests. Review everything, then confirm. Nothing is issued automatically.")

# ---- result of the last issued challan stays on top until dismissed -------
last = st.session_state.get("last_challan")
if last:
    with st.container(border=True):
        ui.render_challan_panel(last, officer, key="last")
        if st.button("➕ Start a new challan"):
            st.session_state.pop("last_challan", None)
            st.session_state.pop("analysis", None)
            st.rerun()
    st.stop()

# ---- 1. evidence ----------------------------------------------------------
st.subheader("1 · Evidence photo")
tab_up, tab_cam = st.tabs(["Upload photo", "Use camera"])
with tab_up:
    up = st.file_uploader("Vehicle / violation photo", type=["jpg", "jpeg", "png"])
with tab_cam:
    cam = st.camera_input("Take a photo")
image_file = up or cam
if image_file is None:
    st.info("Upload or capture a photo to begin.")
    st.stop()

data = image_file.getvalue()
sha = hashlib.sha256(data).hexdigest()
sfx = sha[:8]

c1, c2 = st.columns([1, 1])
with c1:
    st.image(data, use_container_width=True)
with c2:
    analysis = st.session_state.get("analysis")
    if analysis and analysis["sha"] == sha:
        res = analysis["result"]
    else:
        res = detector.DetectionResult.empty()
        analysis = None

    if st.button("🔍 Analyze with AI", type="primary"):
        analyzed = None
        with st.spinner("Analyzing image…"):
            try:
                analyzed = detector.analyze_image_bytes(data)
            except Exception as exc:  # noqa: BLE001
                st.error(f"AI analysis failed: {exc}")
                st.info("You can still fill in the details manually below.")
        if analyzed is not None:
            st.session_state["analysis"] = {"sha": sha, "result": analyzed}
            st.rerun()
    if analysis:
        badge = {"high": "🟢", "medium": "🟡", "low": "🔴"}[res.confidence]
        st.write(f"{badge} AI confidence: **{res.confidence}**")
        if res.note:
            st.caption(f"AI note: {res.note}")
        if res.violation == "None":
            st.warning("The AI did not see a clear violation. Check the photo yourself.")

# ---- 2. review ------------------------------------------------------------
st.subheader("2 · Review and correct")
r1, r2 = st.columns(2)
with r1:
    plate_in = st.text_input("Number plate", value=res.plate_raw, key=f"plate_{sfx}")
    pv = plates.check_plate(plate_in)
    if pv.valid:
        (st.warning if pv.corrected else st.success)(f"{pv.display} — {pv.message}")
    elif plate_in:
        st.error(pv.message)
    plate_override = False
    if plate_in and not pv.valid:
        plate_override = st.checkbox(
            "Plate is non-standard but I have verified it on the photo", key=f"ovr_{sfx}")

    default_idx = (config.VIOLATIONS.index(res.violation)
                   if res.violation in config.VIOLATIONS else 0)
    violation = st.selectbox("Violation", config.VIOLATIONS, index=default_idx,
                             key=f"viol_{sfx}")
    fine = db.get_fine(violation)
    st.metric("Fine", f"₹{fine}")

    speed, limit = None, None
    if violation == "Overspeed":
        st.caption("A photo cannot prove speed. Enter the reading from the radar/speed gun.")
        s1, s2 = st.columns(2)
        speed = s1.number_input("Recorded speed (km/h)", min_value=0, max_value=300,
                                value=0, key=f"spd_{sfx}")
        limit = s2.number_input("Speed limit (km/h)", min_value=10, max_value=200,
                                value=60, key=f"lim_{sfx}")

with r2:
    location = st.text_input("Location", value=config.DEFAULT_LOCATION, key=f"loc_{sfx}")
    now = db.now_ist()
    d = st.date_input("Offence date", value=now.date(), key=f"d_{sfx}")
    t = st.time_input("Offence time", value=now.time().replace(second=0), key=f"t_{sfx}")
    offence_time = datetime.combine(d, t).strftime("%Y-%m-%d %H:%M:%S")

    vehicle = db.get_vehicle(pv.normalized) if (pv.valid or plate_override) else None
    st.markdown("**Registered owner**")
    if vehicle:
        oc1, oc2 = st.columns([1, 2])
        photo = ui.driver_photo_path(vehicle["driver_photo"])
        if photo:
            oc1.image(str(photo), width=110)
        oc2.write(f"**{vehicle['owner_name']}**")
        oc2.write(f"{vehicle['vehicle_type'] or '-'}  ·  {notify.mask_mobile(vehicle['mobile'])}")
    elif plate_in:
        st.warning("No owner found for this plate.")
        with st.expander("Register this vehicle now"):
            with st.form(f"reg_{sfx}"):
                o_name = st.text_input("Owner name")
                o_type = st.selectbox("Vehicle type", ["Bike", "Scooty", "Car", "Auto", "Other"])
                o_mob = st.text_input("Owner mobile (10 digits)")
                if st.form_submit_button("Save owner"):
                    if not o_name.strip() or not notify.normalize_mobile(o_mob):
                        st.error("Enter a name and a valid mobile number.")
                    else:
                        norm = pv.normalized or plates.normalize(plate_in)
                        db.upsert_vehicle(norm, pv.display or norm, o_name.strip(), o_type,
                                          "", o_mob.strip(), by=officer["username"])
                        st.rerun()

# ---- 3. confirm -----------------------------------------------------------
st.subheader("3 · Confirm and issue")
norm = pv.normalized if pv.valid else plates.normalize(plate_in)
dup = db.find_recent_duplicate(norm, violation) if norm else None
dup_ok = True
if dup:
    st.warning(f"Challan {dup['challan_no']} for the same vehicle and violation was already "
               f"issued at {dup['created_at']}.")
    dup_ok = st.checkbox("This is a separate offence — issue anyway", key=f"dup_{sfx}")

speed_ok = violation != "Overspeed" or bool(speed and limit and speed > limit)
if violation == "Overspeed" and not speed_ok:
    st.error("For Overspeed, the recorded speed must be higher than the limit.")

confirmed = st.checkbox(
    "I have checked the photo and confirm the plate, violation, and details above are correct.",
    key=f"conf_{sfx}")

can_issue = bool(norm) and (pv.valid or plate_override) and confirmed and dup_ok and speed_ok
if st.button("🚨 Issue challan", type="primary", disabled=not can_issue,
             use_container_width=True):
    config.ensure_dirs()
    _, ext = detector.prepare_image(data)
    ev_path = config.EVIDENCE_DIR / f"{sha[:24]}.{ext}"
    ev_path.write_bytes(data)

    edited = (res.plate_raw != plate_in) or (res.violation != violation)
    challan = db.create_challan(
        officer=officer, plate_norm=norm,
        plate_display=pv.display if pv.valid else norm,
        owner_name=vehicle["owner_name"] if vehicle else "",
        owner_mobile=vehicle["mobile"] if vehicle else "",
        violation=violation, fine=fine, location=location, offence_time=offence_time,
        speed_recorded=int(speed) if violation == "Overspeed" else None,
        speed_limit=int(limit) if violation == "Overspeed" else None,
        evidence_path=str(ev_path), evidence_sha256=sha,
        ai_plate=res.plate_raw, ai_violation=res.violation,
        ai_confidence=res.confidence, officer_edited=edited)
    pdf_path = challan_pdf.build_pdf(challan, config.CHALLAN_DIR / f"{challan['challan_no']}.pdf")
    db.set_pdf_path(challan["challan_no"], pdf_path)
    st.session_state["last_challan"] = challan["challan_no"]
    st.rerun()

if not can_issue:
    st.caption("The Issue button unlocks when the plate is valid (or verified), "
               "the confirmation box is ticked, and any warnings above are resolved.")
