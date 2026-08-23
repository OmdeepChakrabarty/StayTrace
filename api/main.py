"""
StayTrace Application API.
Thin HTTP routing layer delegating business logic to service, pipeline, and self-healing extraction modules.
Supports Ocean / Container Freight tracking as primary mode and Individual Parcel tracking as secondary mode.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
from http import HTTPStatus
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
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
    normalize_shipping_line,
    normalize_container_shipment,
)
from pipeline.resolver import resolve_parcel_update, resolve_container_update
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
    detect_shipping_line,
    detect_shipment_type,
    is_valid_tracking_number,
    is_valid_container_number,
    is_valid_bol_number,
    validate_raw_payload,
    ValidationError,
)
from scraper.ocean_sources import default_ocean_registry
from scraper.browser_session import (
    fetch_carrier_page_via_browser,
    fetch_generic_rendered_carrier_page,
    BrowserSessionError,
)
from scraper.self_healing import (
    extract_with_self_healing,
    ExtractionTelemetry,
    CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger("staytrace.api")


# =====================================================================
# Service Layer (Business Logic)
# =====================================================================

class TrackingService:
    """Coordinates validation, normalization, self-healing extraction, resolution, persistence, and external scraping."""

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
            list_parcels(limit=1, db_path=self.db_path)
            db_status = "connected"
        except Exception as e:
            logger.error("Health check DB query failed: %s", e)
            db_status = "error"

        return {
            "status": "healthy" if db_status == "connected" else "degraded",
            "service": "StayTrace API - Self-Healing Shipment Intelligence",
            "database": db_status,
            "capabilities": ["ocean_container", "parcel", "self_healing_extraction"],
        }

    def track_container(
        self,
        container_number: str,
        shipping_line: Optional[str] = None,
        fetch_live: bool = True,
        raw_payload: Optional[Dict[str, Any]] = None,
        html_payload: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Track or ingest an ocean container shipment.
        Applies ISO 6346 validation, self-healing web extraction, state reconciliation, and persistence.
        """
        norm_container = normalize_tracking_number(container_number)
        if not norm_container:
            raise ValidationError("Container number is required and cannot be empty.")

        # Determine shipping line
        inferred_line = normalize_shipping_line(shipping_line) if shipping_line else detect_shipping_line(norm_container)
        if not inferred_line or inferred_line == "other":
            detected = detect_shipping_line(norm_container)
            inferred_line = detected or inferred_line or "other"

        # Validate container number format
        if not (is_valid_container_number(norm_container, strict_check_digit=False) or is_valid_bol_number(norm_container)):
            raise ValidationError(
                f"Invalid container or B/L number format '{norm_container}'. Expected 4 letters + 7 digits (ISO 6346) or valid B/L reference."
            )

        existing = get_parcel_with_events(norm_container, db_path=self.db_path)
        existing_container = existing if existing else None
        existing_events = existing.get("events", []) if existing else []

        telemetry_dict: Optional[Dict[str, Any]] = None

        if html_payload:
            # Self-healing extraction from provided HTML content
            incoming_container, telemetry = extract_with_self_healing(html_payload, shipment_type="ocean_container")
            telemetry_dict = telemetry.to_dict()
            incoming_container["container_number"] = norm_container
            incoming_container["tracking_number"] = norm_container
            if inferred_line != "other" and incoming_container.get("shipping_line") in (None, "", "other"):
                incoming_container["shipping_line"] = inferred_line
        elif raw_payload:
            # Ingestion from provided structured dictionary
            incoming_container = normalize_container_shipment(raw_payload)
            if not incoming_container.get("container_number"):
                incoming_container["container_number"] = norm_container
                incoming_container["tracking_number"] = norm_container
            if inferred_line != "other" and incoming_container.get("shipping_line") in (None, "", "other"):
                incoming_container["shipping_line"] = inferred_line
        elif fetch_live:
            # Fetch tracking through Bright Data + Self-Healing Extraction.
            # Ocean adapters flagged requires_browser (e.g. CMA CGM) need a real
            # session-based browser flow against their official page; all other
            # sources use the stateless Web Unlocker path.
            ocean_adapter = (
                default_ocean_registry.get_adapter(inferred_line)
                or default_ocean_registry.get_adapter(norm_container)
            )
            try:
                if ocean_adapter is not None and ocean_adapter.requires_browser:
                    page_html = fetch_carrier_page_via_browser(ocean_adapter, norm_container)
                    # Structured parsing from the adapter when the official page
                    # embeds machine-readable state; self-healing as fallback.
                    parsed = ocean_adapter.parse_official_response(page_html)
                else:
                    target_url = self.client.build_tracking_url(inferred_line, norm_container)
                    response = self.client.unlock_url(target_url, format="raw")
                    page_html = response.text
                    parsed = None

                if parsed is not None:
                    incoming_container = normalize_container_shipment(parsed)
                    telemetry = ExtractionTelemetry()
                    telemetry.extraction_status = "normal"
                    telemetry.original_strategy_status = "passed"
                    telemetry.validation_result = "passed"
                    telemetry.confidence = 1.0
                    telemetry.diagnostic_log.append(
                        f"Parsed structured tracking state from official {inferred_line} source."
                    )
                else:
                    # Run self-healing extraction on the carrier webpage
                    incoming_container, telemetry = extract_with_self_healing(page_html, shipment_type="ocean_container")

                    # Escalate to a bounded Scraping Browser session when the
                    # stateless source returned no usable tracking state (e.g.
                    # JavaScript application shells). Carriers with a specific
                    # plan use it; all other registered carriers get the
                    # generic rendered-form fallback against their official
                    # URL. Carriers that already ran a browser session upfront
                    # are not retried. If the rendered page still contains no
                    # genuine results, the session fails safely - nothing is
                    # fabricated.
                    if (
                        telemetry.extraction_status == "failed"
                        and ocean_adapter is not None
                        and not ocean_adapter.requires_browser
                    ):
                        telemetry.diagnostic_log.append(
                            "Stateless source yielded no usable tracking state; "
                            "escalating to Scraping Browser session."
                        )
                        if ocean_adapter.get_browser_plan(norm_container):
                            rendered_html = fetch_carrier_page_via_browser(ocean_adapter, norm_container)
                        else:
                            rendered_html = fetch_generic_rendered_carrier_page(
                                ocean_adapter.build_tracking_url(norm_container),
                                norm_container,
                            )
                        bparsed = ocean_adapter.parse_official_response(rendered_html)
                        bparsed = ocean_adapter.parse_official_response(rendered_html)
                        if bparsed is not None:
                            incoming_container = normalize_container_shipment(bparsed)
                            escalation_note = telemetry.diagnostic_log[-1] if telemetry.diagnostic_log else ""
                            telemetry = ExtractionTelemetry()
                            telemetry.extraction_status = "normal"
                            telemetry.original_strategy_status = "passed"
                            telemetry.validation_result = "passed"
                            telemetry.confidence = 1.0
                            if escalation_note:
                                telemetry.diagnostic_log.append(escalation_note)
                            telemetry.diagnostic_log.append(
                                f"Parsed structured tracking state via {inferred_line} browser session."
                            )
                        else:
                            incoming_container, telemetry = extract_with_self_healing(
                                rendered_html, shipment_type="ocean_container"
                            )
                            telemetry.diagnostic_log.insert(
                                0,
                                "Stateless source yielded no usable tracking state; "
                                "escalating to Scraping Browser session.",
                            )

                telemetry_dict = telemetry.to_dict()
                incoming_container["container_number"] = norm_container
                incoming_container["tracking_number"] = norm_container
                if inferred_line != "other" and incoming_container.get("shipping_line") in (None, "", "other"):
                    incoming_container["shipping_line"] = inferred_line

                log_scrape(norm_container, inferred_line, "success", db_path=self.db_path)
            except BrowserSessionError as e:
                log_scrape(norm_container, inferred_line, "failed", error_message=str(e), db_path=self.db_path)
                raise BrightDataError(str(e))
            except BrightDataNotFoundError as e:
                log_scrape(norm_container, inferred_line, "not_found", error_message=str(e), db_path=self.db_path)
                raise
            except (BrightDataRateLimitError, BrightDataAuthError, BrightDataTimeoutError, BrightDataNetworkError, BrightDataError) as e:
                log_scrape(norm_container, inferred_line, "failed", error_message=str(e), db_path=self.db_path)
                raise
        else:
            if existing:
                return existing, HTTPStatus.OK
            incoming_container = {
                "shipment_type": "ocean_container",
                "container_number": norm_container,
                "tracking_number": norm_container,
                "shipping_line": inferred_line,
                "carrier": inferred_line,
                "status": "unknown",
                "events": [],
            }

        # Resolve state update
        resolved_container, resolved_events, _ = resolve_container_update(
            existing_container=existing_container,
            incoming_container=incoming_container,
            existing_events=existing_events,
            incoming_events=incoming_container.get("events", []),
        )

        # Attach telemetry
        if telemetry_dict:
            resolved_container["healing_status"] = telemetry_dict.get("extraction_status")
            resolved_container["healing_confidence"] = telemetry_dict.get("confidence")
            resolved_container["healing_details"] = json.dumps(telemetry_dict)

        # Persist
        save_parcel_with_events(
            parcel_data=resolved_container,
            events=resolved_events,
            db_path=self.db_path,
        )

        final_container = get_parcel_with_events(norm_container, db_path=self.db_path)
        if final_container:
            final_container["container_number"] = final_container.get("container_number") or norm_container
        status_code = HTTPStatus.CREATED if not existing else HTTPStatus.OK
        return final_container or resolved_container, status_code

    def _parcel_rendered_browser_fallback(
        self,
        carrier: str,
        tracking_number: str,
        current_parcel: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Bounded rendered-browser fallback for parcel tracking. Fetches the
        carrier's official page in a Scraping Browser session, runs the
        self-healing parser on the rendered HTML, and returns a normalized
        parcel only when genuine usable tracking state was extracted.
        Raises BrightDataError otherwise - never fabricates state.
        """
        try:
            official_url = self.client.build_tracking_url(carrier, tracking_number)
            rendered_html = fetch_generic_rendered_carrier_page(official_url, tracking_number)
        except BrowserSessionError as e:
            log_scrape(tracking_number, carrier, "failed", error_message=str(e), db_path=self.db_path)
            raise BrightDataError(f"SOURCE UNAVAILABLE — {e}")
        except ValidationError:
            raise BrightDataError(
                f"SOURCE UNAVAILABLE — no official tracking source configured for carrier '{carrier}'."
            )

        extracted, telemetry = extract_with_self_healing(rendered_html, shipment_type="parcel")
        parcel_status = (extracted.get("status") or "").strip().lower()
        usable_state = bool(extracted.get("events")) or parcel_status not in ("", "unknown")

        if telemetry.extraction_status == "failed" or not usable_state:
            log_scrape(tracking_number, carrier, "failed", error_message="rendered page had no usable tracking state", db_path=self.db_path)
            raise BrightDataError(
                "SOURCE UNAVAILABLE — carrier page did not render usable tracking state for this reference."
            )

        merged = dict(extracted)
        merged["tracking_number"] = tracking_number
        merged["carrier"] = current_parcel.get("carrier") or carrier
        return normalize_parcel(merged)

    def track_parcel(
        self,
        tracking_number: str,
        carrier: Optional[str] = None,
        fetch_live: bool = True,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Track or ingest an individual parcel.
        Validates input, fetches tracking data from Bright Data if requested/needed,
        reconciles with existing database history, persists changes, and logs scrapes.
        """
        norm_tracking = normalize_tracking_number(tracking_number)
        if not norm_tracking:
            raise ValidationError("Tracking number is required and cannot be empty.")

        # If identifier looks like an ISO 6346 container number and no carrier specified, delegate to container tracking
        if not carrier and detect_shipment_type(norm_tracking) == "ocean_container":
            return self.track_container(norm_tracking, shipping_line=carrier, fetch_live=fetch_live, raw_payload=raw_payload)

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
            is_valid, errors = validate_raw_payload(raw_payload)
            if not is_valid:
                raise ValidationError(f"Invalid payload: {'; '.join(errors)}")
            incoming_parcel = normalize_parcel(raw_payload)
            if not incoming_parcel.get("tracking_number"):
                incoming_parcel["tracking_number"] = norm_tracking
        elif fetch_live:
            try:
                incoming_parcel = self.client.fetch_tracking(inferred_carrier, norm_tracking)
                if not incoming_parcel.get("tracking_number"):
                    incoming_parcel["tracking_number"] = norm_tracking

                # A stateless response with no events and no known status is an
                # extraction failure (typically a JS shell), not tracking data.
                parcel_status = (incoming_parcel.get("status") or "").strip().lower()
                usable_state = bool(incoming_parcel.get("events")) or parcel_status not in ("", "unknown")

                if not usable_state:
                    incoming_parcel = self._parcel_rendered_browser_fallback(
                        inferred_carrier, norm_tracking, incoming_parcel
                    )

                log_scrape(norm_tracking, inferred_carrier, "success", db_path=self.db_path)
            except BrightDataNotFoundError as e:
                log_scrape(norm_tracking, inferred_carrier, "not_found", error_message=str(e), db_path=self.db_path)
                raise
            except (BrightDataRateLimitError, BrightDataAuthError, BrightDataTimeoutError, BrightDataNetworkError, BrightDataError) as e:
                log_scrape(norm_tracking, inferred_carrier, "failed", error_message=str(e), db_path=self.db_path)
                raise
        else:
            if existing:
                return existing, HTTPStatus.OK
            incoming_parcel = {
                "shipment_type": "parcel",
                "tracking_number": norm_tracking,
                "carrier": inferred_carrier,
                "status": "unknown",
                "events": [],
            }

        resolved_parcel, resolved_events, _ = resolve_parcel_update(
            existing_parcel=existing_parcel,
            incoming_parcel=incoming_parcel,
            existing_events=existing_events,
            incoming_events=incoming_parcel.get("events", []),
        )

        save_parcel_with_events(
            parcel_data=resolved_parcel,
            events=resolved_events,
            db_path=self.db_path,
        )

        final_parcel = get_parcel_with_events(norm_tracking, db_path=self.db_path)
        status_code = HTTPStatus.CREATED if not existing else HTTPStatus.OK
        return final_parcel or resolved_parcel, status_code

    def track_shipment(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """Unified tracking route supporting ocean container and parcel shipments."""
        tracking_number = (
            payload.get("container_number")
            or payload.get("tracking_number")
            or payload.get("trackingNumber")
            or payload.get("tracking_code")
            or payload.get("id")
        )
        if not tracking_number:
            raise ValidationError("Tracking identifier is required.")

        shipment_type = payload.get("shipment_type")
        if not shipment_type:
            shipment_type = detect_shipment_type(str(tracking_number))

        carrier = payload.get("shipping_line") or payload.get("carrier") or payload.get("courier")
        fetch_live = payload.get("fetch_live", True)
        html_payload = payload.get("html") or payload.get("html_payload")

        # Check if full raw payload was submitted directly with events
        raw_payload = payload if ("events" in payload or "checkpoints" in payload or "destination_port" in payload or "recipient_address" in payload) else None
        if raw_payload or html_payload:
            fetch_live = False

        if shipment_type == "ocean_container":
            return self.track_container(
                container_number=str(tracking_number),
                shipping_line=str(carrier) if carrier else None,
                fetch_live=fetch_live,
                raw_payload=raw_payload,
                html_payload=html_payload,
            )
        else:
            return self.track_parcel(
                tracking_number=str(tracking_number),
                carrier=str(carrier) if carrier else None,
                fetch_live=fetch_live,
                raw_payload=raw_payload,
            )

    def get_parcel(self, tracking_number: str) -> Optional[Dict[str, Any]]:
        """Retrieve shipment with full event history."""
        norm_tracking = normalize_tracking_number(tracking_number)
        return get_parcel_with_events(norm_tracking, db_path=self.db_path)

    def list_parcels(
        self,
        carrier: Optional[str] = None,
        status: Optional[str] = None,
        shipment_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List shipments with filtering and pagination."""
        return list_parcels(
            carrier=carrier,
            status=status,
            shipment_type=shipment_type,
            limit=limit,
            offset=offset,
            db_path=self.db_path,
        )

    def delete_parcel(self, tracking_number: str) -> bool:
        """Delete shipment and its checkpoints."""
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

    def run_self_healing_demo(self, scenario: str = "redesigned", custom_html: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute controlled self-healing extraction benchmark.
        Scenarios: 'original', 'redesigned', 'ambiguous', 'custom'
        """
        fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures" / "ocean"
        
        if custom_html:
            html = custom_html
            scenario_name = "custom"
            description = "Custom User-Provided HTML Simulation"
        elif scenario == "original":
            fixture_path = fixtures_dir / "original_page.html"
            html = fixture_path.read_text(encoding="utf-8") if fixture_path.exists() else ""
            scenario_name = "original"
            description = "Original Carrier Page Layout (Normal Extraction Baseline)"
        elif scenario == "ambiguous":
            fixture_path = fixtures_dir / "ambiguous_page.html"
            html = fixture_path.read_text(encoding="utf-8") if fixture_path.exists() else ""
            scenario_name = "ambiguous"
            description = "Corrupted/Conflicting Evidence Page (Safe Rejection Benchmark)"
        else:  # redesigned
            fixture_path = fixtures_dir / "redesigned_page.html"
            html = fixture_path.read_text(encoding="utf-8") if fixture_path.exists() else ""
            scenario_name = "redesigned"
            description = "Simulated Website Redesign (Self-Healing Recovery Benchmark)"

        if not html:
            raise ValidationError(f"Fixture for scenario '{scenario}' not found.")

        extracted_data, telemetry = extract_with_self_healing(html, shipment_type="ocean_container")

        return {
            "demo_scenario": scenario_name,
            "description": description,
            "telemetry": telemetry.to_dict(),
            "extracted_shipment": extracted_data,
            "html_snippet": html[:500] + ("..." if len(html) > 500 else ""),
        }


# =====================================================================
# HTTP Request Handler & Server
# =====================================================================

class StayTraceAPIHandler(BaseHTTPRequestHandler):
    """HTTP Request handler for StayTrace REST API."""

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

            # Self-Healing Demo benchmark runner via GET
            if path in ("/demo/self-healing", "/api/demo/self-healing", "/demo/heal", "/api/demo/heal"):
                scenario = params.get("scenario", "redesigned")
                demo_result = self.service.run_self_healing_demo(scenario=scenario)
                self._send_json(demo_result, HTTPStatus.OK)
                return

            # List containers: /api/containers or /containers
            if path in ("/containers", "/api/containers"):
                carrier = params.get("shipping_line") or params.get("carrier")
                status = params.get("status")
                limit = int(params.get("limit", 100))
                offset = int(params.get("offset", 0))
                containers = self.service.list_parcels(
                    carrier=carrier,
                    status=status,
                    shipment_type="ocean_container",
                    limit=limit,
                    offset=offset,
                )
                self._send_json({"containers": containers, "total": len(containers)}, HTTPStatus.OK)
                return

            # List parcels / shipments: /api/parcels
            if path in ("/parcels", "/api/parcels"):
                carrier = params.get("carrier")
                status = params.get("status")
                shipment_type = params.get("shipment_type")
                limit = int(params.get("limit", 100))
                offset = int(params.get("offset", 0))
                parcels = self.service.list_parcels(
                    carrier=carrier,
                    status=status,
                    shipment_type=shipment_type,
                    limit=limit,
                    offset=offset,
                )
                self._send_json({"parcels": parcels, "total": len(parcels)}, HTTPStatus.OK)
                return

            # Get events for shipment: /api/parcels/{tracking_number}/events or /api/containers/{container_number}/events
            if (path.startswith("/api/parcels/") or path.startswith("/parcels/") or path.startswith("/api/containers/") or path.startswith("/containers/")) and path.endswith("/events"):
                parts = path.strip("/").split("/")
                tracking_number = parts[-2]
                events = self.service.get_events(tracking_number)
                self._send_json({"tracking_number": tracking_number, "events": events}, HTTPStatus.OK)
                return

            # Get single container: /api/containers/{container_number}
            if path.startswith("/api/containers/") or path.startswith("/containers/"):
                container_number = path.strip("/").split("/")[-1]
                container = self.service.get_parcel(container_number)
                if not container:
                    self._send_error(f"Ocean container '{container_number}' not found.", HTTPStatus.NOT_FOUND)
                    return
                self._send_json(container, HTTPStatus.OK)
                return

            # Get single parcel/shipment: /api/parcels/{tracking_number}
            if path.startswith("/api/parcels/") or path.startswith("/parcels/"):
                tracking_number = path.strip("/").split("/")[-1]
                parcel = self.service.get_parcel(tracking_number)
                if not parcel:
                    self._send_error(f"Shipment with tracking number '{tracking_number}' not found.", HTTPStatus.NOT_FOUND)
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

            # Self-Healing Demo benchmark runner
            if path in ("/demo/heal", "/api/demo/heal", "/demo/self-healing", "/api/demo/self-healing"):
                scenario = body.get("scenario", "redesigned")
                custom_html = body.get("html") or body.get("custom_html")
                demo_result = self.service.run_self_healing_demo(scenario=scenario, custom_html=custom_html)
                self._send_json(demo_result, HTTPStatus.OK)
                return

            # Dedicated container tracking endpoint: /api/track/container or /api/containers
            if path in ("/track/container", "/api/track/container", "/containers", "/api/containers"):
                container_number = (
                    body.get("container_number")
                    or body.get("container_no")
                    or body.get("tracking_number")
                )
                if not container_number:
                    self._send_error("Field 'container_number' is required.", HTTPStatus.BAD_REQUEST)
                    return

                shipping_line = body.get("shipping_line") or body.get("carrier")
                fetch_live = body.get("fetch_live", True)
                html_payload = body.get("html") or body.get("html_payload")
                raw_payload = body if ("events" in body or "destination_port" in body or "pol" in body) else None
                if raw_payload or html_payload:
                    fetch_live = False

                container, status_code = self.service.track_container(
                    container_number=str(container_number),
                    shipping_line=str(shipping_line) if shipping_line else None,
                    fetch_live=fetch_live,
                    raw_payload=raw_payload,
                    html_payload=html_payload,
                )
                self._send_json(container, status_code)
                return

            # Unified track endpoint: /api/track or /api/parcels
            if path in ("/track", "/api/track", "/parcels", "/api/parcels"):
                shipment, status_code = self.service.track_shipment(body)
                self._send_json(shipment, status_code)
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

            # Delete shipment: /api/parcels/{tracking_number} or /api/containers/{container_number}
            if path.startswith("/api/parcels/") or path.startswith("/parcels/") or path.startswith("/api/containers/") or path.startswith("/containers/"):
                tracking_number = path.strip("/").split("/")[-1]
                deleted = self.service.delete_parcel(tracking_number)
                if not deleted:
                    self._send_error(f"Shipment with identifier '{tracking_number}' not found.", HTTPStatus.NOT_FOUND)
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
    port = int(os.environ.get("PORT") or os.environ.get("API_PORT", "8000"))
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
