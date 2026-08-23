import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest
import requests

from api.main import create_app, TrackingService
from db.database import init_db
from scraper.brightdata import BrightDataClient


@pytest.fixture
def ocean_test_server(tmp_path):
    db_file = str(tmp_path / "test_ocean.db")
    mock_client = MagicMock(spec=BrightDataClient)

    server = create_app(db_path=db_file, brightdata_client=mock_client, host="127.0.0.1", port=0)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    yield {
        "url": f"http://127.0.0.1:{port}",
        "mock_client": mock_client,
        "db_path": db_file,
    }

    server.shutdown()
    server.server_close()


def test_track_container_html_payload_self_healing(ocean_test_server):
    fixtures_dir = Path(__file__).parent / "fixtures" / "ocean"
    redesigned_html = (fixtures_dir / "redesigned_page.html").read_text(encoding="utf-8")

    url = f"{ocean_test_server['url']}/api/track/container"
    payload = {
        "container_number": "MSCU1234566",
        "shipping_line": "msc",
        "html_payload": redesigned_html,
    }
    resp = requests.post(url, json=payload)
    assert resp.status_code in (200, 201)
    data = resp.json()

    assert data["shipment_type"] == "ocean_container"
    assert data["container_number"] == "MSCU1234566"
    assert data["shipping_line"] == "msc"
    assert data["status"] == "in_transit"
    assert data["healing_status"] == "healed"
    assert data["healing_confidence"] >= 0.70


def test_list_and_get_containers(ocean_test_server):
    # Ingest 1 container and 1 parcel
    requests.post(
        f"{ocean_test_server['url']}/api/track/container",
        json={
            "container_number": "MAEU6284920",
            "shipping_line": "maersk",
            "status": "gate_in",
            "origin_port": "Shanghai",
            "destination_port": "Rotterdam",
        }
    )
    requests.post(
        f"{ocean_test_server['url']}/api/track",
        json={
            "tracking_number": "9400100000000000000099",
            "carrier": "usps",
            "status": "in_transit",
        }
    )

    # List only containers
    resp = requests.get(f"{ocean_test_server['url']}/api/containers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["containers"][0]["container_number"] == "MAEU6284920"

    # Get single container
    single_resp = requests.get(f"{ocean_test_server['url']}/api/containers/MAEU6284920")
    assert single_resp.status_code == 200
    assert single_resp.json()["container_number"] == "MAEU6284920"


def test_self_healing_demo_endpoint(ocean_test_server):
    # Test GET demo
    resp_get = requests.get(f"{ocean_test_server['url']}/api/demo/heal?scenario=redesigned")
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert data_get["demo_scenario"] == "redesigned"
    assert data_get["telemetry"]["extraction_status"] == "healed"

    # Test POST demo with ambiguous
    resp_post = requests.post(f"{ocean_test_server['url']}/api/demo/heal", json={"scenario": "ambiguous"})
    assert resp_post.status_code == 200
    data_post = resp_post.json()
    assert data_post["demo_scenario"] == "ambiguous"
    assert data_post["telemetry"]["validation_result"] == "rejected_ambiguous"


def test_track_container_live_fetch_routes_to_official_source_and_rejects_empty_page(tmp_path, monkeypatch):
    """
    Deterministic regression for the live ocean fetch path (no network).
    CMA CGM requires the Scraping Browser path; simulate an official carrier
    page shell that carries no shipment data:
    - must route through the browser-session helper to the official source
    - self-healing must safely reject the empty page
    - shipping line from routing must still be stamped on the record
    """
    db_file = str(tmp_path / "live_path.db")
    init_db(db_path=db_file)

    requested_urls = []

    def fake_browser_fetch(adapter, container_number):
        requested_urls.append(adapter.build_tracking_url(container_number))
        # Official CMA CGM search page shell: no tracking results in HTML
        return "<html><body><div id='searchboxId'></div></body></html>"

    monkeypatch.setattr("api.main.fetch_carrier_page_via_browser", fake_browser_fetch)

    mock_client = MagicMock(spec=BrightDataClient)
    svc = TrackingService(brightdata_client=mock_client, db_path=db_file)
    container, status_code = svc.track_container("CMAU0600020", shipping_line="cma_cgm", fetch_live=True)

    # Routing went to the official source, never Google; unlocker not used
    assert requested_urls == [
        "https://www.cma-cgm.com/ebusiness/tracking/search?SearchBy=Container&Reference=CMAU0600020"
    ]
    assert "google.com" in str(mock_client.mock_calls) or not mock_client.unlock_url.called
    assert not any("google.com" in str(c) for c in mock_client.mock_calls)

    # Safe rejection recorded, no fabricated data
    assert container["container_number"] == "CMAU0600020"
    assert container["status"] == "unknown"
    assert container["healing_status"] == "failed"
    assert container["events"] == []
    # Shipping line inferred by routing is stamped even when extractor returns none
    assert container["shipping_line"] == "cma_cgm"
    assert container["carrier"] == "cma_cgm"


def test_track_container_unlocker_path_for_non_browser_carriers(tmp_path, monkeypatch):
    """
    Non-browser ocean carriers (e.g. Maersk) must keep using the stateless
    Web Unlocker fetch path - browser sessions are reserved for carriers that
    declare requires_browser.
    """
    db_file = str(tmp_path / "unlocker_path.db")
    init_db(db_path=db_file)

    def fail_browser_fetch(adapter, container_number):
        raise AssertionError("browser session must not be used for non-browser carriers")

    monkeypatch.setattr("api.main.fetch_carrier_page_via_browser", fail_browser_fetch)

    mock_client = MagicMock(spec=BrightDataClient)
    mock_client.build_tracking_url.return_value = "https://www.maersk.com/tracking/MAEU6284920"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body>shell</body></html>"
    mock_client.unlock_url.return_value = mock_resp

    svc = TrackingService(brightdata_client=mock_client, db_path=db_file)
    container, _ = svc.track_container("MAEU6284920", shipping_line="maersk", fetch_live=True)

    assert mock_client.unlock_url.called
    assert container["shipping_line"] == "maersk"
