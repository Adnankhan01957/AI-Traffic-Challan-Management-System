"""SQLite storage: officers, vehicles, fines, challans, audit log."""
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from core import config

IST = timezone(timedelta(hours=5, minutes=30))

SCHEMA = """
CREATE TABLE IF NOT EXISTS officers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    badge_no TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'officer' CHECK (role IN ('officer','admin')),
    pw_salt TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_norm TEXT NOT NULL UNIQUE,
    plate_display TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    vehicle_type TEXT NOT NULL DEFAULT '',
    vehicle_id TEXT NOT NULL DEFAULT '',
    mobile TEXT NOT NULL DEFAULT '',
    driver_photo TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS fines (
    violation TEXT PRIMARY KEY,
    fine INTEGER NOT NULL CHECK (fine >= 0),
    section TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS challans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challan_no TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    officer_id INTEGER NOT NULL REFERENCES officers(id),
    plate_norm TEXT NOT NULL,
    plate_display TEXT NOT NULL,
    owner_name TEXT NOT NULL DEFAULT '',
    owner_mobile TEXT NOT NULL DEFAULT '',
    violation TEXT NOT NULL,
    fine INTEGER NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    offence_time TEXT NOT NULL,
    speed_recorded INTEGER,
    speed_limit INTEGER,
    evidence_path TEXT NOT NULL DEFAULT '',
    evidence_sha256 TEXT NOT NULL DEFAULT '',
    ai_plate TEXT NOT NULL DEFAULT '',
    ai_violation TEXT NOT NULL DEFAULT '',
    ai_confidence TEXT NOT NULL DEFAULT '',
    officer_edited INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Issued'
        CHECK (status IN ('Issued','Sent','Paid','Cancelled')),
    sent_at TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    pdf_path TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_challans_plate ON challans(plate_norm);
CREATE INDEX IF NOT EXISTS idx_challans_created ON challans(created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    officer TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


def now_ist() -> datetime:
    return datetime.now(IST).replace(microsecond=0)


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def get_conn():
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ----------------------------------------------------------------- passwords
def hash_password(password: str, salt_hex: str | None = None):
    salt_hex = salt_hex or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 200_000
    )
    return salt_hex, digest.hex()


def _check_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, hash_hex)


# ---------------------------------------------------------------------- init
def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for name, fine in config.DEFAULT_FINES.items():
            conn.execute(
                "INSERT OR IGNORE INTO fines (violation, fine) VALUES (?, ?)",
                (name, fine),
            )
        if conn.execute("SELECT COUNT(*) FROM officers").fetchone()[0] == 0:

            if not config.DEFAULT_ADMIN_PASSWORD:
                raise RuntimeError(
                    "ADMIN_PASSWORD is missing. "
                    "Set a strong password in your .env file."
                )

            if len(config.DEFAULT_ADMIN_PASSWORD) < 12:
                raise RuntimeError(
                    "ADMIN_PASSWORD must contain at least 12 characters."
                )

            salt, h = hash_password(config.DEFAULT_ADMIN_PASSWORD)

            conn.execute(
                "INSERT INTO officers (username, full_name, badge_no, role, pw_salt, pw_hash)"
                " VALUES (?, ?, ?, 'admin', ?, ?)",
                (config.DEFAULT_ADMIN_USER, "Administrator", "", salt, h),
            )


def audit(conn, officer: str, action: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, officer, action, detail) VALUES (?, ?, ?, ?)",
        (fmt(now_ist()), officer, action, detail),
    )


# ------------------------------------------------------------------ officers
def verify_login(username: str, password: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM officers WHERE username = ? AND active = 1",
            (username.strip(),),
        ).fetchone()
        if row and _check_password(password, row["pw_salt"], row["pw_hash"]):
            audit(conn, row["username"], "login")
            return dict(row)
        audit(conn, username.strip() or "?", "login_failed")
    return None


def default_admin_password_in_use() -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM officers WHERE username = ?", (config.DEFAULT_ADMIN_USER,)
        ).fetchone()
    return bool(row and _check_password(
        config.DEFAULT_ADMIN_PASSWORD, row["pw_salt"], row["pw_hash"]))


def create_officer(username, full_name, badge_no, role, password, by: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt, h = hash_password(password)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO officers (username, full_name, badge_no, role, pw_salt, pw_hash)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (username.strip(), full_name.strip(), badge_no.strip(), role, salt, h),
        )
        audit(conn, by, "officer_created", username)


def set_password(username: str, password: str, by: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt, h = hash_password(password)
    with get_conn() as conn:
        conn.execute(
            "UPDATE officers SET pw_salt = ?, pw_hash = ? WHERE username = ?",
            (salt, h, username),
        )
        audit(conn, by, "password_changed", username)


def list_officers():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, username, full_name, badge_no, role, active FROM officers ORDER BY id")]


def set_officer_active(username: str, active: bool, by: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE officers SET active = ? WHERE username = ?",
                     (1 if active else 0, username))
        audit(conn, by, "officer_active_changed", f"{username}={active}")


# ------------------------------------------------------------------ vehicles
def get_vehicle(plate_norm: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM vehicles WHERE plate_norm = ?", (plate_norm,)
        ).fetchone()
    return dict(row) if row else None


def upsert_vehicle(plate_norm, plate_display, owner_name, vehicle_type="",
                   vehicle_id="", mobile="", driver_photo="", by="system") -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO vehicles
               (plate_norm, plate_display, owner_name, vehicle_type, vehicle_id, mobile, driver_photo)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(plate_norm) DO UPDATE SET
                 plate_display = excluded.plate_display,
                 owner_name = excluded.owner_name,
                 vehicle_type = excluded.vehicle_type,
                 vehicle_id = excluded.vehicle_id,
                 mobile = excluded.mobile,
                 driver_photo = CASE WHEN excluded.driver_photo = ''
                                     THEN vehicles.driver_photo
                                     ELSE excluded.driver_photo END""",
            (plate_norm, plate_display, owner_name, vehicle_type, vehicle_id,
             mobile, driver_photo),
        )
        audit(conn, by, "vehicle_saved", plate_norm)


def list_vehicles():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY owner_name")]


def delete_vehicle(plate_norm: str, by: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM vehicles WHERE plate_norm = ?", (plate_norm,))
        audit(conn, by, "vehicle_deleted", plate_norm)


# --------------------------------------------------------------------- fines
def get_fine(violation: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT fine FROM fines WHERE violation = ?", (violation,)
        ).fetchone()
    return int(row["fine"]) if row else 0


def list_fines():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM fines ORDER BY violation")]


def update_fine(violation: str, fine: int, section: str, by: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE fines SET fine = ?, section = ? WHERE violation = ?",
            (int(fine), section, violation),
        )
        audit(conn, by, "fine_updated", f"{violation}={fine}")


# ------------------------------------------------------------------ challans
def find_recent_duplicate(plate_norm: str, violation: str):
    since = fmt(now_ist() - timedelta(hours=config.DUPLICATE_WINDOW_HOURS))
    with get_conn() as conn:
        row = conn.execute(
            """SELECT challan_no, created_at FROM challans
               WHERE plate_norm = ? AND violation = ? AND status != 'Cancelled'
                 AND created_at >= ? ORDER BY id DESC LIMIT 1""",
            (plate_norm, violation, since),
        ).fetchone()
    return dict(row) if row else None


def create_challan(*, officer: dict, plate_norm, plate_display, owner_name,
                   owner_mobile, violation, fine, location, offence_time: str,
                   speed_recorded=None, speed_limit=None, evidence_path="",
                   evidence_sha256="", ai_plate="", ai_violation="",
                   ai_confidence="", officer_edited=False, notes="") -> dict:
    now = now_ist()
    day = now.strftime("%Y%m%d")
    with get_conn() as conn:
        seq = conn.execute(
            "SELECT COUNT(*) FROM challans WHERE challan_no LIKE ?", (f"CH{day}-%",)
        ).fetchone()[0] + 1
        challan_no = f"CH{day}-{seq:04d}"
        conn.execute(
            """INSERT INTO challans
               (challan_no, created_at, officer_id, plate_norm, plate_display,
                owner_name, owner_mobile, violation, fine, location, offence_time,
                speed_recorded, speed_limit, evidence_path, evidence_sha256,
                ai_plate, ai_violation, ai_confidence, officer_edited, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (challan_no, fmt(now), officer["id"], plate_norm, plate_display,
             owner_name, owner_mobile, violation, int(fine), location,
             offence_time, speed_recorded, speed_limit, evidence_path,
             evidence_sha256, ai_plate, ai_violation, ai_confidence,
             1 if officer_edited else 0, notes),
        )
        audit(conn, officer["username"], "challan_issued",
              f"{challan_no} {plate_norm} {violation} Rs{fine}")
    return get_challan(challan_no)


def get_challan(challan_no: str):
    with get_conn() as conn:
        row = conn.execute(
            """SELECT c.*, o.full_name AS officer_name, o.badge_no AS officer_badge
               FROM challans c JOIN officers o ON o.id = c.officer_id
               WHERE c.challan_no = ?""", (challan_no,)
        ).fetchone()
    return dict(row) if row else None


def set_pdf_path(challan_no: str, path: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE challans SET pdf_path = ? WHERE challan_no = ?",
                     (str(path), challan_no))


def mark_sent(challan_no: str, by: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE challans SET status = 'Sent', sent_at = ? "
            "WHERE challan_no = ? AND status = 'Issued'",
            (fmt(now_ist()), challan_no),
        )
        audit(conn, by, "challan_sent", challan_no)


def set_status(challan_no: str, status: str, by: str, reason: str = "") -> None:
    if status == "Cancelled" and not reason.strip():
        raise ValueError("A reason is required to cancel a challan")
    with get_conn() as conn:
        conn.execute("UPDATE challans SET status = ?, notes = CASE WHEN ? != '' "
                     "THEN ? ELSE notes END WHERE challan_no = ?",
                     (status, reason, reason, challan_no))
        audit(conn, by, f"challan_{status.lower()}", f"{challan_no} {reason}".strip())


def search_challans(plate="", violation="", status="", date_from="", date_to="",
                    limit=1000):
    sql = ["SELECT c.*, o.full_name AS officer_name FROM challans c "
           "JOIN officers o ON o.id = c.officer_id WHERE 1=1"]
    args = []
    if plate:
        sql.append("AND c.plate_norm LIKE ?")
        args.append(f"%{''.join(ch for ch in plate.upper() if ch.isalnum())}%")
    if violation:
        sql.append("AND c.violation = ?")
        args.append(violation)
    if status:
        sql.append("AND c.status = ?")
        args.append(status)
    if date_from:
        sql.append("AND substr(c.created_at, 1, 10) >= ?")
        args.append(date_from)
    if date_to:
        sql.append("AND substr(c.created_at, 1, 10) <= ?")
        args.append(date_to)
    sql.append("ORDER BY c.id DESC LIMIT ?")
    args.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(" ".join(sql), args)]


def stats():
    with get_conn() as conn:
        q = lambda s, *a: [dict(r) for r in conn.execute(s, a)]
        return {
            "totals": q("""SELECT COUNT(*) AS n,
                                  COALESCE(SUM(fine),0) AS total_fine,
                                  COALESCE(SUM(CASE WHEN status='Paid' THEN fine END),0) AS collected
                           FROM challans WHERE status != 'Cancelled'""")[0],
            "by_violation": q("""SELECT violation, COUNT(*) AS n FROM challans
                                 WHERE status != 'Cancelled' GROUP BY violation ORDER BY n DESC"""),
            "by_status": q("SELECT status, COUNT(*) AS n FROM challans GROUP BY status"),
            "by_day": q("""SELECT substr(created_at,1,10) AS day, COUNT(*) AS n FROM challans
                           WHERE status != 'Cancelled' GROUP BY day ORDER BY day"""),
            "repeat": q("""SELECT plate_display, COUNT(*) AS n, SUM(fine) AS total FROM challans
                           WHERE status != 'Cancelled' GROUP BY plate_norm
                           HAVING n > 1 ORDER BY n DESC LIMIT 10"""),
        }
