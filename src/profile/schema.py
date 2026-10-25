"""JSON schema and validation for ``data/profile.json``."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator


class ProfileValidationError(ValueError):
    """The generated or edited profile does not match the schema."""


PROFILE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Job Application Assistant profile",
    "type": "object",
    "required": [
        "name",
        "contact",
        "summary",
        "skills",
        "education",
        "experience",
        "projects",
        "certifications",
        "inferred_target_roles",
        "meta",
    ],
    "properties": {
        "name": {"type": "string"},
        "contact": {
            "type": "object",
            "required": [
                "email",
                "phone",
                "location",
                "linkedin_url",
                "github_url",
                "portfolio_url",
            ],
            "properties": {
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "location": {"type": "string"},
                "linkedin_url": {"type": "string"},
                "github_url": {"type": "string"},
                "portfolio_url": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "summary": {"type": "string"},
        "skills": {
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["institution", "degree", "dates", "details"],
                "properties": {
                    "institution": {"type": "string"},
                    "degree": {"type": "string"},
                    "dates": {"type": "string"},
                    "details": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": True,
            },
        },
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["company", "role", "dates", "bullets"],
                "properties": {
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "dates": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": True,
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "description", "technologies"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "technologies": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": True,
            },
        },
        "certifications": {
            "type": "array",
            "items": {"type": "string"},
        },
        "inferred_target_roles": {
            "type": "array",
            "items": {"type": "string"},
        },
        "meta": {"type": "object", "additionalProperties": True},
    },
    "additionalProperties": True,
}


def validate_profile(profile: Any) -> dict[str, Any]:
    """Validate a profile mapping and return it unchanged.

    Raises :class:`ProfileValidationError` with a compact, readable message.
    """

    if not isinstance(profile, dict):
        raise ProfileValidationError("profile must be a JSON object")

    validator = Draft202012Validator(PROFILE_SCHEMA)
    errors = sorted(validator.iter_errors(profile), key=lambda error: list(error.path))
    if not errors:
        return profile

    messages = []
    for error in errors[:8]:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    if len(errors) > 8:
        messages.append(f"... and {len(errors) - 8} more error(s)")
    raise ProfileValidationError("; ".join(messages))


def load_profile(path: str | Any) -> dict[str, Any]:
    """Load and validate a profile JSON file."""

    import json
    from pathlib import Path

    profile_path = Path(path)
    try:
        with profile_path.open("r", encoding="utf-8") as handle:
            profile = json.load(handle)
    except FileNotFoundError as exc:
        raise ProfileValidationError(
            f"profile file not found: {profile_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ProfileValidationError(
            f"profile file is not valid JSON: {exc.msg}"
        ) from exc
    return validate_profile(profile)
