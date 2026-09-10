import time
import logging
from typing import Optional
import redis
from redis.retry import Retry
from redis.backoff import ExponentialBackoff
from src.core.config import settings

logger = logging.getLogger(__name__)

class RedisManager:
    """
    Centralized Redis connection manager with connection pooling,
    fast health checks, and automatic transient failure retry.
    """

    def __init__(self):
        self._pool: Optional[redis.ConnectionPool] = None
        self._last_health_check_time: float = 0.0
        self._last_health_status: bool = False
        # Avoid opening a new socket on every API request when Redis is not
        # running locally. A short cached health state still recovers quickly
        # after Redis comes back, while keeping local development responsive.
        self._health_check_cache_ttl: float = 30.0  # seconds

    def get_pool(self) -> redis.ConnectionPool:
        """Lazily initializes and returns the shared connection pool."""
        if self._pool is None:
            retry_strategy = Retry(ExponentialBackoff(cap=0.5, base=0.1), 2)
            self._pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=getattr(settings, "REDIS_MAX_CONNECTIONS", 20),
                socket_timeout=getattr(settings, "REDIS_SOCKET_TIMEOUT", 2.0),
                socket_connect_timeout=getattr(settings, "REDIS_CONNECT_TIMEOUT", 2.0),
                retry_on_timeout=True,
                retry=retry_strategy,
                health_check_interval=30,
                decode_responses=True,
            )
            logger.info(f"Initialized shared Redis connection pool for {settings.REDIS_URL}")
        return self._pool

    def get_client(self) -> redis.Redis:
        """Returns a thread-safe Redis client from the shared connection pool."""
        pool = self.get_pool()
        return redis.Redis(connection_pool=pool)

    def is_available(self, force_refresh: bool = False) -> bool:
        """
        Fast, non-blocking check to determine if Redis is reachable.
        Caches the status for a brief duration (3s) to prevent socket thrashing.
        """
        now = time.time()
        if not force_refresh and (now - self._last_health_check_time) < self._health_check_cache_ttl:
            return self._last_health_status

        try:
            client = self.get_client()
            # Fast ping with 1-second timeout
            res = client.ping()
            self._last_health_status = bool(res)
        except Exception as e:
            logger.debug(f"Redis health check failed ({settings.REDIS_URL}): {e}")
            self._last_health_status = False

        self._last_health_check_time = now
        return self._last_health_status

    def close(self) -> None:
        """Closes the connection pool."""
        if self._pool:
            self._pool.disconnect()
            self._pool = None
            self._last_health_status = False

# Global singleton
redis_manager = RedisManager()

def get_redis_client() -> redis.Redis:
    """Helper to retrieve active Redis client instance."""
    return redis_manager.get_client()

def is_redis_available(force_refresh: bool = False) -> bool:
    """Helper to check if Redis is currently reachable."""
    return redis_manager.is_available(force_refresh=force_refresh)
