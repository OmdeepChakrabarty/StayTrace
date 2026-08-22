"""
Parcel resolution and checkpoint reconciliation logic for StayTrace.
Completely deterministic, pure logic, no I/O, no network calls, no database connections.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from pipeline.normalize import (
    normalize_parcel,
    normalize_event,
    normalize_status,
    normalize_container_shipment,
    normalize_ocean_event,
    normalize_ocean_status,
)


TERMINAL_STATUSES = {"delivered", "returned"}
OCEAN_TERMINAL_STATUSES = {"delivered"}

STATUS_RANK = {
    "unknown": 0,
    "pre_transit": 1,
    "in_transit": 2,
    "failed_attempt": 3,
    "exception": 3,
    "out_for_delivery": 4,
    "delivered": 5,
    "returned": 5,
}

OCEAN_STATUS_RANK = {
    "unknown": 0,
    "booked": 1,
    "gate_in": 2,
    "loaded": 3,
    "in_transit": 4,
    "transshipment": 5,
    "discharged": 6,
    "customs_hold": 6,
    "gate_out": 7,
    "delivered": 8,
}


def is_terminal_status(status: Optional[str]) -> bool:
    """Check if the status is a terminal state (e.g., delivered or returned)."""
    if not status:
        return False
    return status.strip().lower() in TERMINAL_STATUSES


def make_event_signature(event: Dict[str, Any]) -> str:
    """Generate a unique fingerprint for an event to detect duplicates."""
    ts = event.get("timestamp") or ""
    status = event.get("status") or ""
    loc = event.get("location") or ""
    desc = event.get("description") or ""
    return f"{ts}|{status.lower()}|{loc.lower()}|{desc.lower()}"


def deduplicate_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate a list of events while preserving first-seen order."""
    seen: Set[str] = set()
    deduped: List[Dict[str, Any]] = []

    for ev in events:
        if not isinstance(ev, dict):
            continue
        sig = make_event_signature(ev)
        if sig not in seen:
            seen.add(sig)
            deduped.append(ev)

    return deduped


def sort_events(events: List[Dict[str, Any]], descending: bool = False) -> List[Dict[str, Any]]:
    """Sort events chronologically by timestamp (ascending by default)."""
    def get_sort_key(ev: Dict[str, Any]) -> str:
        ts = ev.get("timestamp")
        return str(ts) if ts is not None else ""

    return sorted(events, key=get_sort_key, reverse=descending)


def determine_latest_status(
    current_status: Optional[str],
    incoming_status: Optional[str],
    sorted_events_asc: List[Dict[str, Any]],
) -> str:
    """Determine the most accurate current status based on parcel statuses and checkpoint history."""
    # If the parcel is already in a terminal state, keep it unless incoming explicitly overrides with another terminal state
    if current_status and is_terminal_status(current_status):
        if incoming_status and is_terminal_status(incoming_status):
            return incoming_status
        return current_status

    # If sorted events exist, check the latest event status
    latest_event_status = None
    if sorted_events_asc:
        last_event = sorted_events_asc[-1]
        ev_st = last_event.get("status")
        if ev_st and ev_st != "unknown":
            latest_event_status = normalize_status(ev_st)

    # Prefer latest event status if available and valid
    if latest_event_status:
        if incoming_status and incoming_status != "unknown":
            # If both exist, take the one with higher/equal rank or latest event
            norm_inc = normalize_status(incoming_status)
            if is_terminal_status(norm_inc):
                return norm_inc
            if STATUS_RANK.get(norm_inc, 0) > STATUS_RANK.get(latest_event_status, 0):
                return norm_inc
            return latest_event_status
        return latest_event_status

    # Fallback to incoming_status, then current_status, then unknown
    if incoming_status and incoming_status != "unknown":
        return normalize_status(incoming_status)
    if current_status and current_status != "unknown":
        return normalize_status(current_status)
    return "unknown"


def resolve_parcel_update(
    existing_parcel: Optional[Dict[str, Any]],
    incoming_parcel: Dict[str, Any],
    existing_events: Optional[List[Dict[str, Any]]] = None,
    incoming_events: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], bool]:
    """
    Reconcile existing parcel state with incoming tracking update.

    Returns:
        (resolved_parcel, resolved_events, change_detected)
    """
    normalized_incoming = normalize_parcel(incoming_parcel)

    # Combine events from parcel dictionary and explicit parameters
    all_incoming_events = list(normalized_incoming.get("events") or [])
    if incoming_events:
        for ev in incoming_events:
            all_incoming_events.append(normalize_event(ev))

    norm_existing_events = []
    if existing_events:
        for ev in existing_events:
            norm_existing_events.append(normalize_event(ev))

    # Deduplicate and sort events chronologically (oldest to newest)
    combined_events = deduplicate_events(norm_existing_events + all_incoming_events)
    sorted_events = sort_events(combined_events, descending=False)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not existing_parcel:
        # Brand new parcel
        latest_status = determine_latest_status(
            None,
            normalized_incoming.get("status"),
            sorted_events,
        )

        resolved_parcel = {
            "tracking_number": normalized_incoming["tracking_number"],
            "carrier": normalized_incoming["carrier"],
            "status": latest_status,
            "sender_address": normalized_incoming.get("sender_address"),
            "recipient_address": normalized_incoming.get("recipient_address"),
            "origin_country": normalized_incoming.get("origin_country"),
            "destination_country": normalized_incoming.get("destination_country"),
            "estimated_delivery": normalized_incoming.get("estimated_delivery"),
            "weight": normalized_incoming.get("weight"),
            "service_type": normalized_incoming.get("service_type"),
            "created_at": normalized_incoming.get("created_at") or now_iso,
            "updated_at": normalized_incoming.get("updated_at") or now_iso,
        }
        return resolved_parcel, sorted_events, True

    # Reconcile with existing parcel
    change_detected = False
    existing_event_sigs = {make_event_signature(ev) for ev in norm_existing_events}
    new_event_sigs = {make_event_signature(ev) for ev in sorted_events}
    if new_event_sigs != existing_event_sigs:
        change_detected = True

    current_status = existing_parcel.get("status")
    incoming_status = normalized_incoming.get("status")
    latest_status = determine_latest_status(current_status, incoming_status, sorted_events)

    if latest_status != current_status:
        change_detected = True

    # Check for field updates
    fields_to_update = [
        "sender_address",
        "recipient_address",
        "origin_country",
        "destination_country",
        "estimated_delivery",
        "weight",
        "service_type",
    ]

    resolved_parcel = dict(existing_parcel)
    resolved_parcel["status"] = latest_status
    resolved_parcel["carrier"] = normalized_incoming.get("carrier") or existing_parcel.get("carrier")

    for field in fields_to_update:
        inc_val = normalized_incoming.get(field)
        exist_val = existing_parcel.get(field)
        if inc_val is not None and inc_val != exist_val:
            resolved_parcel[field] = inc_val
            change_detected = True

    # Preserve created_at, update updated_at if changed
    resolved_parcel["created_at"] = existing_parcel.get("created_at") or now_iso
    if change_detected:
        resolved_parcel["updated_at"] = normalized_incoming.get("updated_at") or now_iso
    else:
        resolved_parcel["updated_at"] = existing_parcel.get("updated_at") or now_iso

    return resolved_parcel, sorted_events, change_detected


def determine_latest_ocean_status(
    current_status: Optional[str],
    incoming_status: Optional[str],
    sorted_events_asc: List[Dict[str, Any]],
) -> str:
    """Determine the most accurate ocean shipment status based on history and updates."""
    if current_status and current_status.strip().lower() in OCEAN_TERMINAL_STATUSES:
        if incoming_status and incoming_status.strip().lower() in OCEAN_TERMINAL_STATUSES:
            return incoming_status.strip().lower()
        return current_status.strip().lower()

    latest_event_status = None
    if sorted_events_asc:
        last_event = sorted_events_asc[-1]
        ev_st = last_event.get("status")
        if ev_st and ev_st != "unknown":
            latest_event_status = normalize_ocean_status(ev_st)

    if latest_event_status:
        if incoming_status and incoming_status != "unknown":
            norm_inc = normalize_ocean_status(incoming_status)
            if norm_inc in OCEAN_TERMINAL_STATUSES:
                return norm_inc
            if OCEAN_STATUS_RANK.get(norm_inc, 0) > OCEAN_STATUS_RANK.get(latest_event_status, 0):
                return norm_inc
            return latest_event_status
        return latest_event_status

    if incoming_status and incoming_status != "unknown":
        return normalize_ocean_status(incoming_status)
    if current_status and current_status != "unknown":
        return normalize_ocean_status(current_status)
    return "unknown"


def resolve_container_update(
    existing_container: Optional[Dict[str, Any]],
    incoming_container: Dict[str, Any],
    existing_events: Optional[List[Dict[str, Any]]] = None,
    incoming_events: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], bool]:
    """
    Reconcile existing ocean container shipment state with incoming tracking update.

    Returns:
        (resolved_container, resolved_events, change_detected)
    """
    normalized_incoming = normalize_container_shipment(incoming_container)

    all_incoming_events = list(normalized_incoming.get("events") or [])
    if incoming_events:
        for ev in incoming_events:
            all_incoming_events.append(normalize_ocean_event(ev))

    norm_existing_events = []
    if existing_events:
        for ev in existing_events:
            norm_existing_events.append(normalize_ocean_event(ev))

    combined_events = deduplicate_events(norm_existing_events + all_incoming_events)
    sorted_events = sort_events(combined_events, descending=False)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not existing_container:
        latest_status = determine_latest_ocean_status(
            None,
            normalized_incoming.get("status"),
            sorted_events,
        )

        resolved_container = {
            "shipment_type": "ocean_container",
            "tracking_number": normalized_incoming["tracking_number"],
            "container_number": normalized_incoming["container_number"],
            "shipping_line": normalized_incoming["shipping_line"],
            "carrier": normalized_incoming["carrier"],
            "status": latest_status,
            "vessel_name": normalized_incoming.get("vessel_name"),
            "voyage_number": normalized_incoming.get("voyage_number"),
            "origin_port": normalized_incoming.get("origin_port"),
            "origin_port_code": normalized_incoming.get("origin_port_code"),
            "destination_port": normalized_incoming.get("destination_port"),
            "destination_port_code": normalized_incoming.get("destination_port_code"),
            "current_location": normalized_incoming.get("current_location"),
            "estimated_departure": normalized_incoming.get("estimated_departure"),
            "actual_departure": normalized_incoming.get("actual_departure"),
            "estimated_arrival": normalized_incoming.get("estimated_arrival"),
            "actual_arrival": normalized_incoming.get("actual_arrival"),
            "healing_status": normalized_incoming.get("healing_status"),
            "healing_confidence": normalized_incoming.get("healing_confidence"),
            "healing_details": normalized_incoming.get("healing_details"),
            "created_at": normalized_incoming.get("created_at") or now_iso,
            "updated_at": normalized_incoming.get("updated_at") or now_iso,
        }
        return resolved_container, sorted_events, True

    change_detected = False
    existing_event_sigs = {make_event_signature(ev) for ev in norm_existing_events}
    new_event_sigs = {make_event_signature(ev) for ev in sorted_events}
    if new_event_sigs != existing_event_sigs:
        change_detected = True

    current_status = existing_container.get("status")
    incoming_status = normalized_incoming.get("status")
    latest_status = determine_latest_ocean_status(current_status, incoming_status, sorted_events)

    if latest_status != current_status:
        change_detected = True

    fields_to_update = [
        "vessel_name",
        "voyage_number",
        "origin_port",
        "origin_port_code",
        "destination_port",
        "destination_port_code",
        "current_location",
        "estimated_departure",
        "actual_departure",
        "estimated_arrival",
        "actual_arrival",
        "healing_status",
        "healing_confidence",
        "healing_details",
    ]

    resolved_container = dict(existing_container)
    resolved_container["status"] = latest_status
    resolved_container["shipping_line"] = normalized_incoming.get("shipping_line") or existing_container.get("shipping_line")
    resolved_container["carrier"] = resolved_container["shipping_line"]

    for field in fields_to_update:
        inc_val = normalized_incoming.get(field)
        exist_val = existing_container.get(field)
        if inc_val is not None and inc_val != exist_val:
            resolved_container[field] = inc_val
            change_detected = True

    resolved_container["created_at"] = existing_container.get("created_at") or now_iso
    if change_detected:
        resolved_container["updated_at"] = normalized_incoming.get("updated_at") or now_iso
    else:
        resolved_container["updated_at"] = existing_container.get("updated_at") or now_iso

    return resolved_container, sorted_events, change_detected
