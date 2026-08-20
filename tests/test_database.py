import os
import tempfile
from pathlib import Path
import pytest

from db.database import (
    init_db,
    get_connection,
    upsert_parcel,
    get_parcel,
    get_parcel_by_id,
    list_parcels,
    delete_parcel,
    insert_event,
    insert_events,
    get_events_by_parcel_id,
    get_events_by_tracking_number,
    save_parcel_with_events,
    get_parcel_with_events,
    log_scrape,
    get_scrape_logs,
)
from pipeline.normalize import normalize_parcel


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path=path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_init_db_creates_tables(temp_db):
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "parcels" in tables
    assert "events" in tables
    assert "scrape_logs" in tables


def test_upsert_and_get_parcel(temp_db):
    parcel_data = {
        "tracking_number": "9400100000000000000022",
        "carrier": "usps",
        "status": "in_transit",
        "sender_address": "Seattle, WA",
        "recipient_address": "New York, NY",
        "weight": 2.5,
    }
    
    parcel_id = upsert_parcel(parcel_data, db_path=temp_db)
    assert parcel_id > 0

    fetched = get_parcel("9400100000000000000022", db_path=temp_db)
    assert fetched is not None
    assert fetched["id"] == parcel_id
    assert fetched["tracking_number"] == "9400100000000000000022"
    assert fetched["status"] == "in_transit"
    assert fetched["carrier"] == "usps"
    assert fetched["weight"] == 2.5

    # Update parcel
    update_data = {
        "tracking_number": "9400100000000000000022",
        "carrier": "usps",
        "status": "delivered",
    }
    updated_id = upsert_parcel(update_data, db_path=temp_db)
    assert updated_id == parcel_id

    fetched_updated = get_parcel_by_id(parcel_id, db_path=temp_db)
    assert fetched_updated["status"] == "delivered"
    assert fetched_updated["sender_address"] == "Seattle, WA"  # Preserved via COALESCE


def test_upsert_missing_tracking_number_raises_error(temp_db):
    with pytest.raises(ValueError, match="tracking_number is required"):
        upsert_parcel({"carrier": "fedex"}, db_path=temp_db)


def test_list_parcels_filtering(temp_db):
    parcels = [
        {"tracking_number": "USPS001", "carrier": "usps", "status": "delivered"},
        {"tracking_number": "USPS002", "carrier": "usps", "status": "in_transit"},
        {"tracking_number": "FEDEX001", "carrier": "fedex", "status": "in_transit"},
    ]
    for p in parcels:
        upsert_parcel(p, db_path=temp_db)

    all_parcels = list_parcels(db_path=temp_db)
    assert len(all_parcels) == 3

    usps_only = list_parcels(carrier="usps", db_path=temp_db)
    assert len(usps_only) == 2

    in_transit_only = list_parcels(status="in_transit", db_path=temp_db)
    assert len(in_transit_only) == 2

    fedex_in_transit = list_parcels(carrier="fedex", status="in_transit", db_path=temp_db)
    assert len(fedex_in_transit) == 1
    assert fedex_in_transit[0]["tracking_number"] == "FEDEX001"


def test_events_operations_and_cascade(temp_db):
    parcel_id = upsert_parcel({"tracking_number": "TRK123", "carrier": "ups", "status": "in_transit"}, db_path=temp_db)
    
    ev1 = {"timestamp": "2026-08-20T10:00:00Z", "status": "pre_transit", "description": "Label Created"}
    ev2 = {"timestamp": "2026-08-20T14:00:00Z", "status": "in_transit", "description": "Arrived at Facility"}
    
    insert_event(parcel_id, ev1, db_path=temp_db)
    insert_events(parcel_id, [ev2], db_path=temp_db)

    events_by_id = get_events_by_parcel_id(parcel_id, db_path=temp_db)
    assert len(events_by_id) == 2
    assert events_by_id[0]["status"] == "pre_transit"
    assert events_by_id[1]["status"] == "in_transit"

    events_by_trk = get_events_by_tracking_number("TRK123", db_path=temp_db)
    assert len(events_by_trk) == 2

    # Verify cascading delete
    deleted = delete_parcel("TRK123", db_path=temp_db)
    assert deleted is True
    assert get_parcel("TRK123", db_path=temp_db) is None
    assert len(get_events_by_parcel_id(parcel_id, db_path=temp_db)) == 0


def test_save_and_get_parcel_with_events(temp_db):
    raw_parcel = {
        "tracking_number": "9400100000000000000022",
        "carrier": "usps",
        "status": "delivered",
        "sender_address": "Seattle, WA",
        "recipient_address": "New York, NY",
        "events": [
            {"timestamp": "2026-08-19T10:00:00Z", "status": "in_transit", "description": "In transit"},
            {"timestamp": "2026-08-20T12:00:00Z", "status": "delivered", "description": "Delivered"},
        ]
    }

    parcel_id = save_parcel_with_events(raw_parcel, db_path=temp_db)
    assert parcel_id > 0

    full_parcel = get_parcel_with_events("9400100000000000000022", db_path=temp_db)
    assert full_parcel is not None
    assert full_parcel["status"] == "delivered"
    assert len(full_parcel["events"]) == 2
    assert full_parcel["events"][1]["status"] == "delivered"


def test_log_scrape_and_get_logs(temp_db):
    log_id1 = log_scrape("9400100000000000000022", "usps", "success", db_path=temp_db)
    log_id2 = log_scrape("9400100000000000000022", "usps", "failed", error_message="Rate limit", db_path=temp_db)
    log_id3 = log_scrape("FEDEX999", "fedex", "success", db_path=temp_db)

    assert log_id1 > 0
    assert log_id2 > 0

    logs_all = get_scrape_logs(db_path=temp_db)
    assert len(logs_all) == 3

    logs_specific = get_scrape_logs("9400100000000000000022", db_path=temp_db)
    assert len(logs_specific) == 2
    assert logs_specific[0]["status"] == "failed"
    assert logs_specific[0]["error_message"] == "Rate limit"
