"""
Deterministic tests for the universal carrier rendered-browser fallback.

Covers:
- generic ocean carrier (no carrier-specific plan) JS-shell -> browser
  fallback -> genuine extracted shipment
- parcel JS-shell/empty stateless result -> browser fallback -> extracted
  shipment persisted only when usable state exists
- fallback failure -> honest error, zero fabricated data
- CMA CGM / MSC / Maersk existing behaviors preserved
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api.main import TrackingService
from db.database import init_db
from scraper.brightdata import BrightDataClient, BrightDataError

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ocean"
RENDERED_HTML = (FIXTURES_DIR / "redesigned_page.html").read_text(encoding="utf-8")
SHELL_HTML = "<html><body><div id='app'></div></body></html>"


@pytest.fixture
def svc(tmp_path):
    db_file = str(tmp_path / "fallback.db")
    init_db(db_path=db_file)
    client = MagicMock(spec=BrightDataClient)
    return TrackingService(brightdata_client=client, db_path=db_file), client, db_file


def _shell_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = SHELL_HTML
    return resp


def test_generic_ocean_carrier_shell_uses_generic_browser_fallback(svc, monkeypatch):
    """COSCO has no carrier-specific plan: shell page must escalate through
    the generic rendered-form fallback against its official URL."""
    service, mock_client, _ = svc
    mock_client.build_tracking_url.return_value = (
        "https://lines.coscoshipping.com/ebusiness/cargoTracking?searchType=CONTAINER&trackingNo=COSU1234567"
    )
    mock_client.unlock_url.return_value = _shell_response()

    calls = []

    def fake_generic(url, reference, **kwargs):
        calls.append((url, reference))
        return RENDERED_HTML

    monkeypatch.setattr("api.main.fetch_generic_rendered_carrier_page", fake_generic)

    container, status_code = service.track_container("COSU1234567", shipping_line="cosco", fetch_live=True)

    assert calls == [(
        "https://lines.coscoshipping.com/ebusiness/cargoTracking?searchType=CONTAINER&trackingNo=COSU1234567",
        "COSU1234567",
    )]
    assert container["container_number"] == "COSU1234567"
    assert container["status"] == "in_transit"
    assert container["vessel_name"] == "MSC ISABELLA"
    details = json.loads(container["healing_details"])
    assert any("escalat" in entry.lower() for entry in details["diagnostic_log"])


def test_parcel_empty_stateless_result_uses_browser_fallback(svc, monkeypatch):
    """A stateless parcel result with unknown status and no events is an
    extraction failure; the rendered-browser fallback must run and its usable
    output persisted."""
    service, mock_client, _ = svc
    mock_client.fetch_tracking.return_value = {
        "tracking_number": "9400100000000000000099",
        "carrier": "usps",
        "status": "unknown",
        "events": [],
    }
    mock_client.build_tracking_url.return_value = (
        "https://tools.usps.com/go/TrackConfirmAction?tLabels=9400100000000000000099"
    )

    def fake_generic(url, reference, **kwargs):
        assert reference == "9400100000000000000099"
        return RENDERED_HTML

    monkeypatch.setattr("api.main.fetch_generic_rendered_carrier_page", fake_generic)

    parcel, _ = service.track_parcel("9400100000000000000099", carrier="usps", fetch_live=True)
    assert parcel["status"] == "in_transit"
    stored = service.get_parcel("9400100000000000000099")
    assert stored is not None and stored["status"] == "in_transit"


def test_parcel_known_state_skips_fallback(svc):
    """Usable stateless results (real status) must never trigger a browser session."""
    service, mock_client, _ = svc
    mock_client.fetch_tracking.return_value = {
        "tracking_number": "1Z9999999999999999",
        "carrier": "ups",
        "status": "in_transit",
        "events": [],
    }

    with patch("api.main.fetch_generic_rendered_carrier_page") as fake:
        parcel, _ = service.track_parcel("1Z9999999999999999", carrier="ups", fetch_live=True)

    assert not fake.called
    assert parcel["status"] == "in_transit"


def test_fallback_failure_is_honest_and_fabricates_nothing(svc, monkeypatch):
    """When both the stateless source and the rendered fallback fail to show
    the reference, the request fails - no vessel/route/events invented."""
    service, mock_client, _ = svc
    mock_client.build_tracking_url.return_value = "https://www.msc.com/en/track-a-shipment?trackingNumber=MSCU1234566"
    mock_client.unlock_url.return_value = _shell_response()

    from scraper.browser_session import BrowserSessionError

    def fail_any(*args, **kwargs):
        raise BrowserSessionError("carrier page never rendered tracking results")

    monkeypatch.setattr("api.main.fetch_generic_rendered_carrier_page", fail_any)
    monkeypatch.setattr("api.main.fetch_carrier_page_via_browser", fail_any)

    with pytest.raises(BrightDataError):
        service.track_container("MSCU1234566", shipping_line="msc", fetch_live=True)

    # Nothing fabricated or persisted
    assert service.get_parcel("MSCU1234566") is None


def test_cma_cgm_requires_browser_upfront_without_double_fallback(tmp_path, monkeypatch):
    """CMA CGM runs its own session upfront; a failed attempt must not spawn a
    second generic fallback for the same request."""
    db_file = str(tmp_path / "cma_no_double.db")
    init_db(db_path=db_file)
    client = MagicMock(spec=BrightDataClient)
    service = TrackingService(brightdata_client=client, db_path=db_file)

    calls = []

    def fake_plan_fetch(adapter, container_number):
        calls.append(container_number)
        return SHELL_HTML

    monkeypatch.setattr("api.main.fetch_carrier_page_via_browser", fake_plan_fetch)
    with patch("api.main.fetch_generic_rendered_carrier_page") as fake_generic:
        container, _ = service.track_container("CMAU0600020", shipping_line="cma_cgm", fetch_live=True)

    assert calls == ["CMAU0600020"]  # one bounded plan execution only
    assert not fake_generic.called
    assert container["healing_status"] == "failed"
    assert container["events"] == []
