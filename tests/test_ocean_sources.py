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


# ---------------------------------------------------------------------------
# CMA CGM structured response parsing (Scraping Browser path)
# ---------------------------------------------------------------------------

import json as _json

SYNTHETIC_RESPONSE_DATA = {
    "ContainerReference": "CMAU0600020",
    "NotFoundContainer": None,
    "PlaceOfLoading": "LEKKI, LA (NG)",
    "LastDischargePort": "QINGDAO (CN)",
    "POL": "NGLKK",
    "POD": "CNTAO",
    "POLDate": "2026-08-24T18:00:00",
    "EstimatedTimeOfArrival": "2026-09-27T17:00:00",
    "CurrentMoves": [
        {"Date": "2026-08-08T11:57:00", "StatusDescription": "Ready to be loaded",
         "Location": "LEKKI, LA", "LocationCode": "NGLKK", "Vessel": "", "Voyage": ""}
    ],
    "ProvisionalMoves": [
        {"Date": "2026-08-24T18:00:00", "StatusDescription": "Planned Vessel departure",
         "Location": "LEKKI, LA", "LocationCode": "NGLKK",
         "Vessel": "TEST VESSEL", "Voyage": "0W10JE1MA"},
    ],
    "PastMoves": [
        {"Date": "2026-07-13T10:37:01", "StatusDescription": "Gate out empty from depot",
         "Location": "LEKKI, LA", "LocationCode": "NGLKK", "Vessel": "", "Voyage": ""},
    ],
}


def _synthetic_html():
    embedded = _json.dumps(SYNTHETIC_RESPONSE_DATA).replace("'", "\\'")
    return f"<html><script>options.responseData = '{embedded}';</script></html>"


def test_cma_cgm_parse_official_response_maps_structured_state():
    adapter = default_ocean_registry.get_adapter("cma_cgm")
    parsed = adapter.parse_official_response(_synthetic_html())
    assert parsed is not None
    assert parsed["container_number"] == "CMAU0600020"
    assert parsed["origin_port_code"] == "NGLKK"
    assert parsed["destination_port_code"] == "CNTAO"
    assert parsed["vessel_name"] == "TEST VESSEL"
    assert parsed["voyage_number"] == "0W10JE1MA"
    assert len(parsed["events"]) == 3


def test_cma_cgm_parse_official_response_returns_none_for_shell_page():
    adapter = default_ocean_registry.get_adapter("cma_cgm")
    # Search-form shell without embedded state must fall back to self-healing
    assert adapter.parse_official_response("<html><body><div id='searchboxId'></div></body></html>") is None
    # Explicit carrier not-found marker must yield no fabricated data
    not_found = _json.dumps({**SYNTHETIC_RESPONSE_DATA, "NotFoundContainer": True})
    html = f"<html><script>options.responseData = '{not_found}';</script></html>"
    assert adapter.parse_official_response(html) is None


def test_ready_to_be_loaded_normalizes_to_gate_in():
    from pipeline.normalize import normalize_ocean_status
    assert normalize_ocean_status("Ready to be loaded") == "gate_in"


# ---------------------------------------------------------------------------
# MSC browser-plan and structured parsing of the rendered results page
# ---------------------------------------------------------------------------

from pathlib import Path

MSC_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ocean"


def test_msc_browser_plan_drives_official_search_form():
    """
    msc.com's SPA ignores a plain ?trackingNumber= query (its init() only
    auto-searches from a base64-encoded 'params' query, which robots.txt
    disallows), so the plan must drive the official search form in-session.
    """
    adapter = default_ocean_registry.get_adapter("msc")
    plan = adapter.get_browser_plan("MSCU5285725")

    # Plain start URL: no query string at all.
    assert plan["start_url"] == "https://www.msc.com/en/track-a-shipment"
    # Form interaction targets observed in the real page DOM.
    assert plan["ready_selector"] == "#trackingNumber"
    assert plan["fill"] == {"selector": "#trackingNumber", "value": "MSCU5285725"}
    assert plan["submit"] == ".msc-flow-tracking .msc-search-autocomplete__search"
    # Success strictly requires the searched reference in rendered text.
    assert "MSCU5285725" in plan["success_js"]
    assert "innerText" in plan["success_js"]
    # Bounds sized from live session measurements; positive and bounded.
    assert 0 < plan["max_page_wait"] <= plan["overall_timeout"]


def test_msc_parse_official_response_maps_hydrated_results():
    html = (MSC_FIXTURES_DIR / "msc_tracking.html").read_text(encoding="utf-8")
    adapter = default_ocean_registry.get_adapter("msc")
    parsed = adapter.parse_official_response(html)
    assert parsed is not None

    assert parsed["container_number"] == "MSCU5285725"
    assert parsed["tracking_number"] == "MSCU5285725"
    assert parsed["shipping_line"] == "msc"
    assert parsed["bill_of_lading_number"] == "MEDUJS999038"
    # Ports come from the official Port of Load / Port of Discharge facts,
    # with whitespace runs collapsed ("Chattogram,  BD" as rendered).
    assert parsed["origin_port"] == "Chattogram, BD"
    assert parsed["destination_port"] == "Veracruz, MX"

    # Status is the newest timeline event description.
    assert parsed["status"] == "Empty received at CY"

    # Events: hydrated rows only, chronological ascending, dd/MM/yyyy
    # converted deterministically to ISO 8601 UTC (never month-first).
    events = parsed["events"]
    assert len(events) == 7  # template row without a date must be skipped
    assert [e["timestamp"] for e in events] == [
        "2026-05-20T00:00:00Z",
        "2026-05-31T00:00:00Z",
        "2026-06-06T00:00:00Z",
        "2026-06-08T00:00:00Z",
        "2026-07-24T00:00:00Z",
        "2026-07-28T00:00:00Z",
        "2026-07-30T00:00:00Z",
    ]
    assert events[0]["description"] == "Empty to Shipper"
    assert events[0]["location"] == "Chattogram, BD"
    assert events[-1]["description"] == "Empty received at CY"
    assert events[-1]["location"] == "Veracruz, MX"
    assert events[3]["location"] == "Colombo, LK"


def test_msc_parse_official_response_returns_none_without_results():
    adapter = default_ocean_registry.get_adapter("msc")
    # Application shell (no rendered result block): fall back safely.
    shell = (
        '<html><body><div class="msc-flow-tracking" '
        'data-api-url="/api/feature/tools/TrackingInfo"></div></body></html>'
    )
    assert adapter.parse_official_response(shell) is None
    # Real carrier not-found rendering observed on msc.com: an error block
    # with no .msc-flow-tracking__result - never fabricate data from it.
    not_found = (
        '<html><body><template x-if="!isSuccess">'
        '<div class="msc-flow-tracking__error">'
        '<span class="msc-icon-dry-container-logo-empty"></span>'
        "<p x-text=\"errorMessage\">No results found for this Container "
        "number. Please recheck that the number is complete and correct and "
        "in the Container number format.</p>"
        "</div></template></body></html>"
    )
    assert adapter.parse_official_response(not_found) is None
    assert adapter.parse_official_response("") is None


def test_msc_parsed_fixture_normalizes_to_canonical_schema():
    from pipeline.normalize import normalize_container_shipment

    html = (MSC_FIXTURES_DIR / "msc_tracking.html").read_text(encoding="utf-8")
    adapter = MSCOceanAdapter()
    parsed = adapter.parse_official_response(html)
    normalized = normalize_container_shipment(parsed)

    assert normalized["container_number"] == "MSCU5285725"
    assert normalized["shipping_line"] == "msc"
    # Country-suffixed port names carry through canonicalization unchanged
    # (no 5-letter UN/LOCODE is present in MSC's rendered values).
    assert normalized["origin_port"] == "Chattogram, BD"
    assert normalized["destination_port"] == "Veracruz, MX"
    assert normalized["estimated_arrival"] is None  # POD ETA absent on page
    assert len(normalized["events"]) == 7
    first = normalized["events"][0]
    assert first["timestamp"] == "2026-05-20T00:00:00Z"
    # Carrier descriptions normalize through the shared ocean status map.
    assert normalized["events"][1]["status"] == "loaded"  # Export Loaded on Vessel
    assert normalized["events"][2]["status"] == "discharged"  # Full Transshipment Discharged
    assert normalized["events"][3]["status"] == "transshipment"  # Full Transshipment Loaded
    assert normalized["events"][4]["status"] == "discharged"  # Import Discharged from Vessel
    assert first["source"] == "carrier"


# ---------------------------------------------------------------------------
# Maersk browser-plan and structured parsing of the rendered results page
# ---------------------------------------------------------------------------

MAERSK_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ocean"


def test_maersk_browser_plan_drives_official_search_form():
    """
    maersk.com robots.txt allows exactly 'Allow: /tracking/$' and disallows
    every deep link ('Disallow: /tracking/*'), so the plan must load the bare
    search page and drive the official form in-session; direct navigation to
    /tracking/<REF> is refused by the Scraping Browser.
    """
    adapter = default_ocean_registry.get_adapter("maersk")
    plan = adapter.get_browser_plan("MRKU6357473")

    # Bare robots-allowed search page: no reference in the start URL.
    assert plan["start_url"] == "https://www.maersk.com/tracking/"
    # Official search form targets observed in the real page DOM: the visible
    # mc-input host is the ready marker, its light-DOM <input> child is what a
    # native value setter can fill, and the mc-button host submits.
    assert plan["ready_selector"] == "#track-input"
    assert plan["fill"] == {"selector": "#track-input input", "value": "MRKU6357473"}
    assert plan["submit"] == 'mc-button[data-test="track-button"]'
    # Success strictly requires the searched reference in rendered text -
    # input values, <title>, and analytics URLs never appear there, so shells
    # and not-found pages never pass.
    assert "MRKU6357473" in plan["success_js"]
    assert "innerText" in plan["success_js"]
    # Bounds sized from live session measurements (load 4-41s, results <=10s
    # after submit); positive, bounded by the SPA-fallback service guardrail,
    # and consistent with fetch_rendered_html's internal windows.
    assert 0 < plan["max_page_wait"] <= plan["overall_timeout"] <= 120.0


def test_maersk_parse_official_response_maps_hydrated_results():
    html = (MAERSK_FIXTURES_DIR / "maersk_tracking.html").read_text(encoding="utf-8")
    adapter = default_ocean_registry.get_adapter("maersk")
    parsed = adapter.parse_official_response(html)
    assert parsed is not None

    assert parsed["container_number"] == "MRKU6357473"
    assert parsed["tracking_number"] == "MRKU6357473"
    assert parsed["shipping_line"] == "maersk"
    # Ports come from the official From / To summary facts.
    assert parsed["origin_port"] == "ROSARIO"
    assert parsed["destination_port"] == "LE HAVRE"

    # Status is the newest timeline event description (raw carrier wording).
    assert parsed["status"] == "Empty container return"

    # Vessel/voyage come from the most recent vessel-bearing milestone.
    assert parsed["vessel_name"] == "KASSIAKOS"
    assert parsed["voyage_number"] == "619N"

    # No ETA trigger value rendered for this delivered container.
    assert parsed["estimated_arrival"] is None

    # Events: hydrated rows only, chronological ascending, 'DD Mon YYYY HH:MM'
    # converted deterministically to ISO 8601 UTC (never month-first).
    events = parsed["events"]
    assert len(events) == 16
    assert [e["timestamp"] for e in events] == [
        "2026-03-13T17:20:00Z",
        "2026-03-20T12:53:00Z",
        "2026-03-30T21:36:00Z",
        "2026-03-31T10:30:00Z",
        "2026-04-05T16:17:00Z",
        "2026-04-05T21:12:00Z",
        "2026-04-14T13:20:00Z",
        "2026-04-15T08:50:00Z",
        "2026-05-06T11:35:00Z",
        "2026-05-06T20:49:00Z",
        "2026-05-16T04:35:00Z",
        "2026-05-16T19:20:00Z",
        "2026-05-20T07:13:00Z",
        "2026-05-21T04:28:00Z",
        "2026-05-21T14:45:00Z",
        "2026-05-26T07:52:00Z",
    ]
    assert events[0]["description"] == "Gate out Empty"
    assert events[0]["location"] == "ROSARIO ROSARIO PORT TERMINAL"
    assert events[3]["description"] == "Feeder departure (MAERSK VENEZIA / 614N)"
    assert events[3]["vessel"] == "MAERSK VENEZIA"
    assert events[3]["voyage"] == "614N"
    assert events[4]["location"] == "ITAPOA ITAPOA TERMINAIS PORTUARIOS SA"
    assert events[-1]["description"] == "Empty container return"
    assert events[-1]["location"] == ""
    assert events[12]["location"] == "LE HAVRE HAVRE LE CNM TERMINAL"
    assert all(e["source"] == "carrier" for e in events)


def test_maersk_parse_official_response_returns_none_without_results():
    adapter = default_ocean_registry.get_adapter("maersk")
    # Application shell (search form only, no hydrated results): fall back safely.
    shell = (
        '<html><body><div id="maersk-app" data-v-app="">'
        '<mc-input data-test="track-input" id="track-input" name="track-input">'
        '<input type="text" name="track-input"></mc-input>'
        '<mc-button data-test="track-button"></mc-button></div></body></html>'
    )
    assert adapter.parse_official_response(shell) is None
    # Real carrier not-found rendering observed on maersk.com after searching
    # an unknown reference - no summary block and no transport-plan items:
    # never fabricate data from it.
    not_found = (
        "<html><body><main data-test=\"track-content\">"
        "<div class=\"track-grid__content\">No results found</div>"
        "<p>We couldn't find any Bills of Lading or containers available on "
        "public track for your search.</p></main></body></html>"
    )
    assert adapter.parse_official_response(not_found) is None
    assert adapter.parse_official_response("") is None


def test_maersk_parsed_fixture_normalizes_to_canonical_schema():
    from pipeline.normalize import normalize_container_shipment

    html = (MAERSK_FIXTURES_DIR / "maersk_tracking.html").read_text(encoding="utf-8")
    adapter = default_ocean_registry.get_adapter("maersk")
    parsed = adapter.parse_official_response(html)
    normalized = normalize_container_shipment(parsed)

    assert normalized["container_number"] == "MRKU6357473"
    assert normalized["shipping_line"] == "maersk"
    assert normalized["origin_port"] == "ROSARIO"
    assert normalized["destination_port"] == "LE HAVRE"
    assert len(normalized["events"]) == 16
    first = normalized["events"][0]
    assert first["timestamp"] == "2026-03-13T17:20:00Z"
    # Carrier descriptions normalize through the shared ocean status map.
    assert normalized["events"][0]["status"] == "delivered"  # Gate out Empty
    assert normalized["events"][1]["status"] == "gate_in"  # Gate in
    assert normalized["events"][7]["status"] == "in_transit"  # Vessel departure
    assert normalized["events"][9]["status"] == "unknown"  # Discharge (VESSEL / VOY) suffix
    assert normalized["events"][14]["status"] == "gate_out"  # Gate out for delivery
    assert first["source"] == "carrier"


# ---------------------------------------------------------------------------
# COSCO browser-fallback target and structured parsing of the rendered SCCT
# results page
# ---------------------------------------------------------------------------

COSCO_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ocean"


def test_cosco_tracking_url_targets_auto_searching_scct_app():
    """
    lines.coscoshipping.com serves only a JS application shell whose tracking
    iframe carries an EMPTY number parameter, so a stateless fetch can never
    show results. The SCCT app hosted on elines.coscoshipping.com auto-runs
    the search from its own ?number= query when rendered, so the adapter must
    target it directly - that URL is what both the stateless Web Unlocker
    pass and the generic rendered-browser fallback request.
    """
    adapter = default_ocean_registry.get_adapter("cosco")
    url = adapter.build_tracking_url(" cosu1234567 ")
    assert url == (
        "https://elines.coscoshipping.com/scct/public/ct/base"
        "?lang=en&trackingType=CONTAINER&number=COSU1234567"
    )
    assert url == COSCOOceanAdapter().build_tracking_url("COSU1234567")

    # The escalation design relies on staying on the generic rendered-form
    # fallback path (no upfront session, no carrier-specific plan).
    assert adapter.requires_browser is False
    assert adapter.browser_fallback is False


def test_cosco_parse_official_response_maps_hydrated_results():
    html = (COSCO_FIXTURES_DIR / "cosco_tracking.html").read_text(encoding="utf-8")
    adapter = default_ocean_registry.get_adapter("cosco")
    parsed = adapter.parse_official_response(html)
    assert parsed is not None

    assert parsed["container_number"] == "FCIU9480317"
    assert parsed["tracking_number"] == "FCIU9480317"
    assert parsed["shipping_line"] == "cosco"

    # Status is the newest timeline event description (raw carrier wording).
    assert parsed["status"] == "Vessel departure from First POL"

    # ETA comes from the date block rendered before the 'Last Pod Eta' label,
    # converted deterministically to ISO 8601 UTC.
    assert parsed["estimated_arrival"] == "2026-10-09T06:00:00Z"

    # Events: hydrated rows only ('YYYY-MM-DD HH:MM:SS' -> ISO 8601 UTC),
    # column order taken from the rendered header labels.
    events = parsed["events"]
    assert len(events) == 1
    assert events[0]["timestamp"] == "2026-08-19T04:14:41Z"
    assert events[0]["description"] == "Vessel departure from First POL"
    assert events[0]["location"] == "Gaevle Containerterminal AB"
    assert events[0]["transport_mode"] == "Feeder"
    assert events[0]["source"] == "carrier"


def test_cosco_parse_official_response_returns_none_without_results():
    adapter = default_ocean_registry.get_adapter("cosco")
    # Application shells observed live (parent page and SCCT app pre-search):
    # no rendered container number and no timeline rows - fall back safely.
    parent_shell = (
        "<!DOCTYPE html><html lang=\"\"><head><title>COSCO SHIPPING Lines</title>"
        "</head><body><noscript><strong>We're sorry but homevue3 doesn't work "
        "properly without JavaScript enabled.</strong></noscript>"
        "<div id=\"app\"></div></body></html>"
    )
    scct_shell = (
        '<!DOCTYPE html><html lang="en"><head><title>SCCT</title></head>'
        '<body class="font-default"><div id="app"></div></body></html>'
    )
    assert adapter.parse_official_response(parent_shell) is None
    assert adapter.parse_official_response(scct_shell) is None
    # A rendered but empty results table (not-found response): never fabricate.
    not_found = (
        '<html><body><div class="ant-table"><div class="ant-table-container">'
        '<div class="ant-table-content"><table style="table-layout: auto;">'
        '<thead class="ant-table-thead"><tr>'
        '<th class="ant-table-cell">Dynamic Node</th>'
        '<th class="ant-table-cell">Event Time</th>'
        "</tr></thead>"
        '<tbody class="ant-table-tbody"></tbody>'
        "</table></div></div></div></body></html>"
    )
    assert adapter.parse_official_response(not_found) is None
    assert adapter.parse_official_response("") is None


def test_cosco_timeline_rows_without_dates_are_skipped_and_order_is_chronological():
    """Unhydrated template rows carry no date and must be skipped; emitted
    events are chronological even if the DOM lists them newest-first."""
    html = (
        '<html><body><table><thead class="ant-table-thead"><tr>'
        '<th class="ant-table-cell">Dynamic Node</th>'
        '<th class="ant-table-cell">Event Time</th>'
        '<th class="ant-table-cell">Event Location</th>'
        "</tr></thead>"
        '<tbody class="ant-table-tbody">'
        '<tr class="ant-table-row"><td class="ant-table-cell">'
        "<div><span>Discharged at Last POD</span></div></td>"
        '<td class="ant-table-cell"><div><span></span></div></td>'  # template row
        '<td class="ant-table-cell"></td></tr>'
        '<tr class="ant-table-row"><td class="ant-table-cell">'
        "<div><span>Vessel departure from First POL</span></div></td>"
        '<td class="ant-table-cell"><div><span>2026-08-19 04:14:41</span></div></td>'
        '<td class="ant-table-cell">Gaevle Containerterminal AB</td></tr>'
        '<tr class="ant-table-row"><td class="ant-table-cell">'
        "<div><span>Loaded at First POL</span></div></td>"
        '<td class="ant-table-cell"><div><span>2026-08-18 18:36</span></div></td>'
        '<td class="ant-table-cell">Gaevle Containerterminal AB</td></tr>'
        "</tbody></table>"
        "<div>FCIU9480317</div>"
        "</body></html>"
    )
    adapter = default_ocean_registry.get_adapter("cosco")
    parsed = adapter.parse_official_response(html)
    assert parsed is not None
    assert [e["timestamp"] for e in parsed["events"]] == [
        "2026-08-18T18:36:00Z",
        "2026-08-19T04:14:41Z",
    ]
    assert parsed["events"][0]["description"] == "Loaded at First POL"
    assert parsed["status"] == "Vessel departure from First POL"


def test_cosco_parsed_fixture_normalizes_to_canonical_schema():
    from pipeline.normalize import normalize_container_shipment

    html = (COSCO_FIXTURES_DIR / "cosco_tracking.html").read_text(encoding="utf-8")
    adapter = default_ocean_registry.get_adapter("cosco")
    parsed = adapter.parse_official_response(html)
    normalized = normalize_container_shipment(parsed)

    assert normalized["container_number"] == "FCIU9480317"
    assert normalized["shipping_line"] == "cosco"
    assert normalized["estimated_arrival"] == "2026-10-09T06:00:00Z"
    assert len(normalized["events"]) == 1
    first = normalized["events"][0]
    assert first["timestamp"] == "2026-08-19T04:14:41Z"
    # Carrier descriptions normalize through the shared ocean status map;
    # the newest move drives the shipment status.
    assert first["status"] == "in_transit"  # Vessel departure from First POL
    assert normalized["status"] == "in_transit"
    assert first["source"] == "carrier"
