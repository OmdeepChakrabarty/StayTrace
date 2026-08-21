"""
ParcelPulse / StayTrace Application API.
Thin HTTP routing layer delegating business logic to service and pipeline modules.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
from http import HTTPStatus
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional, Tuple

from db.database import (
    init_db,
    get_parcel,
    get_parcel_with_events,
    list_parcels,
    delete_parcel,
    save_parcel_with_events,
    get_events_by_tracking_number,
    log_scrape,
    get_scrape_logs,
)
from pipeline.normalize import (
    normalize_carrier,
    normalize_parcel,
    normalize_tracking_number,
)
from pipeline.resolver import resolve_parcel_update
from scraper.brightdata import (
    BrightDataClient,
    BrightDataError,
    BrightDataAuthError,
    BrightDataRateLimitError,
    BrightDataNotFoundError,
    BrightDataTimeoutError,
    BrightDataNetworkError,
)
from scraper.validator import (
    detect_carrier,
    is_valid_tracking_number,
    validate_raw_payload,
    ValidationError,
)

logger = logging.getLogger("staytrace.api")


# =====================================================================
# Service Layer (Business Logic)
# =====================================================================

class TrackingService:
    """Coordinates validation, normalization, resolution, persistence, and external scraping."""

    def __init__(
        self,
        brightdata_client: Optional[BrightDataClient] = None,
        db_path: Optional[str] = None,
    ):
        self.client = brightdata_client or BrightDataClient()
        self.db_path = db_path

    def health_check(self) -> Dict[str, Any]:
        """Perform system health check."""
        try:
            # Simple read check
            list_parcels(limit=1, db_path=self.db_path)
            db_status = "connected"
        except Exception as e:
            logger.error("Health check DB query failed: %s", e)
            db_status = "error"

        return {
            "status": "healthy" if db_status == "connected" else "degraded",
            "service": "StayTrace ParcelPulse API",
            "database": db_status,
        }

    def track_parcel(
        self,
        tracking_number: str,
        carrier: Optional[str] = None,
        fetch_live: bool = True,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Track or ingest a parcel.
        Validates input, fetches tracking data from Bright Data if requested/needed,
        reconciles with existing database history, persists changes, and logs scrapes.
        """
        norm_tracking = normalize_tracking_number(tracking_number)
        if not norm_tracking:
            raise ValidationError("Tracking number is required and cannot be empty.")

        # Determine carrier
        inferred_carrier = normalize_carrier(carrier) if carrier else detect_carrier(norm_tracking)
        if not inferred_carrier or inferred_carrier == "other":
            detected = detect_carrier(norm_tracking)
            if detected:
                inferred_carrier = detected
            else:
                inferred_carrier = inferred_carrier or "other"

        if inferred_carrier != "other" and not is_valid_tracking_number(inferred_carrier, norm_tracking):
            raise ValidationError(
                f"Invalid tracking number '{norm_tracking}' format for carrier '{inferred_carrier}'."
            )

        existing = get_parcel_with_events(norm_tracking, db_path=self.db_path)
        existing_parcel = existing if existing else None
        existing_events = existing.get("events", []) if existing else []

        if raw_payload:
            # Ingestion from provided payload
            is_valid, errors = validate_raw_payload(raw_payload)
            if not is_valid:
                raise ValidationError(f"Invalid payload: {'; '.join(errors)}")
            incoming_parcel = normalize_parcel(raw_payload)
        elif fetch_live:
            # Fetch tracking via Bright Data client
            try:
                incoming_parcel = self.client.fetch_tracking(inferred_carrier, norm_tracking)
                log_scrape(norm_tracking, inferred_carrier, "success", db_path=self.db_path)
            except BrightDataNotFoundError as e:
                log_scrape(norm_tracking, inferred_carrier, "not_found", error_message=str(e), db_path=self.db_path)
                raise
            except (BrightDataRateLimitError, BrightDataAuthError, BrightDataTimeoutError, BrightDataNetworkError, BrightDataError) as e:
                log_scrape(norm_tracking, inferred_carrier, "failed", error_message=str(e), db_path=self.db_path)
                raise
        else:
            # Return existing or construct stub
            if existing:
                return existing, HTTPStatus.OK
            incoming_parcel = {
                "tracking_number": norm_tracking,
                "carrier": inferred_carrier,
                "status": "unknown",
                "events": [],
            }

        # Resolve state update
        resolved_parcel, resolved_events, _ = resolve_parcel_update(
            existing_parcel=existing_parcel,
            incoming_parcel=incoming_parcel,
            existing_events=existing_events,
            incoming_events=incoming_parcel.get("events", []),
        )

        # Persist
        save_parcel_with_events(
            parcel_data=resolved_parcel,
            events=resolved_events,
            db_path=self.db_path,
        )

        # Fetch fresh complete state
        final_parcel = get_parcel_with_events(norm_tracking, db_path=self.db_path)
        status_code = HTTPStatus.CREATED if not existing else HTTPStatus.OK
        return final_parcel or resolved_parcel, status_code

    def get_parcel(self, tracking_number: str) -> Optional[Dict[str, Any]]:
        """Retrieve parcel with full event history."""
        norm_tracking = normalize_tracking_number(tracking_number)
        return get_parcel_with_events(norm_tracking, db_path=self.db_path)

    def list_parcels(
        self,
        carrier: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List parcels with filtering and pagination."""
        return list_parcels(
            carrier=carrier,
            status=status,
            limit=limit,
            offset=offset,
            db_path=self.db_path,
        )

    def delete_parcel(self, tracking_number: str) -> bool:
        """Delete parcel and its checkpoints."""
        norm_tracking = normalize_tracking_number(tracking_number)
        return delete_parcel(norm_tracking, db_path=self.db_path)

    def get_events(self, tracking_number: str) -> List[Dict[str, Any]]:
        """Get event checkpoints for tracking number."""
        norm_tracking = normalize_tracking_number(tracking_number)
        return get_events_by_tracking_number(norm_tracking, db_path=self.db_path)

    def get_logs(self, tracking_number: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve scraping audit logs."""
        norm_tracking = normalize_tracking_number(tracking_number) if tracking_number else None
        return get_scrape_logs(norm_tracking, limit=limit, db_path=self.db_path)


# =====================================================================
# HTTP Request Handler & Server
# =====================================================================

class StayTraceAPIHandler(BaseHTTPRequestHandler):
    """HTTP Request handler for StayTrace ParcelPulse REST API."""

    service: TrackingService = TrackingService()

    def _set_headers(self, status_code: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.end_headers()

    def _send_json(self, data: Any, status_code: int = 200) -> None:
        self._set_headers(status_code)
        body = json.dumps(data, indent=2, ensure_ascii=False)
        self.wfile.write(body.encode("utf-8"))

    def _send_error(self, message: str, status_code: int = 400, details: Optional[Any] = None) -> None:
        payload: Dict[str, Any] = {"error": message, "status_code": status_code}
        if details is not None:
            payload["details"] = details
        self._send_json(payload, status_code)

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self._set_headers(HTTPStatus.NO_CONTENT)

    def parse_request_body(self) -> Dict[str, Any]:
        """Safely parse JSON request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        try:
            raw_body = self.rfile.read(content_length).decode("utf-8")
            return json.loads(raw_body)
        except json.JSONDecodeError:
            raise ValidationError("Malformed JSON payload in request body.")

    def parse_path_and_query(self) -> Tuple[str, Dict[str, str]]:
        """Parse request path and query parameters."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)
        params = {k: v[0] for k, v in query.items() if v}
        return path, params

    def do_GET(self) -> None:
        """Handle GET requests."""
        try:
            path, params = self.parse_path_and_query()

            # Health check
            if path in ("", "/health", "/api/health"):
                health_data = self.service.health_check()
                self._send_json(health_data, HTTPStatus.OK)
                return

            # List parcels
            if path in ("/parcels", "/api/parcels"):
                carrier = params.get("carrier")
                status = params.get("status")
                limit = int(params.get("limit", 100))
                offset = int(params.get("offset", 0))
                parcels = self.service.list_parcels(carrier=carrier, status=status, limit=limit, offset=offset)
                self._send_json({"parcels": parcels, "total": len(parcels)}, HTTPStatus.OK)
                return

            # Get events for parcel: /api/parcels/{tracking_number}/events
            if (path.startswith("/api/parcels/") or path.startswith("/parcels/")) and path.endswith("/events"):
                parts = path.strip("/").split("/")
                tracking_number = parts[-2]
                events = self.service.get_events(tracking_number)
                self._send_json({"tracking_number": tracking_number, "events": events}, HTTPStatus.OK)
                return

            # Get single parcel: /api/parcels/{tracking_number}
            if path.startswith("/api/parcels/") or path.startswith("/parcels/"):
                tracking_number = path.strip("/").split("/")[-1]
                parcel = self.service.get_parcel(tracking_number)
                if not parcel:
                    self._send_error(f"Parcel with tracking number '{tracking_number}' not found.", HTTPStatus.NOT_FOUND)
                    return
                self._send_json(parcel, HTTPStatus.OK)
                return

            # Get scrape logs: /api/logs or /api/logs/{tracking_number}
            if path in ("/logs", "/api/logs"):
                tracking_number = params.get("tracking_number")
                limit = int(params.get("limit", 50))
                logs = self.service.get_logs(tracking_number=tracking_number, limit=limit)
                self._send_json({"logs": logs, "total": len(logs)}, HTTPStatus.OK)
                return

            if path.startswith("/api/logs/") or path.startswith("/logs/"):
                tracking_number = path.strip("/").split("/")[-1]
                logs = self.service.get_logs(tracking_number=tracking_number)
                self._send_json({"tracking_number": tracking_number, "logs": logs}, HTTPStatus.OK)
                return

            self._send_error(f"Endpoint not found: {path}", HTTPStatus.NOT_FOUND)

        except ValidationError as e:
            self._send_error(str(e), HTTPStatus.BAD_REQUEST)
        except Exception as e:
            logger.exception("Unexpected error in GET request handler")
            self._send_error("Internal server error occurred.", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        """Handle POST requests."""
        try:
            path, _ = self.parse_path_and_query()
            body = self.parse_request_body()

            # Track / ingest parcel: /api/track or /api/parcels
            if path in ("/track", "/api/track", "/parcels", "/api/parcels"):
                tracking_number = (
                    body.get("tracking_number")
                    or body.get("trackingNumber")
                    or body.get("tracking_code")
                )
                if not tracking_number:
                    self._send_error("Field 'tracking_number' is required.", HTTPStatus.BAD_REQUEST)
                    return

                carrier = body.get("carrier") or body.get("courier")
                fetch_live = body.get("fetch_live", True)
                
                # Check if full raw payload was submitted directly with events
                raw_payload = body if ("events" in body or "recipient_address" in body) else None
                if raw_payload:
                    fetch_live = False

                parcel, status_code = self.service.track_parcel(
                    tracking_number=str(tracking_number),
                    carrier=str(carrier) if carrier else None,
                    fetch_live=fetch_live,
                    raw_payload=raw_payload,
                )
                self._send_json(parcel, status_code)
                return

            self._send_error(f"Endpoint not found: {path}", HTTPStatus.NOT_FOUND)

        except ValidationError as e:
            self._send_error(str(e), HTTPStatus.BAD_REQUEST)
        except BrightDataNotFoundError as e:
            self._send_error(f"Tracking information not found: {e}", HTTPStatus.NOT_FOUND)
        except BrightDataRateLimitError:
            self._send_error("External tracking rate limit exceeded. Please retry shortly.", HTTPStatus.TOO_MANY_REQUESTS)
        except BrightDataAuthError:
            self._send_error("External tracking service authentication failed.", HTTPStatus.BAD_GATEWAY)
        except BrightDataTimeoutError:
            self._send_error("External tracking service timed out.", HTTPStatus.GATEWAY_TIMEOUT)
        except (BrightDataNetworkError, BrightDataError) as e:
            self._send_error("Failed to retrieve data from external tracking provider.", HTTPStatus.BAD_GATEWAY)
        except Exception as e:
            logger.exception("Unexpected error in POST request handler")
            self._send_error("Internal server error occurred.", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        """Handle DELETE requests."""
        try:
            path, _ = self.parse_path_and_query()

            # Delete parcel: /api/parcels/{tracking_number}
            if path.startswith("/api/parcels/") or path.startswith("/parcels/"):
                tracking_number = path.strip("/").split("/")[-1]
                deleted = self.service.delete_parcel(tracking_number)
                if not deleted:
                    self._send_error(f"Parcel with tracking number '{tracking_number}' not found.", HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"deleted": True, "tracking_number": tracking_number}, HTTPStatus.OK)
                return

            self._send_error(f"Endpoint not found: {path}", HTTPStatus.NOT_FOUND)

        except Exception as e:
            logger.exception("Unexpected error in DELETE request handler")
            self._send_error("Internal server error occurred.", HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        """Redirect standard request logging to logger."""
        logger.info("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)


def create_app(
    db_path: Optional[str] = None,
    brightdata_client: Optional[BrightDataClient] = None,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> ThreadingHTTPServer:
    """Factory to initialize database and create HTTP server instance."""
    init_db(db_path=db_path)
    
    # Configure custom handler with injected dependencies
    handler_cls = StayTraceAPIHandler
    handler_cls.service = TrackingService(
        brightdata_client=brightdata_client,
        db_path=db_path,
    )
    
    server = ThreadingHTTPServer((host, port), handler_cls)
    return server


def main() -> None:
    """CLI entry point for running the StayTrace API server."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
    )
    
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    db_path = os.environ.get("DATABASE_PATH", "parcels.db")
    
    logger.info("Starting StayTrace API on %s:%d (Database: %s)", host, port, db_path)
    server = create_app(db_path=db_path, host=host, port=port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down StayTrace API server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
