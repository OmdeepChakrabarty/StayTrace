# StayTrace

StayTrace is an automated parcel tracking, normalization, and logistics data aggregation engine. It ingests tracking data across various shipping carriers (USPS, FedEx, UPS, DHL, Amazon Logistics, OnTrac, etc.), normalizes carrier-specific structures into canonical models, reconciles historical checkpoints with incoming updates, and provides a persistent SQLite/Turso query layer, REST API, scheduled polling worker, and web dashboard.

---

## 1. Architecture Overview

StayTrace enforces clean separation of concerns across pure domain logic, external network boundaries, persistence, API, worker infrastructure, and frontend layers.

```text
┌─────────────────────────────────────────────────────────────┐
│                      Web Dashboard                          │
│                      (React + Vite)                         │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / JSON
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                        REST API                             │
│                      (api/main.py)                          │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────────┐┌─────────────────────────────┐
│      Scraper & Validator     ││      Pipeline Engine        │
│  - Carrier detection         ││  - Data normalization       │
│  - Format validation         ││  - Checkpoint deduplication │
│  - Bright Data Web Unlocker  ││  - Status reconciliation    │
└──────────────┬───────────────┘└─────────────┬───────────────┘
               │                              │
               └──────────────┬───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Persistence Layer                       │
│             (SQLite or Turso / libSQL Database)             │
│              parcels • events • scrape_logs                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Repository Structure

```text
StayTrace/
├── .github/
│   └── workflows/
│       └── crawl.yml         # CI pipeline and scheduled parcel crawl workflow
├── api/
│   ├── __init__.py
│   └── main.py              # REST API server and routing layer
├── db/
│   ├── database.py          # SQLite persistence layer and transactional CRUD operations
│   └── schema.sql           # Database schema (parcels, events, scrape_logs)
├── pipeline/
│   ├── __init__.py
│   ├── normalize.py         # Pure data normalization (carriers, statuses, timestamps, locations)
│   └── resolver.py          # State reconciliation and event deduplication logic
├── scraper/
│   ├── __init__.py
│   ├── brightdata.py        # External service boundary for Bright Data Web Unlocker
│   ├── crawl.py             # Periodic / background polling worker for active parcels
│   └── validator.py         # Format validation and carrier auto-detection rules
├── tests/
│   ├── mock_data.json       # Deterministic test fixtures and sample carrier payloads
│   ├── test_api.py          # API route and integration tests
│   ├── test_brightdata.py   # Scraper boundary and mock network tests
│   ├── test_config.py       # Configuration and fixture verification
│   ├── test_crawler.py      # Background crawl worker tests
│   ├── test_database.py     # Database persistence and transactional integrity tests
│   ├── test_normalize.py    # Normalization tests
│   ├── test_resolver.py     # Resolver and state transition tests
│   ├── test_schema.py       # Schema DDL and constraint tests
│   └── test_validator.py    # Tracking number and schema validation tests
├── web/
│   ├── index.html           # Frontend HTML entry point
│   ├── package.json         # Frontend dependencies and build scripts
│   ├── vite.config.js       # Vite configuration with API proxy
│   └── src/
│       ├── App.jsx          # Main dashboard component
│       ├── api.js           # Frontend API client
│       ├── index.css        # Dashboard styling and theme
│       └── main.jsx         # React mounting script
├── Dockerfile               # Production container definition
├── docker-compose.yml       # Local container orchestration
├── pytest.ini               # Pytest test discovery configuration
├── requirements.txt         # Backend Python dependencies
├── .env.example             # Example environment variable configuration
└── AGENTS.md                # System specification and development roadmap
```

---

## 3. Installation & Setup

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm (for web frontend)
- Docker & Docker Compose (optional, for containerized deployment)

### 1. Clone & Configure Environment
```bash
git clone https://github.com/OmdeepChakrabarty/StayTrace.git
cd StayTrace
cp .env.example .env
```

Edit `.env` with your Bright Data credentials (optional for testing/mock mode):
```ini
BRIGHTDATA_API_KEY=your_brightdata_api_key_here
BRIGHTDATA_ZONE=web_unlocker
BRIGHTDATA_ENDPOINT=https://api.brightdata.com
DATABASE_PATH=parcels.db
LOG_LEVEL=INFO
```

### 2. Install Backend Dependencies
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Install Frontend Dependencies
```bash
cd web
npm install
cd ..
```

---

## 4. Running Locally

### Run Backend API Server
```bash
python -m api.main
```
The API server starts by default on `http://0.0.0.0:8000`.

### Run Frontend Development Server
```bash
cd web
npm run dev
```
The frontend starts on `http://localhost:3000` with requests to `/api` and `/health` automatically proxied to `http://localhost:8000`.

### Run Active Parcel Background Crawler
To poll and update all non-terminal parcels in the database:
```bash
python -m scraper.crawl
```

### Run Tests
```bash
pytest -v
```
To run tests with coverage reporting:
```bash
pytest --cov=.
```

---

## 5. Docker Deployment

To build and run the application container using Docker Compose:

```bash
docker compose up --build -d
```

The container exposes the API on port `8000` and persists the SQLite database to a named volume (`staytrace_data`).

To view logs:
```bash
docker compose logs -f api
```

To stop containers:
```bash
docker compose down
```

---

## 6. Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DATABASE_BACKEND` | Database backend selector (`sqlite` or `turso`) | `sqlite` |
| `DATABASE_PATH` | Path to local SQLite database file | `parcels.db` |
| `TURSO_DATABASE_URL` | Turso / libSQL database URL (e.g., `libsql://db-name.turso.io`) | `""` |
| `TURSO_AUTH_TOKEN` | Turso authentication token | `""` |
| `BRIGHTDATA_API_KEY` | Bright Data API token for Web Unlocker proxy requests | `""` |
| `BRIGHTDATA_ZONE` | Bright Data zone name | `web_unlocker` |
| `BRIGHTDATA_ENDPOINT`| Bright Data base API endpoint | `https://api.brightdata.com` |
| `API_HOST` | Host address for API server binding | `0.0.0.0` |
| `API_PORT` | Port for API server | `8000` |
| `LOG_LEVEL` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

---

## 7. API Reference

### Health Check
- **`GET /health`** or **`GET /api/health`**
- **Response `200 OK`**:
  ```json
  {
    "status": "healthy",
    "service": "StayTrace API",
    "database": "connected"
  }
  ```

### Track / Ingest Parcel
- **`POST /api/track`** or **`POST /api/parcels`**
- **Request Body**:
  ```json
  {
    "tracking_number": "9400100000000000000001",
    "carrier": "usps"
  }
  ```
  *(Carrier is optional; if omitted, the carrier format will be auto-detected).*
- **Response `201 Created` / `200 OK`**:
  ```json
  {
    "id": 1,
    "tracking_number": "9400100000000000000001",
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
    "updated_at": "2026-08-20T12:00:00Z",
    "events": [
      {
        "id": 1,
        "parcel_id": 1,
        "timestamp": "2026-08-20T11:30:00Z",
        "status": "in_transit",
        "description": "Departed USPS Regional Facility",
        "location": "LOS ANGELES CA DISTRIBUTION CENTER",
        "event_code": "DEPART",
        "created_at": "2026-08-20T11:30:00Z"
      }
    ]
  }
  ```
- **Error Responses**:
  - `400 Bad Request`: Missing tracking number or invalid tracking number format for the specified carrier.
  - `404 Not Found`: Tracking entity not found by external provider.
  - `429 Too Many Requests`: Rate limit exceeded on external service.
  - `502 Bad Gateway`: External provider authentication or communication failure.

### List Parcels
- **`GET /api/parcels`**
- **Query Parameters**:
  - `carrier` *(optional)*: Filter by carrier (`usps`, `fedex`, `ups`, `dhl`, `amazon`, `ontrac`, `other`)
  - `status` *(optional)*: Filter by status (`pre_transit`, `in_transit`, `out_for_delivery`, `delivered`, `failed_attempt`, `exception`, `returned`, `unknown`)
  - `limit` *(optional, default 100)*: Maximum number of records
  - `offset` *(optional, default 0)*: Pagination offset
- **Response `200 OK`**:
  ```json
  {
    "parcels": [...],
    "total": 1
  }
  ```

### Get Single Parcel
- **`GET /api/parcels/{tracking_number}`**
- **Response `200 OK`**: Returns parcel object with complete checkpoint event list.
- **Error `404 Not Found`**: When tracking number is not present in the database.

### Get Parcel Events
- **`GET /api/parcels/{tracking_number}/events`**
- **Response `200 OK`**:
  ```json
  {
    "tracking_number": "9400100000000000000001",
    "events": [...]
  }
  ```

### Delete Parcel
- **`DELETE /api/parcels/{tracking_number}`**
- **Response `200 OK`**:
  ```json
  {
    "deleted": true,
    "tracking_number": "9400100000000000000001"
  }
  ```

### Audit Logs
- **`GET /api/logs`** (or `GET /api/logs?tracking_number=...`)
- **Response `200 OK`**: List of scraping attempt logs with timestamp, status, and error details.

---

## 8. Bright Data Integration

- The external scraping boundary is encapsulated in `scraper/brightdata.py`.
- Carrier tracking URLs are dynamically generated for supported carriers.
- Requests pass through Bright Data's Web Unlocker endpoint with exponential backoff on 429 / 5xx responses.
- **Testing Safety**: The entire unit and API test suite runs with mock clients. No live HTTP requests are made during testing or CI builds unless credentials are explicitly provided.

---

## 9. Continuous Integration & Automation

The GitHub Actions workflow (`.github/workflows/crawl.yml`) executes on:
- Every push to `main`
- Every pull request to `main`
- Periodic schedule (every 6 hours)
- Manual workflow dispatch

The workflow runs the full test suite and executes the active parcel crawler using configured repository secrets (`BRIGHTDATA_API_KEY`, `BRIGHTDATA_ZONE`).

---

## 10. Known Limitations

- **Carrier Parsing Variations**: Raw HTML scraping fallback returns minimal status if carrier tracking page layout changes without API structured output.
- **Single-Node SQLite vs. Cloud libSQL**: Local development uses standard SQLite file storage; production can use managed Turso/libSQL for distributed edge queries.
