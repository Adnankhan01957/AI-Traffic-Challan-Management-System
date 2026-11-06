"""UI smoke test with a stand-in for Streamlit (the real one is not needed).
Run:  python tests/smoke_ui.py
Checks that each page runs without Python errors and that the issue-challan
flow creates a challan + PDF."""
import datetime
import runpy
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Stop(BaseException):
    pass


class Col:
    """Stand-in for a column/tab: widgets inside behave like the page-level ones."""
    def __init__(self, st):
        self._st = st

    def __getattr__(self, name):
        return getattr(self._st, name)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_st(state, *, issue=False, uploaded=None, wa_click=False):
    st = mock.MagicMock(name="streamlit")
    st.session_state = state
    st.stop.side_effect = Stop
    st.rerun.side_effect = Stop
    st.cache_resource = lambda f: f
    st.cache_data = lambda **k: (lambda f: f)
    st.columns.side_effect = lambda spec, **k: [
        Col(st) for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs.side_effect = lambda labels: [Col(st) for _ in labels]
    st.button.side_effect = lambda label, *a, **k: bool(issue and "Issue challan" in label)
    st.form_submit_button.return_value = False
    st.checkbox.return_value = True
    st.text_input.side_effect = lambda label, value="", **k: (
        "TS10EX2850" if label == "Number plate" else (value or ""))
    st.selectbox.side_effect = lambda label, options, index=0, **k: list(options)[index]
    st.number_input.side_effect = lambda label, **k: k.get("value", 0)
    st.date_input.side_effect = lambda label, value=None, **k: value
    st.time_input.side_effect = lambda label, value=None, **k: value
    st.file_uploader.return_value = uploaded
    st.camera_input.return_value = None
    st.data_editor.side_effect = lambda df, **k: df
    return st


def run_page(path, st):
    # Swap in only the stand-in "streamlit"; leave every other module alone.
    previous = sys.modules.get("streamlit")
    sys.modules["streamlit"] = st
    for m in ("core.auth", "core.ui"):
        sys.modules.pop(m, None)
    try:
        runpy.run_path(str(ROOT / path), run_name="__main__")
    except Stop:
        pass
    finally:
        if previous is None:
            sys.modules.pop("streamlit", None)
        else:
            sys.modules["streamlit"] = previous


def main():
    import reportlab.platypus, pandas  # noqa: F401  (pre-import)
    from core import config, db, detector, challan_pdf  # noqa: F401
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    with mock.patch.object(config, "DATA_DIR", root), \
         mock.patch.object(config, "DB_PATH", root / "t.db"), \
         mock.patch.object(config, "EVIDENCE_DIR", root / "evidence"), \
         mock.patch.object(config, "CHALLAN_DIR", root / "challans"), \
         mock.patch.object(config, "DRIVER_DIR", root / "drivers"):
        db.init_db()
        officer = db.verify_login(config.DEFAULT_ADMIN_USER, config.DEFAULT_ADMIN_PASSWORD)
        assert officer
        db.upsert_vehicle("TS10EX2850", "TS 10 EX 2850", "Test Owner", "Bike", "1", "9876543210")

        img = (ROOT / "samples" / "triple_riding.jpg").read_bytes()
        up = mock.MagicMock()
        up.getvalue.return_value = img

        # 1) not logged in -> login form, then stop
        st = make_st({})
        run_page("app.py", st)
        assert "officer" not in st.session_state

        # 2) logged in, photo uploaded, nothing clicked -> renders review form
        st = make_st({"officer": officer}, uploaded=up)
        run_page("app.py", st)

        # 3) AI analysis present + confirm + click Issue -> challan and PDF created
        import hashlib
        sha = hashlib.sha256(img).hexdigest()
        res = detector.DetectionResult("TS10EX2850", "Triple Riding", "high", "3 on a bike")
        state = {"officer": officer, "analysis": {"sha": sha, "result": res}}
        st = make_st(state, issue=True, uploaded=up)
        run_page("app.py", st)
        no = state.get("last_challan")
        assert no, "challan was not issued"
        c = db.get_challan(no)
        assert c["violation"] == "Triple Riding" and c["owner_name"] == "Test Owner"
        assert c["officer_edited"] == 0 and Path(c["pdf_path"]).exists()
        assert Path(c["evidence_path"]).exists()
        print("issued:", no, "| pdf bytes:", Path(c["pdf_path"]).stat().st_size)

        # 4) result panel + other pages render
        for page in ["app.py", "pages/1_Challan_Records.py", "pages/2_Vehicle_Registry.py",
                     "pages/3_Dashboard.py", "pages/4_Admin.py"]:
            st = make_st({"officer": officer, "last_challan": no} if page == "app.py"
                         else {"officer": officer})
            run_page(page, st)
            print("rendered:", page)

        # 5) non-admin cannot open Admin page
        db.create_officer("pc1", "PC One", "B-1", "officer", "Password123", "admin")
        pc = db.verify_login("pc1", "Password123")
        st = make_st({"officer": pc})
        run_page("pages/4_Admin.py", st)
        assert st.error.called, "admin page should reject non-admin"
        print("non-admin blocked: OK")
    tmp.cleanup()
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
