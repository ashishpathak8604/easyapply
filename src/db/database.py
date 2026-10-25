"""SQLite persistence layer with safe initialization and job deduplication."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.db.schema import SCHEMA_SQL, SCHEMA_VERSION
from src.models import Job, utc_now_iso


class DatabaseError(RuntimeError):
    """Raised when the database cannot be opened or migrated safely."""


@dataclass(slots=True)
class InsertResult:
    status: str  # inserted | duplicate_source | duplicate_hash
    job_id: int | None = None

    @property
    def inserted(self) -> bool:
        return self.status == "inserted"


class Database:
    """Small synchronous wrapper around a local SQLite database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._conn: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._conn is None:
            raise DatabaseError("Database is not initialized; call initialize()")
        return self._conn

    def initialize(self) -> "Database":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path)
        except sqlite3.Error as exc:
            raise DatabaseError(f"could not open database: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()
        return self

    def _migrate(self) -> None:
        conn = self.connection
        try:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise DatabaseError(
                    "database schema is newer than this code "
                    f"({current} > {SCHEMA_VERSION}); refusing to modify it"
                )
            if current < SCHEMA_VERSION:
                with conn:
                    conn.executescript(SCHEMA_SQL)
                    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.Error as exc:
            raise DatabaseError(f"could not initialize schema: {exc}") from exc

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        if self._conn is None:
            self.initialize()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------ jobs

    def insert_job(self, job: Job) -> InsertResult:
        """Insert a job, rejecting duplicates by source/id or content hash."""

        conn = self.connection
        existing = conn.execute(
            "SELECT id FROM jobs WHERE source = ? AND source_job_id = ?",
            (job.source, job.id),
        ).fetchone()
        if existing is not None:
            return InsertResult("duplicate_source", int(existing["id"]))

        existing = conn.execute(
            "SELECT id FROM jobs WHERE dedupe_hash = ?", (job.dedupe_hash,)
        ).fetchone()
        if existing is not None:
            return InsertResult("duplicate_hash", int(existing["id"]))

        try:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO jobs (
                        source, source_job_id, title, company, location, remote,
                        description, apply_url, posted_date, fetched_at, dedupe_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.source,
                        job.id,
                        job.title,
                        job.company,
                        job.location,
                        int(bool(job.remote)),
                        job.description,
                        job.apply_url,
                        job.posted_date,
                        job.fetched_at,
                        job.dedupe_hash,
                    ),
                )
            return InsertResult("inserted", int(cursor.lastrowid))
        except sqlite3.IntegrityError:
            # A concurrent or very recent insert won the race. Resolve it as a
            # duplicate by reading the existing row rather than failing the run.
            row = conn.execute(
                "SELECT id, source, source_job_id, dedupe_hash FROM jobs "
                "WHERE dedupe_hash = ? OR (source = ? AND source_job_id = ?)",
                (job.dedupe_hash, job.source, job.id),
            ).fetchone()
            if row is None:
                raise
            status = (
                "duplicate_source"
                if row["source"] == job.source
                and row["source_job_id"] == job.id
                else "duplicate_hash"
            )
            return InsertResult(status, int(row["id"]))

    def insert_jobs(self, jobs: list[Job]) -> list[InsertResult]:
        return [self.insert_job(job) for job in jobs]

    def count_jobs(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
        return int(row["n"])

    def list_jobs(self, limit: int = 20) -> list[sqlite3.Row]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        return list(
            self.connection.execute(
                """
                SELECT id, source, source_job_id, title, company, location,
                       remote, apply_url, posted_date, fetched_at
                FROM jobs
                ORDER BY fetched_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def get_job(self, job_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()

    # --------------------------------------------------------------- run log

    def log_run(
        self,
        command: str,
        status: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> int:
        payload = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO run_log (run_at, command, status, message, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), command, status, message, payload),
            )
        return int(cursor.lastrowid)

    def recent_runs(self, limit: int = 10) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM run_log ORDER BY id DESC LIMIT ?", (limit,)
            )
        )
