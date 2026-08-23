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


# ---------------------------------------------------------------------------
# Reliability improvements: candidate association, validation, consistency
# ---------------------------------------------------------------------------

def test_nested_candidates_are_collapsed_not_treated_as_contradiction():
    """An event sentence containing the vessel name is consistent evidence,
    not a conflicting candidate - the concise value must win."""
    html = """
    <html><body>
      <div class="timeline">
        <div class="event">Container laden on board MSC ISABELLA at CNSHA on 2026-09-01 08:30</div>
        <div class="event">Departed Shanghai on 2026-09-02</div>
      </div>
      <dl><dt>Vessel Name</dt><dd>MSC ISABELLA</dd></dl>
      <table>
        <tr><th>Origin</th><td>Shanghai, China</td></tr>
        <tr><th>Destination</th><td>Rotterdam, Netherlands</td></tr>
        <tr><th>Status</th><td>In Transit</td></tr>
      </table>
      <p>Container MSCU1234566 · Voyage FD432R</p>
    </body></html>
    """
    data, telemetry = extract_with_self_healing(html)
    assert telemetry.extraction_status == "healed"
    assert data["vessel_name"] == "MSC ISABELLA"


def test_conflicting_equal_strength_candidates_are_refused():
    """Two equally strong, mutually exclusive vessel candidates must not be
    resolved by guessing."""
    html = """
    <html><body>
      <section class="card-a"><span>Vessel</span> <b>MV OCEAN QUEEN</b></section>
      <section class="card-b"><span>Vessel</span> <b>MV SEA PHOENIX</b></section>
      <p>Container MSCU1234566</p>
    </body></html>
    """
    data, telemetry = extract_with_self_healing(html)
    # Either no vessel is claimed at all, or the refusal is logged - never a coin flip.
    if data.get("vessel_name"):
        raise AssertionError("ambiguous vessel candidates must not be silently resolved")
    assert any("vessel" in log.lower() and ("ambiguit" in log.lower() or "refus" in log.lower())
               for log in telemetry.diagnostic_log)


def test_implausible_eta_candidate_is_discarded():
    """A non-parseable value near an ETA label must never become the ETA."""
    html = """
    <html><body>
      <div><dt>ETA</dt><dd>upon vessel departure confirmation</dd></div>
      <p>Shipment MSCU1234566 from Shanghai to Rotterdam, status in transit.</p>
    </body></html>
    """
    data, _ = extract_with_self_healing(html)
    assert not data.get("estimated_arrival")


def test_identical_origin_and_destination_is_rejected_as_conflicting():
    html = """
    <html><body>
      <table>
        <tr><th>Origin</th><td>Singapore</td></tr>
        <tr><th>Destination</th><td>Singapore</td></tr>
        <tr><th>Status</th><td>In Transit</td></tr>
      </table>
      <p>Container MSCU1234566 voyage FD432R</p>
    </body></html>
    """
    data, telemetry = extract_with_self_healing(html)
    ports = {data.get("origin_port"), data.get("destination_port")}
    assert "Singapore" not in ports
    assert any("identical" in log.lower() for log in telemetry.diagnostic_log)
