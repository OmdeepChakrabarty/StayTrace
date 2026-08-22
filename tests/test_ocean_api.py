import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest
import requests

from api.main import create_app
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
