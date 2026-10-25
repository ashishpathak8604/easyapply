"""Shared collector primitives: errors, HTTP client and normalization helpers."""

from __future__ import annotations

import html
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from src.models import Job, utc_now_iso

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class CollectorError(RuntimeError):
    """A job source could not be read or understood."""


class MissingCredentialsError(CollectorError):
    """A source requires credentials that are not configured."""


class NoEnabledSourcesError(CollectorError):
    """No job sources are enabled in the configuration."""


def safe_url(url: str) -> str:
    """Strip query string and fragment so credentials never reach logs."""

    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def html_to_text(value: Any) -> str:
    """Convert a small HTML fragment to readable plain text."""

    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</(p|li|div|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def is_remote(*values: Any) -> bool:
    """Infer a remote flag from location/title/workplace strings."""

    haystack = " ".join(str(value or "") for value in values).casefold()
    return any(word in haystack for word in ("remote", "work from home", "wfh"))


def to_iso_date(value: Any) -> str | None:
    """Best-effort conversion of a source date to an ISO-8601 string."""

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1_000_000_000_000:  # milliseconds
            number /= 1000.0
        try:
            dt = datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return dt.replace(microsecond=0).isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except ValueError:
        return text


class HttpClient:
    """HTTP JSON client with timeouts, retries and no secret logging."""

    def __init__(
        self,
        *,
        timeout: float = 20,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        user_agent: str = "job-assistant-phase1/0.1 (personal use)",
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.user_agent = user_agent
        self.session = session or requests.Session()

    def _sleep(self, attempt: int, response: requests.Response | None = None) -> None:
        delay = self.backoff_seconds * (2**attempt)
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = min(max(float(retry_after), 0.0), 10.0)
                except ValueError:
                    pass
        if delay > 0:
            time.sleep(delay)

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        display_url = safe_url(url)
        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=request_headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep(attempt)
                    continue
                raise CollectorError(
                    f"request to {display_url} failed ({type(exc).__name__})"
                ) from exc

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt < self.max_retries:
                    self._sleep(attempt, response)
                    continue
                raise CollectorError(
                    f"{display_url} returned HTTP {response.status_code} "
                    "after retries"
                )

            if response.status_code >= 400:
                raise CollectorError(
                    f"{display_url} returned HTTP {response.status_code}"
                )

            try:
                return response.json()
            except ValueError as exc:
                raise CollectorError(f"{display_url} returned invalid JSON") from exc

        raise CollectorError(
            f"request to {display_url} failed ({type(last_error).__name__})"
        )


class Collector(ABC):
    """Base class for one job source."""

    name = "unknown"

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        *,
        http: HttpClient | None = None,
        timeout: float = 20,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
        rate_limit_seconds: float = 0.5,
        user_agent: str = "job-assistant-phase1/0.1 (personal use)",
    ) -> None:
        self.settings = dict(settings or {})
        self.http = http or HttpClient(
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            user_agent=user_agent,
        )
        self.rate_limit_seconds = max(0.0, float(rate_limit_seconds))
        self._last_request_at: float | None = None

    def _rate_limit(self) -> None:
        if self.rate_limit_seconds <= 0 or self._last_request_at is None:
            self._last_request_at = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.rate_limit_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _get_json(
        self, url: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        self._rate_limit()
        return self.http.get_json(url, params=params)

    def _try_job(self, **fields: Any) -> Job | None:
        """Create a Job, skipping individual malformed source entries."""

        try:
            return Job(source=self.name, fetched_at=utc_now_iso(), **fields)
        except (TypeError, ValueError):
            return None

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Fetch and normalize jobs from the source."""
