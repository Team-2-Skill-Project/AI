import time
import logging
import threading
import uuid
from collections import defaultdict, deque
from typing import Tuple, Optional, Dict
from starlette.requests import Request
from src.core.config import settings
from src.core.redis import get_redis_client, is_redis_available

logger = logging.getLogger(__name__)

class InMemoryRateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter.
    Used for local standalone mode or fallback when Redis is unavailable.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._records: Dict[str, deque] = defaultdict(deque)

    def check(
        self,
        key: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None
    ) -> Tuple[bool, int, int]:
        limit = max_requests if max_requests is not None else settings.RATE_LIMIT_REQUESTS
        window = window_seconds if window_seconds is not None else settings.RATE_LIMIT_WINDOW_SECONDS
        now = time.time()
        cutoff = now - window

        with self._lock:
            timestamps = self._records[key]

            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            current_count = len(timestamps)

            if current_count < limit:
                timestamps.append(now)
                remaining = max(0, limit - len(timestamps))
                return True, remaining, 0
            else:
                oldest = timestamps[0]
                retry_after = max(1, int(oldest + window - now))
                return False, 0, retry_after

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is not None:
                self._records.pop(key, None)
            else:
                self._records.clear()


class RedisRateLimiter:
    """
    Distributed sliding-window rate limiter backed by Redis.
    Uses Redis Sorted Sets (ZADD, ZREMRANGEBYSCORE, ZCARD) in an atomic pipeline
    to coordinate rate limiting across multiple Uvicorn worker processes or cluster nodes.
    """

    def __init__(self, key_prefix: str = "ratelimit:"):
        self.prefix = key_prefix

    def _get_key(self, client_key: str) -> str:
        return f"{self.prefix}{client_key}"

    def check(
        self,
        key: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None
    ) -> Tuple[bool, int, int]:
        limit = max_requests if max_requests is not None else settings.RATE_LIMIT_REQUESTS
        window = window_seconds if window_seconds is not None else settings.RATE_LIMIT_WINDOW_SECONDS
        redis_key = self._get_key(key)
        now = time.time()
        cutoff = now - window

        client = get_redis_client()

        # Atomic sliding-window pipeline
        pipe = client.pipeline()
        pipe.zremrangebyscore(redis_key, "-inf", cutoff)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count < limit:
            # Add current request timestamp with a unique token as member
            member = f"{now}:{uuid.uuid4().hex[:8]}"
            pipe = client.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, window + 5)
            pipe.execute()

            remaining = max(0, limit - (current_count + 1))
            return True, remaining, 0
        else:
            # Over quota: inspect earliest timestamp in the current window
            oldest_entries = client.zrange(redis_key, 0, 0, withscores=True)
            if oldest_entries:
                oldest_score = oldest_entries[0][1]
                retry_after = max(1, int(oldest_score + window - now))
            else:
                retry_after = max(1, window)
            return False, 0, retry_after

    def reset(self, key: Optional[str] = None) -> None:
        client = get_redis_client()
        if key is not None:
            client.delete(self._get_key(key))
        else:
            pattern = f"{self.prefix}*"
            keys = client.keys(pattern)
            if keys:
                client.delete(*keys)


class HybridRateLimiter:
    """
    Resilient rate limiter combining Redis-backed distributed tracking with an
    in-memory fallback. Automatically delegates to Redis when reachable;
    transparently falls back to in-memory tracking if Redis is offline.
    """

    def __init__(self):
        self._memory_limiter = InMemoryRateLimiter()
        self._redis_limiter = RedisRateLimiter()

    def check(
        self,
        key: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None
    ) -> Tuple[bool, int, int]:
        if is_redis_available():
            try:
                return self._redis_limiter.check(key, max_requests, window_seconds)
            except Exception as e:
                logger.warning(f"Redis rate limiter encountered error ({e}); failing over to memory limiter.")

        return self._memory_limiter.check(key, max_requests, window_seconds)

    def reset(self, key: Optional[str] = None) -> None:
        self._memory_limiter.reset(key)
        if is_redis_available():
            try:
                self._redis_limiter.reset(key)
            except Exception as e:
                logger.warning(f"Error resetting Redis rate limiter: {e}")


def get_client_ip(request: Request) -> str:
    """
    Resolves client IP address safely from request headers, taking into
    account reverse proxies and load balancers (e.g. Nginx, Cloudflare, AWS ALB).
    """
    client_key = request.headers.get("x-client-id") or request.headers.get("x-api-key")
    if client_key:
        return f"key:{client_key.strip()}"

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


# Default active singleton: resilient hybrid limiter
rate_limiter = HybridRateLimiter()
