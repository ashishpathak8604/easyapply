"""RemoteOK public feed collector."""

from __future__ import annotations

from typing import Any

from src.collectors.base import Collector, CollectorError, html_to_text, to_iso_date
from src.models import Job

BASE_URL = "https://remoteok.com/api"


class RemoteOKCollector(Collector):
    name = "remoteok"

    def fetch(self) -> list[Job]:
        payload = self._get_json(BASE_URL)
        return self.parse_payload(payload)

    def parse_payload(self, payload: Any) -> list[Job]:
        """Normalize the RemoteOK feed.

        The feed starts with a legal-notice object that has no job id; it and
        other malformed entries are skipped.
        """

        if not isinstance(payload, list):
            raise CollectorError("RemoteOK payload must be a JSON list")

        jobs: list[Job] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if "legal" in item and not item.get("id"):
                continue

            raw_id = item.get("id")
            title = str(
                item.get("position") or item.get("title") or ""
            ).strip()
            company = str(item.get("company") or "").strip()
            if raw_id is None or not title or not company:
                continue

            location = str(item.get("location") or "Remote").strip() or "Remote"
            description = html_to_text(
                item.get("description") or item.get("description_html")
            )
            url = str(
                item.get("apply_url") or item.get("url") or item.get("applyUrl") or ""
            ).strip()
            posted = to_iso_date(item.get("date") or item.get("epoch"))

            job = self._try_job(
                id=str(raw_id),
                title=title,
                company=company,
                location=location,
                remote=True,
                description=description,
                apply_url=url,
                posted_date=posted,
                raw=item,
            )
            if job is not None:
                jobs.append(job)
        return jobs
