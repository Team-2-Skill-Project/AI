from __future__ import annotations
import hashlib
import hmac
import logging
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, cast

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from starlette.requests import Request as StarletteRequest

from src.core.config import get_app_settings, settings
from src.core.redis import get_redis_client, is_redis_available

logger = logging.getLogger(__name__)


# =====================================================================
# --- API Key Auth & Rate Limiting ---
# =====================================================================

# API Key header definition for OpenAPI docs
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class SlidingWindowRateLimiter:
    """
    Thread-safe in-memory sliding window rate limiter per client identifier (IP / API key).
    Provides abuse and flood protection for CV extraction and feature endpoints.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._clients: dict[str, list[float]] = {}
        self._last_cleanup = time.time()

    def is_allowed(self, client_id: str, limit_per_minute: int) -> tuple[bool, int]:
        """
        Checks if client request is within rate limit.
        Returns (is_allowed, retry_after_seconds).
        """
        if limit_per_minute <= 0:
            return True, 0

        now = time.time()
        window_start = now - 60.0

        with self._lock:
            # Periodic cleanup of inactive clients every 5 minutes
            if now - self._last_cleanup > 300:
                self._cleanup_stale(window_start)
                self._last_cleanup = now

            timestamps = self._clients.setdefault(client_id, [])
            # Filter timestamps within current 60s sliding window
            self._clients[client_id] = [t for t in timestamps if t > window_start]
            current_count = len(self._clients[client_id])

            if current_count >= limit_per_minute:
                oldest_timestamp = self._clients[client_id][0]
                retry_after = max(1, int(60.0 - (now - oldest_timestamp)))
                return False, retry_after

            self._clients[client_id].append(now)
            return True, 0

    def _cleanup_stale(self, window_start: float) -> None:
        stale_keys = [k for k, v in self._clients.items() if not v or v[-1] <= window_start]
        for k in stale_keys:
            del self._clients[k]

    def reset(self) -> None:
        """Clears all rate limit records (primarily for testing)."""
        with self._lock:
            self._clients.clear()


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
        window_seconds: Optional[int] = None,
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
    Uses Redis Sorted Sets (ZADD, ZREMRANGEBYSCORE, ZCARD) in an atomic pipeline.
    """

    def __init__(self, key_prefix: str = "ratelimit:"):
        self.prefix = key_prefix

    def _get_key(self, client_key: str) -> str:
        return f"{self.prefix}{client_key}"

    def check(
        self,
        key: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> Tuple[bool, int, int]:
        limit = max_requests if max_requests is not None else settings.RATE_LIMIT_REQUESTS
        window = window_seconds if window_seconds is not None else settings.RATE_LIMIT_WINDOW_SECONDS
        redis_key = self._get_key(key)
        now = time.time()
        cutoff = now - window

        client: Any = get_redis_client()

        pipe: Any = client.pipeline()
        pipe.zremrangebyscore(redis_key, "-inf", cutoff)
        pipe.zcard(redis_key)
        pipe_results = cast(Any, pipe.execute())
        current_count = int(pipe_results[1]) if pipe_results and len(pipe_results) > 1 else 0

        if current_count < limit:
            member = f"{now}:{uuid.uuid4().hex[:8]}"
            pipe = client.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, window + 5)
            pipe.execute()

            remaining = max(0, limit - (current_count + 1))
            return True, remaining, 0
        else:
            raw_entries = cast(Any, client.zrange(redis_key, 0, 0, withscores=True))
            if raw_entries and isinstance(raw_entries, (list, tuple)) and len(raw_entries) > 0:
                first_entry = cast(Any, raw_entries[0])
                if isinstance(first_entry, (list, tuple)) and len(first_entry) > 1:
                    oldest_score = float(first_entry[1])
                elif isinstance(first_entry, (int, float)):
                    oldest_score = float(first_entry)
                else:
                    oldest_score = now
                retry_after = max(1, int(oldest_score + window - now))
            else:
                retry_after = max(1, window)
            return False, 0, retry_after

    def reset(self, key: Optional[str] = None) -> None:
        client = get_redis_client()
        if key is not None:
            client.delete(self._get_key(key))
        else:
            batch_size = 100
            batch = []
            for k in client.scan_iter(match=f"{self.prefix}*", count=batch_size):
                batch.append(k)
                if len(batch) >= batch_size:
                    client.delete(*batch)
                    batch.clear()
            if batch:
                client.delete(*batch)


class HybridRateLimiter:
    """
    Resilient rate limiter combining Redis-backed distributed tracking with an
    in-memory fallback. Automatically delegates to Redis when reachable;
    transparently falls back to in-memory tracking if Redis is offline.
    """

    def __init__(self):
        self._memory_limiter = InMemoryRateLimiter()
        self._redis_limiter = RedisRateLimiter()
        self._sliding_limiter = SlidingWindowRateLimiter()

    def check(
        self,
        key: str,
        max_requests: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> Tuple[bool, int, int]:
        if is_redis_available():
            try:
                return self._redis_limiter.check(key, max_requests, window_seconds)
            except Exception as e:
                logger.warning(f"Redis rate limiter encountered error ({e}); failing over to memory limiter.")

        return self._memory_limiter.check(key, max_requests, window_seconds)

    def is_allowed(self, client_id: str, limit_per_minute: int) -> tuple[bool, int]:
        return self._sliding_limiter.is_allowed(client_id, limit_per_minute)

    def reset(self, key: Optional[str] = None) -> None:
        self._memory_limiter.reset(key)
        self._sliding_limiter.reset()
        if is_redis_available():
            try:
                self._redis_limiter.reset(key)
            except Exception as e:
                logger.warning(f"Error resetting Redis rate limiter: {e}")


rate_limiter = HybridRateLimiter()


def get_client_ip(request: Request | StarletteRequest) -> str:
    """
    Resolves client identifier safely for rate limiting and auditing.
    Precedence:
      1. Hashed API Key (X-API-Key or Authorization Bearer) -> 'key:<sha256>'
      2. Client ID (X-Client-ID) -> 'client:<id>'
      3. Peer client IP (request.client.host) -> '<ip>'
    """
    api_key = request.headers.get("x-api-key")
    if not api_key:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            api_key = auth[7:].strip()

    if api_key:
        hashed = hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()
        return f"key:{hashed}"

    client_id = request.headers.get("x-client-id")
    if client_id:
        return f"client:{client_id.strip()}"

    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


get_client_identifier = get_client_ip


async def verify_api_key(
    request: Request,
    api_key_header_val: str | None = Security(api_key_header),
) -> str | None:
    """
    Verifies API Key authentication when enabled.
    Supports 'X-API-Key' header or 'Authorization: Bearer <key>'.
    """
    auth_enabled = bool(getattr(settings, "enable_api_key_auth", False) or getattr(settings, "ENABLE_API_KEY_AUTH", False))
    if not auth_enabled:
        return None

    provided_key = api_key_header_val
    if not provided_key:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:].strip()

    expected_key = getattr(settings, "api_key", None) or getattr(settings, "API_KEY", None)
    if not provided_key or provided_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "Invalid or missing API key.", "error_code": "UNAUTHORIZED"},
        )

    return provided_key


async def check_rate_limit(request: Request) -> None:
    """
    Dependency that enforces rate limits on incoming API calls.
    """
    rate_enabled = bool(getattr(settings, "enable_rate_limiting", True) and getattr(settings, "RATE_LIMIT_ENABLED", True))
    if not rate_enabled:
        return

    client_id = get_client_identifier(request)
    limit = getattr(settings, "rate_limit_per_minute", None) or getattr(settings, "RATE_LIMIT_REQUESTS", 60)
    window = getattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)
    allowed, remaining, retry_after = rate_limiter.check(
        key=client_id,
        max_requests=limit,
        window_seconds=window,
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "detail": f"Rate limit exceeded. Try again in {retry_after} seconds.",
                "error_code": "RATE_LIMIT_EXCEEDED",
            },
            headers={"Retry-After": str(retry_after)},
        )



# =====================================================================
# --- Password Hashing & Tokens ---
# =====================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a stored salt$hash string."""
    try:
        if "$" not in hashed_password:
            return False
        salt, expected_hash = hashed_password.split("$", 1)
        actual_hash = hashlib.sha256((salt + plain_password).encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Hash a password with a cryptographically secure random salt."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${pwd_hash}"


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Generate a lightweight signed token containing data and expiry timestamp."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire.timestamp(), "jti": uuid.uuid4().hex})
    token_payload = "&".join(f"{k}={v}" for k, v in sorted(to_encode.items()))
    secret = settings.SECRET_KEY.encode("utf-8")
    sig = hmac.new(secret, token_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{token_payload}.{sig}"


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and verify access token signature and expiration."""
    try:
        if "." not in token:
            return None
        payload_str, signature = token.rsplit(".", 1)
        secret = settings.SECRET_KEY.encode("utf-8")
        expected_sig = hmac.new(secret, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None

        parsed = {}
        for pair in payload_str.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                parsed[k] = v

        if "exp" in parsed:
            exp_ts = float(parsed["exp"])
            if datetime.now(timezone.utc).timestamp() > exp_ts:
                return None  # Expired
        return parsed
    except Exception:
        return None
