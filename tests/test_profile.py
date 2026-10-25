"""Tests for resume parsing, profile validation and manual-edit preservation."""

from __future__ import annotations

import json

import pytest

from src.profile.builder import build_profile
from src.profile.extractor import ExtractionResult
from src.profile.parser import parse_resume_text, split_sections
from src.profile.schema import (
    ProfileValidationError,
    load_profile,
    validate_profile,
)

SAMPLE_RESUME = """ALEX EXAMPLE
Email: alex@example.com | Phone: +91 98765 43210
Location: Pune, India
LinkedIn: linkedin.com/in/alexexample
GitHub: github.com/alexexample
Portfolio: https://alex.example

SUMMARY
Entry-level Python developer with internship experience building web services.

SKILLS
Languages: Python, JavaScript, SQL
Frameworks: FastAPI, Flask, React
Tools: Git, Docker

EXPERIENCE
Software Engineer Intern | Acme Systems | Jan 2025 - Jun 2025
- Built REST APIs with FastAPI and PostgreSQL.
- Wrote pytest tests for backend services.

EDUCATION
Bachelor of Technology in Computer Science
Pune University
2021 - 2025

PROJECTS
Job Tracker
Tech: Python, FastAPI, SQLite
- Built a job tracking app with a SQLite database.

CERTIFICATIONS
- AWS Cloud Practitioner
"""


def _valid_profile() -> dict:
    return {
        "name": "Alex Example",
        "contact": {
            "email": "alex@example.com",
            "phone": "+91 98765 43210",
            "location": "Pune, India",
            "linkedin_url": "https://linkedin.com/in/alexexample",
            "github_url": "https://github.com/alexexample",
            "portfolio_url": "",
        },
        "summary": "Entry-level Python developer.",
        "skills": {"Languages": ["Python", "SQL"]},
        "education": [
            {
                "institution": "Pune University",
                "degree": "B.Tech Computer Science",
                "dates": "2021 - 2025",
                "details": [],
            }
        ],
        "experience": [
            {
                "company": "Acme Systems",
                "role": "Software Engineer Intern",
                "dates": "Jan 2025 - Jun 2025",
                "bullets": ["Built REST APIs."],
            }
        ],
        "projects": [
            {
                "name": "Job Tracker",
                "description": "Built a job tracking app.",
                "technologies": ["Python", "SQLite"],
            }
        ],
        "certifications": ["AWS Cloud Practitioner"],
        "inferred_target_roles": ["Backend Developer"],
        "meta": {"extractor": "test"},
    }


def test_valid_profile_passes_schema() -> None:
    profile = validate_profile(_valid_profile())
    assert profile["name"] == "Alex Example"


def test_profile_missing_required_key_is_rejected() -> None:
    profile = _valid_profile()
    del profile["experience"]
    with pytest.raises(ProfileValidationError, match="experience"):
        validate_profile(profile)


def test_profile_wrong_type_is_rejected() -> None:
    profile = _valid_profile()
    profile["skills"] = ["Python"]
    with pytest.raises(ProfileValidationError):
        validate_profile(profile)


def test_load_profile_round_trips(tmp_path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_valid_profile()), encoding="utf-8")
    loaded = load_profile(path)
    assert loaded["contact"]["email"] == "alex@example.com"


def test_split_sections_recognizes_headings() -> None:
    sections = split_sections(SAMPLE_RESUME)
    assert "Python, JavaScript, SQL" in " ".join(sections["skills"])
    assert any("Acme Systems" in line for line in sections["experience"])


def test_parse_resume_text_extracts_structured_profile() -> None:
    profile = parse_resume_text(
        SAMPLE_RESUME, target_roles=["Backend Developer"], source_file="resume.pdf"
    )
    validate_profile(profile)

    assert profile["name"] == "ALEX EXAMPLE"
    assert profile["contact"]["email"] == "alex@example.com"
    assert profile["contact"]["location"] == "Pune, India"
    assert profile["contact"]["linkedin_url"].startswith("https://")
    assert profile["contact"]["github_url"].startswith("https://")
    assert profile["contact"]["portfolio_url"] == "https://alex.example"
    assert "entry-level" in profile["summary"].casefold()

    assert profile["skills"]["Languages"] == ["Python", "JavaScript", "SQL"]
    assert profile["skills"]["Frameworks"] == ["FastAPI", "Flask", "React"]

    assert profile["experience"][0]["role"] == "Software Engineer Intern"
    assert profile["experience"][0]["company"] == "Acme Systems"
    assert profile["experience"][0]["dates"] == "Jan 2025 - Jun 2025"
    assert len(profile["experience"][0]["bullets"]) == 2

    assert profile["education"][0]["institution"] == "Pune University"
    assert profile["education"][0]["degree"].startswith("Bachelor")

    assert profile["projects"][0]["name"] == "Job Tracker"
    assert profile["projects"][0]["technologies"] == ["Python", "FastAPI", "SQLite"]

    assert profile["certifications"] == ["AWS Cloud Practitioner"]
    assert profile["inferred_target_roles"] == ["Backend Developer"]
    assert profile["meta"]["target_roles_source"] == "config"


def test_parse_resume_text_infers_target_roles_from_experience() -> None:
    profile = parse_resume_text(SAMPLE_RESUME)
    assert profile["inferred_target_roles"] == ["Software Engineer Intern"]
    assert profile["meta"]["target_roles_source"] == "inferred_from_experience"


def test_parser_output_matches_schema() -> None:
    validate_profile(parse_resume_text(SAMPLE_RESUME))


def test_build_profile_preserves_manual_edits(tmp_path) -> None:
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(_valid_profile()), encoding="utf-8")

    result = build_profile(
        tmp_path / "missing-resume.pdf", profile_path, force=False
    )

    assert result.preserved
    assert result.status == "preserved"
    assert result.profile["name"] == "Alex Example"
    assert json.loads(profile_path.read_text(encoding="utf-8")) == _valid_profile()


def test_build_profile_backs_up_when_forced(tmp_path, monkeypatch) -> None:
    import src.profile.builder as builder

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(_valid_profile()), encoding="utf-8")

    monkeypatch.setattr(
        builder,
        "extract_resume_text",
        lambda path: ExtractionResult(
            text=SAMPLE_RESUME, method="test", page_count=1
        ),
    )

    result = build_profile(tmp_path / "resume.pdf", profile_path, force=True)

    assert result.status == "updated"
    assert result.backup_path is not None
    assert result.backup_path.exists()
    rebuilt = load_profile(profile_path)
    assert rebuilt["meta"]["extractor"] == "local_heuristic"
    assert rebuilt["experience"][0]["company"] == "Acme Systems"
