"""
Unit and integration tests for StayTrace API layer (Level 5).
Uses mock clients to avoid live network requests to Bright Data.
"""

import json
import os
import tempfile
import threading
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import requests

from api.main import create_app, TrackingService, StayTraceAPIHandler
from db.database import init_db, get_parcel_with_events, get_scrape_logs
from scraper.brightdata import (
    BrightDataClient,
    BrightDataAuthError,
    BrightDataRateLimitError,
    BrightDataNotFoundError,
    BrightDataTimeoutError,
    BrightDataNetworkError,
)
from scraper.validator import ValidationError


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path=path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def mock_brightdata():
    mock = MagicMock(spec=BrightDataClient)
    return mock


@pytest.fixture
def test_server(temp_db, mock_brightdata):
    # Bind to port 0 for dynamic ephemeral port allocation
    server = create_app(
        db_path=temp_db,
        brightdata_client=mock_brightdata,
        host="127.0.0.1",
        port=0,
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    yield {"url": base_url, "db_path": temp_db, "mock_client": mock_brightdata}

    server.shutdown()
    server.server_close()


def test_health_check(test_server):
    url = f"{test_server['url']}/health"
    resp = requests.get(url)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert "StayTrace" in data["service"]


def test_cors_options_preflight(test_server):
    url = f"{test_server['url']}/api/parcels"
    resp = requests.options(url)
    assert resp.status_code == 204
    assert resp.headers.get("Access-Control-Allow-Origin") == "*"
    assert "GET" in resp.headers.get("Access-Control-Allow-Methods", "")


def test_track_parcel_successful_via_brightdata(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.return_value = {
        "tracking_number": "9400100000000000000001",
        "carrier": "usps",
        "status": "in_transit",
        "sender_address": "Los Angeles, CA",
        "recipient_address": "New York, NY",
        "events": [
            {
                "timestamp": "2026-08-20T10:00:00Z",
                "status": "in_transit",
                "description": "Departed USPS facility",
                "location": "Los Angeles, CA",
            }
        ],
    }

    url = f"{test_server['url']}/api/track"
    payload = {
        "tracking_number": "9400100000000000000001",
        "carrier": "usps",
    }
    resp = requests.post(url, json=payload)
    assert resp.status_code == 201
    data = resp.json()

    assert data["tracking_number"] == "9400100000000000000001"
    assert data["carrier"] == "usps"
    assert data["status"] == "in_transit"
    assert len(data["events"]) == 1

    # Verify persisted in database
    db_record = get_parcel_with_events("9400100000000000000001", db_path=test_server["db_path"])
    assert db_record is not None
    assert db_record["status"] == "in_transit"
    assert len(db_record["events"]) == 1

    # Verify scrape log recorded
    logs = get_scrape_logs(db_path=test_server["db_path"])
    assert len(logs) == 1
    assert logs[0]["status"] == "success"


def test_track_parcel_with_auto_detected_carrier(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.return_value = {
        "tracking_number": "1Z9999999999999999",
        "carrier": "ups",
        "status": "in_transit",
        "events": [],
    }

    url = f"{test_server['url']}/api/track"
    payload = {"tracking_number": "1Z9999999999999999"}
    resp = requests.post(url, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["carrier"] == "ups"
    assert data["tracking_number"] == "1Z9999999999999999"


def test_track_parcel_direct_payload_ingestion(test_server):
    url = f"{test_server['url']}/api/track"
    payload = {
        "tracking_number": "9400100000000000000002",
        "carrier": "usps",
        "status": "delivered",
        "recipient_address": "Chicago, IL",
        "events": [
            {
                "timestamp": "2026-08-21T12:00:00Z",
                "status": "delivered",
                "description": "Package delivered to mailbox",
                "location": "Chicago, IL",
            }
        ],
    }
    resp = requests.post(url, json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["tracking_number"] == "9400100000000000000002"
    assert data["status"] == "delivered"
    assert len(data["events"]) == 1


def test_track_parcel_missing_tracking_number_returns_400(test_server):
    url = f"{test_server['url']}/api/track"
    resp = requests.post(url, json={"carrier": "usps"})
    assert resp.status_code == 400
    assert "required" in resp.json()["error"].lower()


def test_track_parcel_invalid_tracking_number_returns_400(test_server):
    url = f"{test_server['url']}/api/track"
    # Invalid USPS format
    resp = requests.post(url, json={"tracking_number": "INVALID_USPS", "carrier": "usps"})
    assert resp.status_code == 400
    assert "invalid" in resp.json()["error"].lower()


def test_track_parcel_malformed_json_returns_400(test_server):
    url = f"{test_server['url']}/api/track"
    resp = requests.post(url, data="NOT_JSON", headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert "malformed json" in resp.json()["error"].lower()


def test_track_parcel_brightdata_not_found(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.side_effect = BrightDataNotFoundError("Tracking number not found on carrier")

    url = f"{test_server['url']}/api/track"
    resp = requests.post(url, json={"tracking_number": "9400100000000000000003", "carrier": "usps"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"].lower()

    # Scrape log should record not_found
    logs = get_scrape_logs("9400100000000000000003", db_path=test_server["db_path"])
    assert len(logs) == 1
    assert logs[0]["status"] == "not_found"


def test_track_parcel_brightdata_rate_limit(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.side_effect = BrightDataRateLimitError("Rate limit exceeded")

    url = f"{test_server['url']}/api/track"
    resp = requests.post(url, json={"tracking_number": "9400100000000000000004", "carrier": "usps"})
    assert resp.status_code == 429
    assert "rate limit" in resp.json()["error"].lower()


def test_track_parcel_brightdata_auth_failure(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.side_effect = BrightDataAuthError("Invalid API key")

    url = f"{test_server['url']}/api/track"
    resp = requests.post(url, json={"tracking_number": "9400100000000000000005", "carrier": "usps"})
    assert resp.status_code == 502
    assert "authentication failed" in resp.json()["error"].lower()


def test_track_parcel_brightdata_timeout(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.side_effect = BrightDataTimeoutError("Timeout")

    url = f"{test_server['url']}/api/track"
    resp = requests.post(url, json={"tracking_number": "9400100000000000000006", "carrier": "usps"})
    assert resp.status_code == 504
    assert "timed out" in resp.json()["error"].lower()


def test_track_parcel_brightdata_network_error(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.side_effect = BrightDataNetworkError("Connection refused")

    url = f"{test_server['url']}/api/track"
    resp = requests.post(url, json={"tracking_number": "9400100000000000000007", "carrier": "usps"})
    assert resp.status_code == 502
    assert "external tracking provider" in resp.json()["error"].lower()


def test_list_and_get_parcels(test_server):
    mock_client = test_server["mock_client"]
    
    # Ingest two parcels
    mock_client.fetch_tracking.return_value = {
        "tracking_number": "9400100000000000000010",
        "carrier": "usps",
        "status": "in_transit",
        "events": [],
    }
    requests.post(f"{test_server['url']}/api/track", json={"tracking_number": "9400100000000000000010", "carrier": "usps"})

    mock_client.fetch_tracking.return_value = {
        "tracking_number": "1Z9999999999999991",
        "carrier": "ups",
        "status": "delivered",
        "events": [],
    }
    requests.post(f"{test_server['url']}/api/track", json={"tracking_number": "1Z9999999999999991", "carrier": "ups"})

    # List all
    resp = requests.get(f"{test_server['url']}/api/parcels")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2

    # Filter by carrier
    resp_carrier = requests.get(f"{test_server['url']}/api/parcels?carrier=usps")
    assert resp_carrier.status_code == 200
    assert resp_carrier.json()["total"] == 1
    assert resp_carrier.json()["parcels"][0]["tracking_number"] == "9400100000000000000010"

    # Filter by status
    resp_status = requests.get(f"{test_server['url']}/api/parcels?status=delivered")
    assert resp_status.status_code == 200
    assert resp_status.json()["total"] == 1
    assert resp_status.json()["parcels"][0]["tracking_number"] == "1Z9999999999999991"

    # Get single parcel
    resp_single = requests.get(f"{test_server['url']}/api/parcels/9400100000000000000010")
    assert resp_single.status_code == 200
    assert resp_single.json()["tracking_number"] == "9400100000000000000010"

    # Get non-existent parcel
    resp_404 = requests.get(f"{test_server['url']}/api/parcels/NONEXISTENT999")
    assert resp_404.status_code == 404


def test_delete_parcel(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.return_value = {
        "tracking_number": "9400100000000000000020",
        "carrier": "usps",
        "status": "in_transit",
        "events": [],
    }
    requests.post(f"{test_server['url']}/api/track", json={"tracking_number": "9400100000000000000020", "carrier": "usps"})

    # Delete existing
    del_resp = requests.delete(f"{test_server['url']}/api/parcels/9400100000000000000020")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    # Delete non-existing returns 404
    del_404 = requests.delete(f"{test_server['url']}/api/parcels/9400100000000000000020")
    assert del_404.status_code == 404


def test_get_events_and_logs(test_server):
    mock_client = test_server["mock_client"]
    mock_client.fetch_tracking.return_value = {
        "tracking_number": "9400100000000000000030",
        "carrier": "usps",
        "status": "in_transit",
        "events": [
            {
                "timestamp": "2026-08-20T10:00:00Z",
                "status": "in_transit",
                "description": "Departed USPS Facility",
            }
        ],
    }
    requests.post(f"{test_server['url']}/api/track", json={"tracking_number": "9400100000000000000030", "carrier": "usps"})

    # Get events
    events_resp = requests.get(f"{test_server['url']}/api/parcels/9400100000000000000030/events")
    assert events_resp.status_code == 200
    events_data = events_resp.json()
    assert events_data["tracking_number"] == "9400100000000000000030"
    assert len(events_data["events"]) == 1

    # Get logs
    logs_resp = requests.get(f"{test_server['url']}/api/logs")
    assert logs_resp.status_code == 200
    assert logs_resp.json()["total"] >= 1
