import json
from pathlib import Path
from pipeline.normalize import (
    normalize_carrier,
    normalize_status,
    normalize_timestamp,
    normalize_tracking_number,
    normalize_country,
    normalize_location,
    normalize_weight,
    normalize_event,
    normalize_parcel,
)


def load_mock_data():
    mock_file = Path(__file__).parent / "mock_data.json"
    with open(mock_file, "r", encoding="utf-8") as f:
        return json.load(f)


def test_normalize_carrier():
    mock_data = load_mock_data()
    for expected_carrier, aliases in mock_data["carrier_aliases"].items():
        for alias in aliases:
            assert normalize_carrier(alias) == expected_carrier

    assert normalize_carrier(None) == "other"
    assert normalize_carrier("") == "other"
    assert normalize_carrier("Unknown Carrier X") == "other"


def test_normalize_status():
    mock_data = load_mock_data()
    for expected_status, raw_list in mock_data["status_mappings"].items():
        for raw in raw_list:
            assert normalize_status(raw) == expected_status

    assert normalize_status(None) == "unknown"
    assert normalize_status("") == "unknown"


def test_normalize_timestamp():
    assert normalize_timestamp("2026-08-20T11:30:00Z") == "2026-08-20T11:30:00Z"
    assert normalize_timestamp("2026-08-20 08:30:00 -0400") == "2026-08-20T12:30:00Z"
    assert normalize_timestamp(1787227800) is not None
    assert normalize_timestamp(None) is None
    assert normalize_timestamp("invalid-date-xyz") is None


def test_normalize_tracking_number():
    assert normalize_tracking_number(" 9400 1000 0000 0000 0000 22 ") == "9400100000000000000022"
    assert normalize_tracking_number("1z 999 999 ") == "1Z999999"
    assert normalize_tracking_number(None) == ""


def test_normalize_country():
    assert normalize_country("USA") == "US"
    assert normalize_country("United States") == "US"
    assert normalize_country("germany") == "DE"
    assert normalize_country("CA") == "CA"
    assert normalize_country(None) is None


def test_normalize_location():
    assert normalize_location("  Seattle, WA  ") == "Seattle, WA"
    dict_loc = {"city": "Austin", "state": "TX", "postalCode": "73301", "country": "US"}
    assert normalize_location(dict_loc) == "Austin, TX, 73301, US"
    assert normalize_location(None) is None


def test_normalize_weight():
    assert normalize_weight("2.5 lbs") == 1.13
    assert normalize_weight("4.2 kg") == 4.2
    assert normalize_weight(1.8) == 1.8
    assert normalize_weight({"value": 10, "unit": "lbs"}) == 4.54
    assert normalize_weight(None) is None


def test_normalize_event():
    raw_ev = {
        "timestamp": "2026-08-20 08:30:00 -0400",
        "status": "Delivered",
        "description": "Delivered, in/at mailbox",
        "location": "NEW YORK, NY 10001",
        "code": "DLV",
    }
    norm = normalize_event(raw_ev)
    assert norm["timestamp"] == "2026-08-20T12:30:00Z"
    assert norm["status"] == "delivered"
    assert norm["description"] == "Delivered, in/at mailbox"
    assert norm["location"] == "NEW YORK, NY 10001"
    assert norm["event_code"] == "DLV"


def test_normalize_parcel_usps():
    mock_data = load_mock_data()
    raw_usps = mock_data["raw_parcels"]["usps_valid"]
    parcel = normalize_parcel(raw_usps)

    assert parcel["tracking_number"] == "9400100000000000000022"
    assert parcel["carrier"] == "usps"
    assert parcel["status"] == "delivered"
    assert parcel["sender_address"] == "SEATTLE WA 98101"
    assert parcel["recipient_address"] == "NEW YORK NY 10001"
    assert parcel["origin_country"] == "US"
    assert parcel["destination_country"] == "US"
    assert parcel["weight"] == 1.13
    assert len(parcel["events"]) == 3
    assert parcel["events"][0]["status"] == "delivered"


def test_normalize_parcel_fedex():
    mock_data = load_mock_data()
    raw_fedex = mock_data["raw_parcels"]["fedex_valid"]
    parcel = normalize_parcel(raw_fedex)

    assert parcel["tracking_number"] == "123456789012"
    assert parcel["carrier"] == "fedex"
    assert parcel["status"] == "in_transit"
    assert parcel["weight"] == 1.8
    assert len(parcel["events"]) == 2
