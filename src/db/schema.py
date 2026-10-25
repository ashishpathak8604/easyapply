"""SQLite schema definitions for the job assistant."""

from __future__ import annotations

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,
    source_job_id   TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    company         TEXT    NOT NULL,
    location        TEXT    NOT NULL DEFAULT '',
    remote          INTEGER NOT NULL DEFAULT 0 CHECK (remote IN (0, 1)),
    description     TEXT    NOT NULL DEFAULT '',
    apply_url       TEXT    NOT NULL DEFAULT '',
    posted_date     TEXT,
    fetched_at      TEXT    NOT NULL,
    dedupe_hash     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_jobs_source_job UNIQUE (source, source_job_id),
    CONSTRAINT uq_jobs_dedupe_hash UNIQUE (dedupe_hash)
);

CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs (source);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs (company);
CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at ON jobs (fetched_at);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL UNIQUE,
    score       REAL    NOT NULL CHECK (score >= 0 AND score <= 100),
    reasons     TEXT    NOT NULL DEFAULT '',
    gaps        TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_matches_score ON matches (score DESC);

CREATE TABLE IF NOT EXISTS applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL UNIQUE,
    status          TEXT    NOT NULL DEFAULT 'drafted',
    cover_note      TEXT    NOT NULL DEFAULT '',
    answers_json    TEXT    NOT NULL DEFAULT '{}',
    updated_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications (status);

CREATE TABLE IF NOT EXISTS run_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at        TEXT    NOT NULL,
    command       TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    message       TEXT    NOT NULL DEFAULT '',
    details_json  TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_run_log_run_at ON run_log (run_at);
"""
