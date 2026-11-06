"""Shared Streamlit widgets."""
from pathlib import Path

import streamlit as st

from core import config, db, notify


def driver_photo_path(name: str):
    if not name:
        return None
    p = config.DRIVER_DIR / name
    return p if p.exists() else None


def render_challan_panel(challan_no: str, officer: dict, key: str = "panel"):
    c = db.get_challan(challan_no)
    if not c:
        st.error("Challan not found")
        return

    st.subheader(f"📄 Challan {c['challan_no']}  ·  {c['status']}")
    left, right = st.columns([1, 1])
    with left:
        st.write(f"**Vehicle:** {c['plate_display']}")
        st.write(f"**Owner:** {c['owner_name'] or 'Not on record'}")
        st.write(f"**Violation:** {c['violation']}")
        st.write(f"**Fine:** ₹{c['fine']}")
        st.write(f"**When:** {c['offence_time']}")
        st.write(f"**Where:** {c['location'] or '-'}")
        st.write(f"**Issued by:** {c['officer_name']}")
        if c["speed_recorded"]:
            st.write(f"**Speed:** {c['speed_recorded']} km/h (limit {c['speed_limit']})")
    with right:
        if c["evidence_path"] and Path(c["evidence_path"]).exists():
            st.image(c["evidence_path"], caption="Evidence", use_container_width=True)

    pdf = Path(c["pdf_path"]) if c["pdf_path"] else None
    if pdf and pdf.exists():
        st.download_button("⬇️ Download challan PDF", pdf.read_bytes(),
                           file_name=pdf.name, mime="application/pdf",
                           key=f"{key}_pdf_{challan_no}")

    st.markdown("#### 📱 Notify vehicle owner on WhatsApp")
    message = notify.build_message(c)
    with st.expander("Message preview"):
        st.text(message)

    if c["status"] == "Cancelled":
        st.info("This challan is cancelled.")
        return
    if not notify.normalize_mobile(c["owner_mobile"]):
        st.warning("No valid owner mobile number on record, so WhatsApp cannot be used.")
        return

    st.caption(f"Sending to {notify.mask_mobile(c['owner_mobile'])}")
    if config.WHATSAPP_MODE in ("twilio", "meta"):
        if st.button("📤 Send via WhatsApp", key=f"{key}_send_{challan_no}", type="primary"):
            ok, detail = notify.send_whatsapp(c["owner_mobile"], message)
            if ok:
                db.mark_sent(challan_no, officer["username"])
                st.success(detail)
                st.rerun()
            else:
                st.error(detail)
    else:
        st.link_button("📱 Open WhatsApp with message",
                       notify.whatsapp_link(c["owner_mobile"], message),
                       use_container_width=True)
        if c["status"] == "Issued" and st.button(
                "✅ I sent it - mark as Sent", key=f"{key}_mark_{challan_no}"):
            db.mark_sent(challan_no, officer["username"])
            st.rerun()
