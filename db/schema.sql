-- StayTrace Database Schema

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS parcels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_type TEXT NOT NULL DEFAULT 'parcel',
    tracking_number TEXT NOT NULL UNIQUE,
    carrier TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    shipping_line TEXT,
    vessel_name TEXT,
    voyage_number TEXT,
    origin_port TEXT,
    origin_port_code TEXT,
    destination_port TEXT,
    destination_port_code TEXT,
    current_location TEXT,
    estimated_departure TEXT,
    actual_departure TEXT,
    estimated_arrival TEXT,
    actual_arrival TEXT,
    sender_address TEXT,
    recipient_address TEXT,
    origin_country TEXT,
    destination_country TEXT,
    estimated_delivery TEXT,
    weight REAL,
    service_type TEXT,
    healing_status TEXT,
    healing_confidence REAL,
    healing_details TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    event_type TEXT,
    description TEXT,
    location TEXT,
    location_code TEXT,
    event_code TEXT,
    vessel TEXT,
    voyage TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (parcel_id) REFERENCES parcels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scrape_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_number TEXT NOT NULL,
    carrier TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    scraped_at TEXT NOT NULL
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_parcels_tracking_number ON parcels(tracking_number);
CREATE INDEX IF NOT EXISTS idx_parcels_shipment_type ON parcels(shipment_type);
CREATE INDEX IF NOT EXISTS idx_parcels_carrier ON parcels(carrier);
CREATE INDEX IF NOT EXISTS idx_parcels_status ON parcels(status);
CREATE INDEX IF NOT EXISTS idx_events_parcel_id ON events(parcel_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_scrape_logs_tracking_number ON scrape_logs(tracking_number);
