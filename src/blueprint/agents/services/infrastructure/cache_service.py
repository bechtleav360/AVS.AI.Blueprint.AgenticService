"""Abstract cache service interface and DiskCache implementation."""

import logging
import threading
import time
from abc import abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from diskcache_rs import Cache

from ..service_base import ServiceBase
from .cache_key_mixin import _CacheKeyMixin

logger = logging.getLogger(__name__)


class CacheService(ServiceBase):
    """Abstract base class for cache services.

    Provides a unified interface for caching operations with support for:
    - TTL (time-to-live) for automatic expiration
    - Namespacing to avoid key collisions
    - Thread-safe operations
    - Persistence across restarts
    """

    @abstractmethod
    def get(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> Any | None:
        """Retrieve a value from cache.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            namespace: Namespace for the key (default: "default")

        Returns:
            Cached value or None if not found or expired
        """

    @abstractmethod
    def set(
        self,
        key: str | list[str] | dict[str, Any],
        value: Any,
        namespace: str = "default",
        ttl: int | None = None,
    ) -> None:
        """Store a value in cache.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            value: Value to cache
            namespace: Namespace for the key (default: "default")
            ttl: Time-to-live in seconds (None = no expiration)
        """

    @abstractmethod
    def delete(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        """Delete a value from cache.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            namespace: Namespace for the key (default: "default")

        Returns:
            True if key existed and was deleted, False otherwise
        """

    @abstractmethod
    def clear(self, namespace: str | None = None) -> None:
        """Clear cache entries.

        Args:
            namespace: Clear only this namespace (None = clear all)
        """

    @abstractmethod
    def close(self) -> None:
        """Close the cache and release any resources."""
        pass

    @abstractmethod
    def exists(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        """Check if a key exists in cache.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            namespace: Namespace for the key (default: "default")

        Returns:
            True if key exists and is not expired
        """

    @abstractmethod
    def claim(self, key: str | list[str] | dict[str, Any], value: Any, namespace: str = "default", ttl: int | None = None) -> bool:
        """Store a value only if the key is absent, and report whether this caller stored it.

        The set-if-absent primitive that ``exists`` followed by ``set`` cannot provide: two
        callers racing on the same key both pass an ``exists`` check before either ``set``
        lands, and both then believe they hold the key. Anything that uses the cache to
        decide *which one of several processes does a piece of work* needs this instead --
        the scheduler tick claim, and event deduplication.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            value: Value to store if the claim succeeds
            namespace: Namespace for the key (default: "default")
            ttl: Time-to-live in seconds (None = the cache-wide default)

        Returns:
            True if this caller stored the value, False if the key was already held.
        """

    @abstractmethod
    def hash(self, value: str | list[str] | dict[str, Any]) -> str:
        """Generate a hash of a value for use as a cache key.

        Handles different input types with consistent ordering:
        - Strings: Hashed directly
        - Lists: Sorted before hashing to ensure consistent results
        - Dicts: Sorted by keys before hashing to ensure consistent results

        Args:
            value: Value to hash (string, list of strings, or dict)

        Returns:
            SHA256 hash of the value
        """

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats (size, hit rate, etc.)
        """

    @abstractmethod
    def list_namespaces(self) -> list[str]:
        """List all namespaces currently present in the cache."""

    @abstractmethod
    def list_values(self, namespace: str = "default", limit: int = 100, offset: int = 0) -> Iterator[Any]:
        """Iterate over values stored in a namespace with pagination support.

        Args:
            namespace: Namespace to list values from (default: "default")
            limit: Maximum number of values to yield (default: 100)
            offset: Number of values to skip before yielding (default: 0)

        Yields:
            Cached values in the namespace one at a time. Order is not guaranteed.
        """


class DiskCacheService(_CacheKeyMixin, CacheService):
    """Persistent disk-based cache implementation using diskcache-rs.

    Features:
    - High-performance Rust-backed persistence to disk
    - TTL support with automatic expiration (manual cleanup)
    - Namespacing for key organization
    - Thread-safe operations
    - Optimized binary serialization

    Note: diskcache-rs is a simplified, high-performance alternative to python-diskcache.
    It focuses on core caching operations without advanced features like queues or transactions.

    Example:
        ```python
        cache = DiskCacheService(cache_dir=".cache/blueprint")
        cache.set("user:123", {"name": "John"}, ttl=3600)
        user = cache.get("user:123")
        ```
    """

    def __init__(
        self,
        cache_dir: str = ".cache/blueprint",
        size_limit: int = 1_000_000_000,  # 1GB (informational, not enforced by diskcache-rs)
        eviction_policy: str = "least-recently-used",
        enable_locking: bool = True,
        default_ttl: int | None = None,
        component_name: str | None = None,
    ):
        """Initialize DiskCacheService.

        Args:
            cache_dir: Directory for cache storage
            size_limit: Maximum cache size in bytes (informational, diskcache-rs doesn't enforce this)
            eviction_policy: Eviction policy (informational, diskcache-rs uses its own strategy)
            enable_locking: Enable locking for thread-safe operations (default: True)
            default_ttl: Cache-wide default TTL in seconds applied when ``set`` is
                called without an explicit ``ttl``. ``None`` means no expiration.
                Mirrors ``RedisCacheService`` so the choice of backend does not
                silently change TTL behaviour.
            component_name: Registry name to use instead of the derived ``disk_cache_service``.
                Needed because a process may hold several named caches (spec sec. 8) and two
                instances of this class would otherwise collide on the one derived name. The
                default keeps an existing single-cache application's registry key unchanged.
        """
        super().__init__(name=component_name)
        self.cache_dir = Path(cache_dir)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            # The common production failure, and the least self-explanatory: a container image
            # whose working directory is root-owned, or a pod with `readOnlyRootFilesystem: true`
            # and nothing mounted here. Both surface as an errno from deep inside a constructor,
            # so the cause and the fix are named here instead.
            raise RuntimeError(
                f"Cache directory '{self.cache_dir}' could not be created ({error.strerror}). A container cannot "
                "create it at runtime unless the path is writable by the user the process runs as: create it in the "
                "image and chown it, mount a volume there if the root filesystem is read-only, point "
                "'cache.cache_dir' somewhere writable, or use the redis cache backend, which needs no filesystem."
            ) from error

        self._size_limit = size_limit
        self._eviction_policy = eviction_policy
        self._enable_locking = enable_locking
        self._default_ttl = default_ttl
        self._lock = threading.RLock()  # Reentrant lock for thread-safe operations

        # Initialize diskcache-rs Cache with file locking for multi-process access
        # use_file_locking=True allows multiple processes to safely access the same cache
        self._cache = Cache(str(self.cache_dir), use_file_locking=True)

        logger.info(
            "Initialized DiskCacheService at %s (size_limit=%s, policy=%s, locking=%s, default_ttl=%s)",
            self.cache_dir,
            size_limit,
            eviction_policy,
            enable_locking,
            default_ttl,
        )

    async def on_startup(self) -> None:
        """No startup actions required."""

    async def on_shutdown(self) -> None:
        """Close the cache on shutdown."""
        self.close()

    @contextmanager
    def _acquire_lock(self) -> Any:
        """Context manager for thread-safe cache operations.

        Acquires lock on entry and releases on exit, ensuring proper cleanup
        even if exceptions occur. Allows clean usage with 'with' statement.

        Example:
            ```python
            with self._acquire_lock():
                # Perform cache operations
                value = self._cache.get(key)
            ```
        """
        if self._enable_locking:
            self._lock.acquire()
        try:
            yield
        finally:
            if self._enable_locking:
                try:
                    self._lock.release()
                except RuntimeError:
                    # Lock was not acquired
                    pass

    def wait_for_cache_availability(self, timeout: float | None = None) -> bool:
        """Wait until the cache is available (not locked by another thread).

        This method allows threads to wait for cache availability without
        performing an operation. Useful for coordinating access patterns.

        Args:
            timeout: Maximum time to wait in seconds (None = wait indefinitely)

        Returns:
            True if cache became available, False if timeout occurred
        """
        if not self._enable_locking:
            return True

        try:
            # Use -1 for blocking indefinitely if timeout is None
            timeout_val = -1 if timeout is None else timeout
            acquired = self._lock.acquire(timeout=timeout_val)
            if acquired:
                self._lock.release()
            return acquired
        except Exception as e:
            logger.warning("Error waiting for cache availability: %s", e)
            return False

    def get(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> Any | None:
        """Retrieve a value from cache."""
        try:
            with self._acquire_lock():
                namespaced_key = self._make_key(key, namespace)
                ttl_key = self._make_ttl_key(namespaced_key)

                # Check if TTL has expired (Option 1: persistent TTL)
                ttl_timestamp = self._cache.get(ttl_key)
                if ttl_timestamp is not None:
                    try:
                        expiration_time = float(ttl_timestamp)
                        if time.time() > expiration_time:
                            # TTL expired, delete both value and TTL metadata
                            self.delete(key, namespace)
                            return None
                    except (ValueError, TypeError):
                        logger.warning("Invalid TTL timestamp for key %s", namespaced_key)

                value = self._cache.get(namespaced_key)
                if value is not None:
                    logger.debug("Cache hit: %s", namespaced_key)
                return value
        except Exception as e:
            logger.warning("Error retrieving from cache: %s", e)
            return None

    def set(
        self,
        key: str | list[str] | dict[str, Any],
        value: Any,
        namespace: str = "default",
        ttl: int | None = None,
    ) -> None:
        """Store a value in cache."""
        try:
            with self._acquire_lock():
                namespaced_key = self._make_key(key, namespace)
                self._cache.set(namespaced_key, value)

                # Fall back to the cache-wide default_ttl when the caller doesn't
                # specify one, matching RedisCacheService's behaviour.
                effective_ttl = ttl if ttl is not None else self._default_ttl
                ttl_key = self._make_ttl_key(namespaced_key)
                if effective_ttl is not None:
                    expiration_time = time.time() + effective_ttl
                    self._cache.set(ttl_key, str(expiration_time))
                    logger.debug("Cache set: %s (ttl=%s)", namespaced_key, effective_ttl)
                else:
                    if ttl_key in self._cache:
                        del self._cache[ttl_key]
                    logger.debug("Cache set: %s (no ttl)", namespaced_key)
        except Exception as e:
            logger.warning("Error setting cache: %s", e)

    def claim(self, key: str | list[str] | dict[str, Any], value: Any, namespace: str = "default", ttl: int | None = None) -> bool:
        """Store a value only if the key is absent (atomic), and report whether we stored it.

        ``diskcache_rs.Cache.add`` is the set-if-absent operation, and it is atomic across
        processes sharing the directory because the cache is opened with file locking. Its
        own ``expire`` argument is **not** honoured by that backend -- an entry added with
        ``expire=1`` is still readable minutes later -- so the TTL is kept in the parallel
        metadata entry this service already maintains, exactly as ``set`` does.

        That split is what the stale branch below is for: ``add`` refuses a key whose logical
        TTL has passed, because physically it is still there. Taking such a key over is a
        read followed by a write, so two callers can both take over one expired claim. This
        is the one non-atomic path, and it is only reached by a caller that reuses a key
        beyond its TTL rather than deriving a fresh one.
        """
        try:
            with self._acquire_lock():
                namespaced_key = self._make_key(key, namespace)
                ttl_key = self._make_ttl_key(namespaced_key)
                effective_ttl = ttl if ttl is not None else self._default_ttl

                if not self._cache.add(namespaced_key, value):
                    if not self._logically_expired(ttl_key):
                        return False
                    self._cache.set(namespaced_key, value)

                if effective_ttl is not None:
                    self._cache.set(ttl_key, str(time.time() + effective_ttl))
                elif ttl_key in self._cache:
                    del self._cache[ttl_key]
                logger.debug("Cache claimed: %s (ttl=%s)", namespaced_key, effective_ttl)
                return True
        except Exception as e:
            # Fails open, as every other operation on this service does: a cache that cannot
            # be reached must not stop the caller from doing its work.
            logger.warning("Error claiming cache key: %s", e)
            return True

    def _logically_expired(self, ttl_key: str) -> bool:
        """Report whether the TTL metadata for an entry says it has expired.

        A missing or unparseable timestamp means "no expiry recorded", so the entry is
        treated as live -- the same reading ``exists`` and ``get`` take.
        """
        ttl_timestamp = self._cache.get(ttl_key)
        if ttl_timestamp is None:
            return False
        try:
            return time.time() > float(ttl_timestamp)
        except (ValueError, TypeError):
            return False

    def delete(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        """Delete a value from cache."""
        try:
            with self._acquire_lock():
                namespaced_key = self._make_key(key, namespace)
                if namespaced_key in self._cache:
                    del self._cache[namespaced_key]
                    # Also delete TTL metadata
                    ttl_key = self._make_ttl_key(namespaced_key)
                    if ttl_key in self._cache:
                        del self._cache[ttl_key]
                    logger.debug("Cache deleted: %s", namespaced_key)
                    return True
                return False
        except Exception as e:
            logger.warning("Error deleting from cache: %s", e)
            return False

    def clear(self, namespace: str | None = None) -> None:
        """Clear cache entries."""
        try:
            with self._acquire_lock():
                if namespace is None:
                    self._cache.clear()
                    logger.info("Cleared entire cache")
                else:
                    # Clear only keys in the specified namespace
                    prefix = f"{namespace}:"
                    keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
                    for key in keys_to_delete:
                        del self._cache[key]
                    logger.info("Cleared cache namespace: %s (%d keys)", namespace, len(keys_to_delete))
        except Exception as e:
            logger.warning("Error clearing cache: %s", e)

    def exists(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        """Check if a key exists in cache."""
        try:
            with self._acquire_lock():
                namespaced_key = self._make_key(key, namespace)
                ttl_key = self._make_ttl_key(namespaced_key)

                # Check if TTL has expired
                ttl_timestamp = self._cache.get(ttl_key)
                if ttl_timestamp is not None:
                    try:
                        expiration_time = float(ttl_timestamp)
                        if time.time() > expiration_time:
                            # TTL expired
                            return False
                    except (ValueError, TypeError):
                        pass

                return namespaced_key in self._cache
        except Exception as e:
            logger.warning("Error checking cache existence: %s", e)
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        try:
            with self._acquire_lock():
                # diskcache-rs doesn't provide volume() method, so we estimate from key count
                stats = {
                    "cache_dir": str(self.cache_dir),
                    "size": len(self._cache),
                    "size_limit": self._size_limit,
                    "eviction_policy": self._eviction_policy,
                }
                logger.debug("Cache stats: %s", stats)
                return stats
        except Exception as e:
            logger.warning("Error getting cache stats: %s", e)
            return {}

    def list_namespaces(self) -> list[str]:
        """List all namespaces currently present in the cache."""
        try:
            namespaces: set[str] = set()
            for key in self._cache.keys():
                if ":" in key:
                    namespace = key.split(":", 1)[0]
                    namespaces.add(namespace)
            result = sorted(namespaces)
            logger.debug("Cache namespaces: %s", result)
            return result
        except Exception as e:
            logger.warning("Error listing cache namespaces: %s", e)
            return []

    def list_values(self, namespace: str = "default", limit: int = 100, offset: int = 0) -> Iterator[Any]:
        """Iterate over values stored in a namespace."""
        try:
            prefix = f"{namespace}:"
            with self._acquire_lock():
                # Snapshot keys only — release the lock before fetching values
                keys = [k for k in self._cache.keys() if k.startswith(prefix) and not k.endswith(":__ttl__")][offset : offset + limit]
        except Exception as e:
            logger.warning("Error listing keys from cache namespace '%s': %s", namespace, e)
            return

        yielded = 0
        for key in keys:
            try:
                value = self._cache.get(key)
                if value is not None:
                    yield value
                    yielded += 1
            except Exception as e:
                logger.warning("Error reading cache key '%s': %s", key, e)
        logger.debug("Iterated %d values from namespace '%s'", yielded, namespace)

    def close(self) -> None:
        """Close the cache and flush to disk."""
        try:
            # diskcache-rs handles cleanup automatically
            logger.info("Closed DiskCacheService")
        except Exception as e:
            logger.warning("Error closing cache: %s", e)

    def __enter__(self) -> "DiskCacheService":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()
