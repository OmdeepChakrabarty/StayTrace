"""
Ocean Carrier Source Adapters and Registry for StayTrace.
Encapsulates official tracking URL strategies for major ocean container shipping lines.
Extensible, modular, zero hardcoded secrets, no Google search fallback.
"""

from __future__ import annotations

import abc
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Type


class UnsupportedOceanCarrierError(ValueError):
    """Raised when an ocean carrier is unrecognized or lacks an official source adapter."""
    pass


class OceanSourceAdapter(abc.ABC):
    """Abstract base class for official ocean carrier tracking source adapters."""

    carrier_id: str
    display_name: str
    supported_prefixes: Tuple[str, ...]
    # Carriers whose official source requires a real session-based browser flow
    # (CSRF token + cookie bound form POST) instead of a stateless page fetch.
    requires_browser: bool = False
    # Carriers whose stateless page fetch may return only a JavaScript shell;
    # when normal extraction fails on such a source, the service escalates to
    # the Scraping Browser session using the adapter's declared plan.
    browser_fallback: bool = False

    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    def build_tracking_url(self, container_number: str) -> str:
        """Construct the official carrier tracking URL for a given container number."""
        pass

    def get_browser_plan(self, container_number: str) -> Optional[Dict[str, Any]]:
        """
        Declarative plan describing how to drive this carrier's official page in
        a Scraping Browser session. Only defined when requires_browser is True.
        """
        return None

    def parse_official_response(self, html: str) -> Optional[Dict[str, Any]]:
        """
        Optionally parse a rendered official page into the canonical raw
        container schema (pre-normalization). Return None to fall back to the
        generic self-healing extraction engine.
        """
        return None

    def get_request_headers(self) -> Dict[str, str]:
        """Optional HTTP headers specific to this carrier."""
        return {}

    def get_request_payload(self, container_number: str) -> Optional[Dict[str, Any]]:
        """Optional POST payload if carrier uses form/API requests."""
        return None


# =====================================================================
# Carrier Source Adapter Implementations
# =====================================================================


def _rendered_reference_success_js(reference: str) -> str:
    """
    Strict browser-session success marker: the searched container reference
    must appear in the *rendered text* of the page (innerText excludes input
    values and URL strings), so anti-bot shells and empty search forms never
    count as tracking results. No data is fabricated when this never fires.
    """
    safe_ref = re.escape(re.sub(r"\s+", "", reference.strip().upper()))
    return f"/{safe_ref}/.test(document.body.innerText)"


class MSCOceanAdapter(OceanSourceAdapter):
    """
    MSC Mediterranean Shipping Company official tracking adapter.

    msc.com/track-a-shipment is an Alpine.js single-page app. Tracking state
    is fetched by an authenticated XHR (POST /api/feature/tools/TrackingInfo)
    and hydrated into the DOM as plain text inside stable containers - there
    is no embedded JSON blob. The SPA ignores a plain ?trackingNumber= query
    parameter (its init() only auto-searches from a base64-encoded "params"
    query, which msc.com/robots.txt disallows), so results can only be
    produced by filling the official search form and submitting it within a
    real browser session.
    """
    # MSC's own date format across the rendered page (dd/MM/yyyy), confirmed
    # in the site bundle (format "dd/MM/yyyy HH:mm"); converted explicitly to
    # ISO 8601 UTC during parsing so day/month are never swapped heuristically.
    _DATE_FORMATS = ("%d/%m/%Y %H:%M", "%d/%m/%Y")

    carrier_id = "msc"
    display_name = "MSC Mediterranean Shipping Company"
    supported_prefixes = ("MSCU", "MEDU")
    # A stateless fetch returns only the application shell without tracking
    # state, so extraction escalates to a real browser session that drives
    # the official search form and renders the results.
    browser_fallback = True

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.msc.com/en/track-a-shipment?trackingNumber={clean}"

    def get_browser_plan(self, container_number: str) -> Dict[str, Any]:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return {
            # Plain URL: robots.txt disallows the "?params=" deep link the SPA
            # would need to auto-search, and a bare ?trackingNumber= query is
            # ignored by the application.
            "start_url": "https://www.msc.com/en/track-a-shipment",
            # Official search form (Alpine): input#trackingNumber with
            # x-model binding, submit button inside .msc-flow-tracking.
            "ready_selector": "#trackingNumber",
            "fill": {"selector": "#trackingNumber", "value": clean},
            "submit": ".msc-flow-tracking .msc-search-autocomplete__search",
            "success_js": _rendered_reference_success_js(clean),
            # Measured on live Scraping Browser sessions: page load fires
            # between ~1s and ~150s (slow third-party resources), while the
            # XHR result renders ~3-10s after submit. max_page_wait bounds
            # the post-load interaction/result window; overall_timeout stays
            # within the service's declared bound for SPA fallback plans,
            # with fetch_carrier_page_via_browser's fresh-session retry
            # covering occasional slow page loads.
            "max_page_wait": 60.0,
            "overall_timeout": 120.0,
        }

    @staticmethod
    def _clean(text: Optional[str]) -> str:
        """
        Collapse whitespace runs (rendered values contain doubles like
        'City,  CC') and drop leftover empty location-code parentheses -
        msc.com renders literal '()' spans around PortOfLoad/PodLocationCode
        even when the code itself is absent.
        """
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        cleaned = re.sub(r"\(\s*\)", "", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip(" ,")

    def _parse_msc_date(self, raw: Optional[str]) -> Optional[str]:
        """Convert MSC's dd/MM/yyyy [HH:MM] rendering into ISO 8601 UTC."""
        cleaned = self._clean(raw)
        if not cleaned:
            return None
        for fmt in self._DATE_FORMATS:
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
        return None

    def parse_official_response(self, html: str) -> Optional[Dict[str, Any]]:
        """
        Parse MSC's rendered track-a-shipment page into the canonical raw
        container schema. The SPA hydrates values as plain text inside stable
        containers:

          .msc-flow-tracking__details-heading / __details-value  shipment facts
          .msc-flow-tracking__data (.data-heading / .data-value) container bar
          .msc-flow-tracking__step                               event timeline

        Returns None when no rendered tracking results exist (application
        shell or a "No results found" response) so callers fail safely and
        never fabricate data.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:  # pragma: no cover - bs4 is a hard repo dependency
            return None

        soup = BeautifulSoup(html or "", "html.parser")
        if not soup.select_one(".msc-flow-tracking__result"):
            return None

        facts: Dict[str, str] = {}
        for heading in soup.select(".msc-flow-tracking__details-heading"):
            value_el = heading.find_next_sibling(class_="msc-flow-tracking__details-value")
            if value_el is None:
                continue
            key = re.sub(r"[\s:*]+$", "", self._clean(heading.get_text())).lower()
            facts[key] = self._clean(value_el.get_text())

        container_bar: Dict[str, str] = {}
        for block in soup.select(".msc-flow-tracking__data"):
            head_el = block.select_one(".data-heading")
            val_el = block.select_one(".data-value")
            if head_el is None or val_el is None:
                continue
            key = self._clean(head_el.get_text()).lower()
            value = self._clean(val_el.get_text())
            if value:
                container_bar.setdefault(key, value)

        events: List[Dict[str, Any]] = []
        seen: Set[Tuple[Optional[str], Optional[str], Optional[str]]] = set()
        for step in soup.select(".msc-flow-tracking__step"):
            classes = " ".join(step.get("class") or [])
            if "msc-flow-tracking__step--intermediate" in classes:
                continue
            date_el = step.select_one(".msc-flow-tracking__cell--two .data-value")
            loc_el = step.select_one(".msc-flow-tracking__cell--three .data-value")
            desc_el = step.select_one(".msc-flow-tracking__cell--four .data-value")
            timestamp = self._parse_msc_date(date_el.get_text() if date_el else "")
            # Rows without a rendered date are unhydrated templates - skip.
            if not timestamp:
                continue
            location = self._clean(loc_el.get_text()) if loc_el else ""
            description = self._clean(desc_el.get_text()) if desc_el else ""
            signature = (timestamp, description, location)
            if signature in seen:
                continue
            seen.add(signature)
            events.append(
                {
                    "timestamp": timestamp,
                    "status": description or None,
                    "description": description or None,
                    "location": location,
                    "source": "carrier",
                }
            )
        # DOM lists newest-first; emit chronological ascending order.
        events.sort(key=lambda ev: ev["timestamp"] or "")

        container_number = (
            facts.get("container number")
            or container_bar.get("container")
            or None
        )
        if not container_number and not events:
            return None

        origin_port = facts.get("port of load") or facts.get("shipped from") or None
        destination_port = (
            facts.get("port of discharge") or facts.get("shipped to") or None
        )
        # The container bar's "Latest Move" is the most recent activity;
        # prefer the newest timeline event description when present.
        status = (events[-1].get("description") if events else None) or container_bar.get("latest move")

        return {
            "container_number": container_number,
            "tracking_number": container_number,
            "shipping_line": self.carrier_id,
            "bill_of_lading_number": facts.get("bill of lading") or None,
            "status": status,
            "origin_port": origin_port,
            "destination_port": destination_port,
            "estimated_arrival": self._parse_msc_date(facts.get("pod eta")),
            "events": events,
        }


class MaerskOceanAdapter(OceanSourceAdapter):
    """
    Maersk Line official tracking adapter.

    maersk.com/tracking is a Vue single-page app built on Lit web components
    (mc-input / mc-button). Results exist ONLY as client-side rendered DOM -
    there is no embedded JSON blob and no server-rendered tracking state.
    robots.txt allows exactly 'Allow: /tracking/$' while 'Disallow:
    /tracking/*' forbids every deep link (/tracking/<REF>), so direct
    navigation to a reference URL is refused by Bright Data and stateless
    Web Unlocker fetches are rejected outright. Tracking can therefore only
    be produced by loading the allowed bare search page and driving the
    official search form within one browser session; the SPA then routes
    client-side to /tracking/<REF> and hydrates the results.
    """
    # Maersk renders milestone dates as local port times in 'DD Mon YYYY
    # HH:MM' format (the page states: "All times are given in local time");
    # converted explicitly to ISO 8601 UTC during parsing so day/month can
    # never be swapped heuristically.
    _DATE_FORMATS = ("%d %b %Y %H:%M", "%d %b %Y")

    carrier_id = "maersk"
    display_name = "Maersk Line"
    supported_prefixes = ("MAEU", "MSKU", "MRKU", "PONU")
    # A stateless fetch returns an error string (robots/KYC refusal) or the
    # application shell without tracking state, so extraction escalates to a
    # real browser session that drives the official search form.
    browser_fallback = True

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.maersk.com/tracking/{clean}"

    def get_browser_plan(self, container_number: str) -> Dict[str, Any]:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return {
            # Bare search page only - the ONLY robots-allowed tracking route
            # ('Allow: /tracking/$'); deep links match 'Disallow: /tracking/*'
            # and are refused by the Scraping Browser.
            "start_url": "https://www.maersk.com/tracking/",
            # Official search form (Lit web components): ready/fill target
            # differ deliberately. The visible form control is the mc-input
            # HOST (#track-input); its light-DOM <input> child is the real
            # HTMLInputElement the native value setter can fill, after which
            # the component syncs host/shadow state and the Vue app sees it.
            "ready_selector": "#track-input",
            "fill": {"selector": "#track-input input", "value": clean},
            "submit": 'mc-button[data-test="track-button"]',
            # Success strictly requires the searched reference in rendered
            # text: input values, <title>, and analytics URLs never appear in
            # body.innerText, so shells and not-found pages never pass.
            "success_js": _rendered_reference_success_js(clean),
            # Measured on live Scraping Browser sessions: page load fires
            # between ~4s and ~41s (slow third-party resources), while the
            # hydrated result timeline renders within ~10s of submitting the
            # official form. max_page_wait bounds both the post-load ready
            # window and the post-submit result window; overall_timeout stays
            # within the service's declared bound for SPA fallback plans,
            # with fetch_carrier_page_via_browser's fresh-session retry
            # covering occasional slow loads.
            "max_page_wait": 60.0,
            "overall_timeout": 120.0,
        }

    @staticmethod
    def _clean(text: Optional[str]) -> str:
        """Collapse whitespace runs left by the web-component rendering."""
        return re.sub(r"\s+", " ", text or "").strip()

    def _parse_maersk_date(self, raw: Optional[str]) -> Optional[str]:
        """Convert Maersk's 'DD Mon YYYY [HH:MM]' rendering into ISO 8601 UTC."""
        cleaned = self._clean(raw)
        if not cleaned:
            return None
        for fmt in self._DATE_FORMATS:
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
        return None

    def parse_official_response(self, html: str) -> Optional[Dict[str, Any]]:
        """
        Parse Maersk's rendered tracking page into the canonical raw container
        schema. The SPA hydrates values as plain DOM marked with stable
        data-test attributes:

          [data-test="search-summary-ocean"]      shipment facts (doc/ports)
          [data-test^="transport-plan-item"]      event timeline rows
            [data-test="location-name"]           row port + terminal
            [data-test="milestone"]               row description + date
              [data-test="milestone-date"]        'DD Mon YYYY HH:MM'

        Returns None when no rendered tracking results exist (application
        shell, cookie wall, or the carrier's 'No results found' response) so
        callers fail safely and never fabricate data.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:  # pragma: no cover - bs4 is a hard repo dependency
            return None

        soup = BeautifulSoup(html or "", "html.parser")
        doc_value = soup.select_one('[data-test="transport-doc-value"]')
        items = soup.select('li[data-test^="transport-plan-item"]')
        if doc_value is None and not items:
            return None

        container_number = self._clean(doc_value.get_text()) if doc_value else None
        if not container_number:
            header = soup.select_one("header[data-test^='container-header-']")
            if header is not None:
                candidate = self._clean(
                    (header.get("data-test") or "").replace("container-header-", "")
                )
                container_number = candidate or None

        origin_port = dest_port = None
        summary = soup.select_one('[data-test="search-summary-ocean"]')
        if summary is not None:
            origin_el = summary.select_one('[data-test="track-from-value"]')
            dest_el = summary.select_one('[data-test="track-to-value"]')
            origin_port = self._clean(origin_el.get_text()) if origin_el else None
            dest_port = self._clean(dest_el.get_text()) if dest_el else None

        vessel_re = re.compile(r"\(([^()]+?)\s*/\s*([A-Za-z0-9]+)\)\s*$")

        events: List[Dict[str, Any]] = []
        seen: Set[Tuple[Optional[str], Optional[str], Optional[str]]] = set()
        for item in items:
            date_el = item.select_one('[data-test="milestone-date"]')
            timestamp = self._parse_maersk_date(date_el.get_text() if date_el else "")
            # Rows without a rendered date are unhydrated templates - skip.
            if not timestamp:
                continue
            milestone = item.select_one('[data-test="milestone"]')
            description = ""
            if milestone is not None:
                date_text = self._clean(date_el.get_text())
                description = self._clean(
                    self._clean(milestone.get_text()).replace(date_text, "")
                )
            location = ""
            loc_el = item.select_one('[data-test="location-name"]')
            if loc_el is not None:
                # 'ROSARIO<br>ROSARIO PORT TERMINAL' renders as two strings;
                # join them explicitly so the port and terminal stay separated.
                location = self._clean(loc_el.get_text(" ", strip=True))

            vessel = voyage = None
            if description:
                vm = vessel_re.search(description)
                if vm:
                    vessel, voyage = vm.group(1).strip(), vm.group(2)

            signature = (timestamp, description, location)
            if signature in seen:
                continue
            seen.add(signature)
            events.append(
                {
                    "timestamp": timestamp,
                    "status": description or None,
                    "description": description or None,
                    "location": location,
                    "vessel": vessel,
                    "voyage": voyage,
                    "source": "carrier",
                }
            )
        # DOM lists oldest-first already; emit deterministic chronological order.
        events.sort(key=lambda ev: ev["timestamp"] or "")

        if not container_number and not events:
            return None

        latest_vessel_event = next(
            (ev for ev in reversed(events) if ev.get("vessel")), None
        )
        # The newest timeline move is the current shipment status.
        status = (events[-1].get("description") if events else None) or None

        estimated_arrival = None
        eta_el = soup.select_one('[data-test="container-eta"]')
        if eta_el is not None:
            estimated_arrival = self._parse_maersk_date(eta_el.get_text())

        return {
            "container_number": container_number,
            "tracking_number": container_number,
            "shipping_line": self.carrier_id,
            "status": status,
            "vessel_name": (latest_vessel_event or {}).get("vessel"),
            "voyage_number": (latest_vessel_event or {}).get("voyage"),
            "origin_port": origin_port,
            "destination_port": dest_port,
            "estimated_arrival": estimated_arrival,
            "events": events,
        }


class CMACGMOceanAdapter(OceanSourceAdapter):
    """
    CMA CGM Group (including APL, ANL) official tracking adapter.

    The official search page serves results only after a session-bound form
    POST (anti-forgery token + cookies), so it requires a Scraping Browser
    session: GET the page, fill the reference field, submit within the same
    session, then extract the rendered result HTML.
    """
    carrier_id = "cma_cgm"
    display_name = "CMA CGM Group"
    supported_prefixes = ("CMAU", "CGMU", "APLU", "ANLU")
    requires_browser = True

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.cma-cgm.com/ebusiness/tracking/search?SearchBy=Container&Reference={clean}"

    def get_browser_plan(self, container_number: str) -> Dict[str, Any]:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        # The official page embeds results server-side as:
        #   options.containerReference = '<REF>';
        # Matching that rendered state avoids false positives from URL query
        # strings or anti-bot interstitials echoing the searched reference.
        safe_ref = re.escape(clean)
        return {
            "start_url": self.build_tracking_url(clean),
            # Official search form: <form action="/ebusiness/tracking/search" method="post">
            "ready_selector": "#Reference",
            "fill": {"selector": "#Reference", "value": clean},
            "submit": "#btnTracking",
            "success_js": (
                "/containerReference\\s*=\\s*'" + safe_ref + "'/"
                ".test(document.documentElement.outerHTML)"
            ),
            # Bounded so a hanging carrier page can never stall the request
            # indefinitely, but generous enough for slow anti-bot resolution
            # (this window is what makes the verified CMA CGM path succeed);
            # the service retries once with a fresh session.
            "max_page_wait": 90.0,
            "overall_timeout": 300.0,
        }

    def parse_official_response(self, html: str) -> Optional[Dict[str, Any]]:
        """
        Parse CMA CGM's server-embedded tracking state (options.responseData)
        into the canonical raw container schema. The official page injects the
        full structured result as JSON inside an inline script.
        """
        match = re.search(r"options\.responseData\s*=\s*'(.*?)'\s*;", html, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
        except (ValueError, TypeError):
            return None

        if not isinstance(data, dict):
            return None
        if data.get("NotFoundContainer") or not data.get("ContainerReference"):
            return None

        moves: List[Dict[str, Any]] = []
        for key in ("PastMoves", "CurrentMoves", "ProvisionalMoves"):
            for move in data.get(key) or []:
                if isinstance(move, dict):
                    moves.append(move)

        def _first_vessel_move() -> Optional[Dict[str, Any]]:
            for move in moves:
                if move.get("Vessel"):
                    return move
            return None

        vessel_move = _first_vessel_move()
        current_move = (data.get("CurrentMoves") or [{}])[0] if data.get("CurrentMoves") else {}

        events = [
            {
                "timestamp": move.get("Date"),
                "status": move.get("StatusDescription"),
                "description": move.get("StatusDescription"),
                "location": move.get("Location"),
                "location_code": move.get("LocationCode"),
                "vessel": move.get("Vessel") or None,
                "voyage": move.get("Voyage") or None,
                "source": "carrier",
            }
            for move in moves
        ]

        parsed: Dict[str, Any] = {
            "container_number": data.get("ContainerReference"),
            "tracking_number": data.get("ContainerReference"),
            "shipping_line": self.carrier_id,
            "status": (current_move or {}).get("StatusDescription")
            or (moves[-1].get("StatusDescription") if moves else None),
            "vessel_name": (vessel_move or {}).get("Vessel"),
            "voyage_number": (vessel_move or {}).get("Voyage"),
            "origin_port": data.get("PlaceOfLoading") or data.get("POL"),
            "origin_port_code": data.get("POL") or None,
            "destination_port": data.get("LastDischargePort") or data.get("POD"),
            "destination_port_code": data.get("POD") or None,
            "estimated_departure": data.get("POLDate"),
            "estimated_arrival": data.get("EstimatedTimeOfArrival") or data.get("PODDate"),
            "events": events,
        }
        return parsed


class COSCOOceanAdapter(OceanSourceAdapter):
    """COSCO Shipping Lines official tracking adapter."""
    carrier_id = "cosco"
    display_name = "COSCO Shipping Lines"
    supported_prefixes = ("COSU", "CCLU", "CBHU")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://lines.coscoshipping.com/ebusiness/cargoTracking?searchType=CONTAINER&trackingNo={clean}"


class HapagLloydOceanAdapter(OceanSourceAdapter):
    """Hapag-Lloyd official tracking adapter."""
    carrier_id = "hapag_lloyd"
    display_name = "Hapag-Lloyd"
    supported_prefixes = ("HLCU", "HLXU", "HAMU", "UASC")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.hapag-lloyd.com/en/online-business/track/track-by-container-solution.html?container={clean}"


class ONEOceanAdapter(OceanSourceAdapter):
    """Ocean Network Express (ONE) official tracking adapter."""
    carrier_id = "one"
    display_name = "Ocean Network Express"
    supported_prefixes = ("ONEU", "NYKU", "MOLU", "KKFU")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://ecomm.one-line.com/one-ecom/manage-shipment/cargo-tracking?type=cntr&no={clean}"


class EvergreenOceanAdapter(OceanSourceAdapter):
    """Evergreen Marine official tracking adapter."""
    carrier_id = "evergreen"
    display_name = "Evergreen Line"
    supported_prefixes = ("EGLV", "EGHU", "EMCU", "EISU")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.shipmentlink.com/servlet/TTrk_Tracking?bkno=&cono={clean}"


class ZIMOceanAdapter(OceanSourceAdapter):
    """ZIM Integrated Shipping official tracking adapter."""
    carrier_id = "zim"
    display_name = "ZIM Integrated Shipping"
    supported_prefixes = ("ZIMU", "ZCSU")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.zim.com/tools/track-a-shipment?cons={clean}"


class YangMingOceanAdapter(OceanSourceAdapter):
    """Yang Ming Marine Transport official tracking adapter."""
    carrier_id = "yang_ming"
    display_name = "Yang Ming Marine"
    supported_prefixes = ("YMLU",)

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.yangming.com/e-service/track_trace/track_trace_cargo_tracking.aspx?type=cntr&num={clean}"


class HMMOceanAdapter(OceanSourceAdapter):
    """HMM (Hyundai Merchant Marine) official tracking adapter."""
    carrier_id = "hmm"
    display_name = "HMM (Hyundai Merchant Marine)"
    supported_prefixes = ("HMMU", "HDMU")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.hmm21.com/cms/business/ebusiness/trackTrace/trackTrace/index.jsp?type=1&number={clean}"


# =====================================================================
# Ocean Source Registry
# =====================================================================

class OceanSourceRegistry:
    """Registry maintaining active ocean carrier source adapters."""

    def __init__(self) -> None:
        self._adapters_by_id: Dict[str, OceanSourceAdapter] = {}
        self._adapters_by_prefix: Dict[str, OceanSourceAdapter] = {}
        self._register_default_adapters()

    def register_adapter(self, adapter_cls: Type[OceanSourceAdapter]) -> None:
        """Register a new ocean source adapter class."""
        adapter = adapter_cls()
        self._adapters_by_id[adapter.carrier_id] = adapter
        for prefix in adapter.supported_prefixes:
            self._adapters_by_prefix[prefix.upper()] = adapter

    def _register_default_adapters(self) -> None:
        self.register_adapter(MSCOceanAdapter)
        self.register_adapter(MaerskOceanAdapter)
        self.register_adapter(CMACGMOceanAdapter)
        self.register_adapter(COSCOOceanAdapter)
        self.register_adapter(HapagLloydOceanAdapter)
        self.register_adapter(ONEOceanAdapter)
        self.register_adapter(EvergreenOceanAdapter)
        self.register_adapter(ZIMOceanAdapter)
        self.register_adapter(YangMingOceanAdapter)
        self.register_adapter(HMMOceanAdapter)

    def get_adapter(self, carrier_or_prefix: str) -> Optional[OceanSourceAdapter]:
        """
        Lookup an ocean carrier adapter by carrier identifier or 4-letter container prefix.
        Example: 'cma_cgm' -> CMACGMOceanAdapter, 'CMAU' -> CMACGMOceanAdapter
        """
        if not carrier_or_prefix or not isinstance(carrier_or_prefix, str):
            return None

        clean = carrier_or_prefix.strip().lower()
        if clean in self._adapters_by_id:
            return self._adapters_by_id[clean]

        clean_prefix = re.sub(r"\s+", "", carrier_or_prefix.strip().upper())
        if len(clean_prefix) >= 4:
            prefix4 = clean_prefix[:4]
            if prefix4 in self._adapters_by_prefix:
                return self._adapters_by_prefix[prefix4]

        return None

    def build_tracking_url(self, carrier_or_prefix: str, container_number: str) -> str:
        """
        Construct official tracking URL for a known ocean carrier.
        Raises UnsupportedOceanCarrierError if carrier has no registered adapter.
        NEVER falls back to Google search.
        """
        adapter = self.get_adapter(carrier_or_prefix)
        if not adapter:
            clean_ident = re.sub(r"\s+", "", container_number.strip().upper())
            adapter = self.get_adapter(clean_ident)

        if not adapter:
            raise UnsupportedOceanCarrierError(
                f"No official ocean tracking source configured for '{carrier_or_prefix}'. "
                f"Supported carriers: {', '.join(sorted(self._adapters_by_id.keys()))}."
            )

        return adapter.build_tracking_url(container_number)

    def list_supported_carriers(self) -> List[Dict[str, Any]]:
        """Return catalog of all configured ocean carrier adapters."""
        return [
            {
                "carrier_id": adapter.carrier_id,
                "display_name": adapter.display_name,
                "supported_prefixes": list(adapter.supported_prefixes),
            }
            for adapter in self._adapters_by_id.values()
        ]


# Singleton instance
default_ocean_registry = OceanSourceRegistry()
