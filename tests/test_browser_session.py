"""
Deterministic tests for the Bright Data Scraping Browser session layer.
No live network calls - all HTTP and CDP interactions are mocked.
Credential values used here are fake test strings; real credentials are
never printed, logged, or persisted by the module under test.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from scraper.browser_session import (
    BrowserSessionError,
    _CdpBrowser,
    discover_browser_credentials,
    fetch_carrier_page_via_browser,
    reset_credentials_cache,
)
from scraper.ocean_sources import default_ocean_registry


FAKE_CREDS = {
    "customer_id": "hl_fakecustomer",
    "zone": "cli_browser",
    "password": "fake-password-for-tests-only",
}


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_credentials_cache()
    yield
    reset_credentials_cache()


# ---------------------------------------------------------------------------
# Credential auto-discovery (BRIGHTDATA_API_KEY only)
# ---------------------------------------------------------------------------

def _mock_requests_get(url, **kwargs):
    resp = MagicMock()
    if url.endswith("/zone/get_active_zones"):
        resp.status_code = 200
        resp.json.return_value = [
            {"name": "cli_unlocker", "type": "unblocker"},
            {"name": "cli_browser", "type": "browser_api"},
        ]
    elif "zone/cost" in url:
        resp.status_code = 200
        resp.json.return_value = {"hl_fakecustomer": {"zone_cost": 0}}
    elif "zone/passwords" in url:
        resp.status_code = 200
        resp.json.return_value = {"passwords": [FAKE_CREDS["password"]]}
    else:
        resp.status_code = 404
        resp.json.return_value = {}
    return resp


def test_discovery_uses_only_api_key_and_finds_browser_zone():
    with patch("scraper.browser_session.requests.get", side_effect=_mock_requests_get):
        creds = discover_browser_credentials(api_key="fake-api-key")
    assert creds["zone"] == "cli_browser"
    assert creds["customer_id"] == FAKE_CREDS["customer_id"]
    assert creds["password"] == FAKE_CREDS["password"]


def test_discovery_result_is_cached_in_memory():
    with patch("scraper.browser_session.requests.get", side_effect=_mock_requests_get) as mock_get:
        first = discover_browser_credentials(api_key="fake-api-key")
        second = discover_browser_credentials(api_key="fake-api-key")
    assert first == second == FAKE_CREDS
    assert mock_get.call_count == 3  # zones + cost + passwords, once only


def test_discovery_raises_clear_error_when_no_browser_zone():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = [{"name": "cli_unlocker", "type": "unblocker"}]
    with patch("scraper.browser_session.requests.get", return_value=resp):
        with pytest.raises(BrowserSessionError, match="No Scraping Browser"):
            discover_browser_credentials(api_key="fake-api-key")


def test_discovery_error_messages_never_contain_secrets():
    import requests as requests_lib

    with patch(
        "scraper.browser_session.requests.get",
        side_effect=requests_lib.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(BrowserSessionError) as exc_info:
            discover_browser_credentials(api_key="fake-api-key")
    message = str(exc_info.value)
    assert "fake-api-key" not in message
    assert FAKE_CREDS["password"] not in message


# ---------------------------------------------------------------------------
# Adapter browser-plan declarations
# ---------------------------------------------------------------------------

CARRIER_IDS = [
    "msc", "maersk", "cma_cgm", "cosco", "hapag_lloyd",
    "one", "evergreen", "zim", "yang_ming", "hmm",
]


@pytest.mark.parametrize("carrier_id", CARRIER_IDS)
def test_browser_session_plans_by_carrier(carrier_id):
    adapter = default_ocean_registry.get_adapter(carrier_id)
    assert adapter is not None
    if carrier_id == "cma_cgm":
        assert adapter.requires_browser is True
        plan = adapter.get_browser_plan("CMAU0600020")
        assert plan is not None
        assert plan["start_url"].startswith("https://www.cma-cgm.com/")
        assert "google.com" not in plan["start_url"]
        assert plan["fill"]["value"] == "CMAU0600020"
        assert plan["submit"] == "#btnTracking"
        # Success must be tied to carrier-rendered state, not raw substrings
        # (URLs and anti-bot pages can echo the reference).
        success_js = plan["success_js"]
        assert "containerReference" in success_js
        assert "CMAU0600020" in success_js
        # Bounded, but generous enough for slow anti-bot resolution (the
        # verified working window for the CMA CGM path).
        assert plan["overall_timeout"] <= 300.0
        assert plan["max_page_wait"] <= 90.0
    elif carrier_id in ("msc", "maersk"):
        # JS-shell SPA sources: stateless first, real browser session as a
        # bounded fallback when normal extraction finds nothing usable.
        assert adapter.requires_browser is False
        assert adapter.browser_fallback is True
        plan = adapter.get_browser_plan("MSCU1234566" if carrier_id == "msc" else "MAEU6284920")
        assert plan is not None
        ref = "MSCU1234566" if carrier_id == "msc" else "MAEU6284920"
        assert plan["start_url"].startswith("https://www.")
        assert "google.com" not in plan["start_url"]
        # Success must require the rendered reference text - shells never pass.
        assert ref in plan["success_js"]
        assert "innerText" in plan["success_js"]
        assert plan["overall_timeout"] <= 120.0
        assert plan["max_page_wait"] <= 60.0
    else:
        assert adapter.requires_browser is False
        assert adapter.browser_fallback is False
        assert adapter.get_browser_plan("X") is None


def test_fetch_carrier_page_via_browser_executes_plan():
    adapter = default_ocean_registry.get_adapter("cma_cgm")
    with patch("scraper.browser_session.fetch_rendered_html") as mock_fetch:
        mock_fetch.return_value = "<html>results</html>"
        html = fetch_carrier_page_via_browser(adapter, "CMAU0600020")
    assert html == "<html>results</html>"
    kwargs = mock_fetch.call_args.kwargs
    assert kwargs["fill"] == {"selector": "#Reference", "value": "CMAU0600020"}
    assert kwargs["submit_selector"] == "#btnTracking"
    assert "containerReference" in kwargs["success_js"]


def test_fetch_carrier_page_via_browser_rejects_missing_plan():
    adapter = default_ocean_registry.get_adapter("cosco")
    with pytest.raises(BrowserSessionError, match="does not define a browser session plan"):
        fetch_carrier_page_via_browser(adapter, "COSU1234567")


# ---------------------------------------------------------------------------
# CDP mini-client (scripted websocket)
# ---------------------------------------------------------------------------

class FakeWebSocket:
    """Scripted websocket: records client sends, queues response frames."""

    def __init__(self):
        self.sent = []
        self._frames = []
        self.closed = False

    def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)

    def queue(self, frame):
        self._frames.append(frame)

    def settimeout(self, t):
        pass

    def recv(self):
        return json.dumps(self._frames.pop(0))

    def close(self):
        self.closed = True


def test_cdp_client_sends_auth_and_drives_navigation_flow():
    ws = FakeWebSocket()

    def fake_create_connection(url, header=None, timeout=None, enable_multithread=False):
        # Authorization header must be present (Basic auth over CDP websocket)
        assert any(str(h).startswith("Authorization: Basic ") for h in header or [])
        assert url.startswith("wss://brd.superproxy.io:9222")
        return ws

    with patch("scraper.browser_session.create_connection", side_effect=fake_create_connection):
        browser = _CdpBrowser(dict(FAKE_CREDS))
        ws.queue({"id": 1, "result": {"targetId": "TARGET1"}})
        target = browser.command("Target.createTarget", url="about:blank")
        ws.queue({"id": 2, "result": {"sessionId": "SESSION1"}})
        attached = browser.command(
            "Target.attachToTarget", targetId=target["targetId"], flatten=True
        )
        ws.queue({"id": 3, "result": {}})
        browser.command("Page.enable", session_id=attached["sessionId"])
        ws.queue({"id": 4, "result": {"frameId": "F"}})
        browser.command(
            "Page.navigate", session_id=attached["sessionId"],
            url="https://www.cma-cgm.com/ebusiness/tracking/search",
        )
        browser.close()

    methods = [m["method"] for m in ws.sent]
    assert methods == [
        "Target.createTarget", "Target.attachToTarget",
        "Page.enable", "Page.navigate",
    ]
    assert ws.closed is True
