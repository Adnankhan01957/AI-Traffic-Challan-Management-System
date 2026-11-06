"""Message building and WhatsApp delivery."""
import urllib.parse

import requests

from core import config


def normalize_mobile(mobile: str) -> str:
    """Return an Indian mobile as digits with country code (91XXXXXXXXXX),
    or '' if it does not look valid."""
    digits = "".join(ch for ch in str(mobile or "") if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return digits
    return ""


def mask_mobile(mobile: str) -> str:
    m = normalize_mobile(mobile)
    if not m:
        return "-"
    return f"+91 {m[2:4]}••••••{m[-2:]}"


def build_message(c: dict) -> str:
    lines = [
        f"TRAFFIC CHALLAN - {config.STATION_NAME}",
        "",
        f"Dear {c.get('owner_name') or 'Vehicle Owner'},",
        "A traffic violation was recorded for your vehicle.",
        "",
        f"Challan No: {c['challan_no']}",
        f"Vehicle: {c['plate_display']}",
        f"Violation: {c['violation']}",
        f"Date/Time: {c['offence_time']}",
        f"Location: {c['location']}",
        f"Fine: ₹{c['fine']}",
    ]
    if c.get("speed_recorded"):
        lines.append(f"Recorded speed: {c['speed_recorded']} km/h "
                     f"(limit {c['speed_limit']} km/h)")
    lines.append("")
    if config.PAYMENT_URL:
        lines.append(f"Pay ONLY on the official portal: {config.PAYMENT_URL}")
    else:
        lines.append("Pay only through official traffic police channels.")
    if config.HELPLINE:
        lines.append(f"If you believe this is a mistake, contact: {config.HELPLINE}")
    lines.append("Do not share OTPs or card details with anyone.")
    return "\n".join(lines)


def whatsapp_link(mobile: str, message: str) -> str:
    number = normalize_mobile(mobile)
    return f"https://wa.me/{number}?text={urllib.parse.quote(message)}"


def send_whatsapp(mobile: str, message: str):
    """Send automatically. Returns (ok, detail). Only used for twilio/meta."""
    number = normalize_mobile(mobile)
    if not number:
        return False, "Owner mobile number is missing or invalid"

    try:
        if config.WHATSAPP_MODE == "twilio":
            if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN):
                return False, "Twilio credentials are not configured"
            r = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/"
                f"{config.TWILIO_ACCOUNT_SID}/Messages.json",
                auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
                data={"From": config.TWILIO_WHATSAPP_FROM,
                      "To": f"whatsapp:+{number}", "Body": message},
                timeout=20,
            )
        elif config.WHATSAPP_MODE == "meta":
            if not (config.META_ACCESS_TOKEN and config.META_PHONE_NUMBER_ID):
                return False, "Meta WhatsApp credentials are not configured"
            r = requests.post(
                f"https://graph.facebook.com/v20.0/{config.META_PHONE_NUMBER_ID}/messages",
                headers={"Authorization": f"Bearer {config.META_ACCESS_TOKEN}"},
                json={"messaging_product": "whatsapp", "to": number,
                      "type": "text", "text": {"body": message}},
                timeout=20,
            )
        else:
            return False, "WHATSAPP_MODE is 'link'; use the WhatsApp button instead"
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"

    if 200 <= r.status_code < 300:
        return True, "Message accepted by the WhatsApp provider"
    return False, f"Provider error {r.status_code}: {r.text[:300]}"
