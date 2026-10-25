"""Collection orchestration: enabled sources, network guard, database writes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.collectors.adzuna import AdzunaCollector
from src.collectors.base import (
    Collector,
    CollectorError,
    HttpClient,
    NoEnabledSourcesError,
)
from src.collectors.fixtures import FixtureHttpClient
from src.collectors.greenhouse import GreenhouseCollector
from src.collectors.lever import LeverCollector
from src.collectors.remoteok import RemoteOKCollector
from src.config import AppConfig
from src.db.database import Database
from src.models import utc_now_iso

COLLECTOR_CLASSES: dict[str, type[Collector]] = {
    "greenhouse": GreenhouseCollector,
    "lever": LeverCollector,
    "adzuna": AdzunaCollector,
    "remoteok": RemoteOKCollector,
}

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SourceReport:
    source: str
    fetched: int = 0
    inserted: int = 0
    duplicate_source: int = 0
    duplicate_hash: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fetched": self.fetched,
            "inserted": self.inserted,
            "duplicate_source": self.duplicate_source,
            "duplicate_hash": self.duplicate_hash,
            "error": self.error,
        }


@dataclass(slots=True)
class CollectionReport:
    fixture_mode: bool
    started_at: str = field(default_factory=utc_now_iso)
    sources: list[SourceReport] = field(default_factory=list)

    @property
    def fetched(self) -> int:
        return sum(item.fetched for item in self.sources)

    @property
    def inserted(self) -> int:
        return sum(item.inserted for item in self.sources)

    @property
    def duplicates(self) -> int:
        return sum(
            item.duplicate_source + item.duplicate_hash for item in self.sources
        )

    @property
    def errors(self) -> list[str]:
        return [
            f"{item.source}: {item.error}"
            for item in self.sources
            if item.error
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fixture_mode": self.fixture_mode,
            "started_at": self.started_at,
            "fetched": self.fetched,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "sources": [item.as_dict() for item in self.sources],
        }


def _make_collector(
    name: str,
    source_settings: dict[str, Any],
    collection_settings: dict[str, Any],
    http: HttpClient | FixtureHttpClient,
) -> Collector:
    collector_class = COLLECTOR_CLASSES[name]
    return collector_class(
        settings=source_settings,
        http=http,  # type: ignore[arg-type]
        timeout=float(collection_settings.get("timeout_seconds", 20)),
        max_retries=int(collection_settings.get("max_retries", 3)),
        backoff_seconds=float(collection_settings.get("backoff_seconds", 1.0)),
        rate_limit_seconds=float(collection_settings.get("rate_limit_seconds", 0.5)),
        user_agent=str(
            collection_settings.get(
                "user_agent", "job-assistant-phase1/0.1 (personal use)"
            )
        ),
    )


def run_collection(
    config: AppConfig,
    database: Database,
    *,
    allow_network: bool = False,
    fixture_dir: str | Path | None = None,
    logger_: logging.Logger | None = None,
) -> CollectionReport:
    """Collect from enabled sources into SQLite.

    Live network access is refused unless ``allow_network`` is true. Passing
    ``fixture_dir`` uses saved responses instead and never touches the network.
    """

    log = logger_ or logger

    if fixture_dir is None and not allow_network:
        raise PermissionError(
            "Live network collection is blocked. Re-run with "
            "--fixtures <dir> for offline mode, or --allow-network only after "
            "you have explicitly approved external access."
        )

    enabled = config.enabled_sources()
    if not enabled:
        raise NoEnabledSourcesError(
            "No job sources are enabled. Set sources.<name>.enabled: true in "
            "config.yaml (start with one source)."
        )

    if fixture_dir is not None:
        http: HttpClient | FixtureHttpClient = FixtureHttpClient(fixture_dir)
        is_fixture = True
    else:
        http = HttpClient(
            timeout=float(config.collection.get("timeout_seconds", 20)),
            max_retries=int(config.collection.get("max_retries", 3)),
            backoff_seconds=float(config.collection.get("backoff_seconds", 1.0)),
            user_agent=str(
                config.collection.get(
                    "user_agent", "job-assistant-phase1/0.1 (personal use)"
                )
            ),
        )
        is_fixture = False

    report = CollectionReport(fixture_mode=is_fixture)

    for name in enabled:
        source_report = SourceReport(source=name)
        try:
            collector = _make_collector(
                name,
                config.source_settings(name),
                config.collection,
                http,
            )
            jobs = collector.fetch()
            source_report.fetched = len(jobs)
            for job in jobs:
                result = database.insert_job(job)
                if result.status == "inserted":
                    source_report.inserted += 1
                elif result.status == "duplicate_source":
                    source_report.duplicate_source += 1
                else:
                    source_report.duplicate_hash += 1
            log.info(
                "collected source=%s fetched=%d inserted=%d",
                name,
                source_report.fetched,
                source_report.inserted,
            )
        except CollectorError as exc:
            source_report.error = str(exc)
            log.warning("collector failed source=%s error=%s", name, exc)
        except Exception as exc:  # defensive: one bad source must not stop others
            source_report.error = f"{type(exc).__name__}: {exc}"
            log.exception("unexpected collector error source=%s", name)
        report.sources.append(source_report)

    return report
