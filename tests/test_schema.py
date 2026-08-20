import sqlite3
from pathlib import Path


def test_schema_execution():
    schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
    assert schema_path.exists()
    
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    
    schema_sql = schema_path.read_text(encoding="utf-8")
    cursor.executescript(schema_sql)
    
    # Verify tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    assert "parcels" in tables
    assert "events" in tables
    assert "scrape_logs" in tables
    
    # Verify foreign key enforcement
    cursor.execute("INSERT INTO parcels (tracking_number, carrier, created_at, updated_at) VALUES ('123', 'usps', '2026-08-20', '2026-08-20');")
    parcel_id = cursor.lastrowid
    
    cursor.execute("INSERT INTO events (parcel_id, timestamp, status, created_at) VALUES (?, '2026-08-20T10:00:00Z', 'in_transit', '2026-08-20T10:00:00Z');", (parcel_id,))
    
    cursor.execute("SELECT COUNT(*) FROM events WHERE parcel_id = ?;", (parcel_id,))
    assert cursor.fetchone()[0] == 1
    
    conn.close()
