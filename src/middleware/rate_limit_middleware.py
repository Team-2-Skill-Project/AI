import logging
from typing import Callable, Set
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from src.core.config import settings
from src.core.security import rate_limiter, get_client_ip

logger = logging.getLogger(__name__)

# Endpoints exempt from throttling to avoid monitoring or doc lockouts
EXEMPT_EXACT_PATHS: Set[str] = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}

EXEMPT_PREFIXES: Set[str] = {
    "/docs",
    "/redoc",
    f"{settings.API_V1_STR}/openapi.json",
    # The canonical CV router keeps its original dependency-based limiter.
    f"{settings.API_V1_STR}/cv",
}

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Security middleware enforcing rate limits across all API endpoints.
    Protects infrastructure against denial-of-service, brute force, and runaway AI loops.

    Returns standard rate limit headers on every response:
      - X-RateLimit-Limit: Total allowed requests in sliding window.
      - X-RateLimit-Remaining: Number of remaining requests in window.
      - X-RateLimit-Reset: Sliding window duration in seconds.

    Returns HTTP 429 Too Many Requests with Retry-After header when threshold is breached.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check global toggle
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path

        # Bypass exempt monitoring and documentation endpoints
        if path in EXEMPT_EXACT_PATHS or any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            return await call_next(request)

        # Identify client
        client_key = get_client_ip(request)

        # Evaluate rate quota
        allowed, remaining, retry_after = rate_limiter.check(
            key=client_key,
            max_requests=settings.RATE_LIMIT_REQUESTS,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )

        if not allowed:
            logger.warning(
                f"Rate limit exceeded for client {client_key} on {request.method} {path}. "
                f"Retry after {retry_after}s."
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "RATE_LIMIT_EXCEEDED",
                    "detail": (
                        f"Rate limit exceeded. Maximum {settings.RATE_LIMIT_REQUESTS} requests "
                        f"per {settings.RATE_LIMIT_WINDOW_SECONDS} seconds allowed."
                    ),
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(settings.RATE_LIMIT_REQUESTS),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                },
            )

        # Proceed with request execution
        response = await call_next(request)

        # Attach standard rate limit headers
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(settings.RATE_LIMIT_WINDOW_SECONDS)

        return response
