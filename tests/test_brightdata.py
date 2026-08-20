import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from scraper.brightdata import (
    BrightDataClient,
    BrightDataAuthError,
    BrightDataRateLimitError,
    BrightDataNotFoundError,
    BrightDataTimeoutError,
    BrightDataNetworkError,
    BrightDataError,
)
from scraper.validator import ValidationError


def load_mock_data():
    mock_file = Path(__file__).parent / "mock_data.json"
    with open(mock_file, "r", encoding="utf-8") as f:
        return json.load(f)


def test_missing_api_key_raises_auth_error():
    client = BrightDataClient(api_key="")
    with pytest.raises(BrightDataAuthError, match="API key is required"):
        client.unlock_url("https://example.com")


def test_build_tracking_url():
    client = BrightDataClient(api_key="test_key")
    
    usps_url = client.build_tracking_url("usps", "9400100000000000000022")
    assert "tools.usps.com" in usps_url
    assert "9400100000000000000022" in usps_url

    fedex_url = client.build_tracking_url("fedex", "123456789012")
    assert "fedex.com" in fedex_url
    assert "123456789012" in fedex_url

    ups_url = client.build_tracking_url("ups", "1Z9999999999999999")
    assert "ups.com" in ups_url

    dhl_url = client.build_tracking_url("dhl", "1234567890")
    assert "dhl.com" in dhl_url


def test_fetch_tracking_raw_success():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    
    mock_data = load_mock_data()
    raw_usps = mock_data["raw_parcels"]["usps_valid"]
    mock_resp.json.return_value = raw_usps
    mock_session.post.return_value = mock_resp

    client = BrightDataClient(api_key="valid_token", session=mock_session)
    result = client.fetch_tracking_raw("usps", "9400100000000000000022")

    assert result["tracking_number"] == raw_usps["tracking_number"]
    assert mock_session.post.called


def test_fetch_tracking_normalized():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    
    mock_data = load_mock_data()
    raw_usps = mock_data["raw_parcels"]["usps_valid"]
    mock_resp.json.return_value = raw_usps
    mock_session.post.return_value = mock_resp

    client = BrightDataClient(api_key="valid_token", session=mock_session)
    parcel = client.fetch_tracking("usps", "9400100000000000000022")

    assert parcel["tracking_number"] == "9400100000000000000022"
    assert parcel["carrier"] == "usps"
    assert parcel["status"] == "delivered"
    assert len(parcel["events"]) == 3


def test_invalid_tracking_number_raises_validation_error():
    client = BrightDataClient(api_key="valid_token")
    with pytest.raises(ValidationError):
        client.fetch_tracking("usps", "INVALID_TRACKING_123")


def test_http_401_raises_auth_error():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_session.post.return_value = mock_resp

    client = BrightDataClient(api_key="invalid_token", session=mock_session, max_retries=1)
    with pytest.raises(BrightDataAuthError):
        client.unlock_url("https://tools.usps.com")


def test_http_404_raises_not_found():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    mock_session.post.return_value = mock_resp

    client = BrightDataClient(api_key="token", session=mock_session, max_retries=1)
    with pytest.raises(BrightDataNotFoundError):
        client.unlock_url("https://tools.usps.com")


def test_http_429_rate_limit_retry():
    mock_session = MagicMock()
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = "Rate Limited"

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {"status": "ok"}

    mock_session.post.side_effect = [mock_resp_429, mock_resp_200]

    with patch("time.sleep", return_value=None):
        client = BrightDataClient(api_key="token", session=mock_session, max_retries=2)
        resp = client.unlock_url("https://example.com")
        assert resp.status_code == 200
        assert mock_session.post.call_count == 2


def test_timeout_error_handling():
    mock_session = MagicMock()
    mock_session.post.side_effect = requests.exceptions.Timeout("Connection timed out")

    with patch("time.sleep", return_value=None):
        client = BrightDataClient(api_key="token", session=mock_session, max_retries=2)
        with pytest.raises(BrightDataTimeoutError):
            client.unlock_url("https://example.com")


def test_connection_error_handling():
    mock_session = MagicMock()
    mock_session.post.side_effect = requests.exceptions.ConnectionError("Failed to connect")

    with patch("time.sleep", return_value=None):
        client = BrightDataClient(api_key="token", session=mock_session, max_retries=1)
        with pytest.raises(BrightDataNetworkError):
            client.unlock_url("https://example.com")


def test_batch_fetch_tracking():
    mock_session = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    
    mock_data = load_mock_data()
    raw_fedex = mock_data["raw_parcels"]["fedex_valid"]
    mock_resp.json.return_value = raw_fedex
    mock_session.post.return_value = mock_resp

    client = BrightDataClient(api_key="token", session=mock_session)
    batch_req = [
        {"carrier": "fedex", "tracking_number": "123456789012"},
        {"carrier": "usps", "tracking_number": "INVALID"},
    ]

    results = client.batch_fetch_tracking(batch_req)
    assert len(results) == 2
    assert results[0]["carrier"] == "fedex"
    assert results[0]["status"] == "in_transit"
    assert "error" in results[1]
