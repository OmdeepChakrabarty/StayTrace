"""
Bright Data Scraping Browser session layer for StayTrace.

Runtime auto-discovery:
    BRIGHTDATA_API_KEY -> locate the account's browser_api zone
                       -> derive customer id + zone password (in memory only)
                       -> connect over CDP to Bright Data's remote browser

Credentials are never logged, persisted, or returned by any public function.
Used only for official carrier sources that require a real session-based
browser flow (e.g. CSRF-token form POSTs) that stateless Web Unlocker
requests cannot complete.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from websocket import create_connection  # websocket-client

DEFAULT_BRIGHTDATA_ENDPOINT = "https://api.brightdata.com"
DEFAULT_WS_HOST = "wss://brd.superproxy.io"
DEFAULT_WS_PORT = 9222


class BrowserSessionError(Exception):
    """Raised when the Scraping Browser session cannot be established or completed."""
    pass


_credentials_lock = threading.Lock()
_credentials_cache: Optional[Dict[str, str]] = None


def reset_credentials_cache() -> None:
    """Test helper / rotation support: forget cached credentials."""
    global _credentials_cache
    with _credentials_lock:
        _credentials_cache = None


def discover_browser_credentials(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    zone: Optional[str] = None,
    use_cache: bool = True,
) -> Dict[str, str]:
    """
    Auto-discover Scraping Browser credentials using only BRIGHTDATA_API_KEY.

    Returns {"customer_id": ..., "zone": ..., "password": ...}.
    Values are sensitive: callers must keep them in memory only.
    Raises BrowserSessionError with non-sensitive messages on failure.
    """
    global _credentials_cache

    if use_cache:
        with _credentials_lock:
            if _credentials_cache is not None:
                return dict(_credentials_cache)

    key = api_key if api_key is not None else __import__("os").environ.get("BRIGHTDATA_API_KEY", "")
    base = (endpoint or DEFAULT_BRIGHTDATA_ENDPOINT).rstrip("/")
    headers = {"Authorization": f"Bearer {key}"}

    if not key:
        raise BrowserSessionError(
            "BRIGHTDATA_API_KEY is required to auto-discover Scraping Browser credentials."
        )

    try:
        # 1. Locate the browser_api zone
        resp = requests.get(f"{base}/zone/get_active_zones", headers=headers, timeout=30)
        resp.raise_for_status()
        zones = resp.json()
        browser_zone = zone
        if not browser_zone:
            for item in zones:
                if item.get("type") == "browser_api":
                    browser_zone = item.get("name")
                    break
        if not browser_zone:
            raise BrowserSessionError(
                "No Scraping Browser (browser_api) zone found on this Bright Data account."
            )

        # 2. Customer id is the top-level key of the per-zone cost report
        resp = requests.get(f"{base}/zone/cost?zone={browser_zone}", headers=headers, timeout=30)
        resp.raise_for_status()
        cost = resp.json()
        customer_id = next(iter(cost.keys()), None)
        if not customer_id:
            raise BrowserSessionError("Could not derive customer id from zone cost report.")

        # 3. Zone password (kept in memory only; never logged)
        resp = requests.get(f"{base}/zone/passwords?zone={browser_zone}", headers=headers, timeout=30)
        resp.raise_for_status()
        passwords = resp.json().get("passwords") or []
        if not passwords:
            raise BrowserSessionError("Browser zone password list is empty.")
        password = passwords[0]

    except requests.exceptions.RequestException as e:
        raise BrowserSessionError(f"Bright Data credential discovery request failed: {type(e).__name__}")
    except (ValueError, KeyError, IndexError, StopIteration):
        raise BrowserSessionError("Unexpected response shape during credential discovery.")

    creds = {"customer_id": customer_id, "zone": browser_zone, "password": password}

    if use_cache:
        with _credentials_lock:
            _credentials_cache = dict(creds)

    return dict(creds)


class _CdpBrowser:
    """Minimal raw CDP client over a websocket to Bright Data's remote browser."""

    def __init__(
        self,
        credentials: Dict[str, str],
        host: str = DEFAULT_WS_HOST,
        port: int = DEFAULT_WS_PORT,
        connect_timeout: float = 60.0,
    ):
        username = f"brd-customer-{credentials['customer_id']}-zone-{credentials['zone']}"
        raw_token = f"{username}:{credentials['password']}".encode("utf-8")
        auth_header = "Authorization: Basic " + base64.b64encode(raw_token).decode("ascii")
        self._ws = create_connection(
            f"{host}:{port}",
            header=[auth_header],
            timeout=connect_timeout,
            enable_multithread=True,
        )
        self._next_id = 0
        self._pending_events: List[Dict[str, Any]] = []

    def command(self, method: str, session_id: Optional[str] = None, timeout: float = 90.0, **params) -> Any:
        self._next_id += 1
        msg_id = self._next_id
        message: Dict[str, Any] = {"id": msg_id, "method": method, "params": params}
        if session_id:
            message["sessionId"] = session_id
        self._ws.send(json.dumps(message))

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserSessionError(f"Timed out waiting for CDP response to {method}")
            self._ws.settimeout(max(0.5, remaining))
            raw = self._ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise BrowserSessionError(f"CDP error for {method}: {data['error'].get('message')}")
                return data.get("result")
            if "method" in data:
                self._pending_events.append(data)

    def wait_for_event(self, method: str, session_id: str, timeout: float = 90.0) -> Optional[Dict[str, Any]]:
        deadline = time.monotonic() + timeout
        while True:
            for i, ev in enumerate(self._pending_events):
                if ev.get("method") == method and ev.get("sessionId") == session_id:
                    return self._pending_events.pop(i)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._ws.settimeout(max(0.5, remaining))
            try:
                raw = self._ws.recv()
            except Exception:
                continue
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if "method" in data:
                self._pending_events.append(data)

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


_FILL_VALUE_JS = """
(() => {
  const el = document.querySelector(%(selector)s);
  if (!el) return false;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  ).set;
  setter.call(el, %(value)s);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})()
"""

_CLICK_JS = """
(() => {
  const el = document.querySelector(%(selector)s);
  if (!el) return false;
  el.click();
  return true;
})()
"""

_MARKER_CHECK_JS = """
(() => {
  return { success: %(success_expr)s };
})()
"""

_NOT_READY_JS = """
(() => {
  const el = document.querySelector(%(selector)s);
  const visible = !!(el && (el.offsetParent !== null || document.activeElement === el));
  const captcha = /captcha-delivery\\.com/.test(document.documentElement.outerHTML);
  return !visible || captcha;
})()
"""


def fetch_rendered_html(
    start_url: str,
    fill: Optional[Dict[str, str]] = None,
    submit_selector: Optional[str] = None,
    ready_selector: Optional[str] = None,
    success_js: Optional[str] = None,
    max_page_wait: float = 60.0,
    poll_interval: float = 2.0,
    overall_timeout: float = 240.0,
) -> str:
    """
    Run a single remote-browser session against an official carrier page and
    return the final rendered HTML.

    Flow: enable CAPTCHA auto-solve -> navigate -> optionally fill a field +
    click submit within the same session (preserving cookies/CSRF tokens) ->
    wait until success_js evaluates true (or timeout) -> return outerHTML.

    If ready_selector is given, interaction waits until that element is present
    (anti-bot interstitials such as DataDome challenges resolve automatically).

    success_js must be a carrier-defined JavaScript boolean expression so that
    only genuinely rendered tracking results count as success - never URL
    query strings, referer echoes in anti-bot pages, or script scaffolding.
    """
    if not success_js:
        raise BrowserSessionError("A carrier-specific success_js expression is required.")
    credentials = discover_browser_credentials()

    try:
        browser = _CdpBrowser(credentials)
    except Exception as e:
        raise BrowserSessionError(f"Could not connect to Scraping Browser: {type(e).__name__}")

    try:
        target = browser.command("Target.createTarget", url="about:blank")
        target_id = target["targetId"]
        attached = browser.command("Target.attachToTarget", targetId=target_id, flatten=True)
        session_id = attached["sessionId"]
        browser.command("Page.enable", session_id=session_id)
        # Resolve anti-bot interstitials (e.g. DataDome) automatically.
        auto_solved = False
        for _ in range(2):
            try:
                browser.command("Captcha.setAutoSolve", session_id=session_id, autoSolve=True)
                auto_solved = True
                break
            except BrowserSessionError:
                continue

        started = time.monotonic()

        def time_left() -> float:
            return max(1.0, overall_timeout - (time.monotonic() - started))

        browser.command("Page.navigate", session_id=session_id, url=start_url)
        load_event = browser.wait_for_event(
            "Page.loadEventFired", session_id=session_id, timeout=min(90.0, time_left())
        )
        if load_event is None:
            raise BrowserSessionError(f"Page load timed out for official source: {start_url}")

        # Wait until the page is actually interactable (anti-bot interstitials
        # resolve and the carrier's own form is rendered).
        interaction_deadline = time.monotonic() + max_page_wait
        if fill and ready_selector:
            became_ready = False
            while time.monotonic() < interaction_deadline and time.monotonic() - started < overall_timeout:
                try:
                    not_ready = browser.command(
                        "Runtime.evaluate",
                        session_id=session_id,
                        expression=_NOT_READY_JS % {"selector": json.dumps(ready_selector)},
                        returnByValue=True,
                    ).get("result", {}).get("value")
                except BrowserSessionError:
                    not_ready = True  # transient context loss during challenge reloads
                if not not_ready:
                    became_ready = True
                    break
                time.sleep(poll_interval)
            if not became_ready:
                raise BrowserSessionError(
                    f"Official carrier page never became interactive (waiting for {ready_selector}); "
                    "carrier anti-bot challenge may not have resolved."
                )

        if fill:
            ok = browser.command(
                "Runtime.evaluate",
                session_id=session_id,
                expression=_FILL_VALUE_JS % {
                    "selector": json.dumps(fill["selector"]),
                    "value": json.dumps(fill["value"]),
                },
                returnByValue=True,
            ).get("result", {}).get("value")
            if not ok:
                raise BrowserSessionError(f"Fill target not found on page: {fill['selector']}")

        if submit_selector:
            ok = browser.command(
                "Runtime.evaluate",
                session_id=session_id,
                expression=_CLICK_JS % {"selector": json.dumps(submit_selector)},
                returnByValue=True,
            ).get("result", {}).get("value")
            if not ok:
                raise BrowserSessionError(f"Submit target not found on page: {submit_selector}")

        page_deadline = time.monotonic() + max_page_wait
        final_html: Optional[str] = None
        outcome = "timeout"
        while time.monotonic() < page_deadline and time.monotonic() - started < overall_timeout:
            try:
                check = browser.command(
                    "Runtime.evaluate",
                    session_id=session_id,
                    expression=_MARKER_CHECK_JS % {"success_expr": success_js},
                    returnByValue=True,
                ).get("result", {}).get("value") or {}
            except BrowserSessionError:
                check = {}  # transient context loss during result-page navigation
            if check.get("success"):
                outcome = "success"
                break
            time.sleep(poll_interval)

        html_result = browser.command(
            "Runtime.evaluate",
            session_id=session_id,
            expression="document.documentElement.outerHTML",
            returnByValue=True,
            timeout=time_left(),
        )
        final_html = html_result.get("result", {}).get("value")

        if outcome != "success":
            raise BrowserSessionError(
                "Official carrier source did not render tracking results for this "
                "reference within the allowed time (unknown reference, no data, or "
                "unresolved anti-bot challenge). No tracking data was fabricated."
            )

        if not final_html:
            raise BrowserSessionError("Empty page returned by Scraping Browser session.")

        return final_html

    finally:
        browser.close()


def fetch_carrier_page_via_browser(adapter: Any, container_number: str) -> str:
    """
    Execute an ocean adapter's declared browser plan against its official source.
    Anti-bot challenges can resolve slowly or intermittently, so a single retry
    with a fresh session is performed before giving up.
    """
    plan = adapter.get_browser_plan(container_number)
    if not plan:
        raise BrowserSessionError(
            f"Carrier '{getattr(adapter, 'carrier_id', '?')}' does not define a browser session plan."
        )
    kwargs = dict(
        fill=plan.get("fill"),
        submit_selector=plan.get("submit"),
        ready_selector=plan.get("ready_selector"),
        success_js=plan.get("success_js"),
        max_page_wait=float(plan.get("max_page_wait", 60.0)),
        overall_timeout=float(plan.get("overall_timeout", 240.0)),
    )
    last_error: Optional[BrowserSessionError] = None
    for attempt in range(2):
        try:
            return fetch_rendered_html(plan["start_url"], **kwargs)
        except BrowserSessionError as e:
            last_error = e
    raise last_error
