"""Redis-only caching for personalized recommendation feeds.

The cache key is derived from the current recommendation inputs, rather than
from a mutable Redis-only version counter.  This lets the next request bypass
old entries after a candidate, interaction, or catalog change even when Redis
was unavailable while that change was written.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Iterable, Optional

from src.core.config import settings
from src.core.redis import get_redis_client, is_redis_available
from src.schemas.recommendation import CandidateBehaviorHistory, RecommendationFeedResponse

logger = logging.getLogger(__name__)


class RecommendationFeedCache:
    """A fail-open, Redis-only cache for successful feed responses.

    This deliberately has no process-local fallback.  When Redis is unavailable
    or a cache operation fails, the caller recomputes from the normal database
    and recommendation services instead of serving potentially stale data.
    """

    KEY_PREFIX = "skillmatch:recommendations:v1:"

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self.ttl_seconds = ttl_seconds or settings.RECOMMENDATION_CACHE_TTL_SECONDS

    @staticmethod
    def _hash(value: Any) -> str:
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _candidate_state(candidate: Any) -> dict[str, Any]:
        if hasattr(candidate, "model_dump"):
            return candidate.model_dump(mode="json")
        if isinstance(candidate, dict):
            return candidate
        return {"candidate_id": getattr(candidate, "candidate_id", None)}

    @staticmethod
    def _behavior_state(behavior: CandidateBehaviorHistory) -> dict[str, list[str]]:
        # Views/clicks are intentionally excluded: current scoring and filters
        # do not use them.  Save, apply, dismiss, unsave, and undismiss change
        # one of these persisted sets and therefore produce a new key.
        return {
            "saved_job_ids": sorted(behavior.saved_job_ids),
            "applied_job_ids": sorted(behavior.applied_job_ids),
            "dismissed_job_ids": sorted(behavior.dismissed_job_ids),
        }

    @staticmethod
    def _catalog_state(jobs: Iterable[Any]) -> list[Any]:
        state: list[Any] = []
        for job in jobs:
            if hasattr(job, "model_dump"):
                state.append(job.model_dump(mode="json"))
            elif isinstance(job, dict):
                state.append(job)
            else:
                state.append({"job_id": getattr(job, "job_id", None)})
        return state

    def build_key(
        self,
        *,
        candidate: Any,
        behavior: CandidateBehaviorHistory,
        jobs: Iterable[Any],
        page: int,
        limit: int,
        work_mode: str | None,
        location: str | None,
        min_score: float,
    ) -> str:
        """Return a non-sensitive deterministic key for all feed inputs."""
        filters = {
            "page": page,
            "limit": limit,
            "work_mode": (work_mode or "").strip().lower(),
            "location": (location or "").strip().lower(),
            "min_score": float(min_score),
        }
        return (
            f"{self.KEY_PREFIX}"
            f"c:{self._hash(self._candidate_state(candidate))}:"
            f"b:{self._hash(self._behavior_state(behavior))}:"
            f"j:{self._hash(self._catalog_state(jobs))}:"
            f"q:{self._hash(filters)}"
        )

    def get(self, key: str) -> Optional[RecommendationFeedResponse]:
        """Return a validated cached feed, or ``None`` for a safe cache miss."""
        if not is_redis_available():
            return None
        try:
            raw = get_redis_client().get(key)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            return RecommendationFeedResponse.model_validate(payload)
        except Exception as exc:
            # Corrupted data and Redis read failures are both fail-open.  Delete
            # only the known key; never scan the cache namespace.
            logger.warning("Recommendation cache read failed; recomputing feed (%s)", type(exc).__name__)
            self.delete(key)
            return None

    def set(self, key: str, feed: RecommendationFeedResponse) -> bool:
        """Cache a validated successful feed, without affecting its response path."""
        if not is_redis_available():
            return False
        try:
            payload = json.dumps(feed.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            get_redis_client().set(key, payload, ex=self.ttl_seconds)
            return True
        except Exception as exc:
            logger.warning("Recommendation cache write failed; returning live feed (%s)", type(exc).__name__)
            return False

    def delete(self, key: str) -> bool:
        """Delete one known key, failing open if Redis cannot perform the delete."""
        if not is_redis_available():
            return False
        try:
            get_redis_client().delete(key)
            return True
        except Exception as exc:
            logger.warning("Recommendation cache delete failed (%s)", type(exc).__name__)
            return False
