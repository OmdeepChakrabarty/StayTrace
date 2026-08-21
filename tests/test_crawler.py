"""
Tests for background crawler / worker (Level 6).
"""

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from db.database import init_db, upsert_parcel, get_parcel_with_events, get_scrape_logs
from scraper.brightdata import BrightDataClient, BrightDataNotFoundError, BrightDataError
from scraper.crawl import crawl_active_parcels


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path=path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_crawl_active_parcels_updates_status(temp_db):
    # Setup parcels in DB: 1 active, 1 terminal
    upsert_parcel(
        {"tracking_number": "9400100000000000000001", "carrier": "usps", "status": "in_transit"},
        db_path=temp_db,
    )
    upsert_parcel(
        {"tracking_number": "9400100000000000000002", "carrier": "usps", "status": "delivered"},
        db_path=temp_db,
    )

    mock_client = MagicMock(spec=BrightDataClient)
    mock_client.fetch_tracking.return_value = {
        "tracking_number": "9400100000000000000001",
        "carrier": "usps",
        "status": "delivered",
        "events": [
            {
                "timestamp": "2026-08-21T15:00:00Z",
                "status": "delivered",
                "description": "Delivered in mailbox",
            }
        ],
    }

    stats = crawl_active_parcels(db_path=temp_db, client=mock_client)
    assert stats["processed"] == 1  # Delivered parcel was skipped
    assert stats["updated"] == 1
    assert stats["terminal"] == 1
    assert stats["errors"] == 0

    updated = get_parcel_with_events("9400100000000000000001", db_path=temp_db)
    assert updated["status"] == "delivered"
    assert len(updated["events"]) == 1


def test_crawl_active_parcels_handles_not_found(temp_db):
    upsert_parcel(
        {"tracking_number": "9400100000000000000003", "carrier": "usps", "status": "pre_transit"},
        db_path=temp_db,
    )

    mock_client = MagicMock(spec=BrightDataClient)
    mock_client.fetch_tracking.side_effect = BrightDataNotFoundError("Parcel not found on USPS")

    stats = crawl_active_parcels(db_path=temp_db, client=mock_client)
    assert stats["processed"] == 1
    assert stats["errors"] == 1

    logs = get_scrape_logs("9400100000000000000003", db_path=temp_db)
    assert len(logs) == 1
    assert logs[0]["status"] == "not_found"
