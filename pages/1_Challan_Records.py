import csv
import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import config, db, notify, ui
from core.auth import require_login

st.set_page_config(page_title="Challan Records", page_icon="📋", layout="wide")
officer = require_login()
st.title("📋 Challan Records")

f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
plate = f1.text_input("Plate contains")
violation = f2.selectbox("Violation", [""] + config.VIOLATIONS, format_func=lambda x: x or "All")
status = f3.selectbox("Status", ["", "Issued", "Sent", "Paid", "Cancelled"],
                      format_func=lambda x: x or "All")
dr = f4.date_input("Created between", value=(date.today() - timedelta(days=30), date.today()))
d_from, d_to = (dr if isinstance(dr, tuple) and len(dr) == 2 else (None, None))

rows = db.search_challans(plate, violation, status,
                          d_from.isoformat() if d_from else "",
                          d_to.isoformat() if d_to else "")
st.write(f"**{len(rows)}** challans")

if rows:
    df = pd.DataFrame(rows)[["challan_no", "created_at", "plate_display", "owner_name",
                             "violation", "fine", "status", "location", "officer_name"]]
    st.dataframe(df, use_container_width=True, hide_index=True)

    if officer["role"] == "admin":
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        st.download_button("⬇️ Export CSV", buf.getvalue(), "challans.csv", "text/csv")

    st.divider()
    chosen = st.selectbox("Open a challan", [r["challan_no"] for r in rows])
    with st.container(border=True):
        ui.render_challan_panel(chosen, officer, key="rec")

    c = db.get_challan(chosen)
    st.markdown("#### Update status")
    s1, s2 = st.columns(2)
    with s1:
        if c["status"] in ("Issued", "Sent") and st.button("💰 Mark as Paid"):
            db.set_status(chosen, "Paid", officer["username"])
            st.rerun()
    with s2:
        if c["status"] != "Cancelled":
            reason = st.text_input("Reason for cancelling (required)")
            if st.button("🚫 Cancel challan"):
                try:
                    db.set_status(chosen, "Cancelled", officer["username"], reason)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
