"""
Persistence layer for ParcelPulse.
Encapsulates SQLite connection management, schema initialization, and transactional CRUD operations.
Isolated from API and scraping network layers.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


DEFAULT_DB_PATH = "parcels.db"
DEFAULT_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Resolve database path from argument or environment."""
    if custom_path:
        return custom_path
    return os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create and configure a SQLite database connection."""
    target_path = get_db_path(db_path)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_session(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for automatic commit and rollback of database transactions."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None, schema_path: Optional[Path | str] = None) -> None:
    """Initialize database tables and indexes from schema SQL script."""
    schema_file = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found at: {schema_file}")

    schema_sql = schema_file.read_text(encoding="utf-8")
    with db_session(db_path) as conn:
        conn.executescript(schema_sql)


def dict_from_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    """Convert sqlite3.Row object to a plain dictionary."""
    if row is None:
        return None
    return dict(row)


def upsert_parcel(
    parcel: Dict[str, Any],
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Insert a new parcel or update an existing parcel by tracking_number."""
    tracking_number = parcel.get("tracking_number", "").strip()
    if not tracking_number:
        raise ValueError("tracking_number is required to save a parcel")

    carrier = parcel.get("carrier", "other")
    status = parcel.get("status", "unknown")
    sender_address = parcel.get("sender_address")
    recipient_address = parcel.get("recipient_address")
    origin_country = parcel.get("origin_country")
    destination_country = parcel.get("destination_country")
    estimated_delivery = parcel.get("estimated_delivery")
    weight = parcel.get("weight")
    service_type = parcel.get("service_type")
    
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    created_at = parcel.get("created_at") or now_iso
    updated_at = parcel.get("updated_at") or now_iso

    def _execute(connection: sqlite3.Connection) -> int:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO parcels (
                tracking_number, carrier, status, sender_address, recipient_address,
                origin_country, destination_country, estimated_delivery, weight,
                service_type, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tracking_number) DO UPDATE SET
                carrier = excluded.carrier,
                status = excluded.status,
                sender_address = COALESCE(excluded.sender_address, parcels.sender_address),
                recipient_address = COALESCE(excluded.recipient_address, parcels.recipient_address),
                origin_country = COALESCE(excluded.origin_country, parcels.origin_country),
                destination_country = COALESCE(excluded.destination_country, parcels.destination_country),
                estimated_delivery = COALESCE(excluded.estimated_delivery, parcels.estimated_delivery),
                weight = COALESCE(excluded.weight, parcels.weight),
                service_type = COALESCE(excluded.service_type, parcels.service_type),
                updated_at = excluded.updated_at
            RETURNING id;
            """,
            (
                tracking_number, carrier, status, sender_address, recipient_address,
                origin_country, destination_country, estimated_delivery, weight,
                service_type, created_at, updated_at,
            ),
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        # Fallback query if RETURNING is not supported in older SQLite versions
        cursor.execute("SELECT id FROM parcels WHERE tracking_number = ?;", (tracking_number,))
        return cursor.fetchone()[0]

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def get_parcel(
    tracking_number: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve parcel record by tracking number."""
    query = "SELECT * FROM parcels WHERE tracking_number = ?;"
    
    def _execute(connection: sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute(query, (tracking_number.strip(),))
        return dict_from_row(cursor.fetchone())

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def get_parcel_by_id(
    parcel_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve parcel record by primary key ID."""
    query = "SELECT * FROM parcels WHERE id = ?;"

    def _execute(connection: sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute(query, (parcel_id,))
        return dict_from_row(cursor.fetchone())

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def list_parcels(
    carrier: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Query list of parcels with optional filtering and pagination."""
    clauses = []
    params: List[Any] = []

    if carrier:
        clauses.append("carrier = ?")
        params.append(carrier.strip().lower())
    if status:
        clauses.append("status = ?")
        params.append(status.strip().lower())

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM parcels {where_sql} ORDER BY updated_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    def _execute(connection: sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def delete_parcel(
    tracking_number: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """Delete a parcel and all cascading records."""
    def _execute(connection: sqlite3.Connection) -> bool:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM parcels WHERE tracking_number = ?;", (tracking_number.strip(),))
        return cursor.rowcount > 0

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def insert_event(
    parcel_id: int,
    event: Dict[str, Any],
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Insert a single tracking event checkpoint."""
    timestamp = event.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = event.get("status", "unknown")
    description = event.get("description")
    location = event.get("location")
    event_code = event.get("event_code")
    created_at = event.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    query = """
    INSERT INTO events (parcel_id, timestamp, status, description, location, event_code, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """

    def _execute(connection: sqlite3.Connection) -> int:
        cursor = connection.cursor()
        cursor.execute(query, (parcel_id, timestamp, status, description, location, event_code, created_at))
        return cursor.lastrowid

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def insert_events(
    parcel_id: int,
    events: List[Dict[str, Any]],
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Batch insert multiple tracking events for a parcel."""
    if not events:
        return 0

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [
        (
            parcel_id,
            ev.get("timestamp") or now_iso,
            ev.get("status", "unknown"),
            ev.get("description"),
            ev.get("location"),
            ev.get("event_code"),
            ev.get("created_at") or now_iso,
        )
        for ev in events
    ]

    query = """
    INSERT INTO events (parcel_id, timestamp, status, description, location, event_code, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """

    def _execute(connection: sqlite3.Connection) -> int:
        cursor = connection.cursor()
        cursor.executemany(query, rows)
        return cursor.rowcount

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def get_events_by_parcel_id(
    parcel_id: int,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all events associated with a parcel, ordered chronologically ascending."""
    query = "SELECT * FROM events WHERE parcel_id = ? ORDER BY timestamp ASC;"

    def _execute(connection: sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute(query, (parcel_id,))
        return [dict(row) for row in cursor.fetchall()]

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def get_events_by_tracking_number(
    tracking_number: str,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all events for a given parcel tracking number."""
    query = """
    SELECT e.* FROM events e
    JOIN parcels p ON e.parcel_id = p.id
    WHERE p.tracking_number = ?
    ORDER BY e.timestamp ASC;
    """

    def _execute(connection: sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute(query, (tracking_number.strip(),))
        return [dict(row) for row in cursor.fetchall()]

    if conn:
        return _execute(conn)
    else:
        with db_session(db_path) as session:
            return _execute(session)


def save_parcel_with_events(
    parcel_data: Dict[str, Any],
    events: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[str] = None,
) -> int:
    """
    Atomically save/update a parcel and its checkpoint events in a single transaction.
    Returns the parcel's database ID.
    """
    with db_session(db_path) as conn:
        parcel_id = upsert_parcel(parcel_data, conn=conn)

        all_events = events if events is not None else parcel_data.get("events", [])
        if all_events:
            # Delete existing events and re-insert or append
            conn.execute("DELETE FROM events WHERE parcel_id = ?;", (parcel_id,))
            insert_events(parcel_id, all_events, conn=conn)

        return parcel_id


def get_parcel_with_events(
    tracking_number: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve complete parcel record along with its event history."""
    with db_session(db_path) as conn:
        parcel = get_parcel(tracking_number, conn=conn)
        if not parcel:
            return None
        events = get_events_by_parcel_id(parcel["id"], conn=conn)
        parcel["events"] = events
        return parcel


def log_scrape(
    tracking_number: str,
    carrier: Optional[str],
    status: str,
    error_message: Optional[str] = None,
    scraped_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Record an entry in the scrape_logs table."""
    now_iso = scraped_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = """
    INSERT INTO scrape_logs (tracking_number, carrier, status, error_message, scraped_at)
    VALUES (?, ?, ?, ?, ?);
    """
    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (tracking_number, carrier, status, error_message, now_iso))
        return cursor.lastrowid


def get_scrape_logs(
    tracking_number: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve scrape logs with optional filtering by tracking number."""
    if tracking_number:
        query = "SELECT * FROM scrape_logs WHERE tracking_number = ? ORDER BY scraped_at DESC, id DESC LIMIT ?;"
        params: List[Any] = [tracking_number.strip(), limit]
    else:
        query = "SELECT * FROM scrape_logs ORDER BY scraped_at DESC, id DESC LIMIT ?;"
        params = [limit]

    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
