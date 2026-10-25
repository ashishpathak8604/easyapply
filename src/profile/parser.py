"""Deterministic, local resume parsing heuristics.

This parser is intentionally conservative: it extracts only what is visibly in
the resume text and leaves uncertain fields blank rather than inventing data.
The AI-assisted path in :mod:`src.profile.builder` is optional and off by
default.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from src.models import utc_now_iso

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)"
)
_DATE_TOKEN = rf"(?:(?:{_MONTH})\.?\s+)?(?:19|20)\d{{2}}"
DATE_RANGE_RE = re.compile(
    rf"{_DATE_TOKEN}\s*(?:-|–|—|to)\s*(?:present|current|now|{_DATE_TOKEN})",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
BULLET_RE = re.compile(r"^\s*(?:[-*•·◦▪●]|\d+[.)])\s+")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]]+", re.IGNORECASE)
LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/[^\s<>()\[\],;]+", re.IGNORECASE
)
GITHUB_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[^\s<>()\[\],;]+", re.IGNORECASE
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.UNICODE)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+\d{1,3}[\s.\-]?)?(?:\(?\d{2,5}\)?[\s.\-]?){2,4}\d{2,5}(?!\d)"
)
LOCATION_LINE_RE = re.compile(
    r"^\s*(?:location|address|based in)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)

SECTION_ALIASES = {
    "summary": {
        "summary",
        "professional summary",
        "profile",
        "about",
        "about me",
        "objective",
        "career objective",
    },
    "skills": {
        "skills",
        "technical skills",
        "core skills",
        "core competencies",
        "technologies",
        "technical expertise",
        "skill set",
    },
    "education": {
        "education",
        "academic background",
        "academics",
        "education details",
    },
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
        "work history",
        "internships",
        "internship experience",
        "professional background",
    },
    "projects": {
        "projects",
        "academic projects",
        "personal projects",
        "selected projects",
        "key projects",
    },
    "certifications": {
        "certifications",
        "certificates",
        "licenses",
        "licenses & certifications",
        "certifications & training",
    },
}

_HEADING_TO_SECTION = {
    alias: section for section, aliases in SECTION_ALIASES.items() for alias in aliases
}

INSTITUTION_KEYWORDS = (
    "university",
    "college",
    "institute",
    "school",
    "academy",
    "polytechnic",
    "iit",
    "nit",
    "iiit",
    "bits",
)

DEGREE_KEYWORDS = (
    "bachelor",
    "master",
    "b.tech",
    "btech",
    "m.tech",
    "mtech",
    "b.e",
    "m.e",
    "b.sc",
    "m.sc",
    "bsc",
    "msc",
    "bca",
    "mca",
    "phd",
    "doctorate",
    "diploma",
    "degree",
    "high school",
    "higher secondary",
    "intermediate",
    "12th",
    "10th",
)


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _heading(line: str) -> str | None:
    candidate = line.strip().strip("#").strip()
    candidate = candidate.rstrip(":").strip()
    if not candidate or len(candidate) > 60:
        return None
    return _HEADING_TO_SECTION.get(_collapse(candidate).casefold())


def split_sections(text: str) -> dict[str, list[str]]:
    """Split resume text into sections keyed by canonical section name."""

    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"
    for raw_line in text.splitlines():
        heading = _heading(raw_line)
        if heading is not None:
            current = heading
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(raw_line.rstrip())
    return sections


def _nonempty(lines: Iterable[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def _split_blocks(lines: Iterable[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _strip_bullet(line: str) -> str:
    return BULLET_RE.sub("", line).strip()


def _with_scheme(url: str) -> str:
    url = url.strip().rstrip(".,;:)]")
    if url.lower().startswith("http://") or url.lower().startswith("https://"):
        return url
    return "https://" + url


def _find_contact(text: str) -> dict[str, str]:
    contact = {
        "email": "",
        "phone": "",
        "location": "",
        "linkedin_url": "",
        "github_url": "",
        "portfolio_url": "",
    }

    email_match = EMAIL_RE.search(text)
    if email_match:
        contact["email"] = email_match.group(0).strip().rstrip(".,;:")

    for match in PHONE_RE.finditer(text):
        candidate = match.group(0).strip(" .-")
        digit_count = sum(character.isdigit() for character in candidate)
        if 10 <= digit_count <= 15:
            contact["phone"] = candidate
            break

    location_match = LOCATION_LINE_RE.search(text)
    if location_match:
        contact["location"] = _collapse(location_match.group(1))

    linkedin = LINKEDIN_RE.search(text)
    if linkedin:
        contact["linkedin_url"] = _with_scheme(linkedin.group(0))

    github = GITHUB_RE.search(text)
    if github:
        contact["github_url"] = _with_scheme(github.group(0))

    for match in URL_RE.finditer(text):
        url = _with_scheme(match.group(0))
        lowered = url.casefold()
        if "linkedin.com" in lowered or "github.com" in lowered:
            continue
        if contact["email"] and contact["email"].casefold() in lowered:
            continue
        contact["portfolio_url"] = url
        break

    return contact


def _detect_name(preamble: Iterable[str]) -> str:
    for line in preamble:
        candidate = line.strip()
        if not candidate or len(candidate) > 60:
            continue
        lowered = candidate.casefold()
        if any(token in lowered for token in ("resume", "curriculum vitae", " cv")):
            continue
        if any(token in candidate for token in ("@", "http", "://", "|", ":")):
            continue
        if any(character.isdigit() for character in candidate):
            continue
        words = candidate.split()
        if not 1 <= len(words) <= 5:
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z .'\-]*", candidate):
            continue
        return candidate
    return ""


def _split_skill_items(value: str) -> list[str]:
    parts = re.split(r"[,;|•·]+", value)
    items: list[str] = []
    for part in parts:
        item = part.strip(" .\t")
        if item:
            items.append(item)
    return items


def _parse_skills(lines: Iterable[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    seen: set[str] = set()

    for raw_line in lines:
        line = _strip_bullet(raw_line)
        if not line:
            continue

        category_match = re.match(r"^([A-Za-z][A-Za-z /&+.-]{1,40}):\s*(.+)$", line)
        if category_match:
            category = _collapse(category_match.group(1)).strip()
            values = _split_skill_items(category_match.group(2))
        else:
            category = "General"
            values = _split_skill_items(line)

        for value in values:
            key = value.casefold()
            if not value or key in seen:
                continue
            seen.add(key)
            groups.setdefault(category, []).append(value)

    return groups


def _parse_summary(lines: Iterable[str]) -> str:
    text = " ".join(_nonempty(lines))
    return _collapse(text)


def _parse_education(lines: Iterable[str]) -> list[dict[str, Any]]:
    education: list[dict[str, Any]] = []
    for block in _split_blocks(lines):
        block_text = " ".join(block)
        date_match = DATE_RANGE_RE.search(block_text)
        dates = date_match.group(0) if date_match else ""
        if not dates:
            year = YEAR_RE.search(block_text)
            if year:
                dates = year.group(0)

        institution = ""
        degree = ""
        used: set[str] = set()
        for line in block:
            lowered = line.casefold()
            if not institution and any(word in lowered for word in INSTITUTION_KEYWORDS):
                institution = line
                used.add(line)
            if not degree and any(word in lowered for word in DEGREE_KEYWORDS):
                degree = line
                used.add(line)

        if not institution and block:
            institution = block[0]
            used.add(block[0])
        if not degree and len(block) > 1:
            for line in block[1:]:
                if line not in used and not DATE_RANGE_RE.search(line):
                    degree = line
                    break

        details = []
        for line in block:
            if line in used:
                continue
            cleaned = _strip_bullet(line)
            if not cleaned or DATE_RANGE_RE.fullmatch(cleaned) or YEAR_RE.fullmatch(cleaned):
                continue
            details.append(cleaned)

        if institution or degree:
            education.append(
                {
                    "institution": institution,
                    "degree": degree,
                    "dates": _collapse(dates),
                    "details": details,
                }
            )
    return education


def _header_parts(lines: list[str], prefix: str, suffix: str) -> list[str]:
    pieces: list[str] = []
    for line in lines:
        for part in re.split(r"\s+(?:at|@)\s+|\s*[|—–]\s*|\s*,\s*", line):
            part = part.strip(" -")
            if part:
                pieces.append(part)
    for value in (prefix, suffix):
        value = value.strip(" -|–—")
        if not value:
            continue
        for part in re.split(r"\s+(?:at|@)\s+|\s*[|—–]\s*|\s*,\s*", value):
            part = part.strip(" -")
            if part:
                pieces.append(part)
    return pieces


def _parse_experience(lines: Iterable[str]) -> list[dict[str, Any]]:
    experience: list[dict[str, Any]] = []
    for block in _split_blocks(lines):
        anchors = [
            index for index, line in enumerate(block) if DATE_RANGE_RE.search(line)
        ]

        if not anchors:
            parts = _header_parts([block[0]], "", "") if block else []
            role = parts[0] if parts else ""
            company = parts[1] if len(parts) > 1 else ""
            bullets = [_strip_bullet(line) for line in block[1:]]
            bullets = [item for item in bullets if item]
            if role or company or bullets:
                experience.append(
                    {
                        "company": company,
                        "role": role,
                        "dates": "",
                        "bullets": bullets,
                    }
                )
            continue

        header_starts: list[int] = []
        for index in anchors:
            start = index
            while (
                start > 0
                and index - start < 2
                and block[start - 1].strip()
                and not BULLET_RE.match(block[start - 1])
                and not DATE_RANGE_RE.search(block[start - 1])
            ):
                start -= 1
            header_starts.append(start)

        for position, anchor in enumerate(anchors):
            start = header_starts[position]
            next_start = (
                header_starts[position + 1]
                if position + 1 < len(header_starts)
                else len(block)
            )

            date_line = block[anchor]
            match = DATE_RANGE_RE.search(date_line)
            dates = match.group(0) if match else ""
            prefix = date_line[: match.start()] if match else ""
            suffix = date_line[match.end() :] if match else ""

            headers = block[start:anchor]
            parts = _header_parts(headers, prefix, suffix)
            role = parts[0] if parts else ""
            company = parts[1] if len(parts) > 1 else ""

            bullets = [
                _strip_bullet(line)
                for line in block[anchor + 1 : next_start]
                if line.strip()
            ]
            bullets = [item for item in bullets if item]

            if role or company or bullets:
                experience.append(
                    {
                        "company": company,
                        "role": role,
                        "dates": _collapse(dates),
                        "bullets": bullets,
                    }
                )
    return experience


def _parse_projects(lines: Iterable[str]) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    for block in _split_blocks(lines):
        if not block:
            continue
        header = block[0]
        name = re.split(r"\s+[|—–]\s+|\s*:\s*", header, maxsplit=1)[0]
        name = _strip_bullet(name).strip()
        technologies: list[str] = []
        description_parts: list[str] = []

        for line in block[1:]:
            tech_match = re.match(
                r"^(?:tech(?:nologies)?|stack|built with)\s*:\s*(.+)$",
                line,
                re.IGNORECASE,
            )
            if tech_match:
                technologies.extend(_split_skill_items(tech_match.group(1)))
                continue
            cleaned = _strip_bullet(line)
            if cleaned:
                description_parts.append(cleaned)

        if not description_parts and "|" in header:
            description_parts.append(header.split("|", 1)[1].strip())

        if name:
            projects.append(
                {
                    "name": name,
                    "description": _collapse(" ".join(description_parts)),
                    "technologies": technologies,
                }
            )
    return projects


def _parse_certifications(lines: Iterable[str]) -> list[str]:
    certifications: list[str] = []
    for line in lines:
        cleaned = _strip_bullet(line)
        if cleaned:
            certifications.append(cleaned)
    return certifications


def _infer_target_roles(
    provided: list[str] | None, experience: list[dict[str, Any]]
) -> tuple[list[str], str]:
    cleaned_provided = [role for role in (provided or []) if str(role).strip()]
    if cleaned_provided:
        return [str(role).strip() for role in cleaned_provided], "config"

    roles: list[str] = []
    seen: set[str] = set()
    for item in experience:
        role = str(item.get("role") or "").strip()
        key = role.casefold()
        if role and key not in seen:
            seen.add(key)
            roles.append(role)
        if len(roles) >= 3:
            break
    if roles:
        return roles, "inferred_from_experience"
    return [], "none"


def parse_resume_text(
    text: str,
    *,
    contact_defaults: dict[str, str] | None = None,
    target_roles: list[str] | None = None,
    source_file: str = "",
) -> dict[str, Any]:
    """Convert resume text into a validated-profile-shaped dictionary."""

    sections = split_sections(text or "")
    defaults = {key: str(value or "") for key, value in (contact_defaults or {}).items()}

    contact = _find_contact(text or "")
    for key in contact:
        if not contact[key] and defaults.get(key):
            contact[key] = defaults[key]

    name = _detect_name(sections.get("preamble", []))
    summary = _parse_summary(sections.get("summary", []))
    skills = _parse_skills(sections.get("skills", []))
    education = _parse_education(sections.get("education", []))
    experience = _parse_experience(sections.get("experience", []))
    projects = _parse_projects(sections.get("projects", []))
    certifications = _parse_certifications(sections.get("certifications", []))
    target_roles_list, target_roles_source = _infer_target_roles(
        target_roles, experience
    )

    warnings: list[str] = []
    if not name:
        warnings.append("Name not detected; add it manually to profile.json.")
    if not contact["email"]:
        warnings.append("Email not detected; add it manually or in config.yaml.")
    if not summary:
        warnings.append("No summary section found.")
    if not skills:
        warnings.append("No skills section found.")
    if not education:
        warnings.append("No education section found.")
    if not experience:
        warnings.append("No experience section found.")
    if not target_roles_list:
        warnings.append("No target roles found in config.yaml or experience.")

    return {
        "name": name,
        "contact": contact,
        "summary": summary,
        "skills": skills,
        "education": education,
        "experience": experience,
        "projects": projects,
        "certifications": certifications,
        "inferred_target_roles": target_roles_list,
        "meta": {
            "source_file": source_file,
            "extracted_at": utc_now_iso(),
            "extractor": "local_heuristic",
            "ai_used": False,
            "target_roles_source": target_roles_source,
            "warnings": warnings,
        },
    }
