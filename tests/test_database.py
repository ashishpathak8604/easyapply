"""Tests for SQLite job deduplication and the run log."""

from __future__ import annotations

from src.db.database import Database
from src.models import Job, compute_dedupe_hash


def _job(
    *,
    source: str = "greenhouse",
    job_id: str = "101",
    title: str = "Junior Python Developer",
    company: str = "Acme Systems",
    location: str = "Bengaluru, India",
) -> Job:
    return Job(
        id=job_id,
        source=source,
        title=title,
        company=company,
        location=location,
        remote=False,
        description="Build Python services.",
        apply_url="https://example.com/jobs/101",
    )


def test_insert_job_and_count(tmp_path) -> None:
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        result = database.insert_job(_job())
        assert result.status == "inserted"
        assert result.inserted
        assert database.count_jobs() == 1
    finally:
        database.close()


def test_duplicate_by_source_and_id(tmp_path) -> None:
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        first = database.insert_job(_job())
        second = database.insert_job(_job(title="Changed title"))
        assert first.status == "inserted"
        assert second.status == "duplicate_source"
        assert second.job_id == first.job_id
        assert database.count_jobs() == 1
    finally:
        database.close()


def test_duplicate_by_content_hash_across_sources(tmp_path) -> None:
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        first = database.insert_job(_job(source="greenhouse", job_id="101"))
        second = database.insert_job(
            _job(source="lever", job_id="lever-201", title="  junior python developer ")
        )
        assert first.status == "inserted"
        assert second.status == "duplicate_hash"
        assert database.count_jobs() == 1
    finally:
        database.close()


def test_same_role_at_different_location_is_not_a_duplicate(tmp_path) -> None:
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        first = database.insert_job(_job())
        second = database.insert_job(
            _job(source="lever", job_id="lever-202", location="Remote")
        )
        assert first.status == "inserted"
        assert second.status == "inserted"
        assert database.count_jobs() == 2
    finally:
        database.close()


def test_dedupe_hash_ignores_case_and_punctuation() -> None:
    first = compute_dedupe_hash("Acme Systems", "Junior Python Developer", "Pune")
    second = compute_dedupe_hash("acme systems!", "junior-python developer", "PUNE")
    assert first == second


def test_run_log_records_details(tmp_path) -> None:
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        database.log_run(
            "collect", "success", "inserted=2", {"inserted": 2, "duplicates": 0}
        )
        runs = database.recent_runs()
        assert len(runs) == 1
        assert runs[0]["command"] == "collect"
        assert runs[0]["status"] == "success"
        assert '"inserted": 2' in runs[0]["details_json"]
    finally:
        database.close()


def test_list_jobs_honours_limit(tmp_path) -> None:
    database = Database(tmp_path / "jobs.db").initialize()
    try:
        database.insert_job(_job())
        database.insert_job(
            _job(source="lever", job_id="lever-201", location="Remote")
        )
        assert len(database.list_jobs(limit=1)) == 1
        assert len(database.list_jobs(limit=10)) == 2
    finally:
        database.close()
