"""Small, non-retrying Jooble REST client."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.core.config import settings

from .models import RawJoobleJob


class JoobleAPIError(RuntimeError):
    """Raised when Jooble cannot return a valid response."""


class JoobleClient:
    """Fetch Jooble jobs on demand; construction never performs network I/O."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.JOOBLE_API_KEY or "").strip()
        self.base_url = (base_url or settings.JOOBLE_API_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.JOOBLE_TIMEOUT
        self._opener = opener

    def search(
        self,
        *,
        keywords: str,
        location: str,
        page: int = 1,
        result_on_page: int = 20,
    ) -> list[RawJoobleJob]:
        if not self.api_key:
            raise JoobleAPIError("JOOBLE_API_KEY is not configured")
        if page < 1:
            raise ValueError("page must be 1 or greater")
        if not 1 <= result_on_page <= 50:
            raise ValueError("result_on_page must be between 1 and 50")

        body = {
            "keywords": keywords,
            "location": location,
            "radius": "40",
            "page": str(page),
            "ResultOnPage": result_on_page,
            "SearchMode": 0,
            "companysearch": False,
        }
        request = Request(
            f"{self.base_url}/{self.api_key}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

        try:
            with self._opener(request, timeout=self.timeout) as response:
                status = getattr(response, "status", 200)
                raw_body = response.read()
        except HTTPError as exc:
            raise JoobleAPIError(f"Jooble request failed with HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise JoobleAPIError("Jooble request failed due to a network error") from exc

        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JoobleAPIError(f"Jooble returned HTTP {status} with invalid JSON") from exc

        if not isinstance(decoded, dict):
            raise JoobleAPIError("Jooble returned an unexpected response shape")
        jobs = decoded.get("jobs", [])
        if not isinstance(jobs, list):
            raise JoobleAPIError("Jooble response field 'jobs' is not a list")

        parsed: list[RawJoobleJob] = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            try:
                parsed.append(RawJoobleJob.from_payload(item))
            except ValueError:
                # Invalid individual records are ignored; the valid page remains usable.
                continue
        return parsed
