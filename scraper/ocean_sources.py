"""
Ocean Carrier Source Adapters and Registry for StayTrace.
Encapsulates official tracking URL strategies for major ocean container shipping lines.
Extensible, modular, zero hardcoded secrets, no Google search fallback.
"""

from __future__ import annotations

import abc
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Type


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
    """MSC Mediterranean Shipping Company official tracking adapter."""
    carrier_id = "msc"
    display_name = "MSC Mediterranean Shipping Company"
    supported_prefixes = ("MSCU", "MEDU")
    # msc.com is a JavaScript single-page app: a stateless fetch returns the
    # application shell without tracking state, so extraction escalates to a
    # real browser session that renders the results for the queried container.
    browser_fallback = True

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.msc.com/en/track-a-shipment?trackingNumber={clean}"

    def get_browser_plan(self, container_number: str) -> Dict[str, Any]:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return {
            "start_url": self.build_tracking_url(clean),
            # The SPA reads the trackingNumber query parameter and renders the
            # shipment result automatically; no form interaction is required.
            "success_js": _rendered_reference_success_js(clean),
            "max_page_wait": 45.0,
            "overall_timeout": 90.0,
        }


class MaerskOceanAdapter(OceanSourceAdapter):
    """Maersk Line official tracking adapter."""
    carrier_id = "maersk"
    display_name = "Maersk Line"
    supported_prefixes = ("MAEU", "MSKU", "MRKU", "PONU")
    # maersk.com/tracking is an anti-bot protected React application; stateless
    # fetches return a challenge/shell page. Escalate to a real browser session.
    browser_fallback = True

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.maersk.com/tracking/{clean}"

    def get_browser_plan(self, container_number: str) -> Dict[str, Any]:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return {
            "start_url": self.build_tracking_url(clean),
            # The tracking route renders the shipment timeline client-side for
            # the requested reference; no form interaction is required.
            "success_js": _rendered_reference_success_js(clean),
            "max_page_wait": 45.0,
            "overall_timeout": 90.0,
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
