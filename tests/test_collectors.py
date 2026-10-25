"""Tests for collectors, offline fixtures and collection orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.collectors.adzuna import AdzunaCollector
from src.collectors.base import CollectorError, NoEnabledSourcesError
from src.collectors.fixtures import FixtureHttpClient
from src.collectors.greenhouse import GreenhouseCollector
from src.collectors.lever import LeverCollector
from src.collectors.remoteok import RemoteOKCollector
from src.collectors.service import run_collection
from src.config import AppConfig
from src.db.database import Database

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "collectors"


def _load(name: str):
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_greenhouse_parses_and_skips_malformed_entries() -> None:
    jobs = GreenhouseCollector().parse_payload(_load("greenhouse.json"))

    assert len(jobs) == 2
    assert jobs[0].id == "101"
    assert jobs[0].title == "Junior Python Developer"
    assert jobs[0].company == "Acme Systems"
    assert jobs[0].location == "Bengaluru, India"
    assert jobs[0].remote is False
    assert jobs[0].description == "Build and test Python services with FastAPI."
    assert jobs[0].posted_date == "2026-10-20T10:00:00+00:00"

    assert jobs[1].remote is True
    assert "Design REST APIs." in jobs[1].description


def test_greenhouse_rejects_bad_payload() -> None:
    with pytest.raises(CollectorError):
        GreenhouseCollector().parse_payload({"jobs": "not-a-list"})


def test_lever_parses_payload() -> None:
    jobs = LeverCollector({"company_name": "Example"}).parse_payload(
        _load("lever.json")
    )

    assert len(jobs) == 2
    assert jobs[0].id == "lever-201"
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].company == "Example"
    assert jobs[0].location == "Pune, India"
    assert jobs[0].remote is False
    assert jobs[0].posted_date == "2024-10-15T13:46:40+00:00"

    assert jobs[1].remote is True
    assert jobs[1].description == "Analyze product data with SQL."


def test_adzuna_parses_payload_and_skips_missing_company() -> None:
    jobs = AdzunaCollector().parse_payload(_load("adzuna.json"))

    assert len(jobs) == 2
    assert jobs[0].id == "adzuna-301"
    assert jobs[0].company == "Gamma Labs"
    assert jobs[0].remote is False
    assert jobs[1].remote is True


def test_remoteok_parses_payload_and_skips_legal_notice() -> None:
    jobs = RemoteOKCollector().parse_payload(_load("remoteok.json"))

    assert len(jobs) == 2
    assert jobs[0].id == "remoteok-401"
    assert jobs[0].title == "Junior Backend Developer"
    assert jobs[0].company == "Echo Remote"
    assert jobs[0].remote is True
    assert jobs[0].description == "Build APIs with Python and PostgreSQL."
    assert jobs[0].posted_date == "2026-10-19T09:30:00+00:00"

    assert jobs[1].id == "remoteok-402"
    assert jobs[1].location == "Remote"
    assert jobs[1].apply_url.endswith("remoteok-402")
    assert jobs[1].posted_date == "2024-10-19T01:06:40+00:00"


def test_remoteok_rejects_non_list_payload() -> None:
    with pytest.raises(CollectorError):
        RemoteOKCollector().parse_payload({"jobs": []})


def test_fixture_http_client_resolves_source_hosts() -> None:
    client = FixtureHttpClient(FIXTURE_DIR)
    assert isinstance(client.get_json("https://remoteok.com/api"), list)
    assert "jobs" in client.get_json("https://boards-api.greenhouse.io/v1/boards/acme/jobs")


def test_fixture_http_client_reports_missing_fixture(tmp_path) -> None:
    client = FixtureHttpClient(tmp_path)
    with pytest.raises(CollectorError, match="no offline fixture"):
        client.get_json("https://remoteok.com/api")


def _config(**sources) -> AppConfig:
    return AppConfig(
        sources=sources,
        collection={
            "timeout_seconds": 1,
            "max_retries": 0,
            "backoff_seconds": 0,
            "rate_limit_seconds": 0,
            "user_agent": "test",
        },
    )


def test_collection_is_offline_and_deduplicates_reruns(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")

    config = _config(
        greenhouse={"enabled": True, "company_slugs": ["acme"]},
        lever={"enabled": True, "company_slugs": ["example"]},
        adzuna={"enabled": True, "country": "in"},
        remoteok={"enabled": True},
    )
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        first = run_collection(
            config, database, fixture_dir=FIXTURE_DIR, logger_=None
        )
        assert first.fixture_mode is True
        assert first.errors == []
        assert first.fetched == 8
        assert first.inserted == 8
        assert first.duplicates == 0
        assert database.count_jobs() == 8

        second = run_collection(
            config, database, fixture_dir=FIXTURE_DIR, logger_=None
        )
        assert second.inserted == 0
        assert second.duplicates == 8
        assert database.count_jobs() == 8
    finally:
        database.close()


def test_collection_requires_network_permission(tmp_path) -> None:
    config = _config(remoteok={"enabled": True})
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        with pytest.raises(PermissionError):
            run_collection(config, database)
    finally:
        database.close()


def test_collection_requires_enabled_source(tmp_path) -> None:
    config = _config()
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        with pytest.raises(NoEnabledSourcesError):
            run_collection(config, database, fixture_dir=FIXTURE_DIR)
    finally:
        database.close()
