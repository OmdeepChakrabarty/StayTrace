"""
Deterministic tests for Ocean Carrier Source Registry and Adapters.
Verifies all 10 supported shipping lines, official URL strategies, and lack of Google fallback.
"""

import pytest
from scraper.ocean_sources import (
    default_ocean_registry,
    OceanSourceRegistry,
    UnsupportedOceanCarrierError,
    MSCOceanAdapter,
    MaerskOceanAdapter,
    CMACGMOceanAdapter,
    COSCOOceanAdapter,
    HapagLloydOceanAdapter,
    ONEOceanAdapter,
    EvergreenOceanAdapter,
    ZIMOceanAdapter,
    YangMingOceanAdapter,
    HMMOceanAdapter,
)
from scraper.brightdata import BrightDataClient
from scraper.validator import ValidationError


CARRIER_TEST_CASES = [
    ("msc", "MSCU1234566", "msc.com", ("MSCU", "MEDU")),
    ("maersk", "MAEU6284920", "maersk.com", ("MAEU", "MSKU", "MRKU", "PONU")),
    ("cma_cgm", "CMAU0600020", "cma-cgm.com", ("CMAU", "CGMU", "APLU", "ANLU")),
    ("cosco", "COSU1234567", "coscoshipping.com", ("COSU", "CCLU", "CBHU")),
    ("hapag_lloyd", "HLCU1234567", "hapag-lloyd.com", ("HLCU", "HLXU", "HAMU", "UASC")),
    ("one", "ONEU1234567", "one-line.com", ("ONEU", "NYKU", "MOLU", "KKFU")),
    ("evergreen", "EGLV1234567", "shipmentlink.com", ("EGLV", "EGHU", "EMCU", "EISU")),
    ("zim", "ZIMU1234567", "zim.com", ("ZIMU", "ZCSU")),
    ("yang_ming", "YMLU1234567", "yangming.com", ("YMLU",)),
    ("hmm", "HMMU1234567", "hmm21.com", ("HMMU", "HDMU")),
]


@pytest.mark.parametrize("carrier_id, container_no, expected_domain, expected_prefixes", CARRIER_TEST_CASES)
def test_ocean_adapter_url_and_prefixes(carrier_id, container_no, expected_domain, expected_prefixes):
    adapter = default_ocean_registry.get_adapter(carrier_id)
    assert adapter is not None, f"Adapter for {carrier_id} must be registered"
    assert adapter.carrier_id == carrier_id

    # Verify prefix mapping
    for prefix in expected_prefixes:
        adapter_by_prefix = default_ocean_registry.get_adapter(prefix)
        assert adapter_by_prefix is not None
        assert adapter_by_prefix.carrier_id == carrier_id

    # Verify official URL construction
    url = default_ocean_registry.build_tracking_url(carrier_id, container_no)
    assert expected_domain in url
    assert container_no in url
    assert "google.com" not in url


@pytest.mark.parametrize("carrier_id, container_no, expected_domain, _", CARRIER_TEST_CASES)
def test_brightdata_client_routes_ocean_carrier_to_official_source(carrier_id, container_no, expected_domain, _):
    client = BrightDataClient(api_key="test_key")
    url = client.build_tracking_url(carrier_id, container_no)
    assert expected_domain in url
    assert "google.com" not in url


def test_unknown_ocean_carrier_raises_unsupported_error():
    registry = OceanSourceRegistry()
    with pytest.raises(UnsupportedOceanCarrierError):
        registry.build_tracking_url("unknown_line", "XXXX1234567")


def test_brightdata_client_unknown_carrier_raises_validation_error():
    client = BrightDataClient(api_key="test_key")
    with pytest.raises(ValidationError, match="Unsupported carrier tracking source"):
        client.build_tracking_url("completely_unknown_courier", "ABC1234567")


def test_parcel_carriers_preserve_existing_routes():
    client = BrightDataClient(api_key="test_key")
    assert "tools.usps.com" in client.build_tracking_url("usps", "9400100000000000000022")
    assert "fedex.com" in client.build_tracking_url("fedex", "123456789012")
    assert "ups.com" in client.build_tracking_url("ups", "1Z9999999999999999")
    assert "dhl.com" in client.build_tracking_url("dhl", "1234567890")
    assert "track.amazon.com" in client.build_tracking_url("amazon", "TBA123456789000")
    assert "ontrac.com" in client.build_tracking_url("ontrac", "C12345678901234")


def test_registry_catalog_completeness():
    catalog = default_ocean_registry.list_supported_carriers()
    assert len(catalog) == 10
    carrier_ids = {item["carrier_id"] for item in catalog}
    assert carrier_ids == {
        "msc", "maersk", "cma_cgm", "cosco", "hapag_lloyd",
        "one", "evergreen", "zim", "yang_ming", "hmm"
    }
