"""Command-line interface for Phase 1.

Commands:
    python -m src.cli build-profile
    python -m src.cli collect [--fixtures DIR | --allow-network]
    python -m src.cli list-jobs --limit 20
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Sequence

from src.collectors.base import CollectorError, NoEnabledSourcesError
from src.collectors.service import CollectionReport, run_collection
from src.config import ConfigError, load_config, load_environment
from src.db.database import Database, DatabaseError
from src.llm.base import LLMError
from src.llm.factory import create_llm
from src.logging_utils import setup_logging
from src.profile.builder import (
    ProfileBuildError,
    build_profile,
    format_profile_summary,
)
from src.profile.extractor import ResumeExtractionError
from src.profile.schema import ProfileValidationError

logger = logging.getLogger("src.cli")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        default="config.yaml",
        help="path to config.yaml (default: ./config.yaml)",
    )
    common.add_argument(
        "--db",
        default=None,
        help="override the SQLite database path from config.yaml",
    )

    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="AI Job Application Assistant - Phase 1 (local only)",
    )
    parser.add_argument(
        "--version", action="version", version="job-assistant 0.1.0 (Phase 1)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_parser = subparsers.add_parser(
        "build-profile",
        parents=[common],
        help="extract a resume PDF into data/profile.json (local extraction)",
    )
    profile_parser.add_argument(
        "--resume", default=None, help="resume PDF path (default from config)"
    )
    profile_parser.add_argument(
        "--profile", default=None, help="output profile path (default from config)"
    )
    profile_parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate even if profile.json exists (creates a backup)",
    )
    profile_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and validate without writing (use with --force to preview)",
    )
    profile_parser.add_argument(
        "--use-ai",
        action="store_true",
        help="use the configured AI provider (requires explicit data-transfer "
        "consent in config.yaml); off by default",
    )

    collect_parser = subparsers.add_parser(
        "collect",
        parents=[common],
        help="collect jobs from enabled sources into SQLite (network blocked by default)",
    )
    collect_parser.add_argument(
        "--fixtures",
        default=None,
        metavar="DIR",
        help="read saved JSON fixtures instead of the network (offline mode)",
    )
    collect_parser.add_argument(
        "--allow-network",
        action="store_true",
        help="permit live HTTP requests to enabled public job sources; only use "
        "after you have explicitly approved external access",
    )

    list_parser = subparsers.add_parser(
        "list-jobs",
        parents=[common],
        help="list jobs stored in the local database",
    )
    list_parser.add_argument(
        "--limit", type=int, default=20, help="maximum jobs to show (default 20)"
    )
    list_parser.add_argument(
        "--json", action="store_true", help="print rows as JSON instead of a table"
    )
    return parser


def _database_for(args: argparse.Namespace, config) -> Database:
    if args.db:
        path = Path(args.db).expanduser()
    else:
        path = config.path_for("database")
    return Database(path).initialize()


def _log_run(
    database: Database,
    command: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        database.log_run(command, status, message, details)
    except Exception as exc:  # audit logging should not hide the real result
        logger.warning("could not write run_log: %s", exc)


def _cmd_build_profile(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config.path_for("log"))
    load_environment()

    resume_path = (
        Path(args.resume).expanduser()
        if args.resume
        else config.path_for("resume")
    )
    profile_path = (
        Path(args.profile).expanduser()
        if args.profile
        else config.path_for("profile")
    )

    llm = None
    if args.use_ai:
        llm = create_llm(config)

    result = build_profile(
        resume_path,
        profile_path,
        config=config,
        force=args.force,
        dry_run=args.dry_run,
        use_ai=args.use_ai,
        llm=llm,
    )

    if result.preserved:
        print(f"Existing profile preserved: {result.profile_path}")
        print("Manual edits were not overwritten. Use --force to rebuild.")
    elif result.status == "dry_run":
        print("Dry run: profile parsed and validated; nothing was written.")
    elif result.status == "created":
        print(f"Created profile: {result.profile_path}")
    else:
        print(f"Updated profile: {result.profile_path}")
        if result.backup_path:
            print(f"Backup of previous profile: {result.backup_path}")

    if result.extraction is not None:
        print(
            f"Extracted with {result.extraction.method} "
            f"({result.extraction.page_count or 0} page(s))."
        )

    print()
    print(format_profile_summary(result.profile))

    if result.warnings:
        print()
        print("Review warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")

    database = _database_for(args, config)
    try:
        _log_run(
            database,
            "build-profile",
            "success" if not result.preserved else "preserved",
            f"status={result.status}",
            {"profile": str(result.profile_path), "status": result.status},
        )
    finally:
        database.close()
    return 0


def _visualise_report(report: CollectionReport) -> None:
    print(f"Mode: {'offline fixtures' if report.fixture_mode else 'live network'}")
    print(
        f"Fetched: {report.fetched} | Inserted: {report.inserted} | "
        f"Duplicates: {report.duplicates}"
    )
    for item in report.sources:
        if item.error:
            print(f"  {item.source}: ERROR - {item.error}")
        else:
            print(
                f"  {item.source}: fetched {item.fetched}, inserted {item.inserted}, "
                f"duplicates {item.duplicate_source + item.duplicate_hash}"
            )


def _cmd_collect(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config.path_for("log"))

    fixtures = Path(args.fixtures).expanduser() if args.fixtures else None
    if fixtures is None and not args.allow_network:
        message = (
            "Live network collection is blocked by default. Use "
            "--fixtures <dir> for offline mode, or --allow-network only after "
            "you explicitly approve external access."
        )
        print(f"Blocked: {message}", file=sys.stderr)
        database = _database_for(args, config)
        try:
            _log_run(database, "collect", "blocked", message)
        finally:
            database.close()
        return 2

    database = _database_for(args, config)
    try:
        report = run_collection(
            config,
            database,
            allow_network=args.allow_network,
            fixture_dir=fixtures,
            logger_=logger,
        )
        _visualise_report(report)
        errors = report.errors
        if errors:
            print("Source errors:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        successful = any(item.error is None for item in report.sources)
        status = "success" if successful and not errors else (
            "partial" if successful else "error"
        )
        _log_run(
            database,
            "collect",
            status,
            f"inserted={report.inserted} duplicates={report.duplicates}",
            report.as_dict(),
        )
        print(f"Database: {database.path}")
        return 0 if successful else 1
    finally:
        database.close()


def _cmd_list_jobs(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    setup_logging(config.path_for("log"))
    if args.limit < 1:
        print("error: --limit must be at least 1", file=sys.stderr)
        return 2

    database = _database_for(args, config)
    try:
        rows = database.list_jobs(limit=args.limit)
        total = database.count_jobs()
        if args.json:
            payload = [dict(row) for row in rows]
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            if not rows:
                print("No jobs found. Run collect first, or check the database path.")
            else:
                print(
                    f"{'ID':>5}  {'SOURCE':<12} {'TITLE':<38} {'COMPANY':<24} "
                    f"{'LOCATION':<22} {'REMOTE':<6} {'POSTED':<10}"
                )
                print("-" * 124)
                for row in rows:
                    title = (row["title"] or "")[:38]
                    company = (row["company"] or "")[:24]
                    location = (row["location"] or "")[:22]
                    posted = (row["posted_date"] or "")[:10]
                    remote = "yes" if row["remote"] else "no"
                    print(
                        f"{row['id']:>5}  {row['source']:<12} {title:<38} "
                        f"{company:<24} {location:<22} {remote:<6} {posted:<10}"
                    )
            print()
            print(f"Showing {len(rows)} of {total} job(s). Database: {database.path}")
        _log_run(database, "list-jobs", "success", f"shown={len(rows)}")
        return 0
    finally:
        database.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "build-profile":
            return _cmd_build_profile(args)
        if args.command == "collect":
            return _cmd_collect(args)
        if args.command == "list-jobs":
            return _cmd_list_jobs(args)
        parser.print_help()
        return 2
    except (
        ConfigError,
        ProfileBuildError,
        ProfileValidationError,
        ResumeExtractionError,
        CollectorError,
        NoEnabledSourcesError,
        DatabaseError,
        LLMError,
        PermissionError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        logger.debug("command failed", exc_info=True)
        return 2
    except Exception as exc:  # last-resort safety net
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        logger.debug("unexpected command failure", exc_info=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
