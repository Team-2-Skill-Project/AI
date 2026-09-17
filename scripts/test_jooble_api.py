"""One-call, read-only Jooble API probe for the Egypt regional feed.

This script is intentionally standalone. It does not import or mutate SkillMatch
recommendation code, repositories, ranking, or mock data.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


API_BASE_URL = "https://eg.jooble.org/api"
REQUEST_TIMEOUT_SECONDS = 20
SAMPLE_LIMIT = 3


def _truncate(value: object, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _sanitized_job(job: object) -> dict[str, object]:
    if not isinstance(job, dict):
        return {"value_type": type(job).__name__}

    fields = (
        "id",
        "title",
        "company",
        "location",
        "type",
        "salary",
        "snippet",
        "source",
        "link",
        "updated",
    )
    result: dict[str, object] = {}
    for field in fields:
        if field in job:
            result[field] = _truncate(job[field])
    return result


def main() -> int:
    load_dotenv()
    api_key = os.getenv("JOOBLE_API_KEY", "").strip()
    if not api_key:
        print("Missing JOOBLE_API_KEY environment variable.", file=sys.stderr)
        return 2

    payload = {
        "keywords": "Python Developer",
        "location": "Egypt",
        "radius": "40",
        "page": "1",
        "ResultOnPage": 5,
        "SearchMode": 0,
        "companysearch": False,
    }
    request = Request(
        f"{API_BASE_URL}/{api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = response.status
            raw_body = response.read()
    except HTTPError as error:
        print(f"Jooble probe failed: HTTP {error.code}.", file=sys.stderr)
        return 1
    except URLError as error:
        print(f"Jooble probe failed: network error ({error.reason}).", file=sys.stderr)
        return 1
    except TimeoutError:
        print("Jooble probe failed: request timed out.", file=sys.stderr)
        return 1

    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        print(f"Jooble probe returned HTTP {status} but a non-JSON response.")
        return 1

    if not isinstance(body, dict):
        print(f"Jooble probe returned HTTP {status} with top-level type {type(body).__name__}.")
        return 0

    jobs = body.get("jobs")
    jobs_list = jobs if isinstance(jobs, list) else []
    job_keys = sorted({key for item in jobs_list if isinstance(item, dict) for key in item})
    summary = {
        "http_status": status,
        "top_level_keys": sorted(body),
        "total_count": body.get("totalCount"),
        "returned_job_count": len(jobs_list),
        "job_keys": job_keys,
        "sample_jobs": [_sanitized_job(job) for job in jobs_list[:SAMPLE_LIMIT]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
