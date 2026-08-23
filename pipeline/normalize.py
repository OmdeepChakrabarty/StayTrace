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

SHIPPING_LINE_ALIASES: Dict[str, str] = {
    "msc": "msc",
    "mediterranean shipping company": "msc",
    "msc mediterranean shipping": "msc",
    "maersk": "maersk",
    "maersk line": "maersk",
    "a.p. moller maersk": "maersk",
    "apm maersk": "maersk",
    "sealand": "maersk",
    "cma cgm": "cma_cgm",
    "cma-cgm": "cma_cgm",
    "cma": "cma_cgm",
    "apl": "cma_cgm",
    "anl": "cma_cgm",
    "cosco": "cosco",
    "cosco shipping": "cosco",
    "cosco shipping lines": "cosco",
    "china ocean shipping": "cosco",
    "hapag lloyd": "hapag_lloyd",
    "hapag-lloyd": "hapag_lloyd",
    "hapag": "hapag_lloyd",
    "one": "one",
    "ocean network express": "one",
    "one line": "one",
    "evergreen": "evergreen",
    "evergreen line": "evergreen",
    "evergreen marine": "evergreen",
    "zim": "zim",
    "zim integrated shipping": "zim",
    "zim line": "zim",
    "yang ming": "yang_ming",
    "yang ming marine": "yang_ming",
    "yml": "yang_ming",
    "hmm": "hmm",
    "hyundai merchant marine": "hmm",
}

OCEAN_STATUS_KEYWORD_MAP: List[tuple[str, str]] = [
    # Delivered / Empty returned
    (r"\b(delivered|empty returned|empty return|cargo delivered|container returned|gate out empty)\b", "delivered"),
    # Gate out for final delivery
    (r"\b(gate out|gate-out|picked up by consignee|out for delivery|loaded on truck|rail departure)\b", "gate_out"),
    # Customs hold / exception
    (r"\b(customs hold|customs inspection|inspection hold|quarantine|clearance delay|exception|held by customs)\b", "customs_hold"),
    # Discharged from vessel
    (r"\b(discharged|unladen|unloaded from vessel|discharge completed|vessel discharge|container discharged)\b", "discharged"),
    # Transshipment
    (r"\b(transshipment|transshipped|transshipment hub|connecting vessel|trans-shipment)\b", "transshipment"),
    # Loaded on vessel / Underway
    (r"\b(vessel departure|departed port|underway|at sea|in transit|in_transit|sailing|en route)\b", "in_transit"),
    (r"\b(ready to be loaded|ready for loading|awaiting vessel loading)\b", "gate_in"),
    (r"\b(loaded on vessel|laden on board|loaded onto vessel|vessel loaded|container loaded|loaded)\b", "loaded"),
    # Gate in at POL
    (r"\b(gate in|gate-in|container received|received at terminal|cy in|terminal in|received at pol)\b", "gate_in"),
    # Booked
    (r"\b(booking confirmed|booked|empty dispatch|equipment assigned|pre_transit)\b", "booked"),
]


def normalize_shipping_line(line: Optional[str]) -> str:
    """Normalize ocean shipping line name into canonical identifier."""
    if not line or not isinstance(line, str):
        return "other"

    cleaned = line.strip().lower()
    cleaned = re.sub(r"[-_/]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if cleaned in SHIPPING_LINE_ALIASES:
        return SHIPPING_LINE_ALIASES[cleaned]

    for alias, canonical in SHIPPING_LINE_ALIASES.items():
        if alias in cleaned:
            return canonical

    return "other"


def normalize_ocean_status(status: Optional[str]) -> str:
    """Normalize raw ocean status into canonical status enum."""
    if not status or not isinstance(status, str):
        return "unknown"

    cleaned = status.strip().lower()
    normalized_cleaned = re.sub(r"[-_]", " ", cleaned)

    standard_ocean_statuses = {
        "booked",
        "gate_in",
        "loaded",
        "in_transit",
        "transshipment",
        "discharged",
        "customs_hold",
        "gate_out",
        "delivered",
        "unknown",
    }
    if status.strip() in standard_ocean_statuses:
        return status.strip()

    for pattern, canonical in OCEAN_STATUS_KEYWORD_MAP:
        if re.search(pattern, normalized_cleaned, re.IGNORECASE):
            return canonical

    # Fallback to general parcel status mapping if applicable
    general_st = normalize_status(status)
    if general_st == "delivered":
        return "delivered"
    if general_st == "in_transit":
        return "in_transit"
    if general_st == "pre_transit":
        return "booked"
    if general_st == "out_for_delivery":
        return "gate_out"
    if general_st == "exception":
        return "customs_hold"

    return "unknown"


def extract_locode_and_port(port_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract UN/LOCODE (5-letter code) and clean port name from a string.
    Example: 'Shanghai (CNSHA)' -> ('Shanghai', 'CNSHA')
    """
    if not port_str or not isinstance(port_str, str):
        return None, None

    cleaned = port_str.strip()
    if not cleaned:
        return None, None

    # Check for (CNSHA) or [CNSHA] or , CNSHA
    match = re.search(r"[\(\[\,\s]([A-Z]{2}\s*[A-Z]{3})[\)\]]?", cleaned)
    locode = None
    port_name = cleaned

    if match:
        raw_code = match.group(1)
        locode = re.sub(r"\s+", "", raw_code).upper()
        # Clean port name
        port_name = re.sub(r"[\(\[\,]\s*" + re.escape(raw_code) + r"\s*[\)\]]?", "", cleaned).strip()
        port_name = re.sub(r"\s+", " ", port_name).strip(" ,-")

    # If the string itself is just a 5-letter UN/LOCODE
    cleaned_no_space = re.sub(r"\s+", "", cleaned).upper()
    if len(cleaned_no_space) == 5 and cleaned_no_space.isalpha() and not locode:
        locode = cleaned_no_space

    return (port_name if port_name else None), locode


def normalize_ocean_event(raw_event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize raw ocean event dictionary into canonical ocean checkpoint schema."""
    if not isinstance(raw_event, dict):
        return {
            "timestamp": None,
            "status": "unknown",
            "event_type": "checkpoint",
            "description": None,
            "location": None,
            "location_code": None,
            "vessel": None,
            "voyage": None,
            "source": "carrier",
        }

    raw_ts = (
        raw_event.get("timestamp")
        or raw_event.get("date")
        or raw_event.get("time")
        or raw_event.get("event_time")
        or raw_event.get("datetime")
    )
    timestamp = normalize_timestamp(raw_ts)

    raw_status = (
        raw_event.get("status")
        or raw_event.get("event_type")
        or raw_event.get("event")
        or raw_event.get("activity")
        or raw_event.get("description")
    )
    status = normalize_ocean_status(raw_status)

    description = (
        raw_event.get("description")
        or raw_event.get("activity")
        or raw_event.get("event_description")
        or raw_event.get("message")
        or raw_event.get("status")
    )
    if isinstance(description, str):
        description = re.sub(r"\s+", " ", description.strip())
    else:
        description = None

    raw_loc = (
        raw_event.get("location")
        or raw_event.get("port")
        or raw_event.get("place")
        or raw_event.get("facility")
    )
    port_name, locode = extract_locode_and_port(raw_loc if isinstance(raw_loc, str) else None)
    if not port_name and isinstance(raw_loc, dict):
        port_name = normalize_location(raw_loc)
    loc_code = raw_event.get("location_code") or raw_event.get("locode") or locode

    vessel = raw_event.get("vessel") or raw_event.get("vessel_name")
    if isinstance(vessel, str):
        vessel = re.sub(r"\s+", " ", vessel.strip())
    else:
        vessel = None

    voyage = raw_event.get("voyage") or raw_event.get("voyage_number")
    if isinstance(voyage, str):
        voyage = re.sub(r"\s+", " ", voyage.strip())
    else:
        voyage = None

    event_type = raw_event.get("event_type") or raw_event.get("event_code") or status

    return {
        "timestamp": timestamp,
        "status": status,
        "event_type": str(event_type),
        "description": description,
        "location": port_name or (loc_code if loc_code else None),
        "location_code": loc_code,
        "vessel": vessel,
        "voyage": voyage,
        "source": raw_event.get("source", "carrier"),
    }


def normalize_container_shipment(raw_container: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize raw container tracking dictionary into canonical ocean shipment schema."""
    if not isinstance(raw_container, dict):
        raw_container = {}

    raw_id = (
        raw_container.get("container_number")
        or raw_container.get("container_no")
        or raw_container.get("tracking_number")
        or raw_container.get("id")
        or ""
    )
    container_number = normalize_tracking_number(str(raw_id))

    raw_line = (
        raw_container.get("shipping_line")
        or raw_container.get("carrier")
        or raw_container.get("line")
        or raw_container.get("carrierName")
    )
    shipping_line = normalize_shipping_line(raw_line)

    raw_status = (
        raw_container.get("status")
        or raw_container.get("current_status")
        or raw_container.get("stage")
    )
    status = normalize_ocean_status(raw_status)

    vessel_name = raw_container.get("vessel_name") or raw_container.get("vessel")
    if isinstance(vessel_name, str):
        vessel_name = re.sub(r"\s+", " ", vessel_name.strip())
    else:
        vessel_name = None

    voyage_number = raw_container.get("voyage_number") or raw_container.get("voyage")
    if isinstance(voyage_number, str):
        voyage_number = re.sub(r"\s+", " ", voyage_number.strip())
    else:
        voyage_number = None

    raw_origin = raw_container.get("origin_port") or raw_container.get("pol") or raw_container.get("loading_port")
    origin_name, origin_locode = extract_locode_and_port(raw_origin if isinstance(raw_origin, str) else None)
    origin_port_code = raw_container.get("origin_port_code") or origin_locode

    raw_dest = raw_container.get("destination_port") or raw_container.get("pod") or raw_container.get("discharge_port")
    dest_name, dest_locode = extract_locode_and_port(raw_dest if isinstance(raw_dest, str) else None)
    destination_port_code = raw_container.get("destination_port_code") or dest_locode

    current_location = normalize_location(raw_container.get("current_location") or raw_container.get("location"))

    estimated_departure = normalize_timestamp(raw_container.get("estimated_departure") or raw_container.get("etd"))
    actual_departure = normalize_timestamp(raw_container.get("actual_departure") or raw_container.get("atd"))
    estimated_arrival = normalize_timestamp(raw_container.get("estimated_arrival") or raw_container.get("eta"))
    actual_arrival = normalize_timestamp(raw_container.get("actual_arrival") or raw_container.get("ata"))

    raw_events = (
        raw_container.get("events")
        or raw_container.get("checkpoints")
        or raw_container.get("timeline")
        or []
    )
    events: List[Dict[str, Any]] = []
    if isinstance(raw_events, list):
        for ev in raw_events:
            if isinstance(ev, dict):
                events.append(normalize_ocean_event(ev))

    created_at = normalize_timestamp(raw_container.get("created_at"))
    updated_at = normalize_timestamp(raw_container.get("updated_at"))

    # Healing telemetry if available
    healing_status = raw_container.get("healing_status")
    healing_confidence = raw_container.get("healing_confidence")
    healing_details = raw_container.get("healing_details")

    return {
        "shipment_type": "ocean_container",
        "tracking_number": container_number,
        "container_number": container_number,
        "shipping_line": shipping_line,
        "carrier": shipping_line,
        "status": status,
        "vessel_name": vessel_name,
        "voyage_number": voyage_number,
        "origin_port": origin_name or (origin_port_code if origin_port_code else None),
        "origin_port_code": origin_port_code,
        "destination_port": dest_name or (destination_port_code if destination_port_code else None),
        "destination_port_code": destination_port_code,
        "current_location": current_location,
        "estimated_departure": estimated_departure,
        "actual_departure": actual_departure,
        "estimated_arrival": estimated_arrival,
        "actual_arrival": actual_arrival,
        "healing_status": healing_status,
        "healing_confidence": healing_confidence,
        "healing_details": healing_details,
        "events": events,
        "created_at": created_at,
        "updated_at": updated_at,
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
        "shipment_type": raw_parcel.get("shipment_type", "parcel"),
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
