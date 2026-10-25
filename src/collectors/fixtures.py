"""Offline fixture HTTP client used by tests and ``collect --fixtures``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.collectors.base import CollectorError, safe_url

HOST_FILES = {
    "boards-api.greenhouse.io": "greenhouse.json",
    "api.lever.co": "lever.json",
    "api.adzuna.com": "adzuna.json",
    "remoteok.com": "remoteok.json",
    "www.remoteok.com": "remoteok.json",
}


class FixtureHttpClient:
    """Looks up saved JSON fixtures instead of making network requests."""

    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir).expanduser()
        if not self.fixture_dir.is_dir():
            raise CollectorError(f"fixture directory not found: {self.fixture_dir}")

    def _candidate_names(self, url: str) -> list[str]:
        parts = urlsplit(url)
        host = parts.netloc.casefold()
        segments = [segment for segment in parts.path.split("/") if segment]

        names: list[str] = []
        slug = ""
        if host == "boards-api.greenhouse.io":
            if len(segments) >= 3 and segments[0] == "boards":
                slug = segments[1]
            if slug:
                names.append(f"greenhouse-{slug}.json")
        elif host == "api.lever.co":
            if len(segments) >= 2 and segments[0] == "postings":
                slug = segments[1]
            if slug:
                names.append(f"lever-{slug}.json")

        default = HOST_FILES.get(host)
        if default:
            names.append(default)
        return names

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        for name in self._candidate_names(url):
            path = self.fixture_dir / name
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
            except json.JSONDecodeError as exc:
                raise CollectorError(
                    f"fixture {name} is not valid JSON: {exc.msg}"
                ) from exc
        raise CollectorError(
            f"no offline fixture found for {safe_url(url)} in {self.fixture_dir}"
        )
