"""Redis-backed centralized cache service."""

import asyncio
import json
import re
import logging
from collections.abc import Iterator
from typing import Any

try:
    import redis
except ImportError as e:
    raise ImportError(
        "Redis backend requires 'avs-blueprint-agents[redis]'. Install with: pip install 'avs-blueprint-agents[redis]'"
    ) from e

from .redis_url_utils import _sanitize_redis_url
from .cache_key_mixin import _CacheKeyMixin
from .cache_service import CacheService

logger = logging.getLogger(__name__)

_DIGEST = re.compile(r"[0-9a-f]{64}")
"""The last segment of every key this class writes: the SHA-256 of the cache key (``CacheKeyMixin.hash``)."""


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
        component_name: str | None = None,
        socket_timeout: float | None = None,
    ) -> None:
        # component_name: registry name to use instead of the derived 'redis_cache_service'.
        # A process may hold several named caches (spec sec. 8), and two instances of this
        # class would otherwise collide on the one derived name. None keeps the existing key.
        super().__init__(name=component_name)
        self._redis_url = redis_url
        # Cached credential-free variant for logs, /readiness payloads, and stats.
        self._safe_redis_url = _sanitize_redis_url(redis_url)
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
        # socket_timeout bounds every call, the connect included (S7). Unset leaves redis-py's
        # default, which is 5 s since redis-py 8 -- the minimum this package requires, because
        # before it the default was no timeout, and a Redis that stopped answering held the call
        # (and, through the claim, a delivery) for ever.
        timeouts = {} if socket_timeout is None else {"socket_timeout": socket_timeout, "socket_connect_timeout": socket_timeout}
        self._client: Any = redis.Redis.from_url(
            effective_url,
            password=password,
            db=db,
            decode_responses=True,
            **timeouts,
        )

    async def ping(self) -> None:
        """Verify connectivity to Redis.

        Wraps the blocking redis-py sync ping in ``asyncio.to_thread`` so the
        event loop is not stalled while we wait. Raises on connection failure.
        """
        await asyncio.to_thread(self._client.ping)

    async def on_startup(self) -> None:
        # ``fallback_to_local`` is consulted only by ``CacheBackendFactory`` at
        # construction time; if we got here, the connection has already been
        # validated, so any failure now is a real problem and must propagate.
        try:
            await self.ping()
        except Exception as e:
            logger.error("RedisCacheService cannot connect to Redis at %s: %s", self._safe_redis_url, e)
            raise
        logger.info("RedisCacheService connected to %s (prefix=%r)", self._safe_redis_url, self._key_prefix)

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
        """The namespace of one of this store's own keys; ``None`` for any other key (see :meth:`_owns`)."""
        if not self._owns(redis_key):
            return None
        key = redis_key[len(self._key_prefix) + 1 :] if self._key_prefix else redis_key
        return key.split(":", 1)[0]

    def _owns(self, redis_key: str) -> bool:
        """Whether ``redis_key`` is this store's own: ``<prefix>:<namespace>:<sha256>``, nothing deeper (M6).

        Every other store of the process nests under this one's prefix -- a named cache, every
        agent's cache: ``<prefix>:<storage>:<namespace>:<sha256>``. A scan of ``<prefix>:*``
        therefore found them all, so clearing the root cache emptied every agent's, and listing
        it reported their storage names as namespaces. One segment too many marks a child's key,
        and a last segment that is not this class's digest marks a key someone else wrote -- with
        ``key_prefix = ""`` the scan covers the whole database.
        """
        key = redis_key
        if self._key_prefix:
            prefix = f"{self._key_prefix}:"
            if not key.startswith(prefix):
                return False
            key = key[len(prefix) :]
        parts = key.split(":")
        return len(parts) == 2 and _DIGEST.fullmatch(parts[1]) is not None

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

    def claim(self, key: str | list[str] | dict[str, Any], value: Any, namespace: str = "default", ttl: int | None = None) -> bool:
        """Store a value only if the key is absent, and report whether we stored it.

        ``SET key value NX EX ttl`` is a single server-side operation, so unlike the disk
        backend there is no stale-takeover branch: expiry is the server's job and an expired
        key simply is not there. Redis returns ``None`` rather than ``False`` when ``NX``
        refuses, hence the truthiness check.
        """
        try:
            full_key = self._full_key(key, namespace)
            effective_ttl = ttl if ttl is not None else self._default_ttl
            stored = self._client.set(full_key, json.dumps(value), nx=True, ex=effective_ttl)
            logger.debug("Cache claim on %s: %s", full_key, bool(stored))
            return bool(stored)
        except Exception as e:
            # Fails open, matching every other operation here: an unreachable cache must not
            # stop the caller from doing its work.
            logger.warning("Error claiming Redis cache key: %s", e)
            return True

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
            if not namespace and not self._key_prefix:
                logger.warning(
                    "Clearing a Redis cache with no key_prefix: its keys share the database with whatever else uses it. "
                    "Only keys of this store's own form are deleted; set 'cache.key_prefix' to give the process a space "
                    "of its own."
                )
            pattern = self._namespace_scan_pattern(namespace) if namespace else self._all_scan_pattern()
            cursor = 0
            deleted_count = 0
            while True:
                cursor, keys = self._client.scan(cursor=cursor, match=pattern, count=500)
                # Only this store's keys: the pattern also matches every store nested under this
                # one's prefix -- every named and every agent cache (M6).
                own = [key for key in keys if self._owns(key)]
                if own:
                    self._client.delete(*own)
                    deleted_count += len(own)
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
                "redis_url": self._safe_redis_url,
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
        # Apply offset/limit during the SCAN loop so we never materialise the
        # full key list — important for namespaces with millions of keys.
        pattern = self._namespace_scan_pattern(namespace)
        cursor = 0
        skipped = 0
        yielded = 0
        try:
            while True:
                cursor, batch = self._client.scan(cursor=cursor, match=pattern, count=500)
                for key in batch:
                    if not self._owns(key):
                        continue  # a nested store's key whose storage name equals this namespace
                    if skipped < offset:
                        skipped += 1
                        continue
                    if yielded >= limit:
                        logger.debug("Iterated %d values from Redis namespace '%s'", yielded, namespace)
                        return
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
                if cursor == 0:
                    break
        except Exception as e:
            logger.warning("Error scanning Redis keys for namespace '%s': %s", namespace, e)
            return
        logger.debug("Iterated %d values from Redis namespace '%s'", yielded, namespace)
