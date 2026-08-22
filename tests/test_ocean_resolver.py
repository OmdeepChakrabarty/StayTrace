import pytest
from pipeline.resolver import (
    determine_latest_ocean_status,
    resolve_container_update,
)


def test_determine_latest_ocean_status():
    events = [
        {"timestamp": "2026-08-20T08:00:00Z", "status": "gate_in"},
        {"timestamp": "2026-08-21T18:00:00Z", "status": "loaded"},
        {"timestamp": "2026-08-22T04:00:00Z", "status": "in_transit"},
    ]
    st = determine_latest_ocean_status("gate_in", "in_transit", events)
    assert st == "in_transit"

    # Terminal state retention
    delivered_events = [
        {"timestamp": "2026-08-25T10:00:00Z", "status": "delivered"},
    ]
    assert determine_latest_ocean_status("delivered", "in_transit", delivered_events) == "delivered"


def test_resolve_container_update_new():
    raw_incoming = {
        "container_number": "MSCU1234566",
        "shipping_line": "msc",
        "status": "gate_in",
        "origin_port": "Shanghai (CNSHA)",
        "destination_port": "Rotterdam (NLRTM)",
        "vessel_name": "MSC ISABELLA",
        "voyage_number": "FD432R",
        "events": [
            {"timestamp": "2026-08-20T08:00:00Z", "status": "gate_in", "description": "Gate in terminal"}
        ]
    }
    resolved, events, changed = resolve_container_update(None, raw_incoming)
    assert changed is True
    assert resolved["container_number"] == "MSCU1234566"
    assert resolved["status"] == "gate_in"
    assert len(events) == 1


def test_resolve_container_update_existing_progression():
    existing = {
        "shipment_type": "ocean_container",
        "tracking_number": "MSCU1234566",
        "container_number": "MSCU1234566",
        "shipping_line": "msc",
        "status": "gate_in",
        "origin_port": "Shanghai",
        "destination_port": "Rotterdam",
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-20T08:00:00Z",
    }
    existing_events = [
        {"timestamp": "2026-08-20T08:00:00Z", "status": "gate_in", "description": "Gate in terminal"}
    ]

    incoming = {
        "container_number": "MSCU1234566",
        "shipping_line": "msc",
        "status": "loaded",
        "vessel_name": "MSC ISABELLA",
        "voyage_number": "FD432R",
        "events": [
            {"timestamp": "2026-08-21T18:30:00Z", "status": "loaded", "description": "Loaded on MSC ISABELLA"}
        ]
    }

    resolved, events, changed = resolve_container_update(
        existing_container=existing,
        incoming_container=incoming,
        existing_events=existing_events,
    )

    assert changed is True
    assert resolved["status"] == "loaded"
    assert resolved["vessel_name"] == "MSC ISABELLA"
    assert len(events) == 2
    assert events[0]["status"] == "gate_in"
    assert events[1]["status"] == "loaded"
