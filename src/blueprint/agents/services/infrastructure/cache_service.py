"""Abstract cache service interface and DiskCache implementation."""

import hashlib
import json
import logging
import threading
import time
from abc import abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from diskcache_rs import Cache

from ..service_base import ServiceBase

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
    def exists(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        """Check if a key exists in cache.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            namespace: Namespace for the key (default: "default")

        Returns:
            True if key exists and is not expired
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


class DiskCacheService(CacheService):
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
    ):
        """Initialize DiskCacheService.

        Args:
            cache_dir: Directory for cache storage
            size_limit: Maximum cache size in bytes (informational, diskcache-rs doesn't enforce this)
            eviction_policy: Eviction policy (informational, diskcache-rs uses its own strategy)
            enable_locking: Enable locking for thread-safe operations (default: True)
        """
        super().__init__()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._size_limit = size_limit
        self._eviction_policy = eviction_policy
        self._enable_locking = enable_locking
        self._lock = threading.RLock()  # Reentrant lock for thread-safe operations

        # Initialize diskcache-rs Cache with file locking for multi-process access
        # use_file_locking=True allows multiple processes to safely access the same cache
        self._cache = Cache(str(self.cache_dir), use_file_locking=True)

        logger.info(
            "Initialized DiskCacheService at %s (size_limit=%s, policy=%s, locking=%s)",
            self.cache_dir,
            size_limit,
            eviction_policy,
            enable_locking,
        )

    async def on_startup(self) -> None:
        """No startup actions required."""

    async def on_shutdown(self) -> None:
        """Close the cache on shutdown."""
        self.close()

    def _make_key(self, key: str | list[str] | dict[str, Any], namespace: str) -> str:
        """Create a namespaced cache key by hashing the input.

        Args:
            key: Base key (string, list of strings, or dict)
            namespace: Namespace

        Returns:
            Namespaced key with hashed value
        """
        key_hash = self.hash(key)
        return f"{namespace}:{key_hash}"

    def _make_ttl_key(self, namespaced_key: str) -> str:
        """Create a TTL metadata key for a cache entry.

        Args:
            namespaced_key: The namespaced cache key

        Returns:
            TTL metadata key (special format to avoid collisions)
        """
        return f"{namespaced_key}:__ttl__"

    @contextmanager
    def _acquire_lock(self):
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

                # Store TTL metadata persistently (Option 1)
                if ttl is not None:
                    ttl_key = self._make_ttl_key(namespaced_key)
                    expiration_time = time.time() + ttl
                    self._cache.set(ttl_key, str(expiration_time))
                    logger.debug("Cache set: %s (ttl=%s)", namespaced_key, ttl)
                else:
                    # Remove TTL metadata if no TTL specified
                    ttl_key = self._make_ttl_key(namespaced_key)
                    if ttl_key in self._cache:
                        del self._cache[ttl_key]
                    logger.debug("Cache set: %s (no ttl)", namespaced_key)
        except Exception as e:
            logger.warning("Error setting cache: %s", e)

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

    def hash(self, value: str | list[str] | dict[str, Any]) -> str:
        """Generate a SHA256 hash of a value.

        Handles different input types with consistent ordering:
        - Strings: Checks if JSON, converts to dict/list and sorts. Otherwise hashed directly.
        - Lists: Sorted before hashing to ensure consistent results
        - Dicts: Sorted by keys before hashing to ensure consistent results
        """
        try:
            # Normalize input to dict or list for consistent hashing
            normalized = self._normalize_for_hash(value)

            # Serialize to JSON with consistent formatting
            if isinstance(normalized, dict):
                content = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
            elif isinstance(normalized, list):
                content = json.dumps(normalized, separators=(",", ":"))
            else:
                content = str(normalized)

            return hashlib.sha256(content.encode()).hexdigest()
        except Exception as e:
            logger.warning("Error generating hash: %s", e)
            return hashlib.sha256(str(value).encode()).hexdigest()

    def _normalize_for_hash(self, value: str | list[str] | dict[str, Any]) -> Any:
        """Normalize input value for consistent hashing.

        - None: Not supported (raises ValueError)
        - Strings: Attempts JSON parsing, returns parsed dict/list or original string
        - Lists: Removes ``None`` entries, sorts, and returns
        - Dicts: Sorted by keys before returning
        """
        if value is None:
            raise ValueError("Cache key value cannot be None")

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                # Recursively normalize parsed JSON
                return self._normalize_for_hash(parsed)
            except (json.JSONDecodeError, ValueError):
                # Not JSON: return as-is
                return value
        elif isinstance(value, list):
            # Remove null values before sorting for consistency
            filtered_list = [item for item in value if item is not None]
            return sorted(filtered_list)
        elif isinstance(value, dict):
            return dict(sorted(value.items()))
        else:
            return value

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

    def close(self) -> None:
        """Close the cache and flush to disk."""
        try:
            # diskcache-rs handles cleanup automatically
            logger.info("Closed DiskCacheService")
        except Exception as e:
            logger.warning("Error closing cache: %s", e)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
