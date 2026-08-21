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
