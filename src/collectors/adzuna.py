"""Adzuna jobs API collector (requires free API credentials)."""

from __future__ import annotations

from typing import Any

from src.collectors.base import (
    Collector,
    CollectorError,
    MissingCredentialsError,
    html_to_text,
    is_remote,
    to_iso_date,
)
from src.config import get_env
from src.models import Job

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


class AdzunaCollector(Collector):
    name = "adzuna"

    def __init__(self, settings: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(settings, **kwargs)
        self.app_id = str(
            self.settings.get("app_id") or get_env("ADZUNA_APP_ID") or ""
        ).strip()
        self.app_key = str(
            self.settings.get("app_key") or get_env("ADZUNA_APP_KEY") or ""
        ).strip()

    def fetch(self) -> list[Job]:
        if not self.app_id or not self.app_key:
            raise MissingCredentialsError(
                "Adzuna requires ADZUNA_APP_ID and ADZUNA_APP_KEY in .env "
                "(or sources.adzuna.app_id/app_key in config.yaml)"
            )

        country = str(self.settings.get("country") or "in").strip().lower()
        params: dict[str, Any] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": self._results_per_page(),
        }
        for key in ("what", "where", "max_days_old", "salary_min"):
            value = self.settings.get(key)
            if value not in (None, "", 0):
                params[key] = value

        payload = self._get_json(BASE_URL.format(country=country), params=params)
        return self.parse_payload(payload)

    def _results_per_page(self) -> int:
        try:
            value = int(self.settings.get("results_per_page", 50))
        except (TypeError, ValueError):
            value = 50
        return max(1, min(value, 50))

    def parse_payload(self, payload: Any) -> list[Job]:
        """Normalize an Adzuna search response."""

        if not isinstance(payload, dict):
            raise CollectorError("Adzuna payload must be a JSON object")
        results = payload.get("results")
        if not isinstance(results, list):
            raise CollectorError("Adzuna payload is missing a results list")

        jobs: list[Job] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            title = str(item.get("title") or "").strip()
            if raw_id is None or not title:
                continue

            company_value = item.get("company")
            if isinstance(company_value, dict):
                company = str(company_value.get("display_name") or "").strip()
            else:
                company = str(company_value or "").strip()
            if not company:
                continue

            location_value = item.get("location")
            if isinstance(location_value, dict):
                location = str(location_value.get("display_name") or "").strip()
            else:
                location = str(location_value or "").strip()

            description = html_to_text(item.get("description"))
            url = str(item.get("redirect_url") or item.get("url") or "").strip()
            posted = to_iso_date(item.get("created"))

            job = self._try_job(
                id=str(raw_id),
                title=title,
                company=company,
                location=location,
                remote=is_remote(location, title, description[:500]),
                description=description,
                apply_url=url,
                posted_date=posted,
                raw=item,
            )
            if job is not None:
                jobs.append(job)
        return jobs
