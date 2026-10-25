"""Configuration loading, validation and environment handling."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_FILENAME = "config.yaml"

SOURCE_NAMES = ("greenhouse", "lever", "adzuna", "remoteok")

REQUIRED_KEYS = (
    "target_roles",
    "preferred_locations",
    "experience_level",
    "excluded_keywords",
    "daily_application_limit",
    "expected_salary",
    "notice_period",
    "work_authorization",
    "phone",
    "email",
    "linkedin_url",
    "github_url",
    "portfolio_url",
    "sources",
)

DEFAULT_PATHS = {
    "resume": "data/resume.pdf",
    "profile": "data/profile.json",
    "database": "data/jobs.db",
    "log": "logs/app.log",
}

DEFAULT_AI = {
    "provider": "ollama",
    "model": "llama3.1",
    "timeout_seconds": 120,
    "max_retries": 3,
    "backoff_seconds": 2.0,
    "resume_data_transfer_approved": False,
}

DEFAULT_COLLECTION = {
    "timeout_seconds": 20,
    "max_retries": 3,
    "backoff_seconds": 1.0,
    "rate_limit_seconds": 0.5,
    "user_agent": "job-assistant-phase1/0.1 (personal use)",
}


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


@dataclass(slots=True)
class AppConfig:
    """Validated application configuration.

    ``raw`` keeps the entire YAML document so future phases can read new keys
    without changing this class.
    """

    target_roles: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)
    experience_level: str = "entry-level"
    excluded_keywords: list[str] = field(default_factory=list)
    daily_application_limit: int = 10
    expected_salary: str = ""
    notice_period: str = ""
    work_authorization: str = ""
    phone: str = ""
    email: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    paths: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PATHS))
    ai: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_AI))
    collection: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_COLLECTION)
    )
    matching: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    base_dir: Path = field(default_factory=Path.cwd)

    def path_for(self, name: str) -> Path:
        """Resolve a configured local path relative to the config file."""

        value = self.paths.get(name)
        if not value:
            raise ConfigError(f"paths.{name} is not configured")
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.base_dir / candidate
        return candidate

    def source_enabled(self, name: str) -> bool:
        source = self.sources.get(name) or {}
        return bool(source.get("enabled", False))

    def enabled_sources(self) -> list[str]:
        return [name for name in SOURCE_NAMES if self.source_enabled(name)]

    def source_settings(self, name: str) -> dict[str, Any]:
        settings = dict(self.sources.get(name) or {})
        settings.pop("enabled", None)
        return settings

    def contact_defaults(self) -> dict[str, str]:
        return {
            "email": self.email,
            "phone": self.phone,
            "location": "",
            "linkedin_url": self.linkedin_url,
            "github_url": self.github_url,
            "portfolio_url": self.portfolio_url,
        }


def _require_type(raw: dict[str, Any], key: str, expected: type) -> Any:
    value = raw[key]
    if not isinstance(value, expected):
        raise ConfigError(
            f"config key '{key}' must be {expected.__name__}, got "
            f"{type(value).__name__}"
        )
    return value


def validate_config(raw: dict[str, Any]) -> None:
    """Validate a raw config mapping and raise :class:`ConfigError`."""

    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        raise ConfigError("missing required config keys: " + ", ".join(missing))

    for key in (
        "target_roles",
        "preferred_locations",
        "excluded_keywords",
    ):
        _require_type(raw, key, list)
    for key in (
        "experience_level",
        "expected_salary",
        "notice_period",
        "work_authorization",
        "phone",
        "email",
        "linkedin_url",
        "github_url",
        "portfolio_url",
    ):
        _require_type(raw, key, str)

    limit = _require_type(raw, "daily_application_limit", int)
    if limit < 0:
        raise ConfigError("daily_application_limit must be zero or greater")

    sources = _require_type(raw, "sources", dict)
    unknown = sorted(set(sources) - set(SOURCE_NAMES))
    if unknown:
        raise ConfigError("unknown job sources: " + ", ".join(unknown))
    for name, settings in sources.items():
        if not isinstance(settings, dict):
            raise ConfigError(f"sources.{name} must be a mapping")
        enabled = settings.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ConfigError(f"sources.{name}.enabled must be true or false")
        slugs = settings.get("company_slugs", [])
        if name in {"greenhouse", "lever"} and not isinstance(slugs, list):
            raise ConfigError(f"sources.{name}.company_slugs must be a list")

    paths = raw.get("paths", {})
    if not isinstance(paths, dict):
        raise ConfigError("paths must be a mapping")

    ai = raw.get("ai", {})
    if not isinstance(ai, dict):
        raise ConfigError("ai must be a mapping")
    provider = ai.get("provider", DEFAULT_AI["provider"])
    if provider not in {"gemini", "groq", "ollama"}:
        raise ConfigError("ai.provider must be one of: gemini, groq, ollama")
    approved = ai.get("resume_data_transfer_approved", False)
    if not isinstance(approved, bool):
        raise ConfigError("ai.resume_data_transfer_approved must be a boolean")

    collection = raw.get("collection", {})
    if not isinstance(collection, dict):
        raise ConfigError("collection must be a mapping")


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load and validate ``config.yaml``.

    Relative paths inside the config are resolved from the config file's folder,
    not from the current working directory.
    """

    config_path = Path(path or DEFAULT_CONFIG_FILENAME).expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    config_path = config_path.resolve()

    if not config_path.exists():
        raise ConfigError(
            f"config file not found: {config_path}. Copy or create config.yaml."
        )

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {config_path.name}: {exc}") from exc

    validate_config(raw)

    ai = {**DEFAULT_AI, **(raw.get("ai") or {})}
    collection = {**DEFAULT_COLLECTION, **(raw.get("collection") or {})}
    paths = {**DEFAULT_PATHS, **(raw.get("paths") or {})}
    sources = {**{name: {} for name in SOURCE_NAMES}, **(raw.get("sources") or {})}

    scalar_keys = (
        "target_roles",
        "preferred_locations",
        "experience_level",
        "excluded_keywords",
        "daily_application_limit",
        "expected_salary",
        "notice_period",
        "work_authorization",
        "phone",
        "email",
        "linkedin_url",
        "github_url",
        "portfolio_url",
    )
    values = {key: raw[key] for key in scalar_keys}

    return AppConfig(
        **values,
        sources=sources,
        paths=paths,
        ai=ai,
        collection=collection,
        matching=dict(raw.get("matching") or {}),
        raw=raw,
        base_dir=config_path.parent,
    )


def load_environment(dotenv_path: str | Path | None = None, *, override: bool = False):
    """Load ``.env`` if python-dotenv is available.

    Returns the path loaded, or ``None`` when no file exists. Missing optional
    dependency is not an error; real secrets simply remain in the environment.
    """

    path = Path(dotenv_path) if dotenv_path else Path.cwd() / ".env"
    if not path.exists():
        return None
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None
    load_dotenv(path, override=override)
    return path


def get_env(name: str, default: str | None = None) -> str | None:
    """Read an environment variable without logging its value."""

    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default
