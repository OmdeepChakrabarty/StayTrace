"""
Validation rules and schema verification for StayTrace scraper and tracking data.
Completely deterministic, pure logic, no I/O, no network calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


class ValidationError(ValueError):
    """Raised when parcel tracking payload or event fails validation."""
    pass


# Regular expressions for tracking number formats
CARRIER_TRACKING_PATTERNS = {
    "usps": [
        r"^(94|93|92|95|82|83)\d{20}$",                 # Standard USPS 22-digit
        r"^\d{20,22}$",                                  # General 20-22 numeric
        r"^[A-Z]{2}\d{9}[A-Z]{2}$",                      # S10 International format (e.g., EA123456789US)
        r"^\d{13}$",                                     # Priority Mail 13 digits
    ],
    "fedex": [
        r"^\d{12}$",                                     # FedEx Express 12-digit
        r"^\d{14,15}$",                                  # FedEx Ground 14/15-digit
        r"^\d{20}$",                                     # FedEx SmartPost
        r"^\d{22}$",                                     # FedEx 22-digit
        r"^96\d{20}$",                                   # FedEx 96-prefix
    ],
    "ups": [
        r"^1Z[0-9A-Z]{16}$",                             # Standard 18-char 1Z...
        r"^\d{9,12}$",                                   # UPS 9-12 digits
        r"^T\d{10}$",                                    # UPS Mail Innovations T...
        r"^[0-9A-Z]{10,12}$",                            # Alphanumeric UPS reference
    ],
    "dhl": [
        r"^\d{10,11}$",                                  # DHL Express 10 or 11 digits
        r"^(JJD|JVGL|GM|LX|RX)[0-9A-Z]{10,20}$",         # DHL Global Mail / Parcel
        r"^[0-9A-Z]{10,20}$",                            # General DHL alphanumeric
    ],
    "amazon": [
        r"^TB[A-Z0-9]{10,20}$",                          # Amazon Logistics TBA/TBC/TBM...
    ],
    "ontrac": [
        r"^[CD]\d{14}$",                                 # OnTrac C/D + 14 digits
        r"^\d{15}$",                                     # OnTrac 15 digits
    ],
}

# ISO 6346 / BIC Container Letter Values (multiples of 11: 11, 22, 33 are omitted)
ISO_6346_LETTER_VALUES: Dict[str, int] = {
    'A': 10, 'B': 12, 'C': 13, 'D': 14, 'E': 15, 'F': 16, 'G': 17, 'H': 18, 'I': 19, 'J': 20,
    'K': 21, 'L': 23, 'M': 24, 'N': 25, 'O': 26, 'P': 27, 'Q': 28, 'R': 29, 'S': 30, 'T': 31,
    'U': 32, 'V': 34, 'W': 35, 'X': 36, 'Y': 37, 'Z': 38
}

SHIPPING_LINE_PREFIXES: Dict[str, str] = {
    "MSCU": "msc",
    "MEDU": "msc",
    "MAEU": "maersk",
    "MSKU": "maersk",
    "MRKU": "maersk",
    "PONU": "maersk",
    "CMAU": "cma_cgm" ,
    "CGMU": "cma_cgm",
    "APLU": "cma_cgm",
    "ANLU": "cma_cgm",
    "COSU": "cosco",
    "CCLU": "cosco",
    "CBHU": "cosco",
    "HLCU": "hapag_lloyd",
    "HLXU": "hapag_lloyd",
    "HAMU": "hapag_lloyd",
    "UASC": "hapag_lloyd",
    "ONEU": "one",
    "NYKU": "one",
    "MOLU": "one",
    "KKFU": "one",
    "EGLV": "evergreen",
    "EGHU": "evergreen",
    "EMCU": "evergreen",
    "EISU": "evergreen",
    "ZIMU": "zim",
    "ZCSU": "zim",
    "YMLU": "yang_ming",
    "HMMU": "hmm",
    "HDMU": "hmm",
}


def calculate_iso6346_check_digit(container_prefix_and_serial: str) -> Optional[int]:
    """
    Calculate the ISO 6346 check digit for a 10-character container prefix + serial.
    Example: 'MSCU123456' -> 6
    """
    cleaned = re.sub(r"\s+", "", container_prefix_and_serial.strip().upper())
    if len(cleaned) < 10 or not re.match(r"^[A-Z]{4}\d{6}$", cleaned[:10]):
        return None

    first10 = cleaned[:10]
    total = 0
    for i, ch in enumerate(first10):
        if ch in ISO_6346_LETTER_VALUES:
            val = ISO_6346_LETTER_VALUES[ch]
        elif ch.isdigit():
            val = int(ch)
        else:
            return None
        total += val * (2 ** i)

    rem = total % 11
    return 0 if rem == 10 else rem


def is_valid_container_number(container_number: Optional[str], strict_check_digit: bool = True) -> bool:
    """
    Validate an ISO 6346 / BIC shipping container number.
    Format: 4 letters (3 owner code + 1 equipment identifier U/J/Z) + 6 numeric serial + 1 check digit.
    """
    if not container_number or not isinstance(container_number, str):
        return False

    cleaned = re.sub(r"\s+", "", container_number.strip().upper())
    if not re.match(r"^[A-Z]{3}[UJZ]\d{7}$", cleaned):
        return False

    if not strict_check_digit:
        return True

    expected_check = calculate_iso6346_check_digit(cleaned[:10])
    if expected_check is None:
        return False

    actual_check = int(cleaned[10])
    return actual_check == expected_check


def is_valid_bol_number(bol_number: Optional[str]) -> bool:
    """Validate a standard ocean shipping line Bill of Lading (B/L) number."""
    if not bol_number or not isinstance(bol_number, str):
        return False
    cleaned = re.sub(r"\s+", "", bol_number.strip().upper())
    return bool(re.match(r"^[A-Z0-9]{8,22}$", cleaned)) and bool(re.search(r"\d", cleaned)) and bool(re.search(r"[A-Z]", cleaned))


def detect_shipping_line(identifier: Optional[str]) -> Optional[str]:
    """Infer the shipping line from container prefix or B/L prefix."""
    if not identifier or not isinstance(identifier, str):
        return None

    cleaned = re.sub(r"\s+", "", identifier.strip().upper())
    if len(cleaned) >= 4:
        prefix4 = cleaned[:4]
        if prefix4 in SHIPPING_LINE_PREFIXES:
            return SHIPPING_LINE_PREFIXES[prefix4]

    for prefix, line in SHIPPING_LINE_PREFIXES.items():
        if cleaned.startswith(prefix):
            return line

    return None


def detect_shipment_type(identifier: Optional[str]) -> str:
    """
    Detect whether an identifier represents an ocean container shipment or an individual parcel.
    Returns 'ocean_container' or 'parcel'.
    """
    if not identifier or not isinstance(identifier, str):
        return "parcel"

    cleaned = re.sub(r"\s+", "", identifier.strip().upper())

    # Check container format (4 letters + 7 digits)
    if re.match(r"^[A-Z]{3}[UJZ]\d{7}$", cleaned):
        return "ocean_container"

    # Check known ocean shipping line prefixes
    if len(cleaned) >= 4 and cleaned[:4] in SHIPPING_LINE_PREFIXES:
        return "ocean_container"

    return "parcel"


def is_valid_tracking_number(carrier: Optional[str], tracking_number: Optional[str]) -> bool:
    """Validate whether a tracking number is valid for a given carrier."""
    if not tracking_number or not isinstance(tracking_number, str):
        return False

    cleaned_number = re.sub(r"\s+", "", tracking_number.strip().upper())
    if not cleaned_number:
        return False

    if not carrier or not isinstance(carrier, str):
        carrier = "other"

    normalized_carrier = carrier.strip().lower()

    patterns = CARRIER_TRACKING_PATTERNS.get(normalized_carrier)
    if patterns:
        for pattern in patterns:
            if re.match(pattern, cleaned_number):
                return True
        return False

    # For 'other' or unknown carrier, accept any alphanumeric tracking number of 4-40 chars
    return bool(re.match(r"^[A-Z0-9\-_]{4,40}$", cleaned_number))


def detect_carrier(tracking_number: Optional[str]) -> Optional[str]:
    """Infer the carrier from the format of the tracking number."""
    if not tracking_number or not isinstance(tracking_number, str):
        return None

    cleaned_number = re.sub(r"\s+", "", tracking_number.strip().upper())
    if not cleaned_number:
        return None

    # Check specific prefixes first
    if cleaned_number.startswith("1Z"):
        return "ups"
    if cleaned_number.startswith(("TBA", "TBC", "TBM")):
        return "amazon"
    if re.match(r"^[A-Z]{2}\d{9}US$", cleaned_number) or re.match(r"^(94|93|92|95)\d{18,20}$", cleaned_number):
        return "usps"
    if re.match(r"^[CD]\d{14}$", cleaned_number):
        return "ontrac"
    if re.match(r"^\d{12}$", cleaned_number) or re.match(r"^\d{15}$", cleaned_number):
        return "fedex"
    if re.match(r"^\d{10}$", cleaned_number):
        return "dhl"

    # Match all registered patterns
    for carrier, patterns in CARRIER_TRACKING_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, cleaned_number):
                return carrier

    return None


def validate_raw_payload(payload: Any) -> Tuple[bool, List[str]]:
    """
    Validate raw payload from scraper or external source.
    Returns (is_valid, list_of_error_messages).
    """
    errors: List[str] = []

    if not isinstance(payload, dict):
        return False, ["Payload must be a dictionary"]

    if not payload:
        return False, ["Payload is empty"]

    tracking_number = (
        payload.get("tracking_number")
        or payload.get("trackingNumber")
        or payload.get("tracking_code")
        or payload.get("id")
    )
    if not tracking_number or not str(tracking_number).strip():
        errors.append("Missing or empty tracking number")

    carrier = (
        payload.get("carrier")
        or payload.get("carrierName")
        or payload.get("carrier_code")
        or payload.get("courier")
    )
    if not carrier or not str(carrier).strip():
        errors.append("Missing or empty carrier")

    # If both carrier and tracking number are present, validate format
    if tracking_number and carrier:
        from pipeline.normalize import normalize_carrier, normalize_tracking_number
        norm_carrier = normalize_carrier(str(carrier))
        norm_tracking = normalize_tracking_number(str(tracking_number))
        if norm_carrier != "other" and not is_valid_tracking_number(norm_carrier, norm_tracking):
            errors.append(f"Invalid tracking number format for carrier '{norm_carrier}': {norm_tracking}")

    events = (
        payload.get("events")
        or payload.get("scanEvents")
        or payload.get("checkpoints")
        or payload.get("tracking_events")
    )
    if events is not None:
        if not isinstance(events, list):
            errors.append("Events field must be a list")
        else:
            for idx, ev in enumerate(events):
                if not isinstance(ev, dict):
                    errors.append(f"Event at index {idx} must be a dictionary")
                else:
                    ev_valid, ev_errors = validate_event(ev)
                    if not ev_valid:
                        for err in ev_errors:
                            errors.append(f"Event at index {idx}: {err}")

    return len(errors) == 0, errors


def validate_event(event: Any) -> Tuple[bool, List[str]]:
    """Validate a single tracking checkpoint event."""
    errors: List[str] = []

    if not isinstance(event, dict):
        return False, ["Event must be a dictionary"]

    timestamp = (
        event.get("timestamp")
        or event.get("date")
        or event.get("time")
        or event.get("datetime")
        or event.get("checkpoint_time")
    )
    if not timestamp:
        errors.append("Missing event timestamp")

    return len(errors) == 0, errors
