"""
Self-Healing Extraction Layer for StayTrace.
Extracts logistics and shipment data from changing, redesigned, or unstructured web sources.
Demonstrates deterministic candidate discovery, semantic proximity recovery,
table structural inference, confidence evaluation, and safe ambiguity rejection.
"""

from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from bs4 import BeautifulSoup, Tag, NavigableString

from scraper.validator import (
    is_valid_container_number,
    is_valid_bol_number,
    detect_shipping_line,
    calculate_iso6346_check_digit,
)
from pipeline.normalize import (
    normalize_container_shipment,
    normalize_ocean_status,
    normalize_shipping_line,
    normalize_timestamp,
    extract_locode_and_port,
    normalize_ocean_event,
)

logger = logging.getLogger("staytrace.self_healing")

CONFIDENCE_THRESHOLD = 0.70


@dataclass
class ExtractionTelemetry:
    """Structured telemetry recording extraction attempts, failures, and recoveries."""
    extraction_status: str = "normal"  # "normal", "healed", "failed"
    original_strategy_status: str = "passed"  # "passed", "failed"
    failed_fields: List[str] = field(default_factory=list)
    recovery_strategy: str = "none"  # "semantic_label_proximity", "structural_table_inference", "composite_semantic_recovery", "none"
    recovered_fields: List[str] = field(default_factory=list)
    validation_result: str = "passed"  # "passed", "rejected_ambiguous", "failed"
    confidence: float = 1.0
    diagnostic_log: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Semantic label mappings for finding fields in unstructured or redesigned DOM trees
SEMANTIC_ANCHORS = {
    "container_number": [
        r"\b(container\s*(no|number|id|#)|unit\s*(no|number|id)|equipment\s*(id|no|number))\b",
    ],
    "shipping_line": [
        r"\b(shipping\s*line|ocean\s*carrier|carrier|operator|line|vessel\s*operator)\b",
    ],
    "status": [
        r"\b(current\s*status|shipment\s*status|status|cargo\s*status|stage|milestone)\b",
    ],
    "vessel_name": [
        r"\b(vessel\s*name|vessel|mother\s*vessel|feeder\s*vessel|ship\s*name|ship)\b",
    ],
    "voyage_number": [
        r"\b(voyage\s*number|voyage\s*no|voyage|voy\s*#|voy\.|voyage\s*id)\b",
    ],
    "origin_port": [
        r"\b(port\s*of\s*loading|place\s*of\s*receipt|pol|origin\s*port|origin|load\s*port|loading\s*terminal|from)\b",
    ],
    "destination_port": [
        r"\b(port\s*of\s*discharge|place\s*of\s*delivery|pod|destination\s*port|destination|discharge\s*port|discharge\s*terminal|to)\b",
    ],
    "estimated_arrival": [
        r"\b(estimated\s*time\s*of\s*arrival|estimated\s*arrival|est\.\s*arrival|expected\s*arrival|eta|arrival\s*date)\b",
    ],
    "estimated_departure": [
        r"\b(estimated\s*time\s*of\s*departure|estimated\s*departure|est\.\s*departure|expected\s*departure|etd|departure\s*date)\b",
    ],
}


class BaselineOceanExtractor:
    """
    Brittle baseline extractor that relies on expected standard CSS class selectors.
    Simulates a traditional rigid web scraper that breaks on website redesigns.
    """

    @staticmethod
    def extract(soup: BeautifulSoup) -> Dict[str, Any]:
        data: Dict[str, Any] = {}

        # Brittle selector lookups
        cntr_elem = soup.select_one(".container-number, #container-number, .cntr-id")
        if cntr_elem:
            data["container_number"] = cntr_elem.get_text(strip=True)

        line_elem = soup.select_one(".shipping-line, #shipping-line, .carrier-title")
        if line_elem:
            data["shipping_line"] = line_elem.get_text(strip=True)

        status_elem = soup.select_one(".shipment-status, #shipment-status, .status-badge")
        if status_elem:
            data["status"] = status_elem.get_text(strip=True)

        vessel_elem = soup.select_one(".vessel-name, #vessel-name, .ship-title")
        if vessel_elem:
            data["vessel_name"] = vessel_elem.get_text(strip=True)

        voyage_elem = soup.select_one(".voyage-number, #voyage-number, .voyage-id")
        if voyage_elem:
            data["voyage_number"] = voyage_elem.get_text(strip=True)

        origin_elem = soup.select_one(".origin-port, #origin-port, .pol-location")
        if origin_elem:
            data["origin_port"] = origin_elem.get_text(strip=True)

        dest_elem = soup.select_one(".destination-port, #destination-port, .pod-location")
        if dest_elem:
            data["destination_port"] = dest_elem.get_text(strip=True)

        eta_elem = soup.select_one(".eta-date, #eta-date, .delivery-eta")
        if eta_elem:
            data["estimated_arrival"] = eta_elem.get_text(strip=True)

        # Checkpoints
        events = []
        for row in soup.select(".checkpoint-row, tr.event-row"):
            ts = row.select_one(".event-time, .col-time")
            st = row.select_one(".event-status, .col-status")
            desc = row.select_one(".event-desc, .col-desc")
            loc = row.select_one(".event-loc, .col-loc")
            if ts and (st or desc):
                events.append({
                    "timestamp": ts.get_text(strip=True),
                    "status": st.get_text(strip=True) if st else "unknown",
                    "description": desc.get_text(strip=True) if desc else "",
                    "location": loc.get_text(strip=True) if loc else "",
                })
        if events:
            data["events"] = events

        return data


class SelfHealingExtractor:
    """
    Self-healing extraction engine that performs semantic candidate discovery,
    structural label proximity recovery, tabular sequence reconstruction,
    and strict ambiguity detection.
    """

    def __init__(self, confidence_threshold: float = CONFIDENCE_THRESHOLD):
        self.confidence_threshold = confidence_threshold

    def _clean_soup(self, html: str) -> BeautifulSoup:
        soup = BeautifulSoup(html, "html.parser")
        # Remove noisy tags
        for tag in soup(["script", "style", "noscript", "svg", "header", "footer"]):
            tag.decompose()
        return soup

    def _find_value_near_label(self, label_elem: Tag, pattern: str) -> Optional[str]:
        """Look for adjacent value element or text node near a semantic label."""
        elem_text = label_elem.get_text(strip=True)

        # 1. Check if label element contains inline label: value format
        if ":" in elem_text:
            match = re.search(pattern, elem_text, re.IGNORECASE)
            if match:
                parts = elem_text.split(":", 1)
                val = parts[1].strip()
                if val and len(val) < 150:
                    return val

        # 2. Next sibling element or text of the label
        sibling = label_elem.find_next_sibling()
        if sibling and isinstance(sibling, Tag):
            text = sibling.get_text(strip=True)
            if text and len(text) < 150:
                return text

        # 3. If label is in table cell <th> or <td>, check next <td>
        parent = label_elem.parent
        if parent:
            if parent.name in ("th", "td"):
                next_cell = parent.find_next_sibling(["td", "th"])
                if next_cell:
                    text = next_cell.get_text(strip=True)
                    if text and len(text) < 150:
                        return text
            elif parent.name in ("dt", "label"):
                next_elem = parent.find_next_sibling(["dd", "div", "span", "p"])
                if next_elem:
                    text = next_elem.get_text(strip=True)
                    if text and len(text) < 150:
                        return text

        # 4. Check next tag in document tree if within same parent
        next_tag = label_elem.find_next()
        if next_tag and next_tag != label_elem and label_elem.parent == next_tag.parent:
            text = next_tag.get_text(strip=True)
            if text and len(text) < 150 and not re.search(pattern, text, re.IGNORECASE):
                return text

        return None

    def discover_semantic_fields(self, soup: BeautifulSoup) -> Dict[str, List[Tuple[str, float]]]:
        """
        Scan DOM for semantic label matches and extract candidate values with evidence weights.
        Returns: {field_name: [(candidate_value, score), ...]}
        """
        candidates: Dict[str, List[Tuple[str, float]]] = {k: [] for k in SEMANTIC_ANCHORS}

        for element in soup.find_all(True):
            # Only consider elements that are leaf tags or direct containers with short label text
            if element.find_all(True) and len(element.get_text(strip=True)) > 40:
                continue

            elem_text = element.get_text(strip=True)
            if not elem_text or len(elem_text) > 80:
                continue

            for field_name, patterns in SEMANTIC_ANCHORS.items():
                for pat in patterns:
                    if re.search(pat, elem_text, re.IGNORECASE):
                        val = self._find_value_near_label(element, pat)
                        if val:
                            clean_val = re.sub(r"^[:\-\s]+", "", val).strip()
                            if clean_val and not re.match(pat, clean_val, re.IGNORECASE):
                                score = 0.95 if element.name in ("th", "dt", "label") else 0.85
                                candidates[field_name].append((clean_val, score))

        return candidates

    def recover_container_number(self, soup: BeautifulSoup, candidates: List[Tuple[str, float]]) -> Optional[str]:
        """Discover ISO 6346 container number from candidates or regex scan."""
        # Check label candidates first
        for val, _ in candidates:
            m = re.search(r"([A-Z]{3}[UJZ]\d{7})", val.upper().replace(" ", ""))
            if m and is_valid_container_number(m.group(1)):
                return m.group(1)

        # Full DOM scan for ISO 6346 container pattern
        full_text = soup.get_text()
        matches = re.findall(r"\b([A-Z]{3}[UJZ]\d{7})\b", full_text.upper().replace(" ", ""))
        valid_containers = [c for c in matches if is_valid_container_number(c)]
        if valid_containers:
            return valid_containers[0]
        if matches:
            return matches[0]

        return None

    def recover_timeline_events(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Recover chronological event checkpoints from tables, lists, or timeline blocks."""
        recovered_events: List[Dict[str, Any]] = []

        # Strategy 1: Look for table rows containing timestamps
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 2:
                row_text = " | ".join(c.get_text(strip=True) for c in cells)
                ts_match = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(:\d{2})?|\b[A-Za-z]{3}\s+\d{1,2},?\s+\d{4})", row_text)
                if ts_match:
                    ts = normalize_timestamp(ts_match.group(1))
                    # Check for status keyword
                    st = normalize_ocean_status(row_text)
                    loc = None
                    desc = None

                    for c in cells:
                        ctext = c.get_text(strip=True)
                        if ctext and not re.search(r"\d{4}[-/]\d{2}", ctext):
                            if any(k in ctext.lower() for k in ["port", "terminal", "cy", "gate", "cns", "sgs", "usl", "hub"]):
                                loc = ctext
                            elif len(ctext) > 5:
                                desc = ctext

                    if ts:
                        recovered_events.append({
                            "timestamp": ts,
                            "status": st,
                            "description": desc or row_text[:80],
                            "location": loc or "",
                        })

        # Strategy 2: Look for list items or card blocks if table recovery yielded nothing
        if not recovered_events:
            for item in soup.find_all(["li", "div"]):
                classes = " ".join(item.get("class", [])).lower()
                if any(kw in classes for kw in ["timeline", "event", "checkpoint", "history", "milestone"]):
                    item_text = item.get_text(" ", strip=True)
                    ts_match = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(:\d{2})?|\b[A-Za-z]{3}\s+\d{1,2},?\s+\d{4})", item_text)
                    if ts_match:
                        ts = normalize_timestamp(ts_match.group(1))
                        st = normalize_ocean_status(item_text)
                        if ts:
                            recovered_events.append({
                                "timestamp": ts,
                                "status": st,
                                "description": item_text[:100],
                                "location": "",
                            })

        # Deduplicate and sort
        deduped = []
        seen = set()
        for ev in recovered_events:
            sig = f"{ev.get('timestamp')}|{ev.get('status')}"
            if sig not in seen:
                seen.add(sig)
                deduped.append(ev)

        return sorted(deduped, key=lambda x: str(x.get("timestamp") or ""))

    def detect_ambiguity(self, field_name: str, candidates: List[Tuple[str, float]]) -> bool:
        """
        Check whether candidates for a critical single-value field contain
        strong contradictory signals with equal confidence that cannot be disambiguated.
        """
        if len(candidates) < 2:
            return False

        # If candidates have distinct contradictory values with identical highest score
        unique_vals = list({val.strip().lower() for val, _ in candidates if val.strip()})
        if len(unique_vals) > 1:
            # Check if top scores are equally high
            top_score = max(score for _, score in candidates)
            top_candidates = [val for val, score in candidates if score == top_score]
            if len(set(top_candidates)) > 1:
                return True

        return False

    def extract_with_healing(self, html: str, shipment_type: str = "ocean_container") -> Tuple[Dict[str, Any], ExtractionTelemetry]:
        """
        Execute baseline extraction, detect failures, apply semantic recovery,
        evaluate confidence, and reject ambiguous data safely.
        """
        telemetry = ExtractionTelemetry(timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        soup = self._clean_soup(html)

        # 1. Attempt Baseline Extraction
        baseline_data = BaselineOceanExtractor.extract(soup)
        telemetry.diagnostic_log.append("Executed baseline rigid extractor.")

        # Check required fields for ocean container
        required_fields = ["container_number", "status", "destination_port", "origin_port"]
        missing_fields = [f for f in required_fields if not baseline_data.get(f)]

        if not missing_fields and baseline_data.get("container_number") and is_valid_container_number(baseline_data.get("container_number")):
            # Baseline succeeded cleanly
            telemetry.extraction_status = "normal"
            telemetry.original_strategy_status = "passed"
            telemetry.validation_result = "passed"
            telemetry.confidence = 1.0
            telemetry.diagnostic_log.append("Baseline extraction succeeded with complete field coverage.")
            return normalize_container_shipment(baseline_data), telemetry

        # 2. Baseline Failed -> Activate Self-Healing
        telemetry.original_strategy_status = "failed"
        telemetry.failed_fields = missing_fields
        telemetry.recovery_strategy = "composite_semantic_recovery"
        telemetry.diagnostic_log.append(f"Baseline extraction failed missing fields: {', '.join(missing_fields)}. Activating self-healing recovery.")

        candidates = self.discover_semantic_fields(soup)
        recovered_data = dict(baseline_data)
        recovered_field_names: List[str] = []

        # Recover Container Number
        cntr_no = self.recover_container_number(soup, candidates.get("container_number", []))
        if cntr_no:
            recovered_data["container_number"] = cntr_no
            recovered_data["tracking_number"] = cntr_no
            recovered_field_names.append("container_number")
            telemetry.diagnostic_log.append(f"Recovered container number: {cntr_no}")

        # Recover Shipping Line
        line_candidates = candidates.get("shipping_line", [])
        if line_candidates:
            recovered_data["shipping_line"] = line_candidates[0][0]
            recovered_field_names.append("shipping_line")
        elif cntr_no:
            inferred_line = detect_shipping_line(cntr_no)
            if inferred_line:
                recovered_data["shipping_line"] = inferred_line
                recovered_field_names.append("shipping_line")

        # Recover Status
        status_candidates = candidates.get("status", [])
        if status_candidates:
            recovered_data["status"] = status_candidates[0][0]
            recovered_field_names.append("status")
            telemetry.diagnostic_log.append(f"Recovered status: {status_candidates[0][0]}")

        # Recover Ports and check for ambiguity
        origin_candidates = candidates.get("origin_port", [])
        if origin_candidates:
            if self.detect_ambiguity("origin_port", origin_candidates):
                telemetry.diagnostic_log.append("Ambiguity detected in origin port candidates.")
            recovered_data["origin_port"] = origin_candidates[0][0]
            recovered_field_names.append("origin_port")

        dest_candidates = candidates.get("destination_port", [])
        ambiguous_destination = False
        if dest_candidates:
            if self.detect_ambiguity("destination_port", dest_candidates):
                ambiguous_destination = True
                telemetry.diagnostic_log.append("Severe ambiguity: conflicting destination ports with equal evidence.")
            recovered_data["destination_port"] = dest_candidates[0][0]
            recovered_field_names.append("destination_port")

        # Recover Vessel & Voyage
        vessel_candidates = candidates.get("vessel_name", [])
        if vessel_candidates:
            recovered_data["vessel_name"] = vessel_candidates[0][0]
            recovered_field_names.append("vessel_name")

        voyage_candidates = candidates.get("voyage_number", [])
        if voyage_candidates:
            recovered_data["voyage_number"] = voyage_candidates[0][0]
            recovered_field_names.append("voyage_number")

        # Recover ETA
        eta_candidates = candidates.get("estimated_arrival", [])
        if eta_candidates:
            recovered_data["estimated_arrival"] = eta_candidates[0][0]
            recovered_field_names.append("estimated_arrival")

        # Recover Checkpoint Events
        recovered_events = self.recover_timeline_events(soup)
        if recovered_events:
            recovered_data["events"] = recovered_events
            recovered_field_names.append("events")
            telemetry.diagnostic_log.append(f"Recovered {len(recovered_events)} event checkpoints.")

        telemetry.recovered_fields = recovered_field_names

        # 3. Calculate Mathematical Confidence Score
        confidence = 0.0
        # Field weights
        if recovered_data.get("container_number"):
            if is_valid_container_number(recovered_data["container_number"]):
                confidence += 0.30
            else:
                confidence += 0.10

        if recovered_data.get("status") and normalize_ocean_status(recovered_data["status"]) != "unknown":
            confidence += 0.25
        if recovered_data.get("destination_port"):
            confidence += 0.15
        if recovered_data.get("origin_port"):
            confidence += 0.15
        if recovered_data.get("events"):
            confidence += 0.10
        if recovered_data.get("vessel_name"):
            confidence += 0.05

        # Penalties for ambiguity or invalid checksum
        if ambiguous_destination:
            confidence -= 0.40
            telemetry.diagnostic_log.append("Penalized confidence score due to contradictory destination evidence.")

        confidence = max(0.0, min(1.0, round(confidence, 2)))
        telemetry.confidence = confidence

        # 4. Evaluation and Safe Ambiguity Rejection
        if ambiguous_destination or confidence < self.confidence_threshold:
            telemetry.extraction_status = "failed"
            telemetry.validation_result = "rejected_ambiguous"
            telemetry.diagnostic_log.append(f"Confidence score {confidence} below threshold {self.confidence_threshold} or ambiguous. Recovery rejected.")
            # Return partial/empty canonical state marked as failed
            recovered_data["healing_status"] = "failed"
            recovered_data["healing_confidence"] = confidence
            recovered_data["healing_details"] = json.dumps(telemetry.to_dict())
            return normalize_container_shipment(recovered_data), telemetry

        # Successful Self-Healing
        telemetry.extraction_status = "healed"
        telemetry.validation_result = "passed"
        telemetry.diagnostic_log.append(f"Self-healing successfully recovered shipment data with confidence {confidence}.")

        recovered_data["healing_status"] = "healed"
        recovered_data["healing_confidence"] = confidence
        recovered_data["healing_details"] = json.dumps(telemetry.to_dict())

        normalized = normalize_container_shipment(recovered_data)
        return normalized, telemetry


def extract_with_self_healing(
    html: str,
    shipment_type: str = "ocean_container",
) -> Tuple[Dict[str, Any], ExtractionTelemetry]:
    """Top-level functional interface for running self-healing extraction."""
    extractor = SelfHealingExtractor()
    return extractor.extract_with_healing(html, shipment_type=shipment_type)
