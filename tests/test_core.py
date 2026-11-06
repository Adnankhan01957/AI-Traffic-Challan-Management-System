"""Run with:  python -m unittest discover -s tests -v
No internet, Streamlit or Groq account needed."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, db, detector, notify, plates  # noqa: E402


class TempEnv(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patches = [
            mock.patch.object(config, "DATA_DIR", root),
            mock.patch.object(config, "DB_PATH", root / "t.db"),
            mock.patch.object(config, "EVIDENCE_DIR", root / "evidence"),
            mock.patch.object(config, "CHALLAN_DIR", root / "challans"),
            mock.patch.object(config, "DRIVER_DIR", root / "drivers"),
        ]
        for p in self._patches:
            p.start()
        db.init_db()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()


class PlateTests(unittest.TestCase):
    def test_valid_plates(self):
        for raw in ["TS10EX2850", "ts 10 ed 8176", "MH43BA2518", "TG09PA3330", "TS09A1234"]:
            self.assertTrue(plates.check_plate(raw).valid, raw)

    def test_display_format(self):
        self.assertEqual(plates.check_plate("ts10ex2850").display, "TS 10 EX 2850")

    def test_ocr_lookalikes_are_fixed_by_position(self):
        c = plates.check_plate("TS1OEX285O")      # O instead of 0
        self.assertTrue(c.valid and c.corrected)
        self.assertEqual(c.normalized, "TS10EX2850")
        c = plates.check_plate("T510EX2850")      # 5 instead of S
        self.assertEqual(c.normalized, "TS10EX2850")

    def test_invalid(self):
        for raw in ["", "HELLO", "ZZ10EX2850", "TS10EX28", "12345678901"]:
            self.assertFalse(plates.check_plate(raw).valid, raw)


class DetectorTests(unittest.TestCase):
    def test_parse_clean_json(self):
        r = detector.parse_response(
            '{"plate":"TS10EX2850","violation":"triple riding","confidence":"high","note":"3 on bike"}')
        self.assertEqual((r.plate_raw, r.violation, r.confidence),
                         ("TS10EX2850", "Triple Riding", "high"))

    def test_parse_with_thinking_and_fences(self):
        text = '<think>hmm {not json}</think>\n```json\n{"plate":"","violation":"Overspeed","confidence":"weird"}\n```'
        r = detector.parse_response(text)
        self.assertEqual((r.plate_raw, r.violation, r.confidence), ("", "Overspeed", "low"))

    def test_parse_garbage(self):
        self.assertEqual(detector.parse_response("no json here").violation, "None")
        self.assertEqual(detector.parse_response("{bad json}").violation, "None")

    def test_unknown_violation_becomes_none(self):
        r = detector.parse_response('{"plate":"X","violation":"Jaywalking"}')
        self.assertEqual(r.violation, "None")

    def test_analyze_falls_back_when_option_rejected(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (50, 50), "white").save(buf, "JPEG")
        calls = []

        def create(**kw):
            calls.append(kw)
            if "reasoning_format" in kw:
                raise RuntimeError("reasoning_format not supported")
            msg = SimpleNamespace(content='{"plate":"TS10EX2850","violation":"No Helmet","confidence":"medium"}')
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        r = detector.analyze_image_bytes(buf.getvalue(), client=fake)
        self.assertEqual(r.violation, "No Helmet")
        self.assertEqual(len(calls), 2)

    def test_auth_error_is_not_retried(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (20, 20)).save(buf, "JPEG")
        calls = []

        def create(**kw):
            calls.append(1)
            raise RuntimeError("Error code: 401 Invalid API Key")

        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with self.assertRaises(RuntimeError):
            detector.analyze_image_bytes(buf.getvalue(), client=fake)
        self.assertEqual(len(calls), 1)


class NotifyTests(unittest.TestCase):
    def test_mobile_normalisation(self):
        self.assertEqual(notify.normalize_mobile("98765 43210"), "919876543210")
        self.assertEqual(notify.normalize_mobile("+91-98765-43210"), "919876543210")
        self.assertEqual(notify.normalize_mobile("09876543210"), "919876543210")
        self.assertEqual(notify.normalize_mobile("12345"), "")
        self.assertEqual(notify.normalize_mobile("5876543210"), "")  # must start 6-9

    def test_mask(self):
        self.assertNotIn("7654", notify.mask_mobile("9876543210"))
        self.assertEqual(notify.mask_mobile("abc"), "-")

    def test_link(self):
        link = notify.whatsapp_link("9876543210", "hello world ₹100")
        self.assertTrue(link.startswith("https://wa.me/919876543210?text="))
        self.assertNotIn(" ", link)

    def test_send_rejects_bad_number_and_link_mode(self):
        ok, _ = notify.send_whatsapp("123", "x")
        self.assertFalse(ok)
        with mock.patch.object(config, "WHATSAPP_MODE", "link"):
            ok, detail = notify.send_whatsapp("9876543210", "x")
        self.assertFalse(ok)

    def test_twilio_call_shape(self):
        resp = SimpleNamespace(status_code=201, text="{}")
        with mock.patch.object(config, "WHATSAPP_MODE", "twilio"), \
             mock.patch.object(config, "TWILIO_ACCOUNT_SID", "AC1"), \
             mock.patch.object(config, "TWILIO_AUTH_TOKEN", "tok"), \
             mock.patch("core.notify.requests.post", return_value=resp) as post:
            ok, _ = notify.send_whatsapp("9876543210", "hi")
        self.assertTrue(ok)
        self.assertEqual(post.call_args.kwargs["data"]["To"], "whatsapp:+919876543210")

    def test_provider_error_reported(self):
        resp = SimpleNamespace(status_code=401, text="unauthorized")
        with mock.patch.object(config, "WHATSAPP_MODE", "meta"), \
             mock.patch.object(config, "META_ACCESS_TOKEN", "t"), \
             mock.patch.object(config, "META_PHONE_NUMBER_ID", "1"), \
             mock.patch("core.notify.requests.post", return_value=resp):
            ok, detail = notify.send_whatsapp("9876543210", "hi")
        self.assertFalse(ok)
        self.assertIn("401", detail)


class DbFlowTests(TempEnv):
    def _officer(self):
        return db.verify_login(config.DEFAULT_ADMIN_USER, config.DEFAULT_ADMIN_PASSWORD)

    def test_login(self):
        self.assertIsNotNone(self._officer())
        self.assertIsNone(db.verify_login("admin", "wrong"))
        self.assertTrue(db.default_admin_password_in_use())
        db.set_password("admin", "NewStrongPass1", "admin")
        self.assertFalse(db.default_admin_password_in_use())
        with self.assertRaises(ValueError):
            db.set_password("admin", "short", "admin")

    def test_challan_lifecycle(self):
        off = self._officer()
        c = db.create_challan(
            officer=off, plate_norm="TS10EX2850", plate_display="TS 10 EX 2850",
            owner_name="Test Owner", owner_mobile="9876543210",
            violation="Triple Riding", fine=db.get_fine("Triple Riding"),
            location="Test Junction", offence_time="2026-11-06 10:00:00")
        self.assertTrue(c["challan_no"].startswith("CH"))
        self.assertTrue(c["challan_no"].endswith("-0001"))
        c2 = db.create_challan(
            officer=off, plate_norm="TS10EX2850", plate_display="TS 10 EX 2850",
            owner_name="Test Owner", owner_mobile="", violation="No Helmet",
            fine=200, location="x", offence_time="2026-11-06 10:05:00")
        self.assertTrue(c2["challan_no"].endswith("-0002"))

        self.assertIsNotNone(db.find_recent_duplicate("TS10EX2850", "Triple Riding"))
        self.assertIsNone(db.find_recent_duplicate("TS10EX2850", "Overspeed"))

        db.mark_sent(c["challan_no"], "admin")
        self.assertEqual(db.get_challan(c["challan_no"])["status"], "Sent")

        with self.assertRaises(ValueError):
            db.set_status(c["challan_no"], "Cancelled", "admin", "")
        db.set_status(c["challan_no"], "Cancelled", "admin", "wrong vehicle")
        self.assertIsNone(db.find_recent_duplicate("TS10EX2850", "Triple Riding"))

        s = db.stats()
        self.assertEqual(s["totals"]["n"], 1)  # cancelled one excluded
        self.assertEqual(len(db.search_challans(plate="ts10 ex")), 2)
        self.assertEqual(len(db.search_challans(status="Cancelled")), 1)

    def test_vehicle_upsert_keeps_photo(self):
        db.upsert_vehicle("TS10EX2850", "TS 10 EX 2850", "A", "Bike", "1", "9876543210", "a.jpg")
        db.upsert_vehicle("TS10EX2850", "TS 10 EX 2850", "A2", "Bike", "1", "9876543210", "")
        v = db.get_vehicle("TS10EX2850")
        self.assertEqual((v["owner_name"], v["driver_photo"]), ("A2", "a.jpg"))

    def test_pdf_generation(self):
        from PIL import Image
        from core import challan_pdf
        off = self._officer()
        ev = config.EVIDENCE_DIR
        ev.mkdir(parents=True, exist_ok=True)
        img = ev / "e.jpg"
        Image.new("RGB", (800, 600), "gray").save(img)
        c = db.create_challan(
            officer=off, plate_norm="TS10EX2850", plate_display="TS 10 EX 2850",
            owner_name="Test Owner", owner_mobile="9876543210", violation="Overspeed",
            fine=1000, location="ORR", offence_time="2026-11-06 10:00:00",
            speed_recorded=85, speed_limit=60, evidence_path=str(img),
            evidence_sha256="abc")
        pdf = challan_pdf.build_pdf(c, config.CHALLAN_DIR / f"{c['challan_no']}.pdf")
        self.assertTrue(pdf.exists() and pdf.stat().st_size > 1500)
        self.assertEqual(pdf.read_bytes()[:4], b"%PDF")
        msg = notify.build_message(c)
        self.assertIn(c["challan_no"], msg)
        self.assertIn("85 km/h", msg)


class MigrationTests(TempEnv):
    def test_migrate_from_legacy_layout(self):
        import sqlite3
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import migrate_legacy

        legacy = Path(self._tmp.name) / "legacy"
        (legacy / "drivers").mkdir(parents=True)
        (legacy / "drivers" / "d1.jpg").write_bytes(b"x")

        u = sqlite3.connect(legacy / "user.db")
        u.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, vehicle_reg TEXT,"
                  " vehicle_type TEXT, vehnum TEXT, mobile TEXT, driver_photo TEXT)")
        u.execute("INSERT INTO users VALUES (1,'Asha','TS10ED8176','Scooty','1','9876543210','drivers/d1.jpg')")
        u.commit(); u.close()

        c = sqlite3.connect(legacy / "Chalan.db")
        c.execute("CREATE TABLE violations (id INTEGER PRIMARY KEY, violation_name TEXT, fine INTEGER)")
        c.execute("INSERT INTO violations VALUES (1,'Triple Ride',1500)")
        c.execute("CREATE TABLE challans (id INTEGER PRIMARY KEY, driver_name TEXT, vehicle_reg TEXT,"
                  " violation TEXT, fine INTEGER, mobile TEXT, driver_photo TEXT, challan_date TEXT)")
        c.execute("INSERT INTO challans VALUES (1,'Asha','TS10ED8176','No Parking',100,'9876543210','x','2026-08-28 05:25:25')")
        c.commit(); c.close()

        counts = migrate_legacy.migrate(legacy)
        self.assertEqual(counts, {"vehicles": 1, "photos": 1, "fines": 1, "challans": 1})
        self.assertEqual(db.get_vehicle("TS10ED8176")["driver_photo"], "d1.jpg")
        self.assertEqual(db.get_fine("Triple Riding"), 1500)
        # idempotent
        again = migrate_legacy.migrate(legacy)
        self.assertEqual(again["challans"], 0)
        self.assertEqual(len(db.search_challans()), 1)


if __name__ == "__main__":
    unittest.main()
