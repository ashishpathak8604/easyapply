"""Provider factory: choose Gemini, Groq or Ollama from configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from src.config import AppConfig
from src.llm.base import (
    LLMError,
    LLMProvider,
    MissingCredentialError,
)
from src.llm.gemini import GeminiProvider
from src.llm.groq import GroqProvider
from src.llm.ollama import OllamaProvider

DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "groq": "llama-3.1-8b-instant",
    "ollama": "llama3.1",
}


def _ai_settings(config: AppConfig | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(config, AppConfig):
        return dict(config.ai)
    if isinstance(config, Mapping):
        section = config.get("ai", {})
        if isinstance(section, Mapping):
            return dict(section)
    return {}


def create_llm(
    config: AppConfig | Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> LLMProvider:
    """Create the configured provider without making any request."""

    environment = env if env is not None else os.environ
    settings = _ai_settings(config)
    provider = str(settings.get("provider", "ollama")).strip().lower()
    model = str(
        settings.get("model") or DEFAULT_MODELS.get(provider, "")
    ).strip()
    common = {
        "timeout": float(settings.get("timeout_seconds", 120)),
        "max_retries": int(settings.get("max_retries", 3)),
        "backoff_seconds": float(settings.get("backoff_seconds", 2.0)),
    }

    if provider == "gemini":
        api_key = (environment.get("GEMINI_API_KEY") or "").strip()
        if not api_key:
            raise MissingCredentialError(
                "GEMINI_API_KEY is not set. Add it to .env or choose another "
                "provider in config.yaml."
            )
        return GeminiProvider(api_key=api_key, model=model or DEFAULT_MODELS[provider], **common)

    if provider == "groq":
        api_key = (environment.get("GROQ_API_KEY") or "").strip()
        if not api_key:
            raise MissingCredentialError(
                "GROQ_API_KEY is not set. Add it to .env or choose another "
                "provider in config.yaml."
            )
        return GroqProvider(api_key=api_key, model=model or DEFAULT_MODELS[provider], **common)

    if provider == "ollama":
        host = (
            environment.get("OLLAMA_HOST")
            or settings.get("host")
            or "http://127.0.0.1:11434"
        )
        return OllamaProvider(
            host=str(host), model=model or DEFAULT_MODELS[provider], **common
        )

    raise LLMError(
        f"unknown AI provider '{provider}'; choose gemini, groq or ollama"
    )
