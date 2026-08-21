"""
Unit tests for Turso / libSQL production database backend integration.
Verifies URL normalization, serialization, query formatting, response parsing, and backend routing.
"""

import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
import requests

from db.database import (
    TursoClient,
    is_turso_backend,
    init_db,
    upsert_parcel,
    get_parcel,
    list_parcels,
    delete_parcel,
    save_parcel_with_events,
    get_parcel_with_events,
    log_scrape,
    get_scrape_logs,
)


def test_turso_url_normalization():
    client1 = TursoClient(url="libsql://staytrace-prod-org.turso.io")
    assert client1.url == "https://staytrace-prod-org.turso.io/v2/pipeline"

    client2 = TursoClient(url="https://staytrace-prod-org.turso.io")
    assert client2.url == "https://staytrace-prod-org.turso.io/v2/pipeline"

    client3 = TursoClient(url="staytrace-prod-org.turso.io/v2/pipeline")
    assert client3.url == "https://staytrace-prod-org.turso.io/v2/pipeline"


def test_turso_arg_formatting_and_parsing():
    client = TursoClient(url="https://example.turso.io")

    # Format arguments
    assert client._format_arg(None) == {"type": "null"}
    assert client._format_arg(123) == {"type": "integer", "value": "123"}
    assert client._format_arg(45.67) == {"type": "float", "value": 45.67}
    assert client._format_arg("hello") == {"type": "text", "value": "hello"}
    assert client._format_arg(True) == {"type": "integer", "value": "1"}
    assert client._format_arg(False) == {"type": "integer", "value": "0"}

    # Parse cell values
    assert client._parse_val(None) is None
    assert client._parse_val({"type": "null"}) is None
    assert client._parse_val({"type": "integer", "value": "42"}) == 42
    assert client._parse_val({"type": "float", "value": 3.14}) == 3.14
    assert client._parse_val({"type": "text", "value": "test"}) == "test"


def test_is_turso_backend_detection():
    # Explicit path always uses SQLite
    assert is_turso_backend(db_path="/tmp/test.db") is False

    with patch.dict(os.environ, {"DATABASE_BACKEND": "turso"}, clear=True):
        assert is_turso_backend() is True

    with patch.dict(os.environ, {"DATABASE_BACKEND": "sqlite"}, clear=True):
        assert is_turso_backend() is False

    with patch.dict(os.environ, {"TURSO_DATABASE_URL": "libsql://my-db.turso.io"}, clear=True):
        assert is_turso_backend() is True

    with patch.dict(os.environ, {}, clear=True):
        assert is_turso_backend() is False


def test_turso_execute_success():
    session_mock = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "baton": None,
        "results": [
            {
                "type": "ok",
                "response": {
                    "type": "execute",
                    "result": {
                        "cols": [{"name": "id"}, {"name": "tracking_number"}, {"name": "status"}],
                        "rows": [
                            [{"type": "integer", "value": "1"}, {"type": "text", "value": "94001000"}, {"type": "text", "value": "in_transit"}]
                        ],
                        "affected_row_count": 1,
                        "last_insert_rowid": "1",
                    }
                }
            }
        ]
    }
    session_mock.post.return_value = mock_resp

    client = TursoClient(url="https://test.turso.io", auth_token="fake_token", session=session_mock)
    res = client.execute("SELECT * FROM parcels WHERE tracking_number = ?", ["94001000"])

    assert len(res.rows) == 1
    assert res.rows[0]["id"] == 1
    assert res.rows[0]["tracking_number"] == "94001000"
    assert res.rows[0]["status"] == "in_transit"
    assert res.last_insert_rowid == 1
    assert res.rowcount == 1


def test_turso_execute_error_raises_database_error():
    session_mock = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "type": "error",
                "message": "no such table: nonexistent_table",
            }
        ]
    }
    session_mock.post.return_value = mock_resp

    client = TursoClient(url="https://test.turso.io", auth_token="token", session=session_mock)
    with pytest.raises(sqlite3.DatabaseError, match="no such table"):
        client.execute("SELECT * FROM nonexistent_table")


def test_turso_auth_error_raises_operational_error():
    session_mock = MagicMock(spec=requests.Session)
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    session_mock.post.return_value = mock_resp

    client = TursoClient(url="https://test.turso.io", auth_token="bad_token", session=session_mock)
    with pytest.raises(sqlite3.OperationalError, match="Turso authentication failed"):
        client.execute("SELECT 1")


def test_database_operations_route_to_turso():
    with patch.dict(os.environ, {"DATABASE_BACKEND": "turso", "TURSO_DATABASE_URL": "libsql://test.turso.io"}):
        with patch("db.database.get_turso_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # init_db
            init_db()
            assert mock_client.executescript.called

            # get_parcel
            mock_client.execute.return_value.rows = [{"id": 10, "tracking_number": "TRK999", "status": "in_transit"}]
            p = get_parcel("TRK999")
            assert p is not None
            assert p["tracking_number"] == "TRK999"

            # list_parcels
            mock_client.execute.return_value.rows = [{"id": 10, "tracking_number": "TRK999"}]
            parcels = list_parcels()
            assert len(parcels) == 1

            # delete_parcel
            mock_client.execute.return_value.rowcount = 1
            deleted = delete_parcel("TRK999")
            assert deleted is True
