"""Tiny HTTP client for Wikimedia APIs: required User-Agent, retries with backoff,
polite global rate limit. stdlib only so it has no install cost."""
from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

USER_AGENT = os.environ.get(
    "WPV_USER_AGENT",
    "wiki-interest-research/1.0 (https://github.com/Nujabesuuu/wiki_search_skill; agent skill for pageview research)",
)
MAX_REQUESTS_PER_SECOND = 40.0  # Wikimedia asks clients to stay well below 100 req/s


class NetworkError(RuntimeError):
    """Transient problem that survived all retries (offline, 5xx, rate limit)."""


class NotFound(LookupError):
    """HTTP 404 — for pageviews it means 'no data for this title / range'."""


Transport = Callable[[str, float], tuple[int, bytes, dict]]


def _urllib_transport(url: str, timeout: float) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", dict(e.headers or {})


class Client:
    def __init__(self, transport: Transport | None = None, retries: int = 4, timeout: float = 30.0,
                 rate: float = MAX_REQUESTS_PER_SECOND, sleep: Callable[[float], None] = time.sleep):
        self.transport = transport or _urllib_transport
        self.retries = retries
        self.timeout = timeout
        self._interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._sleep = sleep
        self.requests_made = 0

    def _throttle(self) -> None:
        if not self._interval:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._interval
        if wait > 0:
            self._sleep(wait)

    def get_json(self, url: str, params: dict | None = None) -> dict:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        last_error = ""
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                status, body, headers = self.transport(url, self.timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                status, body, headers, last_error = 0, b"", {}, f"{type(e).__name__}: {e}"
            with self._lock:
                self.requests_made += 1
            if status == 200:
                return json.loads(body.decode("utf-8"))
            if status == 404:
                raise NotFound(url)
            if status and status not in (429,) and status < 500:
                raise NetworkError(f"HTTP {status} for {url}: {body[:200].decode('utf-8', 'replace')}")
            last_error = last_error or f"HTTP {status}"
            if attempt < self.retries:
                retry_after = headers.get("Retry-After") or headers.get("retry-after")
                delay = float(retry_after) if retry_after and str(retry_after).isdigit() else 2 ** attempt
                self._sleep(delay + random.uniform(0, 0.3))
        raise NetworkError(f"{last_error} after {self.retries + 1} attempts: {url}")


def quote_title(title: str) -> str:
    """Pageviews API wants underscores and every reserved char (including '/') escaped."""
    return urllib.parse.quote(title.replace(" ", "_"), safe="")
