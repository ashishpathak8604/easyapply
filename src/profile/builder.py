"""Build, validate, back up and preserve ``data/profile.json``."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import AppConfig
from src.llm.base import LLMError, LLMProvider
from src.profile.extractor import ExtractionResult, extract_resume_text
from src.profile.parser import parse_resume_text
from src.profile.schema import ProfileValidationError, load_profile, validate_profile


class ProfileBuildError(RuntimeError):
    """The profile could not be built safely."""


@dataclass(slots=True)
class BuildResult:
    status: str  # created | updated | preserved | dry_run
    profile: dict[str, Any]
    profile_path: Path
    extraction: ExtractionResult | None = None
    backup_path: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def preserved(self) -> bool:
        return self.status == "preserved"


AI_PROMPT = """You convert a resume into strict JSON for a job application tool.

Rules:
- Use only facts found in the resume text below.
- Never invent employers, dates, degrees, skills, metrics or achievements.
- Use empty strings and empty lists when a value is not present.
- Return JSON only, with exactly these top-level keys:
  name, contact, summary, skills, education, experience, projects,
  certifications, inferred_target_roles.
- contact: object with email, phone, location, linkedin_url, github_url,
  portfolio_url.
- skills: object mapping category names to arrays of skill strings.
- education: array of objects with institution, degree, dates, details
  (details is an array of strings).
- experience: array of objects with company, role, dates, bullets
  (bullets is an array of strings).
- projects: array of objects with name, description, technologies
  (technologies is an array of strings).
- certifications: array of strings.
- inferred_target_roles: array of strings based on the resume's own roles.

Resume text:
---
{resume_text}
---
"""


def _ai_settings(config: AppConfig | dict[str, Any] | None) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, AppConfig):
        return dict(config.ai)
    section = config.get("ai", {}) if isinstance(config, dict) else {}
    return dict(section) if isinstance(section, dict) else {}


def _context(
    config: AppConfig | dict[str, Any] | None,
) -> tuple[dict[str, str], list[str]]:
    if config is None:
        return {}, []
    if isinstance(config, AppConfig):
        return config.contact_defaults(), list(config.target_roles)
    contact = {
        "email": str(config.get("email") or ""),
        "phone": str(config.get("phone") or ""),
        "location": "",
        "linkedin_url": str(config.get("linkedin_url") or ""),
        "github_url": str(config.get("github_url") or ""),
        "portfolio_url": str(config.get("portfolio_url") or ""),
    }
    roles = config.get("target_roles") or []
    return contact, [str(role) for role in roles] if isinstance(roles, list) else []


def _strip_code_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _ai_profile(
    resume: ExtractionResult,
    llm: LLMProvider,
    source_name: str,
    target_roles: list[str],
) -> dict[str, Any]:
    prompt = AI_PROMPT.format(resume_text=resume.text)
    try:
        raw = llm.generate(prompt, json_mode=True)
    except LLMError:
        raise
    except Exception as exc:  # defensive: provider implementation bug
        raise ProfileBuildError(
            f"AI extraction failed ({type(exc).__name__})"
        ) from exc

    try:
        payload = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        raise ProfileBuildError(
            "AI extraction did not return valid JSON. Re-run without --use-ai "
            "for local extraction."
        ) from exc
    if not isinstance(payload, dict):
        raise ProfileBuildError("AI extraction returned a non-object JSON value")

    payload.setdefault("meta", {})
    if not isinstance(payload["meta"], dict):
        payload["meta"] = {}
    payload["meta"].update(
        {
            "source_file": source_name,
            "extracted_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "extractor": getattr(llm, "name", "ai"),
            "ai_used": True,
            "ai_model": getattr(llm, "model", ""),
            "warnings": list(resume.warnings),
        }
    )
    if not payload.get("inferred_target_roles") and target_roles:
        payload["inferred_target_roles"] = target_roles
        payload["meta"]["target_roles_source"] = "config"
    validate_profile(payload)
    return payload


def _backup_path(profile_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return profile_path.with_name(f"{profile_path.stem}.backup.{stamp}.json")


def _write_profile(profile: dict[str, Any], profile_path: Path) -> None:
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = profile_path.with_name(profile_path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(profile, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, profile_path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ProfileBuildError(f"could not write profile: {exc}") from exc


def build_profile(
    resume_path: str | Path,
    profile_path: str | Path,
    *,
    config: AppConfig | dict[str, Any] | None = None,
    force: bool = False,
    dry_run: bool = False,
    use_ai: bool = False,
    llm: LLMProvider | None = None,
) -> BuildResult:
    """Build a profile from a resume while preserving manual edits.

    If the profile already exists and ``force`` is false, it is loaded,
    validated and returned untouched. With ``force``, the old file is backed up
    before being replaced.
    """

    resume = Path(resume_path).expanduser()
    profile_file = Path(profile_path).expanduser()

    if profile_file.exists() and not force:
        try:
            existing = load_profile(profile_file)
        except ProfileValidationError as exc:
            raise ProfileBuildError(
                f"existing profile is invalid and was not overwritten: {exc}. "
                "Fix it or pass --force (a backup is created) to rebuild."
            ) from exc
        meta = existing.get("meta") if isinstance(existing.get("meta"), dict) else {}
        warnings = meta.get("warnings") if isinstance(meta.get("warnings"), list) else []
        return BuildResult(
            status="preserved",
            profile=existing,
            profile_path=profile_file,
            warnings=[str(item) for item in warnings],
        )

    extracted = extract_resume_text(resume)
    contact, target_roles = _context(config)

    if use_ai:
        approved = bool(_ai_settings(config).get("resume_data_transfer_approved"))
        if not approved:
            raise ProfileBuildError(
                "AI extraction is not approved. Set "
                "ai.resume_data_transfer_approved: true in config.yaml after "
                "you have consciously approved sending resume text to the "
                "selected provider."
            )
        if llm is None:
            raise ProfileBuildError(
                "AI extraction requested but no LLM provider was supplied."
            )
        profile = _ai_profile(
            extracted, llm, resume.name, target_roles
        )
    else:
        profile = parse_resume_text(
            extracted.text,
            contact_defaults=contact,
            target_roles=target_roles,
            source_file=resume.name,
        )
        profile["meta"]["extraction_method"] = extracted.method
        validate_profile(profile)

    backup: Path | None = None
    if dry_run:
        status = "dry_run"
    else:
        if profile_file.exists():
            backup = _backup_path(profile_file)
            try:
                shutil.copy2(profile_file, backup)
            except OSError as exc:
                raise ProfileBuildError(
                    f"could not back up existing profile; refusing to overwrite: {exc}"
                ) from exc
            status = "updated"
        else:
            status = "created"
        _write_profile(profile, profile_file)

    warnings = list(profile.get("meta", {}).get("warnings", []))
    warnings.extend(extracted.warnings)
    return BuildResult(
        status=status,
        profile=profile,
        profile_path=profile_file,
        extraction=extracted,
        backup_path=backup,
        warnings=warnings,
    )


def format_profile_summary(profile: dict[str, Any]) -> str:
    """Render a compact, human-reviewable profile summary."""

    lines: list[str] = []
    name = profile.get("name") or "(name not detected)"
    lines.append(f"Name: {name}")

    contact = profile.get("contact") or {}
    contact_bits = [
        f"{label}: {contact.get(key)}"
        for key, label in (
            ("email", "Email"),
            ("phone", "Phone"),
            ("location", "Location"),
            ("linkedin_url", "LinkedIn"),
            ("github_url", "GitHub"),
            ("portfolio_url", "Portfolio"),
        )
        if contact.get(key)
    ]
    if contact_bits:
        lines.append("Contact: " + " | ".join(contact_bits))

    summary = str(profile.get("summary") or "").strip()
    if summary:
        if len(summary) > 300:
            summary = summary[:297].rstrip() + "..."
        lines.append(f"Summary: {summary}")

    roles = profile.get("inferred_target_roles") or []
    if roles:
        lines.append("Target roles: " + ", ".join(str(role) for role in roles))

    skills = profile.get("skills") or {}
    if isinstance(skills, dict) and skills:
        lines.append("Skills:")
        for category, items in skills.items():
            values = ", ".join(str(item) for item in items)
            lines.append(f"  - {category}: {values}")

    experience = profile.get("experience") or []
    if experience:
        lines.append("Experience:")
        for item in experience:
            role = item.get("role") or "(role)"
            company = item.get("company") or "(company)"
            dates = item.get("dates") or "dates unknown"
            bullets = item.get("bullets") or []
            lines.append(f"  - {role} at {company} ({dates}); {len(bullets)} bullet(s)")

    education = profile.get("education") or []
    if education:
        lines.append("Education:")
        for item in education:
            degree = item.get("degree") or "(degree)"
            institution = item.get("institution") or "(institution)"
            dates = item.get("dates") or "dates unknown"
            lines.append(f"  - {degree} - {institution} ({dates})")

    projects = profile.get("projects") or []
    if projects:
        lines.append("Projects:")
        for item in projects:
            tech = ", ".join(item.get("technologies") or [])
            suffix = f" [{tech}]" if tech else ""
            lines.append(f"  - {item.get('name') or '(project)'}{suffix}")

    certifications = profile.get("certifications") or []
    if certifications:
        lines.append("Certifications: " + "; ".join(str(item) for item in certifications))

    warnings = profile.get("meta", {}).get("warnings") or []
    if warnings:
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"  - {warning}")

    return "\n".join(lines)
