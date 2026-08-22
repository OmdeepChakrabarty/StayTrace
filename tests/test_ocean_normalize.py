import pytest
from pipeline.normalize import (
    normalize_shipping_line,
    normalize_ocean_status,
    extract_locode_and_port,
    normalize_ocean_event,
    normalize_container_shipment,
)


def test_normalize_shipping_line():
    assert normalize_shipping_line("MSC") == "msc"
    assert normalize_shipping_line("Mediterranean Shipping Company") == "msc"
    assert normalize_shipping_line("Maersk Line") == "maersk"
    assert normalize_shipping_line("A.P. Moller - Maersk") == "maersk"
    assert normalize_shipping_line("CMA CGM") == "cma_cgm"
    assert normalize_shipping_line("COSCO Shipping") == "cosco"
    assert normalize_shipping_line("Hapag-Lloyd") == "hapag_lloyd"
    assert normalize_shipping_line("Ocean Network Express") == "one"
    assert normalize_shipping_line("Evergreen") == "evergreen"
    assert normalize_shipping_line("ZIM Line") == "zim"
    assert normalize_shipping_line("Yang Ming") == "yang_ming"
    assert normalize_shipping_line("HMM") == "hmm"
    assert normalize_shipping_line("Unknown Ocean Line") == "other"
    assert normalize_shipping_line(None) == "other"


def test_normalize_ocean_status():
    assert normalize_ocean_status("Booked") == "booked"
    assert normalize_ocean_status("Gate In") == "gate_in"
    assert normalize_ocean_status("Loaded on Vessel") == "loaded"
    assert normalize_ocean_status("Vessel Departure") == "in_transit"
    assert normalize_ocean_status("Underway at sea") == "in_transit"
    assert normalize_ocean_status("Transshipment hub") == "transshipment"
    assert normalize_ocean_status("Discharged from vessel") == "discharged"
    assert normalize_ocean_status("Customs hold") == "customs_hold"
    assert normalize_ocean_status("Gate Out") == "gate_out"
    assert normalize_ocean_status("Empty returned") == "delivered"
    assert normalize_ocean_status("unknown_status_code") == "unknown"


def test_extract_locode_and_port():
    port, code = extract_locode_and_port("Shanghai (CNSHA)")
    assert port == "Shanghai"
    assert code == "CNSHA"

    port, code = extract_locode_and_port("Port of Rotterdam [NLRTM]")
    assert "Rotterdam" in port
    assert code == "NLRTM"

    port, code = extract_locode_and_port("SGSIN")
    assert code == "SGSIN"


def test_normalize_ocean_event():
    raw_ev = {
        "timestamp": "2026-08-20T08:00:00Z",
        "status": "Loaded on Vessel",
        "description": "Laden on board MSC ISABELLA",
        "location": "Shanghai (CNSHA)",
        "vessel": "MSC ISABELLA",
        "voyage": "FD432R",
    }
    ev = normalize_ocean_event(raw_ev)
    assert ev["timestamp"] == "2026-08-20T08:00:00Z"
    assert ev["status"] == "loaded"
    assert ev["location"] == "Shanghai"
    assert ev["location_code"] == "CNSHA"
    assert ev["vessel"] == "MSC ISABELLA"
    assert ev["voyage"] == "FD432R"


def test_normalize_container_shipment():
    raw = {
        "container_number": "MSCU1234566",
        "shipping_line": "MSC Mediterranean Shipping",
        "status": "Underway at Sea",
        "vessel_name": "MSC ISABELLA",
        "voyage_number": "FD432R",
        "origin_port": "Shanghai, China (CNSHA)",
        "destination_port": "Rotterdam, Netherlands (NLRTM)",
        "estimated_arrival": "2026-09-15T14:00:00Z",
        "events": [
            {
                "timestamp": "2026-08-20T08:00:00Z",
                "status": "Gate In",
                "description": "Container received at terminal",
                "location": "Shanghai (CNSHA)"
            }
        ]
    }
    norm = normalize_container_shipment(raw)
    assert norm["shipment_type"] == "ocean_container"
    assert norm["container_number"] == "MSCU1234566"
    assert norm["shipping_line"] == "msc"
    assert norm["status"] == "in_transit"
    assert norm["origin_port_code"] == "CNSHA"
    assert norm["destination_port_code"] == "NLRTM"
    assert len(norm["events"]) == 1
    assert norm["events"][0]["status"] == "gate_in"
