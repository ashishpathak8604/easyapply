"""Lever public job board collector."""

from __future__ import annotations

from typing import Any

from src.collectors.base import Collector, CollectorError, html_to_text, is_remote, to_iso_date
from src.models import Job

BASE_URL = "https://api.lever.co/v0/postings/{slug}"


class LeverCollector(Collector):
    name = "lever"

    def fetch(self) -> list[Job]:
        slugs = self.settings.get("company_slugs") or []
        if not slugs:
            raise CollectorError(
                "Lever is enabled but sources.lever.company_slugs is empty"
            )
        jobs: list[Job] = []
        for slug in slugs:
            slug = str(slug).strip()
            if not slug:
                continue
            payload = self._get_json(
                BASE_URL.format(slug=slug), params={"mode": "json"}
            )
            jobs.extend(self.parse_payload(payload, slug))
        return jobs

    def parse_payload(self, payload: Any, slug: str = "") -> list[Job]:
        """Normalize a Lever postings payload."""

        if not isinstance(payload, list):
            raise CollectorError("Lever payload must be a JSON list")

        company_default = str(
            self.settings.get("company_name") or slug or ""
        ).strip()
        jobs: list[Job] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            title = str(item.get("text") or item.get("title") or "").strip()
            if raw_id is None or not title:
                continue

            categories = item.get("categories")
            if not isinstance(categories, dict):
                categories = {}
            location = str(categories.get("location") or "").strip()
            workplace = str(item.get("workplaceType") or "").strip()
            company = str(
                item.get("company") or company_default
            ).strip()

            description = html_to_text(
                item.get("descriptionPlain")
                or item.get("description")
                or item.get("descriptionBody")
            )
            url = str(item.get("hostedUrl") or item.get("applyUrl") or "").strip()
            posted = to_iso_date(item.get("createdAt") or item.get("created_at"))

            job = self._try_job(
                id=str(raw_id),
                title=title,
                company=company,
                location=location,
                remote=workplace.casefold() == "remote"
                or is_remote(location, title, workplace),
                description=description,
                apply_url=url,
                posted_date=posted,
                raw=item,
            )
            if job is not None:
                jobs.append(job)
        return jobs
