import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app
from src.core.redis import get_redis_client, is_redis_available, redis_manager
from src.core.security import RedisRateLimiter, HybridRateLimiter
from src.core.cache import CacheService, cache_service
from src.workers.dispatcher import task_dispatcher

client = TestClient(app)
REDIS_AVAILABLE = is_redis_available(force_refresh=True)


redis_required = pytest.mark.skipif(
    not REDIS_AVAILABLE,
    reason="Redis server is not available in this environment",
)

@pytest.fixture(autouse=True)
def clean_test_keys():
    """Flushes test Redis keys before and after each test."""
    if is_redis_available():
        r = get_redis_client()
        keys = r.keys("test:*") + r.keys("ratelimit:test:*") + r.keys("skillmatch:cache:test:*")
        if keys:
            r.delete(*keys)
    yield
    if is_redis_available():
        r = get_redis_client()
        keys = r.keys("test:*") + r.keys("ratelimit:test:*") + r.keys("skillmatch:cache:test:*")
        if keys:
            r.delete(*keys)

@redis_required
def test_redis_connection_and_ping():
    """Verify Redis connection pool is functional and responds to PING."""
    assert is_redis_available(force_refresh=True) is True
    r = get_redis_client()
    assert r.ping() is True

@redis_required
def test_redis_rate_limiter_sliding_window():
    """Verify Redis-backed distributed rate limiter maintains sliding window."""
    limiter = RedisRateLimiter(key_prefix="ratelimit:test:")
    client_key = "client_alpha"

    # Allow 3 requests per 2 seconds
    allowed, remaining, _ = limiter.check(client_key, max_requests=3, window_seconds=2)
    assert allowed is True
    assert remaining == 2

    allowed, remaining, _ = limiter.check(client_key, max_requests=3, window_seconds=2)
    assert allowed is True
    assert remaining == 1

    allowed, remaining, _ = limiter.check(client_key, max_requests=3, window_seconds=2)
    assert allowed is True
    assert remaining == 0

    # 4th request should be throttled
    allowed, remaining, retry_after = limiter.check(client_key, max_requests=3, window_seconds=2)
    assert allowed is False
    assert remaining == 0
    assert retry_after >= 1

    # Reset clears Redis keys
    limiter.reset(client_key)
    allowed, remaining, _ = limiter.check(client_key, max_requests=3, window_seconds=2)
    assert allowed is True
    assert remaining == 2

def test_hybrid_rate_limiter_failover():
    """Verify HybridRateLimiter gracefully fails over to memory if Redis encounters an error."""
    hybrid = HybridRateLimiter()

    with patch("src.core.security.is_redis_available", return_value=False):
        allowed, remaining, _ = hybrid.check("failover_client", max_requests=2, window_seconds=5)
        assert allowed is True
        assert remaining == 1

        allowed, remaining, _ = hybrid.check("failover_client", max_requests=2, window_seconds=5)
        assert allowed is True
        assert remaining == 0

        # Throttled in memory
        allowed, remaining, retry_after = hybrid.check("failover_client", max_requests=2, window_seconds=5)
        assert allowed is False
        assert retry_after >= 1

@redis_required
def test_cache_service_redis_operations():
    """Verify CacheService correctly stores, retrieves, and evicts from Redis."""
    cache = CacheService(key_prefix="skillmatch:cache:test:")
    key = "user_summary_101"
    payload = {"skills": ["Python", "Docker"], "score": 92.5}

    # Set and Get
    assert cache.set(key, payload, ttl_seconds=10) is True
    retrieved = cache.get(key)
    assert retrieved is not None
    assert retrieved["score"] == 92.5
    assert "Docker" in retrieved["skills"]

    # Delete
    assert cache.delete(key) is True
    assert cache.get(key) is None

def test_cache_service_memory_fallback():
    """Verify CacheService falls back to memory cache when Redis is unavailable."""
    cache = CacheService(key_prefix="skillmatch:cache:test:")
    key = "fallback_key"
    payload = {"status": "ok"}

    with patch("src.core.cache.is_redis_available", return_value=False):
        assert cache.set(key, payload, ttl_seconds=10) is True
        cached = cache.get(key)
        assert cached == payload

        cache.delete(key)
        assert cache.get(key) is None

@redis_required
def test_task_dispatcher_with_redis_available():
    """Verify dispatcher attempts Celery queueing when Redis is verified available."""
    mock_task = MagicMock()
    mock_task.id = "celery_task_12345"

    with patch("src.workers.dispatcher.is_redis_available", return_value=True), \
         patch("src.workers.dispatcher.async_analyze_skill_gap.delay", return_value=mock_task):
        res = task_dispatcher.dispatch_skill_gap_analysis({"job_id": "j1"}, use_celery=True)
        assert res["status"] == "queued"
        assert res["mode"] == "celery"
        assert res["task_id"] == "celery_task_12345"

def test_task_dispatcher_fast_sync_fallback_when_redis_offline():
    """Verify dispatcher immediately runs synchronously when Redis is offline."""
    with patch("src.workers.dispatcher.is_redis_available", return_value=False), \
         patch("src.workers.dispatcher.async_analyze_skill_gap", return_value={"job_id": "j1", "score": 80.0}):
        res = task_dispatcher.dispatch_skill_gap_analysis({"job_id": "j1"}, use_celery=True)
        assert res["status"] == "completed"
        assert res["mode"] == "sync"
        assert res["result"]["score"] == 80.0

def test_health_check_reports_redis_status():
    """Verify /health endpoint returns real-time Redis connectivity information."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "redis" in data
    assert data["redis"]["status"] in ("connected", "unavailable")
    assert "url" in data["redis"]
