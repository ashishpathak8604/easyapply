"""Greenhouse public job board collector."""

from __future__ import annotations

from typing import Any

from src.collectors.base import Collector, CollectorError, html_to_text, is_remote, to_iso_date
from src.models import Job

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


class GreenhouseCollector(Collector):
    name = "greenhouse"

    def fetch(self) -> list[Job]:
        slugs = self.settings.get("company_slugs") or []
        if not slugs:
            raise CollectorError(
                "Greenhouse is enabled but sources.greenhouse.company_slugs is empty"
            )
        jobs: list[Job] = []
        for slug in slugs:
            slug = str(slug).strip()
            if not slug:
                continue
            payload = self._get_json(
                BASE_URL.format(slug=slug), params={"content": "true"}
            )
            jobs.extend(self.parse_payload(payload, slug))
        return jobs

    def parse_payload(self, payload: Any, slug: str = "") -> list[Job]:
        """Normalize a Greenhouse board payload.

        Malformed individual entries are skipped; a malformed payload raises.
        """

        if not isinstance(payload, dict):
            raise CollectorError("Greenhouse payload must be a JSON object")
        raw_jobs = payload.get("jobs")
        if not isinstance(raw_jobs, list):
            raise CollectorError("Greenhouse payload is missing a jobs list")

        jobs: list[Job] = []
        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            title = str(item.get("title") or "").strip()
            if raw_id is None or not title:
                continue

            location_value = item.get("location")
            if isinstance(location_value, dict):
                location = str(location_value.get("name") or "").strip()
            else:
                location = str(location_value or "").strip()

            company = str(item.get("company_name") or slug or "").strip()
            url = str(item.get("absolute_url") or "").strip()
            description = html_to_text(item.get("content") or item.get("description"))
            posted = to_iso_date(
                item.get("first_published") or item.get("updated_at")
            )

            job = self._try_job(
                id=str(raw_id),
                title=title,
                company=company,
                location=location,
                remote=is_remote(location, title),
                description=description,
                apply_url=url,
                posted_date=posted,
                raw=item,
            )
            if job is not None:
                jobs.append(job)
        return jobs
