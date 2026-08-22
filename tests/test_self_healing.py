import pytest
from pathlib import Path
from scraper.self_healing import (
    extract_with_self_healing,
    SelfHealingExtractor,
    BaselineOceanExtractor,
    ExtractionTelemetry,
    CONFIDENCE_THRESHOLD,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ocean"


def test_baseline_extractor_succeeds_on_original_page():
    html = (FIXTURES_DIR / "original_page.html").read_text(encoding="utf-8")
    data, telemetry = extract_with_self_healing(html)

    assert telemetry.extraction_status == "normal"
    assert telemetry.original_strategy_status == "passed"
    assert telemetry.validation_result == "passed"
    assert telemetry.confidence == 1.0
    assert data["container_number"] == "MSCU1234566"
    assert data["status"] == "in_transit"
    assert "Rotterdam" in data["destination_port"]
    assert "Shanghai" in data["origin_port"]


def test_self_healing_recovers_on_redesigned_page():
    html = (FIXTURES_DIR / "redesigned_page.html").read_text(encoding="utf-8")
    data, telemetry = extract_with_self_healing(html)

    # Baseline failed, self-healing activated and succeeded
    assert telemetry.original_strategy_status == "failed"
    assert "container_number" in telemetry.failed_fields
    assert telemetry.extraction_status == "healed"
    assert telemetry.validation_result == "passed"
    assert telemetry.confidence >= CONFIDENCE_THRESHOLD

    # Verified recovered fields
    assert data["container_number"] == "MSCU1234566"
    assert data["shipping_line"] == "msc"
    assert data["status"] == "in_transit"
    assert data["vessel_name"] == "MSC ISABELLA"
    assert data["voyage_number"] == "FD432R"
    assert "Shanghai" in data["origin_port"]
    assert "Rotterdam" in data["destination_port"]
    assert len(data["events"]) == 3


def test_self_healing_safely_rejects_ambiguous_evidence():
    html = (FIXTURES_DIR / "ambiguous_page.html").read_text(encoding="utf-8")
    data, telemetry = extract_with_self_healing(html)

    # Safe rejection when signals are conflicting/insufficient
    assert telemetry.extraction_status == "failed"
    assert telemetry.validation_result == "rejected_ambiguous"
    assert telemetry.confidence < CONFIDENCE_THRESHOLD
    assert any("ambiguity" in log.lower() for log in telemetry.diagnostic_log)


def test_telemetry_serialization():
    telemetry = ExtractionTelemetry(
        extraction_status="healed",
        original_strategy_status="failed",
        failed_fields=["destination_port"],
        recovery_strategy="composite_semantic_recovery",
        recovered_fields=["destination_port"],
        validation_result="passed",
        confidence=0.92,
        diagnostic_log=["Recovered destination_port"],
    )
    d = telemetry.to_dict()
    assert d["extraction_status"] == "healed"
    assert d["confidence"] == 0.92
    assert "timestamp" in d
