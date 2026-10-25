"""Shared data models and helpers for the job assistant."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (seconds precision)."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: Any) -> str:
    """Normalize text for stable comparison and hashing.

    Lower-cases, normalizes Unicode, turns punctuation into spaces and collapses
    repeated whitespace. ``None`` becomes an empty string.
    """

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return " ".join(text.split())


def compute_dedupe_hash(company: str, title: str, location: str) -> str:
    """Hash normalized company, title and location for cross-source dedupe."""

    key = "|".join(
        (normalize_text(company), normalize_text(title), normalize_text(location))
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Job:
    """A normalized job listing produced by every collector."""

    id: str
    source: str
    title: str
    company: str
    location: str = ""
    remote: bool = False
    description: str = ""
    apply_url: str = ""
    posted_date: str | None = None
    fetched_at: str = field(default_factory=utc_now_iso)
    raw: Mapping[str, Any] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.id = str(self.id).strip()
        self.source = str(self.source).strip().lower()
        self.title = str(self.title).strip()
        self.company = str(self.company).strip()
        self.location = str(self.location or "").strip()
        self.description = str(self.description or "").strip()
        self.apply_url = str(self.apply_url or "").strip()
        if self.posted_date is not None:
            self.posted_date = str(self.posted_date).strip() or None
        if not self.id or not self.title or not self.company:
            raise ValueError("Job requires a non-empty id, title and company")

    @property
    def dedupe_hash(self) -> str:
        return compute_dedupe_hash(self.company, self.title, self.location)
