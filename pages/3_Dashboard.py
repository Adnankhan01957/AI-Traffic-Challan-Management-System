import pandas as pd
import streamlit as st

from core import db
from core.auth import require_login

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
require_login()
st.title("📊 Dashboard")

s = db.stats()
t = s["totals"]
m1, m2, m3 = st.columns(3)
m1.metric("Challans issued", t["n"])
m2.metric("Total fines", f"₹{t['total_fine']:,}")
m3.metric("Collected (marked Paid)", f"₹{t['collected']:,}")

if t["n"] == 0:
    st.info("No challans yet.")
    st.stop()

a, b = st.columns(2)
with a:
    st.subheader("By violation")
    st.bar_chart(pd.DataFrame(s["by_violation"]).set_index("violation"))
with b:
    st.subheader("By status")
    st.bar_chart(pd.DataFrame(s["by_status"]).set_index("status"))

st.subheader("Challans per day")
st.line_chart(pd.DataFrame(s["by_day"]).set_index("day"))

if s["repeat"]:
    st.subheader("Repeat offenders")
    st.dataframe(pd.DataFrame(s["repeat"]).rename(columns={
        "plate_display": "Vehicle", "n": "Challans", "total": "Total fine (₹)"}),
        use_container_width=True, hide_index=True)
