"""Central configuration.

Secrets (API keys, passwords) are read ONLY from environment variables or a
local .env file. Never hard-code them in source files.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:  # python-dotenv is optional but recommended
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass

# ---------------------------------------------------------------- storage
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "traffic.db"
EVIDENCE_DIR = DATA_DIR / "evidence"
CHALLAN_DIR = DATA_DIR / "challans"
DRIVER_DIR = DATA_DIR / "drivers"

# ------------------------------------------------------------------- AI
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

# --------------------------------------------------------------- WhatsApp
# link   -> officer taps a button; WhatsApp opens with the message pre-filled
# twilio -> automatic sending through Twilio WhatsApp API
# meta   -> automatic sending through Meta WhatsApp Cloud API
WHATSAPP_MODE = os.getenv("WHATSAPP_MODE", "link").lower()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")

# ----------------------------------------------------------- organisation
STATION_NAME = os.getenv("STATION_NAME", "Traffic Police")
DEFAULT_LOCATION = os.getenv("DEFAULT_LOCATION", "Hyderabad")
# Put the OFFICIAL payment/e-challan portal link here so owners are never
# sent to an unofficial site.
PAYMENT_URL = os.getenv("PAYMENT_URL", "")
HELPLINE = os.getenv("HELPLINE", "")

# ------------------------------------------------------------- violations
VIOLATIONS = ["Triple Riding", "No Helmet", "No Parking", "Overspeed", "Wrong Side Driving"]
# Seed values copied from the original project. They are EDITABLE in the
# Admin page. Check them against the official Telangana fine schedule
# before real use.
DEFAULT_FINES = {
    "Triple Riding": 1000,
    "No Helmet": 200,
    "No Parking": 100,
    "Overspeed": 1000,
    "Wrong Side Driving": 1000,
}
DEFAULT_ADMIN_USER = os.getenv("ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

DUPLICATE_WINDOW_HOURS = 24


def ensure_dirs() -> None:
    for d in (DATA_DIR, EVIDENCE_DIR, CHALLAN_DIR, DRIVER_DIR):
        Path(d).mkdir(parents=True, exist_ok=True)
