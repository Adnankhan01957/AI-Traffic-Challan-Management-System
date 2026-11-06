"""AI image analysis (Groq vision): number plate + violation in ONE call.

The AI only SUGGESTS. A police officer must review and confirm before any
challan is issued.
"""
import base64
import io
import json
import re
from dataclasses import dataclass

from core import config

_VALID = {v.lower(): v for v in config.VIOLATIONS}

PROMPT = """You are assisting a traffic police officer. Look at the image.

Return ONLY a JSON object, nothing else, with these keys:
  "plate": the vehicle registration number of the MAIN violating vehicle,
           letters and digits only (example: TS10EX2850), or "" if not readable
  "violation": exactly one of "Triple Riding", "No Helmet", "No Parking",
           "Overspeed", "None"
  "confidence": "high", "medium" or "low"
  "note": one short sentence on what you see

Rules:
- "Triple Riding": three or more people on one two-wheeler.
- "No Helmet": a two-wheeler rider or pillion without a helmet.
- "No Parking": a vehicle stopped where parking is clearly prohibited.
- "Overspeed": only if the image itself clearly shows a speed reading; a photo
  alone usually cannot prove speed, so prefer "None" and say so in the note.
- Do not guess characters you cannot read; use "" for the plate instead.
"""


@dataclass
class DetectionResult:
    plate_raw: str = ""
    violation: str = "None"
    confidence: str = "low"
    note: str = ""
    raw: str = ""

    @classmethod
    def empty(cls, note: str = ""):
        return cls(note=note)


def prepare_image(data: bytes, max_side: int = 1600):
    """Return (base64_jpeg, extension_of_original). Shrinks big photos so the
    request stays small and fast."""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    ext = {"JPEG": "jpg", "PNG": "png"}.get((img.format or "").upper(), "jpg")
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii"), ext


def _strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text.strip()


def parse_response(text: str) -> DetectionResult:
    cleaned = _strip_thinking(text or "")
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return DetectionResult.empty("AI reply could not be understood")
    try:
        obj = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return DetectionResult.empty("AI reply could not be understood")

    violation = _VALID.get(str(obj.get("violation", "")).strip().lower(), "None")
    confidence = str(obj.get("confidence", "low")).strip().lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "low"
    return DetectionResult(
        plate_raw=str(obj.get("plate", "") or "").strip(),
        violation=violation,
        confidence=confidence,
        note=str(obj.get("note", "") or "").strip(),
        raw=cleaned,
    )


def _get_client():
    if not config.GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to the .env file (see .env.example)."
        )
    from groq import Groq

    return Groq(api_key=config.GROQ_API_KEY)


def analyze_image_bytes(data: bytes, client=None) -> DetectionResult:
    b64, _ = prepare_image(data)
    client = client or _get_client()
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }]

    # Some Groq models accept extra options to hide "thinking" text; others
    # reject them. Try the richer request first, then fall back.
    attempts = [
        {"temperature": 0, "reasoning_format": "hidden", "max_completion_tokens": 1500},
        {"temperature": 0, "max_completion_tokens": 1500},
        {"temperature": 0},
    ]
    last_error = None
    for extra in attempts:
        try:
            resp = client.chat.completions.create(
                model=config.GROQ_MODEL, messages=messages, **extra)
            return parse_response(resp.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001 - try the next option
            last_error = exc
            text = str(exc).lower()
            if "api key" in text or "401" in text or "model_not_found" in text:
                raise  # retrying will not help
    raise last_error
