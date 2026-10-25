"""Common LLM provider interface with retries and safe error messages."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import requests

from src.collectors.base import RETRYABLE_STATUS_CODES


class LLMError(RuntimeError):
    """An LLM request failed or returned an unusable response."""


class MissingCredentialError(LLMError):
    """A selected provider has no API key configured."""


class LLMProvider(ABC):
    """Base class for swappable AI providers.

    All providers expose ``generate(prompt, json_mode=False)`` and never log
    prompts, responses or credentials.
    """

    name = "unknown"

    def __init__(
        self,
        *,
        model: str,
        timeout: float = 120,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        session: requests.Session | None = None,
    ) -> None:
        self.model = model
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self.backoff_seconds = max(0.0, float(backoff_seconds))
        self.session = session or requests.Session()

    def _validate_prompt(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise LLMError("prompt must be a non-empty string")
        return prompt

    def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    url,
                    headers=headers,
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep(attempt)
                    continue
                raise LLMError(
                    f"{self.name} request failed ({type(exc).__name__})"
                ) from exc

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt < self.max_retries:
                    self._sleep(attempt)
                    continue
                raise LLMError(
                    f"{self.name} returned HTTP {response.status_code} after retries"
                )

            if response.status_code >= 400:
                raise LLMError(
                    f"{self.name} request failed with HTTP {response.status_code}. "
                    "Check the API key, model name and free-tier quota."
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise LLMError(f"{self.name} returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise LLMError(f"{self.name} returned an unexpected JSON shape")
            return payload

        raise LLMError(
            f"{self.name} request failed ({type(last_error).__name__})"
        )

    def _sleep(self, attempt: int) -> None:
        delay = self.backoff_seconds * (2**attempt)
        if delay > 0:
            time.sleep(delay)

    @abstractmethod
    def generate(self, prompt: str, json_mode: bool = False) -> str:
        """Return the model's text response for a prompt."""
