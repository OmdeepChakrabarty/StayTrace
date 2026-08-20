# AGENTS.md — ParcelPulse Architecture & Development Guide

## 1. Project Overview

**ParcelPulse** is an automated parcel tracking, normalization, and logistics data aggregation engine. It ingests tracking data across various shipping carriers (e.g., USPS, FedEx, UPS, DHL, Amazon), normalizes carrier-specific formats into a canonical representation, reconciles historical and incoming status checkpoints, and provides a persistent queryable database and API service.

---

## 2. Architectural Principles & Boundaries

1. **Layer Isolation**:
   - **Pure Logic** (`pipeline/`, `scraper/validator.py`): Completely deterministic, no I/O, no network calls, no database connections.
   - **External Service Boundary** (`scraper/brightdata.py`): Encapsulates all third-party proxy/scraping service calls. Fully mockable and decoupled from business logic.
   - **Persistence Layer** (`db/`): Encapsulates all database interactions, schema initialization, and transactional guarantees.
   - **API & Scheduling** (`api/`, background workers): Built on top of the domain and database layers.

2. **Data Integrity & Immutability**:
   - Timestamps must always be standardized to ISO 8601 UTC strings (`YYYY-MM-DDTHH:MM:SSZ` or ISO format).
   - Tracking numbers are normalized (trimmed, uppercase, alphanumeric sanitization where appropriate).
   - Checkpoint events are deduplicated based on unique combinations of timestamp, status, location, and description.

3. **Security & Secrets**:
   - Zero hardcoded credentials. All secrets (e.g., Bright Data API keys, zones) must be loaded from environment variables.
   - `.env` must never be committed.

---

## 3. Level-by-Level Development Roadmap

### Level 0: Repository & Configuration
- Configuration files: `requirements.txt`, `.env.example`.
- Mock datasets: `tests/mock_data.json`.
- Authoritative documentation: `AGENTS.md`.

### Level 1: Pure / Independent Foundations
- `pipeline/normalize.py`: Carrier name canonicalization, status code mapping, ISO timestamp parsing, address/location normalization, weight normalization.
- `scraper/validator.py`: Tracking number validation rules per carrier, raw payload schema checking, event validity validation.
- `db/schema.sql`: Relational database schema for `parcels`, `events`, and `scrape_logs` tables with constraints and indexes.
- Unit tests for pure components with 100% deterministic test fixtures.

### Level 2: Pipeline Resolution & Reconciliation
- `pipeline/resolver.py`: Reconciles incoming raw/normalized data with existing database state. Merges and deduplicates event histories, computes latest status, detects progress changes, and validates chronological ordering.
- Unit tests for all conflict and resolution edge cases.

### Level 3: External-Service Boundary
- `scraper/brightdata.py`: Client for Bright Data Web Unlocker / Scraping API. Implements retry logic, rate-limit handling, error wrapping, authentication, and structured response parsing.
- Unit tests using mocks and dependency injection (no live network requests in tests).

### Level 4: Persistence Layer
- `db/database.py`: SQLite persistence implementation supporting connection lifecycle, schema migrations/initialization, CRUD operations, atomic batch insertions, and query filtering.
- Persistence integration tests verifying data integrity, constraints, and transactions.

### Level 5: API Layer (Future Scope)
- `api/main.py`: REST API endpoints for submitting tracking requests, querying parcels, listing checkpoints, and health monitoring.

### Level 6: Background Crawl Worker & Scheduling (Future Scope)
- Asynchronous crawling pipeline, task queuing, periodic polling of active parcels.

### Level 7: Web Frontend (Future Scope)
- `web/`: Dashboard for monitoring tracked parcels, search interface, and visual event timeline.

### Level 8: CI/CD & Deployment (Future Scope)
- Containerization, GitHub Actions workflows, staging and production deployment configurations.

---

## 4. Canonical Data Models

### Carrier Enum / Identifiers
- `usps`
- `fedex`
- `ups`
- `dhl`
- `amazon`
- `ontrac`
- `other`

### Tracking Status Enum
- `pre_transit` (Label created, info received)
- `in_transit` (En route, departure/arrival scans)
- `out_for_delivery` (With delivery courier)
- `delivered` (Delivered to recipient/mailbox)
- `failed_attempt` (Delivery attempted, unable to complete)
- `exception` (Customs hold, delay, weather exception)
- `returned` (Returned to sender)
- `unknown` (Unrecognized status)

### Normalized Parcel Schema
```json
{
  "tracking_number": "9400100000000000000000",
  "carrier": "usps",
  "status": "in_transit",
  "sender_address": "Los Angeles, CA, US",
  "recipient_address": "New York, NY, US",
  "origin_country": "US",
  "destination_country": "US",
  "estimated_delivery": "2026-08-25T18:00:00Z",
  "weight": 1.25,
  "service_type": "Priority Mail",
  "created_at": "2026-08-20T10:00:00Z",
  "updated_at": "2026-08-20T12:00:00Z"
}
```

### Normalized Event Schema
```json
{
  "timestamp": "2026-08-20T11:30:00Z",
  "status": "in_transit",
  "description": "Departed USPS Regional Facility",
  "location": "LOS ANGELES CA DISTRIBUTION CENTER",
  "event_code": "DEPART"
}
```

---

## 5. Development & Testing Commands

- Run all unit tests:
  ```bash
  pytest -v
  ```
- Run specific level tests:
  ```bash
  pytest tests/test_normalize.py tests/test_validator.py
  ```
- Run with coverage:
  ```bash
  pytest --cov=.
  ```
