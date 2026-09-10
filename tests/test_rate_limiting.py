import time
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.core.config import settings
from src.core.security import rate_limiter, InMemoryRateLimiter

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_limiter_state():
    """Ensure a clean rate limiter state before and after each test."""
    rate_limiter.reset()
    original_enabled = settings.RATE_LIMIT_ENABLED
    original_requests = settings.RATE_LIMIT_REQUESTS
    original_window = settings.RATE_LIMIT_WINDOW_SECONDS
    yield
    rate_limiter.reset()
    settings.RATE_LIMIT_ENABLED = original_enabled
    settings.RATE_LIMIT_REQUESTS = original_requests
    settings.RATE_LIMIT_WINDOW_SECONDS = original_window

def test_rate_limiting_headers_on_api_endpoints():
    """Verify standard RFC RateLimit headers are attached to API responses."""
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_REQUESTS = 10
    settings.RATE_LIMIT_WINDOW_SECONDS = 60

    headers = {"X-Forwarded-For": "203.0.113.195"}
    response = client.get("/api/v1/review-queue/", headers=headers)
    assert response.status_code == 200

    assert "X-RateLimit-Limit" in response.headers
    assert response.headers["X-RateLimit-Limit"] == "10"
    assert "X-RateLimit-Remaining" in response.headers
    assert response.headers["X-RateLimit-Remaining"] == "9"
    assert "X-RateLimit-Reset" in response.headers
    assert response.headers["X-RateLimit-Reset"] == "60"

def test_rate_limiting_decrements_quota():
    """Verify remaining count decrements with each consecutive request."""
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_REQUESTS = 5
    settings.RATE_LIMIT_WINDOW_SECONDS = 60

    headers = {"X-Forwarded-For": "198.51.100.1"}

    for i in range(4):
        resp = client.get("/api/v1/review-queue/", headers=headers)
        assert resp.status_code == 200
        expected_remaining = str(5 - (i + 1))
        assert resp.headers["X-RateLimit-Remaining"] == expected_remaining

def test_rate_limiting_enforcement_returns_429():
    """Verify that exceeding the quota returns HTTP 429 with standard headers and error body."""
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_REQUESTS = 3
    settings.RATE_LIMIT_WINDOW_SECONDS = 30

    headers = {"X-Forwarded-For": "198.51.100.42"}

    # Consume available quota (3 requests)
    for _ in range(3):
        res = client.get("/api/v1/review-queue/", headers=headers)
        assert res.status_code == 200

    # 4th request must be throttled with HTTP 429
    blocked = client.get("/api/v1/review-queue/", headers=headers)
    assert blocked.status_code == 429

    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.headers["X-RateLimit-Limit"] == "3"

    body = blocked.json()
    assert body["error"] == "RATE_LIMIT_EXCEEDED"
    assert "retry_after" in body
    assert body["retry_after"] > 0

def test_rate_limiting_exempt_paths():
    """Verify health check and documentation endpoints are exempt from rate limiting."""
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_REQUESTS = 2
    settings.RATE_LIMIT_WINDOW_SECONDS = 60

    headers = {"X-Forwarded-For": "192.0.2.1"}

    # Hit health endpoint many times beyond the limit
    for _ in range(10):
        resp = client.get("/health", headers=headers)
        assert resp.status_code == 200

    # Hit root endpoint beyond the limit
    for _ in range(10):
        resp = client.get("/", headers=headers)
        assert resp.status_code == 200

def test_rate_limiting_client_isolation():
    """Verify distinct client IPs maintain independent quotas."""
    settings.RATE_LIMIT_ENABLED = True
    settings.RATE_LIMIT_REQUESTS = 2
    settings.RATE_LIMIT_WINDOW_SECONDS = 60

    client_a_headers = {"X-Forwarded-For": "10.0.0.1"}
    client_b_headers = {"X-Forwarded-For": "10.0.0.2"}

    # Client A consumes quota
    res1 = client.get("/api/v1/review-queue/", headers=client_a_headers)
    assert res1.status_code == 200
    res2 = client.get("/api/v1/review-queue/", headers=client_a_headers)
    assert res2.status_code == 200
    res3 = client.get("/api/v1/review-queue/", headers=client_a_headers)
    assert res3.status_code == 429

    # Client B should still have full quota
    res_b = client.get("/api/v1/review-queue/", headers=client_b_headers)
    assert res_b.status_code == 200
    assert res_b.headers["X-RateLimit-Remaining"] == "1"

def test_rate_limiting_disabled_toggle():
    """Verify requests bypass throttling when RATE_LIMIT_ENABLED is False."""
    settings.RATE_LIMIT_ENABLED = False
    settings.RATE_LIMIT_REQUESTS = 2
    settings.RATE_LIMIT_WINDOW_SECONDS = 60

    headers = {"X-Forwarded-For": "172.16.0.100"}

    for _ in range(6):
        resp = client.get("/api/v1/review-queue/", headers=headers)
        assert resp.status_code == 200
        # Headers should not be attached when disabled
        assert "X-RateLimit-Limit" not in resp.headers

def test_in_memory_rate_limiter_unit_logic():
    """Unit test for InMemoryRateLimiter sliding window tracking and expiration."""
    limiter = InMemoryRateLimiter()

    # Allow 2 requests per 1-second window
    allowed, remaining, _ = limiter.check("test-client", max_requests=2, window_seconds=1)
    assert allowed is True
    assert remaining == 1

    allowed, remaining, _ = limiter.check("test-client", max_requests=2, window_seconds=1)
    assert allowed is True
    assert remaining == 0

    # 3rd request should fail
    allowed, remaining, retry_after = limiter.check("test-client", max_requests=2, window_seconds=1)
    assert allowed is False
    assert remaining == 0
    assert retry_after >= 1

    # Reset clears quota
    limiter.reset("test-client")
    allowed, remaining, _ = limiter.check("test-client", max_requests=2, window_seconds=1)
    assert allowed is True
    assert remaining == 1
