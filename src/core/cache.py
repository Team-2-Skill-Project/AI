import json
import time
import logging
from typing import Any, Optional, Dict, Tuple
from src.core.redis import get_redis_client, is_redis_available

logger = logging.getLogger(__name__)

class CacheService:
    """
    Distributed cache service backed by Redis with local in-memory fallback.
    Caches expensive AI evaluations, taxonomy lookups, and parsed models.
    """

    def __init__(self, key_prefix: str = "skillmatch:cache:"):
        self.prefix = key_prefix
        self._memory_cache: Dict[str, Tuple[Any, float]] = {}

    def _get_key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get(self, key: str) -> Optional[Any]:
        """Retrieves cached value or None if missing/expired."""
        redis_key = self._get_key(key)

        if is_redis_available():
            try:
                client = get_redis_client()
                val = client.get(redis_key)
                if val is not None:
                    return json.loads(val)
                return None
            except Exception as e:
                logger.warning(f"Redis cache get failed for '{key}' ({e}); checking memory cache.")

        # In-memory fallback
        item = self._memory_cache.get(key)
        if item:
            val, expiry = item
            if time.time() < expiry:
                return val
            else:
                self._memory_cache.pop(key, None)
        return None

    def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        """Stores a JSON-serializable value with a time-to-live (TTL) in seconds."""
        redis_key = self._get_key(key)
        serialized = json.dumps(value)

        # Store in memory cache as fallback
        self._memory_cache[key] = (value, time.time() + ttl_seconds)

        if is_redis_available():
            try:
                client = get_redis_client()
                client.set(redis_key, serialized, ex=ttl_seconds)
                return True
            except Exception as e:
                logger.warning(f"Redis cache set failed for '{key}': {e}")
                return False
        return True

    def delete(self, key: str) -> bool:
        """Removes a key from both Redis and local memory cache."""
        redis_key = self._get_key(key)
        self._memory_cache.pop(key, None)

        if is_redis_available():
            try:
                client = get_redis_client()
                return bool(client.delete(redis_key))
            except Exception as e:
                logger.warning(f"Redis cache delete failed for '{key}': {e}")
        return True

    def flush(self) -> None:
        """Clears all cached items under the prefix."""
        self._memory_cache.clear()
        if is_redis_available():
            try:
                client = get_redis_client()
                keys = client.keys(f"{self.prefix}*")
                if keys:
                    client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis cache flush failed: {e}")

# Global singleton instance
cache_service = CacheService()
