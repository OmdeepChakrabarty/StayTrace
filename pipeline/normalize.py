"""
Pure data normalization functions for StayTrace.
Completely deterministic, no I/O, no network calls, no database connections.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dateutil import parser as date_parser


CARRIER_ALIASES: Dict[str, str] = {
    "usps": "usps",
    "united states postal service": "usps",
    "u.s. postal service": "usps",
    "us postal service": "usps",
    "postal service": "usps",
    "fedex": "fedex",
    "federal express": "fedex",
    "fedex express": "fedex",
    "fedex ground": "fedex",
    "fedex freight": "fedex",
    "fed-ex": "fedex",
    "ups": "ups",
    "united parcel service": "ups",
    "ups ground": "ups",
    "ups express": "ups",
    "dhl": "dhl",
    "dhl express": "dhl",
    "dhl eCommerce": "dhl",
    "dhl ecommerce": "dhl",
    "dhl parcel": "dhl",
    "dhl global forwarding": "dhl",
    "amazon": "amazon",
    "amazon logistics": "amazon",
    "amzn": "amazon",
    "tba": "amazon",
    "ontrac": "ontrac",
    "on trac": "ontrac",
}

STATUS_KEYWORD_MAP: List[tuple[str, str]] = [
    # Delivered
    (r"\b(delivered|front door|mailbox|signed by|left at|package delivered)\b", "delivered"),
    # Out for delivery
    (r"\b(out for delivery|with delivery courier|out_for_delivery|delivery today|loaded onto vehicle)\b", "out_for_delivery"),
    # Failed attempt
    (r"\b(delivery attempt\w*|notice left|receiver not present|failed attempt|attempted delivery|unable to deliver|delivery failed)\b", "failed_attempt"),
    # Exception
    (r"\b(exception|delay|customs|weather|hold|held|clearance delay|address incorrect|damage|lost|uncontrollable)\b", "exception"),
    # Returned
    (r"\b(returned|return to sender|return to origin|undeliverable as addressed|refused)\b", "returned"),
    # In transit
    (r"\b(in transit|in_transit|en route|departed|arrived|processing|processed|transferred|sorted|facility|distribution)\b", "in_transit"),
    # Pre transit
    (r"\b(pre_transit|label created|shipping label created|info received|electronic info|manifest|order created|shipment information sent)\b", "pre_transit"),
]

COUNTRY_MAP: Dict[str, str] = {
    "usa": "US",
    "united states": "US",
    "united states of america": "US",
    "us": "US",
    "canada": "CA",
    "can": "CA",
    "ca": "CA",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "gb": "GB",
    "germany": "DE",
    "deutschland": "DE",
    "de": "DE",
    "france": "FR",
    "fr": "FR",
    "japan": "JP",
    "jp": "JP",
    "china": "CN",
    "cn": "CN",
    "australia": "AU",
    "au": "AU",
}


def normalize_carrier(carrier: Optional[str]) -> str:
    """Normalize carrier name into canonical identifier."""
    if not carrier or not isinstance(carrier, str):
        return "other"
    
    cleaned = carrier.strip().lower()
    cleaned = re.sub(r"[-_/]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if cleaned in CARRIER_ALIASES:
        return CARRIER_ALIASES[cleaned]

    for alias, canonical in CARRIER_ALIASES.items():
        if alias in cleaned:
            return canonical

    return "other"


def normalize_status(status: Optional[str]) -> str:
    """Normalize status string to canonical status enum."""
    if not status or not isinstance(status, str):
        return "unknown"

    cleaned = status.strip().lower()
    normalized_cleaned = re.sub(r"[-_]", " ", cleaned)

    # Exact standard enum match
    standard_statuses = {
        "pre_transit",
        "in_transit",
        "out_for_delivery",
        "delivered",
        "failed_attempt",
        "exception",
        "returned",
        "unknown",
    }
    if status.strip() in standard_statuses:
        return status.strip()

    for pattern, canonical in STATUS_KEYWORD_MAP:
        if re.search(pattern, normalized_cleaned, re.IGNORECASE):
            return canonical

    return "unknown"


def normalize_timestamp(ts: Any) -> Optional[str]:
    """Parse various timestamp representations into standard UTC ISO-8601 string: YYYY-MM-DDTHH:MM:SSZ."""
    if ts is None:
        return None

    if isinstance(ts, (int, float)):
        # Handle epoch seconds or milliseconds
        val = float(ts)
        if val > 1e11:  # Milliseconds
            val = val / 1000.0
        dt = datetime.fromtimestamp(val, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            dt = ts.replace(tzinfo=timezone.utc)
        else:
            dt = ts.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    if isinstance(ts, str):
        cleaned = ts.strip()
        if not cleaned:
            return None
        try:
            parsed = date_parser.parse(cleaned)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OverflowError):
            return None

    return None


def normalize_tracking_number(tracking_number: Optional[str]) -> str:
    """Normalize tracking number by stripping whitespace and non-standard spacing."""
    if not tracking_number or not isinstance(tracking_number, str):
        return ""
    # Strip whitespace, newlines, and internal spaces
    return re.sub(r"\s+", "", tracking_number.strip().upper())


def normalize_country(country: Optional[str]) -> Optional[str]:
    """Normalize country string or code into 2-letter ISO country code if possible."""
    if not country or not isinstance(country, str):
        return None
    cleaned = country.strip().lower()
    if cleaned in COUNTRY_MAP:
        return COUNTRY_MAP[cleaned]
    if len(country.strip()) == 2 and country.strip().isalpha():
        return country.strip().upper()
    return country.strip().upper()


def normalize_location(loc: Any) -> Optional[str]:
    """Normalize location string or dictionary into standardized location string."""
    if loc is None:
        return None

    if isinstance(loc, str):
        cleaned = re.sub(r"\s+", " ", loc.strip())
        return cleaned if cleaned else None

    if isinstance(loc, dict):
        parts = []
        for key in ["address", "street", "city", "state", "province", "postalCode", "postal_code", "zip", "country"]:
            val = loc.get(key)
            if val and isinstance(val, str) and val.strip():
                parts.append(val.strip())
        if parts:
            return ", ".join(parts)

    return None


def normalize_weight(weight: Any) -> Optional[float]:
    """Normalize weight to a standard float in kilograms (rounded to 2 decimal places)."""
    if weight is None:
        return None

    if isinstance(weight, (int, float)):
        return round(float(weight), 2)

    if isinstance(weight, dict):
        val = weight.get("value") or weight.get("weight") or weight.get("amount")
        unit = weight.get("unit") or weight.get("units") or "kg"
        if val is not None:
            try:
                num = float(val)
                if isinstance(unit, str) and unit.lower() in ["lb", "lbs", "pound", "pounds"]:
                    num = num * 0.45359237
                elif isinstance(unit, str) and unit.lower() in ["oz", "ounce", "ounces"]:
                    num = num * 0.0283495
                elif isinstance(unit, str) and unit.lower() in ["g", "gram", "grams"]:
                    num = num / 1000.0
                return round(num, 2)
            except (ValueError, TypeError):
                return None

    if isinstance(weight, str):
        cleaned = weight.strip().lower()
        match = re.search(r"([\d.]+)\s*([a-zA-Z]*)", cleaned)
        if match:
            num_str, unit_str = match.groups()
            try:
                num = float(num_str)
                if unit_str in ["lb", "lbs", "pound", "pounds"]:
                    num = num * 0.45359237
                elif unit_str in ["oz", "ounce", "ounces"]:
                    num = num * 0.0283495
                elif unit_str in ["g", "gram", "grams"]:
                    num = num / 1000.0
                return round(num, 2)
            except (ValueError, TypeError):
                return None

    return None


def normalize_event(raw_event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize raw event dictionary into canonical schema."""
    if not isinstance(raw_event, dict):
        return {
            "timestamp": None,
            "status": "unknown",
            "description": None,
            "location": None,
            "event_code": None,
        }

    raw_ts = (
        raw_event.get("timestamp")
        or raw_event.get("date")
        or raw_event.get("time")
        or raw_event.get("datetime")
        or raw_event.get("checkpoint_time")
    )
    timestamp = normalize_timestamp(raw_ts)

    raw_status = (
        raw_event.get("status")
        or raw_event.get("eventType")
        or raw_event.get("activity")
        or raw_event.get("statusCode")
        or raw_event.get("description")
    )
    status = normalize_status(raw_status)

    description = (
        raw_event.get("description")
        or raw_event.get("eventDescription")
        or raw_event.get("activity")
        or raw_event.get("message")
        or raw_event.get("status")
    )
    if isinstance(description, str):
        description = re.sub(r"\s+", " ", description.strip())
    else:
        description = None

    raw_loc = (
        raw_event.get("location")
        or raw_event.get("scanLocation")
        or raw_event.get("checkpoint_location")
        or raw_event.get("place")
    )
    location = normalize_location(raw_loc)

    event_code = (
        raw_event.get("event_code")
        or raw_event.get("code")
        or raw_event.get("statusCode")
        or raw_event.get("eventType")
    )
    if isinstance(event_code, str):
        event_code = event_code.strip().upper()
    else:
        event_code = None

    return {
        "timestamp": timestamp,
        "status": status,
        "description": description,
        "location": location,
        "event_code": event_code,
    }


def normalize_parcel(raw_parcel: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize raw parcel dictionary into canonical parcel schema."""
    if not isinstance(raw_parcel, dict):
        raw_parcel = {}

    raw_tracking = (
        raw_parcel.get("tracking_number")
        or raw_parcel.get("trackingNumber")
        or raw_parcel.get("tracking_code")
        or raw_parcel.get("id")
        or ""
    )
    tracking_number = normalize_tracking_number(str(raw_tracking))

    raw_carrier = (
        raw_parcel.get("carrier")
        or raw_parcel.get("carrierName")
        or raw_parcel.get("carrier_code")
        or raw_parcel.get("courier")
    )
    carrier = normalize_carrier(raw_carrier)

    raw_status = (
        raw_parcel.get("status")
        or raw_parcel.get("packageStatus")
        or raw_parcel.get("current_status")
        or raw_parcel.get("state")
    )
    status = normalize_status(raw_status)

    sender_address = normalize_location(
        raw_parcel.get("sender_address")
        or raw_parcel.get("shipperAddress")
        or raw_parcel.get("sender")
        or raw_parcel.get("origin")
        or raw_parcel.get("sender_location")
    )

    recipient_address = normalize_location(
        raw_parcel.get("recipient_address")
        or raw_parcel.get("recipientAddress")
        or raw_parcel.get("recipient")
        or raw_parcel.get("destination")
        or raw_parcel.get("receiver_location")
    )

    origin_country = normalize_country(
        raw_parcel.get("origin_country")
        or raw_parcel.get("origin_country_code")
        or raw_parcel.get("originCountry")
    )

    destination_country = normalize_country(
        raw_parcel.get("destination_country")
        or raw_parcel.get("destination_country_code")
        or raw_parcel.get("destinationCountry")
    )

    eta_raw = (
        raw_parcel.get("estimated_delivery")
        or raw_parcel.get("estimatedDeliveryDate")
        or raw_parcel.get("eta")
        or raw_parcel.get("expected_delivery")
        or raw_parcel.get("delivery_date")
    )
    estimated_delivery = normalize_timestamp(eta_raw)

    weight_raw = (
        raw_parcel.get("weight")
        or raw_parcel.get("packageWeight")
        or raw_parcel.get("weight_kg")
    )
    weight = normalize_weight(weight_raw)

    service_type = (
        raw_parcel.get("service_type")
        or raw_parcel.get("service")
        or raw_parcel.get("service_level")
        or raw_parcel.get("serviceType")
    )
    if isinstance(service_type, str):
        service_type = re.sub(r"\s+", " ", service_type.strip())
    else:
        service_type = None

    raw_events = (
        raw_parcel.get("events")
        or raw_parcel.get("scanEvents")
        or raw_parcel.get("checkpoints")
        or raw_parcel.get("tracking_events")
        or []
    )
    events: List[Dict[str, Any]] = []
    if isinstance(raw_events, list):
        for ev in raw_events:
            if isinstance(ev, dict):
                norm_ev = normalize_event(ev)
                events.append(norm_ev)

    created_at = normalize_timestamp(raw_parcel.get("created_at"))
    updated_at = normalize_timestamp(raw_parcel.get("updated_at"))

    return {
        "tracking_number": tracking_number,
        "carrier": carrier,
        "status": status,
        "sender_address": sender_address,
        "recipient_address": recipient_address,
        "origin_country": origin_country,
        "destination_country": destination_country,
        "estimated_delivery": estimated_delivery,
        "weight": weight,
        "service_type": service_type,
        "events": events,
        "created_at": created_at,
        "updated_at": updated_at,
    }
