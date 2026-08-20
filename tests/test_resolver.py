import json
from pathlib import Path
from pipeline.resolver import (
    deduplicate_events,
    sort_events,
    determine_latest_status,
    resolve_parcel_update,
    is_terminal_status,
)


def load_mock_data():
    mock_file = Path(__file__).parent / "mock_data.json"
    with open(mock_file, "r", encoding="utf-8") as f:
        return json.load(f)


def test_is_terminal_status():
    assert is_terminal_status("delivered") is True
    assert is_terminal_status("returned") is True
    assert is_terminal_status("in_transit") is False
    assert is_terminal_status("out_for_delivery") is False
    assert is_terminal_status(None) is False


def test_deduplicate_events():
    events = [
        {"timestamp": "2026-08-20T10:00:00Z", "status": "in_transit", "location": "NYC", "description": "Departed"},
        {"timestamp": "2026-08-20T10:00:00Z", "status": "in_transit", "location": "NYC", "description": "Departed"},
        {"timestamp": "2026-08-20T12:00:00Z", "status": "delivered", "location": "NYC", "description": "Delivered"},
    ]
    deduped = deduplicate_events(events)
    assert len(deduped) == 2
    assert deduped[0]["timestamp"] == "2026-08-20T10:00:00Z"
    assert deduped[1]["timestamp"] == "2026-08-20T12:00:00Z"


def test_sort_events():
    events = [
        {"timestamp": "2026-08-20T14:00:00Z", "status": "delivered"},
        {"timestamp": "2026-08-19T08:00:00Z", "status": "pre_transit"},
        {"timestamp": "2026-08-20T10:00:00Z", "status": "in_transit"},
    ]
    sorted_asc = sort_events(events, descending=False)
    assert sorted_asc[0]["status"] == "pre_transit"
    assert sorted_asc[1]["status"] == "in_transit"
    assert sorted_asc[2]["status"] == "delivered"

    sorted_desc = sort_events(events, descending=True)
    assert sorted_desc[0]["status"] == "delivered"
    assert sorted_desc[2]["status"] == "pre_transit"


def test_resolve_new_parcel():
    mock_data = load_mock_data()
    raw_usps = mock_data["raw_parcels"]["usps_valid"]
    
    resolved_parcel, events, changed = resolve_parcel_update(
        existing_parcel=None,
        incoming_parcel=raw_usps,
    )
    
    assert changed is True
    assert resolved_parcel["tracking_number"] == "9400100000000000000022"
    assert resolved_parcel["carrier"] == "usps"
    assert resolved_parcel["status"] == "delivered"
    assert len(events) == 3
    # Check that events are sorted chronologically ascending
    assert events[0]["timestamp"] < events[-1]["timestamp"]


def test_resolve_existing_parcel_no_changes():
    mock_data = load_mock_data()
    raw_fedex = mock_data["raw_parcels"]["fedex_valid"]
    
    parcel1, events1, changed1 = resolve_parcel_update(None, raw_fedex)
    assert changed1 is True
    
    # Resolving exact same incoming data against existing state
    parcel2, events2, changed2 = resolve_parcel_update(
        existing_parcel=parcel1,
        incoming_parcel=raw_fedex,
        existing_events=events1,
    )
    
    assert changed2 is False
    assert len(events2) == len(events1)
    assert parcel2["status"] == parcel1["status"]


def test_resolve_existing_parcel_with_new_event_and_status_progression():
    existing_parcel = {
        "tracking_number": "123456789012",
        "carrier": "fedex",
        "status": "in_transit",
        "sender_address": "Memphis, TN, US",
        "recipient_address": "Austin, TX, US",
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-20T10:00:00Z",
    }
    existing_events = [
        {"timestamp": "2026-08-20T08:00:00Z", "status": "in_transit", "description": "In transit", "location": "Memphis, TN"},
    ]

    incoming_update = {
        "trackingNumber": "123456789012",
        "carrierName": "fedex",
        "packageStatus": "Delivered",
        "scanEvents": [
            {"date": "2026-08-21T12:00:00Z", "eventType": "delivered", "eventDescription": "Left at Front Door", "scanLocation": "Austin, TX"},
        ]
    }

    resolved_parcel, events, changed = resolve_parcel_update(
        existing_parcel=existing_parcel,
        incoming_parcel=incoming_update,
        existing_events=existing_events,
    )

    assert changed is True
    assert resolved_parcel["status"] == "delivered"
    assert len(events) == 2
    assert events[-1]["status"] == "delivered"
    assert resolved_parcel["created_at"] == "2026-08-20T00:00:00Z"


def test_terminal_status_retention():
    existing_parcel = {
        "tracking_number": "1Z9999999999999999",
        "carrier": "ups",
        "status": "delivered",
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-21T12:00:00Z",
    }
    existing_events = [
        {"timestamp": "2026-08-21T12:00:00Z", "status": "delivered", "description": "Delivered", "location": "Chicago, IL"}
    ]

    # Stale/out-of-order incoming update
    incoming_update = {
        "tracking_number": "1Z9999999999999999",
        "carrier": "ups",
        "status": "in_transit",
        "events": [
            {"timestamp": "2026-08-20T10:00:00Z", "status": "in_transit", "description": "Departed Facility", "location": "Hodgkins, IL"}
        ]
    }

    resolved_parcel, events, changed = resolve_parcel_update(
        existing_parcel=existing_parcel,
        incoming_parcel=incoming_update,
        existing_events=existing_events,
    )

    assert resolved_parcel["status"] == "delivered"
    assert len(events) == 2
