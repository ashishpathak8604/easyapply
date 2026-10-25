"""Logging setup that writes console output and a local log file."""

from __future__ import annotations

import logging
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(log_path: str | Path, *, level: int = logging.INFO) -> Path | None:
    """Configure root logging once per process.

    Returns the log file path when file logging was enabled. Never logs secrets
    because callers only log non-sensitive identifiers and counts.
    """

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    resolved: Path | None = None
    try:
        candidate = Path(log_path).expanduser()
        candidate.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(candidate, encoding="utf-8")
        handlers.append(file_handler)
        resolved = candidate
    except OSError:
        resolved = None

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=handlers,
        force=True,
    )
    return resolved
