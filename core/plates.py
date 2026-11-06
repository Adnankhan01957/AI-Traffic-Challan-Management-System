"""Indian number-plate normalisation and validation.

Format: SS NN XXX NNNN  -> state (2 letters), RTO (2 digits),
series (1-3 letters), number (4 digits). Example: TS10EX2850.
Telangana plates are "TS" (older) and "TG" (new registrations).
"""
from dataclasses import dataclass

STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "TG",
    "UK", "UP", "WB",
}

# OCR often confuses these look-alikes. We fix them by POSITION, because the
# format tells us whether a slot must be a letter or a digit.
_TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
             "S": "5", "G": "6", "B": "8"}


@dataclass
class PlateCheck:
    raw: str
    normalized: str      # letters+digits only, upper case
    valid: bool
    corrected: bool      # True if look-alike characters were fixed
    display: str         # e.g. "TS 10 EX 2850" (or normalized if invalid)
    message: str


def normalize(plate) -> str:
    if not plate:
        return ""
    return "".join(ch for ch in str(plate).upper() if ch.isalnum())


def _fix(chars: str, want_letters: bool) -> str:
    table = _TO_LETTER if want_letters else _TO_DIGIT
    return "".join(table.get(c, c) for c in chars)


def check_plate(raw) -> PlateCheck:
    norm = normalize(raw)
    if not norm:
        return PlateCheck(str(raw or ""), "", False, False, "", "No plate entered")

    series_len = len(norm) - 8
    if series_len not in (1, 2, 3):
        return PlateCheck(str(raw), norm, False, False, norm,
                          "Unexpected length for an Indian plate")

    state, rto = norm[:2], norm[2:4]
    series, number = norm[4:4 + series_len], norm[4 + series_len:]

    fixed_state = _fix(state, True)
    fixed_rto = _fix(rto, False)
    fixed_series = _fix(series, True)
    fixed_number = _fix(number, False)
    fixed = fixed_state + fixed_rto + fixed_series + fixed_number

    ok = (
        fixed_state.isalpha() and fixed_series.isalpha()
        and fixed_rto.isdigit() and fixed_number.isdigit()
        and fixed_state in STATE_CODES
    )
    if not ok:
        return PlateCheck(str(raw), norm, False, False, norm,
                          "Does not match the standard plate format")

    display = f"{fixed_state} {fixed_rto} {fixed_series} {fixed_number}"
    corrected = fixed != norm
    msg = "Valid format" + (" (look-alike characters auto-corrected - please verify)"
                            if corrected else "")
    return PlateCheck(str(raw), fixed, True, corrected, display, msg)
