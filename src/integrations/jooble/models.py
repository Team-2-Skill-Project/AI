"""Models for the untrusted Jooble response boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RawJoobleJob(BaseModel):
    """A traceable representation of one Jooble result before normalization."""

    external_id: str
    title: str
    company: str | None = None
    location: str | None = None
    snippet: str | None = None
    salary: str | None = None
    employment_type: str | None = None
    source: str | None = None
    source_url: str | None = None
    source_updated_at: datetime | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("external_id", "title", mode="before")
    @classmethod
    def _required_text(cls, value: Any) -> str:
        text = "" if value is None else str(value).strip()
        if not text:
            raise ValueError("Jooble job requires a non-empty external_id and title")
        return text

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RawJoobleJob":
        """Parse one API object while retaining the original payload."""
        return cls(
            external_id=payload.get("id"),
            title=payload.get("title"),
            company=payload.get("company") or None,
            location=payload.get("location") or None,
            snippet=payload.get("snippet") or None,
            salary=payload.get("salary") or None,
            employment_type=payload.get("type") or None,
            source=payload.get("source") or None,
            source_url=payload.get("link") or None,
            source_updated_at=payload.get("updated") or None,
            raw_payload=dict(payload),
        )
