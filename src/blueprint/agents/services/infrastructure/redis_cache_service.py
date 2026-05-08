"""Redis-backed centralized cache service."""

import json
import logging
from collections.abc import Iterator
from typing import Any

try:
    import redis
except ImportError as e:
    raise ImportError(
        "Redis backend requires 'avs-blueprint-agents[redis]'. " "Install with: pip install 'avs-blueprint-agents[redis]'"
    ) from e

from .cache_key_mixin import _CacheKeyMixin
from .cache_service import CacheService

logger = logging.getLogger(__name__)


class RedisCacheService(_CacheKeyMixin, CacheService):
    """Centralized Redis cache — shares state across multiple service instances.

    TTL is enforced natively by Redis (EX parameter on SET).
    Uses the synchronous redis-py client to match the CacheService sync interface.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        password: str | None = None,
        db: int = 0,
        tls: bool = False,
        key_prefix: str = "",
        default_ttl: int | None = None,
        fallback_to_local: bool = False,
    ) -> None:
        super().__init__()
        self._redis_url = redis_url
        self._password = password
        self._db = db
        self._tls = tls
        self._key_prefix = key_prefix
        self._default_ttl = default_ttl
        self._fallback_to_local = fallback_to_local
        # redis-py 7.x configures TLS via the URL scheme (rediss://) rather than
        # accepting an ssl= kwarg in from_url(). Upgrade the scheme when tls=True.
        effective_url = redis_url
        if tls and redis_url.startswith("redis://"):
            effective_url = "rediss://" + redis_url[len("redis://") :]
        # Typed as Any: redis-py's sync methods are statically declared as ``Awaitable | T``
        # (the same Redis class is used for sync and async), which trips mypy on every call.
        self._client: Any = redis.Redis.from_url(
            effective_url,
            password=password,
            db=db,
            decode_responses=True,
        )

    async def on_startup(self) -> None:
        try:
            self._client.ping()
            logger.info("RedisCacheService connected to %s (prefix=%r)", self._redis_url, self._key_prefix)
        except Exception as e:
            logger.error("RedisCacheService cannot connect to Redis at %s: %s", self._redis_url, e)
            if not self._fallback_to_local:
                raise

    async def on_shutdown(self) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._client.close()
            logger.info("RedisCacheService disconnected")
        except Exception as e:
            logger.warning("Error closing Redis connection: %s", e)

    def _full_key(self, key: str | list[str] | dict[str, Any], namespace: str) -> str:
        base = f"{namespace}:{self.hash(key)}"
        return f"{self._key_prefix}:{base}" if self._key_prefix else base

    def _namespace_scan_pattern(self, namespace: str) -> str:
        prefix = f"{self._key_prefix}:" if self._key_prefix else ""
        return f"{prefix}{namespace}:*"

    def _all_scan_pattern(self) -> str:
        return f"{self._key_prefix}:*" if self._key_prefix else "*"

    def _parse_namespace(self, redis_key: str) -> str | None:
        """Extract namespace from a Redis key, accounting for optional key_prefix."""
        key = redis_key
        if self._key_prefix:
            prefix = f"{self._key_prefix}:"
            if not key.startswith(prefix):
                return None
            key = key[len(prefix) :]
        parts = key.split(":", 1)
        return parts[0] if len(parts) >= 2 else None

    def get(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> Any | None:
        try:
            full_key = self._full_key(key, namespace)
            raw = self._client.get(full_key)
            if raw is None:
                return None
            logger.debug("Cache hit: %s", full_key)
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw
        except Exception as e:
            logger.warning("Error retrieving from Redis cache: %s", e)
            return None

    def set(
        self,
        key: str | list[str] | dict[str, Any],
        value: Any,
        namespace: str = "default",
        ttl: int | None = None,
    ) -> None:
        try:
            full_key = self._full_key(key, namespace)
            payload = json.dumps(value)
            effective_ttl = ttl if ttl is not None else self._default_ttl
            if effective_ttl is not None:
                self._client.set(full_key, payload, ex=effective_ttl)
                logger.debug("Cache set: %s (ttl=%s)", full_key, effective_ttl)
            else:
                self._client.set(full_key, payload)
                logger.debug("Cache set: %s (no ttl)", full_key)
        except Exception as e:
            logger.warning("Error setting Redis cache: %s", e)

    def delete(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        try:
            full_key = self._full_key(key, namespace)
            deleted = self._client.delete(full_key)
            if deleted:
                logger.debug("Cache deleted: %s", full_key)
            return bool(deleted)
        except Exception as e:
            logger.warning("Error deleting from Redis cache: %s", e)
            return False

    def exists(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        try:
            full_key = self._full_key(key, namespace)
            return bool(self._client.exists(full_key))
        except Exception as e:
            logger.warning("Error checking Redis cache existence: %s", e)
            return False

    def clear(self, namespace: str | None = None) -> None:
        try:
            pattern = self._namespace_scan_pattern(namespace) if namespace else self._all_scan_pattern()
            cursor = 0
            deleted_count = 0
            while True:
                cursor, keys = self._client.scan(cursor=cursor, match=pattern, count=500)
                if keys:
                    self._client.delete(*keys)
                    deleted_count += len(keys)
                if cursor == 0:
                    break
            if namespace:
                logger.info("Cleared Redis cache namespace: %s (%d keys)", namespace, deleted_count)
            else:
                logger.info("Cleared entire Redis cache under prefix %r (%d keys)", self._key_prefix, deleted_count)
        except Exception as e:
            logger.warning("Error clearing Redis cache: %s", e)

    def get_stats(self) -> dict[str, Any]:
        try:
            info = self._client.info()
            return {
                "backend": "redis",
                "key_prefix": self._key_prefix,
                "redis_url": self._redis_url,
                "redis_version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "uptime_in_seconds": info.get("uptime_in_seconds", 0),
            }
        except Exception as e:
            logger.warning("Error getting Redis stats: %s", e)
            return {}

    def list_namespaces(self) -> list[str]:
        try:
            pattern = self._all_scan_pattern()
            namespaces: set[str] = set()
            cursor = 0
            while True:
                cursor, keys = self._client.scan(cursor=cursor, match=pattern, count=500)
                for k in keys:
                    ns = self._parse_namespace(k)
                    if ns:
                        namespaces.add(ns)
                if cursor == 0:
                    break
            result = sorted(namespaces)
            logger.debug("Redis cache namespaces: %s", result)
            return result
        except Exception as e:
            logger.warning("Error listing Redis cache namespaces: %s", e)
            return []

    def list_values(self, namespace: str = "default", limit: int = 100, offset: int = 0) -> Iterator[Any]:
        try:
            pattern = self._namespace_scan_pattern(namespace)
            keys: list[str] = []
            cursor = 0
            while True:
                cursor, batch = self._client.scan(cursor=cursor, match=pattern, count=500)
                keys.extend(batch)
                if cursor == 0:
                    break
            keys = keys[offset : offset + limit]
        except Exception as e:
            logger.warning("Error scanning Redis keys for namespace '%s': %s", namespace, e)
            return

        yielded = 0
        for key in keys:
            try:
                raw = self._client.get(key)
                if raw is not None:
                    try:
                        yield json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        yield raw
                    yielded += 1
            except Exception as e:
                logger.warning("Error reading Redis key '%s': %s", key, e)
        logger.debug("Iterated %d values from Redis namespace '%s'", yielded, namespace)
