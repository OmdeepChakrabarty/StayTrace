"""
Ocean Carrier Source Adapters and Registry for StayTrace.
Encapsulates official tracking URL strategies for major ocean container shipping lines.
Extensible, modular, zero hardcoded secrets, no Google search fallback.
"""

from __future__ import annotations

import abc
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

    def __init__(self) -> None:
        pass

    @abc.abstractmethod
    def build_tracking_url(self, container_number: str) -> str:
        """Construct the official carrier tracking URL for a given container number."""
        pass

    def get_request_headers(self) -> Dict[str, str]:
        """Optional HTTP headers specific to this carrier."""
        return {}

    def get_request_payload(self, container_number: str) -> Optional[Dict[str, Any]]:
        """Optional POST payload if carrier uses form/API requests."""
        return None


# =====================================================================
# Carrier Source Adapter Implementations
# =====================================================================

class MSCOceanAdapter(OceanSourceAdapter):
    """MSC Mediterranean Shipping Company official tracking adapter."""
    carrier_id = "msc"
    display_name = "MSC Mediterranean Shipping Company"
    supported_prefixes = ("MSCU", "MEDU")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.msc.com/en/track-a-shipment?trackingNumber={clean}"


class MaerskOceanAdapter(OceanSourceAdapter):
    """Maersk Line official tracking adapter."""
    carrier_id = "maersk"
    display_name = "Maersk Line"
    supported_prefixes = ("MAEU", "MSKU", "MRKU", "PONU")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.maersk.com/tracking/{clean}"


class CMACGMOceanAdapter(OceanSourceAdapter):
    """CMA CGM Group (including APL, ANL) official tracking adapter."""
    carrier_id = "cma_cgm"
    display_name = "CMA CGM Group"
    supported_prefixes = ("CMAU", "CGMU", "APLU", "ANLU")

    def build_tracking_url(self, container_number: str) -> str:
        clean = re.sub(r"\s+", "", container_number.strip().upper())
        return f"https://www.cma-cgm.com/ebusiness/tracking/search?SearchBy=Container&Reference={clean}"


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
