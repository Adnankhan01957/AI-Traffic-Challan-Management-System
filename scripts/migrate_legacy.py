"""Import data from the ORIGINAL project (user.db + Chalan.db + drivers/).

Usage (from the new project folder):
    python scripts/migrate_legacy.py "E:\\Projects\\traffic_challan\\traffic_challan\\Traffic_Chalan"

Safe to run more than once: vehicles are updated, old challans are skipped
if already imported.
"""
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config, db, plates  # noqa: E402

NAME_MAP = {"Triple Ride": "Triple Riding"}


def migrate(legacy_dir) -> dict:
    legacy = Path(legacy_dir)
    db.init_db()
    config.ensure_dirs()
    counts = {"vehicles": 0, "photos": 0, "fines": 0, "challans": 0}

    user_db = legacy / "user.db"
    if user_db.exists():
        src = sqlite3.connect(user_db)
        src.row_factory = sqlite3.Row
        for r in src.execute("SELECT * FROM users"):
            check = plates.check_plate(r["vehicle_reg"])
            norm = check.normalized or plates.normalize(r["vehicle_reg"])
            photo_name = ""
            rel = (r["driver_photo"] or "").replace("\\", "/")
            if rel:
                photo_src = legacy / rel
                if photo_src.exists():
                    photo_name = photo_src.name
                    shutil.copy2(photo_src, config.DRIVER_DIR / photo_name)
                    counts["photos"] += 1
            db.upsert_vehicle(
                norm, check.display or norm, r["name"], r["vehicle_type"] or "",
                r["vehnum"] or "", r["mobile"] or "", photo_name, by="migration")
            counts["vehicles"] += 1
        src.close()

    chalan_db = legacy / "Chalan.db"
    if chalan_db.exists():
        src = sqlite3.connect(chalan_db)
        src.row_factory = sqlite3.Row
        for r in src.execute("SELECT * FROM violations"):
            name = NAME_MAP.get(r["violation_name"], r["violation_name"])
            with db.get_conn() as conn:
                conn.execute(
                    "INSERT INTO fines (violation, fine) VALUES (?, ?) "
                    "ON CONFLICT(violation) DO UPDATE SET fine = excluded.fine",
                    (name, r["fine"]))
            counts["fines"] += 1

        has_challans = src.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'challans'").fetchone()
        if has_challans:
            with db.get_conn() as conn:
                admin_id = conn.execute(
                    "SELECT id FROM officers ORDER BY id LIMIT 1").fetchone()[0]
                for r in src.execute("SELECT * FROM challans"):
                    no = f"LEGACY-{r['id']:04d}"
                    if conn.execute("SELECT 1 FROM challans WHERE challan_no = ?",
                                    (no,)).fetchone():
                        continue
                    check = plates.check_plate(r["vehicle_reg"])
                    when = r["challan_date"] or db.fmt(db.now_ist())
                    conn.execute(
                        """INSERT INTO challans
                           (challan_no, created_at, officer_id, plate_norm,
                            plate_display, owner_name, owner_mobile, violation,
                            fine, location, offence_time)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (no, when, admin_id,
                         check.normalized or plates.normalize(r["vehicle_reg"]),
                         check.display or r["vehicle_reg"], r["driver_name"],
                         r["mobile"] or "",
                         NAME_MAP.get(r["violation"], r["violation"]),
                         r["fine"], "Imported", when))
                    counts["challans"] += 1
        src.close()
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(migrate(sys.argv[1]))
