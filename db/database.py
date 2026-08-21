"""
Persistence layer for StayTrace.
Encapsulates SQLite and Turso (libSQL) connection management, schema initialization,
and transactional CRUD operations.
Isolated from API and scraping network layers.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, NamedTuple, Optional, Sequence, Tuple, Union

import requests

logger = logging.getLogger("staytrace.db")

DEFAULT_DB_PATH = "parcels.db"
DEFAULT_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class TursoQueryResult(NamedTuple):
    """Normalized query execution result from Turso / libSQL."""
    cols: List[str]
    rows: List[Dict[str, Any]]
    rowcount: int
    last_insert_rowid: Optional[int]


class TursoClient:
    """Lightweight HTTP client for Turso / libSQL Database Pipeline API (v2)."""

    def __init__(
        self,
        url: Optional[str] = None,
        auth_token: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: int = 15,
    ):
        raw_url = (url or os.environ.get("TURSO_DATABASE_URL") or os.environ.get("TURSO_URL") or os.environ.get("LIBSQL_URL") or "").strip()
        self.url = self._normalize_url(raw_url)
        self.auth_token = (auth_token or os.environ.get("TURSO_AUTH_TOKEN") or os.environ.get("TURSO_TOKEN") or os.environ.get("LIBSQL_AUTH_TOKEN") or "").strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    @staticmethod
    def _normalize_url(raw_url: str) -> str:
        """Convert libsql:// or standard URL into the HTTPS pipeline endpoint."""
        if not raw_url:
            return ""
        clean_url = raw_url
        if clean_url.startswith("libsql://"):
            clean_url = "https://" + clean_url[len("libsql://"):]
        elif not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = "https://" + clean_url

        clean_url = clean_url.rstrip("/")
        if not clean_url.endswith("/v2/pipeline"):
            clean_url = f"{clean_url}/v2/pipeline"
        return clean_url

    @staticmethod
    def _format_arg(val: Any) -> Dict[str, Any]:
        """Format Python value for libSQL v2 pipeline argument."""
        if val is None:
            return {"type": "null"}
        if isinstance(val, bool):
            return {"type": "integer", "value": "1" if val else "0"}
        if isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        if isinstance(val, float):
            return {"type": "float", "value": val}
        if isinstance(val, (bytes, bytearray)):
            return {"type": "blob", "base64": base64.b64encode(val).decode("ascii")}
        return {"type": "text", "value": str(val)}

    @staticmethod
    def _parse_val(val_dict: Optional[Dict[str, Any]]) -> Any:
        """Parse libSQL v2 cell value to native Python type."""
        if not val_dict or not isinstance(val_dict, dict):
            return None
        vtype = val_dict.get("type", "null")
        if vtype == "null":
            return None
        if vtype == "integer":
            return int(val_dict.get("value", 0))
        if vtype == "float":
            return float(val_dict.get("value", 0.0))
        if vtype == "text":
            return str(val_dict.get("value", ""))
        if vtype == "blob":
            b64_val = val_dict.get("base64", "")
            return base64.b64decode(b64_val) if b64_val else b""
        return val_dict.get("value")

    def execute_pipeline(self, requests_payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send batched requests to the Turso libSQL pipeline endpoint."""
        if not self.url:
            raise sqlite3.OperationalError("Turso database URL is not configured. Set TURSO_DATABASE_URL.")

        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        body = {
            "requests": requests_payload + [{"type": "close"}]
        }

        try:
            response = self.session.post(self.url, headers=headers, json=body, timeout=self.timeout)
            if response.status_code in (401, 403):
                raise sqlite3.OperationalError(f"Turso authentication failed (HTTP {response.status_code}): {response.text}")
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            raise sqlite3.OperationalError(f"Network error connecting to Turso: {e}") from e

        results = data.get("results", [])
        parsed_results: List[Dict[str, Any]] = []

        for item in results:
            item_type = item.get("type")
            if item_type == "error":
                err_msg = item.get("error", {}).get("message") or item.get("message") or "Unknown Turso error"
                raise sqlite3.DatabaseError(f"Turso execution error: {err_msg}")
            elif item_type == "ok":
                resp = item.get("response", {})
                if resp.get("type") == "execute":
                    parsed_results.append(resp.get("result", {}))

        return parsed_results

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> TursoQueryResult:
        """Execute a single SQL statement against Turso."""
        args = [self._format_arg(p) for p in (params or [])]
        req = {
            "type": "execute",
            "stmt": {
                "sql": sql,
                "args": args,
            }
        }
        res_list = self.execute_pipeline([req])
        if not res_list:
            return TursoQueryResult(cols=[], rows=[], rowcount=0, last_insert_rowid=None)

        res = res_list[0]
        cols = [c.get("name") for c in res.get("cols", [])]
        raw_rows = res.get("rows", [])
        dict_rows: List[Dict[str, Any]] = []

        for row in raw_rows:
            parsed_cells = [self._parse_val(cell) for cell in row]
            dict_rows.append(dict(zip(cols, parsed_cells)))

        last_id_raw = res.get("last_insert_rowid")
        last_insert_id = int(last_id_raw) if last_id_raw is not None else None
        rowcount = int(res.get("affected_row_count", 0))

        return TursoQueryResult(cols=cols, rows=dict_rows, rowcount=rowcount, last_insert_rowid=last_insert_id)

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> int:
        """Execute multiple parameterized instances of a SQL statement."""
        if not params_seq:
            return 0
        requests_list = [
            {
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": [self._format_arg(p) for p in params],
                }
            }
            for params in params_seq
        ]
        res_list = self.execute_pipeline(requests_list)
        total_affected = sum(int(r.get("affected_row_count", 0)) for r in res_list)
        return total_affected

    def executescript(self, script_sql: str) -> None:
        """Execute multi-statement SQL DDL script."""
        # Split statements by semicolon while ignoring comments and whitespace
        statements = []
        for raw_stmt in script_sql.split(";"):
            cleaned = raw_stmt.strip()
            if cleaned and not cleaned.startswith("--"):
                statements.append(cleaned)

        if not statements:
            return

        requests_list = [
            {
                "type": "execute",
                "stmt": {
                    "sql": stmt,
                    "args": [],
                }
            }
            for stmt in statements
        ]
        self.execute_pipeline(requests_list)


def is_turso_backend(db_path: Optional[str] = None) -> bool:
    """Determine whether to route database operations to Turso or local SQLite."""
    # If an explicit custom file path or in-memory DB is provided, always use SQLite
    if db_path is not None:
        return False

    backend = os.environ.get("DATABASE_BACKEND", "").strip().lower()
    if backend in ("turso", "libsql"):
        return True
    if backend == "sqlite":
        return False

    # Auto-detect if TURSO_DATABASE_URL or TURSO_URL is set
    return bool(os.environ.get("TURSO_DATABASE_URL") or os.environ.get("TURSO_URL") or os.environ.get("LIBSQL_URL"))


def get_turso_client() -> TursoClient:
    """Instantiate a TursoClient configured from environment variables."""
    return TursoClient()


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Resolve database path from argument or environment."""
    if custom_path:
        return custom_path
    return os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create and configure a local SQLite database connection."""
    target_path = get_db_path(db_path)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_session(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for automatic commit and rollback of SQLite database transactions."""
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

    if is_turso_backend(db_path):
        client = get_turso_client()
        client.executescript(schema_sql)
    else:
        with db_session(db_path) as conn:
            conn.executescript(schema_sql)


def dict_from_row(row: Optional[Union[sqlite3.Row, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Convert sqlite3.Row or dict object to a plain dictionary."""
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

    sql = """
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
    """
    params = (
        tracking_number, carrier, status, sender_address, recipient_address,
        origin_country, destination_country, estimated_delivery, weight,
        service_type, created_at, updated_at,
    )

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        res = client.execute(sql, params)
        if res.rows and "id" in res.rows[0]:
            return res.rows[0]["id"]
        # Fallback query
        fallback_res = client.execute("SELECT id FROM parcels WHERE tracking_number = ?;", (tracking_number,))
        if fallback_res.rows:
            return fallback_res.rows[0]["id"]
        raise sqlite3.DatabaseError(f"Failed to retrieve inserted parcel ID for {tracking_number}")

    def _execute(connection: sqlite3.Connection) -> int:
        cursor = connection.cursor()
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if row:
            return row[0]
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
    clean_tracking = tracking_number.strip()

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        res = client.execute(query, (clean_tracking,))
        return res.rows[0] if res.rows else None

    def _execute(connection: sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute(query, (clean_tracking,))
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

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        res = client.execute(query, (parcel_id,))
        return res.rows[0] if res.rows else None

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

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        res = client.execute(query, params)
        return res.rows

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
    clean_tracking = tracking_number.strip()
    query = "DELETE FROM parcels WHERE tracking_number = ?;"

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        res = client.execute(query, (clean_tracking,))
        return res.rowcount > 0

    def _execute(connection: sqlite3.Connection) -> bool:
        cursor = connection.cursor()
        cursor.execute(query, (clean_tracking,))
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
    params = (parcel_id, timestamp, status, description, location, event_code, created_at)

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        res = client.execute(query, params)
        return res.last_insert_rowid or 0

    def _execute(connection: sqlite3.Connection) -> int:
        cursor = connection.cursor()
        cursor.execute(query, params)
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

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        return client.executemany(query, rows)

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

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        res = client.execute(query, (parcel_id,))
        return res.rows

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
    clean_tracking = tracking_number.strip()

    if is_turso_backend(db_path) and not conn:
        client = get_turso_client()
        res = client.execute(query, (clean_tracking,))
        return res.rows

    def _execute(connection: sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute(query, (clean_tracking,))
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
    if is_turso_backend(db_path):
        client = get_turso_client()
        parcel_id = upsert_parcel(parcel_data, db_path=db_path)
        all_events = events if events is not None else parcel_data.get("events", [])
        if all_events:
            client.execute("DELETE FROM events WHERE parcel_id = ?;", (parcel_id,))
            insert_events(parcel_id, all_events, db_path=db_path)
        return parcel_id

    with db_session(db_path) as conn:
        parcel_id = upsert_parcel(parcel_data, conn=conn)

        all_events = events if events is not None else parcel_data.get("events", [])
        if all_events:
            conn.execute("DELETE FROM events WHERE parcel_id = ?;", (parcel_id,))
            insert_events(parcel_id, all_events, conn=conn)

        return parcel_id


def get_parcel_with_events(
    tracking_number: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve complete parcel record along with its event history."""
    if is_turso_backend(db_path):
        parcel = get_parcel(tracking_number, db_path=db_path)
        if not parcel:
            return None
        events = get_events_by_parcel_id(parcel["id"], db_path=db_path)
        parcel["events"] = events
        return parcel

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
    params = (tracking_number, carrier, status, error_message, now_iso)

    if is_turso_backend(db_path):
        client = get_turso_client()
        res = client.execute(query, params)
        return res.last_insert_rowid or 0

    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
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

    if is_turso_backend(db_path):
        client = get_turso_client()
        res = client.execute(query, params)
        return res.rows

    with db_session(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
