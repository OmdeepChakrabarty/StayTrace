"""
Bright Data external-service boundary for ParcelPulse.
Encapsulates all communication with Bright Data Web Unlocker / Scraping API.
Mockable, testable, zero hardcoded secrets.
"""

from __future__ import annotations

import os
import time
import requests
from typing import Any, Dict, List, Optional
from pipeline.normalize import normalize_parcel, normalize_carrier, normalize_tracking_number
from scraper.validator import is_valid_tracking_number, ValidationError


class BrightDataError(Exception):
    """Base exception for Bright Data API errors."""
    pass


class BrightDataAuthError(BrightDataError):
    """Raised when authentication fails (401/403)."""
    pass


class BrightDataRateLimitError(BrightDataError):
    """Raised when request is rate limited (429)."""
    pass


class BrightDataNotFoundError(BrightDataError):
    """Raised when tracking entity is not found (404)."""
    pass


class BrightDataTimeoutError(BrightDataError):
    """Raised when request times out."""
    pass


class BrightDataNetworkError(BrightDataError):
    """Raised on connection error."""
    pass


CARRIER_TRACKING_URLS = {
    "usps": "https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={tracking_number}",
    "ups": "https://www.ups.com/track?tracknum={tracking_number}",
    "dhl": "https://www.dhl.com/en/express/tracking.html?AWB={tracking_number}",
    "amazon": "https://track.amazon.com/tracking/{tracking_number}",
    "ontrac": "https://www.ontrac.com/tracking/?number={tracking_number}",
}


class BrightDataClient:
    """Client for interacting with Bright Data Web Unlocker & Scraping APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        zone: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key or os.environ.get("BRIGHTDATA_API_KEY", "")
        self.zone = zone or os.environ.get("BRIGHTDATA_ZONE", "web_unlocker")
        self.endpoint = (endpoint or os.environ.get("BRIGHTDATA_ENDPOINT", "https://api.brightdata.com")).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()

    def build_tracking_url(self, carrier: str, tracking_number: str) -> str:
        """Construct the direct tracking webpage URL for a given carrier and tracking number."""
        norm_carrier = normalize_carrier(carrier)
        norm_tracking = normalize_tracking_number(tracking_number)

        template = CARRIER_TRACKING_URLS.get(norm_carrier)
        if template:
            return template.format(tracking_number=norm_tracking)
        return f"https://www.google.com/search?q={norm_carrier}+{norm_tracking}+tracking"

    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with authorization."""
        if not self.api_key:
            raise BrightDataAuthError("Bright Data API key is required. Set BRIGHTDATA_API_KEY environment variable.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ParcelPulse/1.0",
        }

    def unlock_url(self, target_url: str, format: str = "raw") -> requests.Response:
        """Request page content or data through Bright Data Web Unlocker."""
        headers = self._get_headers()
        payload = {
            "zone": self.zone,
            "url": target_url,
            "format": format,
        }
        api_url = f"{self.endpoint}/request"

        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )

                if response.status_code in (401, 403):
                    raise BrightDataAuthError(f"Authentication failed with status {response.status_code}: {response.text}")
                elif response.status_code == 404:
                    raise BrightDataNotFoundError(f"Tracking resource not found (404) for URL: {target_url}")
                elif response.status_code == 429:
                    if attempt < self.max_retries:
                        time.sleep(0.5 * attempt)
                        continue
                    raise BrightDataRateLimitError("Bright Data rate limit exceeded (429)")
                elif response.status_code >= 500:
                    if attempt < self.max_retries:
                        time.sleep(0.5 * attempt)
                        continue
                    raise BrightDataError(f"Bright Data server error ({response.status_code}): {response.text}")

                response.raise_for_status()
                return response

            except requests.exceptions.Timeout as e:
                last_exception = BrightDataTimeoutError(f"Request timed out for {target_url}: {e}")
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
                    continue
            except requests.exceptions.ConnectionError as e:
                last_exception = BrightDataNetworkError(f"Connection error connecting to Bright Data: {e}")
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
                    continue
            except (BrightDataAuthError, BrightDataNotFoundError, BrightDataRateLimitError, BrightDataError):
                raise
            except requests.exceptions.RequestException as e:
                last_exception = BrightDataError(f"Request failed: {e}")
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
                    continue

        if last_exception:
            raise last_exception
        raise BrightDataError(f"Failed to fetch {target_url} after {self.max_retries} attempts")

    def fetch_tracking_raw(self, carrier: str, tracking_number: str) -> Dict[str, Any]:
        """Fetch raw tracking data via Bright Data."""
        norm_carrier = normalize_carrier(carrier)
        norm_tracking = normalize_tracking_number(tracking_number)

        if norm_carrier != "other" and not is_valid_tracking_number(norm_carrier, norm_tracking):
            raise ValidationError(f"Invalid tracking number {norm_tracking} for carrier {norm_carrier}")

        target_url = self.build_tracking_url(norm_carrier, norm_tracking)
        response = self.unlock_url(target_url, format="json")

        try:
            return response.json()
        except Exception:
            return {
                "tracking_number": norm_tracking,
                "carrier": norm_carrier,
                "raw_html": response.text,
                "status": "unknown",
            }

    def fetch_tracking(self, carrier: str, tracking_number: str) -> Dict[str, Any]:
        """Fetch tracking data and return canonical normalized parcel dictionary."""
        raw_data = self.fetch_tracking_raw(carrier, tracking_number)
        return normalize_parcel(raw_data)

    def batch_fetch_tracking(self, requests_list: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Fetch tracking for multiple parcels."""
        results: List[Dict[str, Any]] = []
        for item in requests_list:
            carrier = item.get("carrier", "other")
            tracking_number = item.get("tracking_number", "")
            try:
                parcel = self.fetch_tracking(carrier, tracking_number)
                results.append(parcel)
            except Exception as e:
                results.append({
                    "tracking_number": normalize_tracking_number(tracking_number),
                    "carrier": normalize_carrier(carrier),
                    "error": str(e),
                    "status": "unknown",
                })
        return results
