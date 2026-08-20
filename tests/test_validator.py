import json
from pathlib import Path
from scraper.validator import (
    is_valid_tracking_number,
    detect_carrier,
    validate_raw_payload,
    validate_event,
)


def load_mock_data():
    mock_file = Path(__file__).parent / "mock_data.json"
    with open(mock_file, "r", encoding="utf-8") as f:
        return json.load(f)


def test_is_valid_tracking_number():
    mock_data = load_mock_data()
    for carrier, cases in mock_data["tracking_numbers"].items():
        for case in cases:
            num = case["number"]
            expected = case["valid"]
            assert is_valid_tracking_number(carrier, num) is expected, f"Failed for {carrier} tracking number: {num}"


def test_detect_carrier():
    assert detect_carrier("1Z9999999999999999") == "ups"
    assert detect_carrier("TBA123456789000") == "amazon"
    assert detect_carrier("9400100000000000000022") == "usps"
    assert detect_carrier("EA123456789US") == "usps"
    assert detect_carrier("123456789012") == "fedex"
    assert detect_carrier("1234567890") == "dhl"
    assert detect_carrier("") is None
    assert detect_carrier(None) is None


def test_validate_raw_payload_valid():
    mock_data = load_mock_data()
    raw_usps = mock_data["raw_parcels"]["usps_valid"]
    valid, errors = validate_raw_payload(raw_usps)
    assert valid is True
    assert len(errors) == 0


def test_validate_raw_payload_invalid():
    mock_data = load_mock_data()
    invalid_payload = mock_data["raw_parcels"]["invalid_payload_missing_tracking"]
    valid, errors = validate_raw_payload(invalid_payload)
    assert valid is False
    assert any("tracking" in err.lower() for err in errors)

    empty_payload = mock_data["raw_parcels"]["invalid_payload_empty"]
    valid_empty, errors_empty = validate_raw_payload(empty_payload)
    assert valid_empty is False
    assert "Payload is empty" in errors_empty


def test_validate_event():
    valid_event = {"timestamp": "2026-08-20T10:00:00Z", "status": "delivered"}
    valid, errors = validate_event(valid_event)
    assert valid is True
    assert len(errors) == 0

    invalid_event = {"status": "delivered"}
    valid_inv, errors_inv = validate_event(invalid_event)
    assert valid_inv is False
    assert any("timestamp" in err.lower() for err in errors_inv)
