"""Abstract cache service interface and DiskCache implementation."""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from diskcache_rs import Cache

logger = logging.getLogger(__name__)


class CacheService(ABC):
    """Abstract base class for cache services.

    Provides a unified interface for caching operations with support for:
    - TTL (time-to-live) for automatic expiration
    - Namespacing to avoid key collisions
    - Thread-safe operations
    - Persistence across restarts
    """

    @abstractmethod
    def get(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> Optional[Any]:
        """Retrieve a value from cache.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            namespace: Namespace for the key (default: "default")

        Returns:
            Cached value or None if not found or expired
        """
        pass

    @abstractmethod
    def set(
        self,
        key: str | list[str] | dict[str, Any],
        value: Any,
        namespace: str = "default",
        ttl: Optional[int] = None,
    ) -> None:
        """Store a value in cache.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            value: Value to cache
            namespace: Namespace for the key (default: "default")
            ttl: Time-to-live in seconds (None = no expiration)
        """
        pass

    @abstractmethod
    def delete(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        """Delete a value from cache.

        Args:
            key: Cache key (string, list of strings, or dict). Will be hashed internally.
            namespace: Namespace for the key (default: "default")

        Returns:
            True if key existed and was deleted, False otherwise
        """
        pass

    @abstractmethod
    def clear(self, namespace: Optional[str] = None) -> None:
        """Clear cache entries.

        Args:
            namespace: Clear only this namespace (None = clear all)
        """
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
        pass

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
        pass

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats (size, hit rate, etc.)
        """
        pass


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
    ):
        """Initialize DiskCacheService.

        Args:
            cache_dir: Directory for cache storage
            size_limit: Maximum cache size in bytes (informational, diskcache-rs doesn't enforce this)
            eviction_policy: Eviction policy (informational, diskcache-rs uses its own strategy)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._size_limit = size_limit
        self._eviction_policy = eviction_policy
        self._ttl_tracking: dict[str, float] = {}  # Track TTL expiration times

        # Initialize diskcache-rs Cache
        self._cache = Cache(str(self.cache_dir))

        logger.info(
            "Initialized DiskCacheService at %s (size_limit=%s, policy=%s)",
            self.cache_dir,
            size_limit,
            eviction_policy,
        )

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

    def get(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> Optional[Any]:
        """Retrieve a value from cache."""
        try:
            namespaced_key = self._make_key(key, namespace)

            # Check if TTL has expired
            if namespaced_key in self._ttl_tracking:
                if time.time() > self._ttl_tracking[namespaced_key]:
                    # TTL expired, delete it
                    self.delete(key, namespace)
                    return None

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
        ttl: Optional[int] = None,
    ) -> None:
        """Store a value in cache."""
        try:
            namespaced_key = self._make_key(key, namespace)
            self._cache.set(namespaced_key, value)

            # Track TTL expiration if provided
            if ttl is not None:
                self._ttl_tracking[namespaced_key] = time.time() + ttl
            else:
                self._ttl_tracking.pop(namespaced_key, None)

            logger.debug("Cache set: %s (ttl=%s)", namespaced_key, ttl)
        except Exception as e:
            logger.warning("Error setting cache: %s", e)

    def delete(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        """Delete a value from cache."""
        try:
            namespaced_key = self._make_key(key, namespace)
            if namespaced_key in self._cache:
                del self._cache[namespaced_key]
                self._ttl_tracking.pop(namespaced_key, None)
                logger.debug("Cache deleted: %s", namespaced_key)
                return True
            return False
        except Exception as e:
            logger.warning("Error deleting from cache: %s", e)
            return False

    def clear(self, namespace: Optional[str] = None) -> None:
        """Clear cache entries."""
        try:
            if namespace is None:
                self._cache.clear()
                self._ttl_tracking.clear()
                logger.info("Cleared entire cache")
            else:
                # Clear only keys in the specified namespace
                prefix = f"{namespace}:"
                keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
                for key in keys_to_delete:
                    del self._cache[key]
                    self._ttl_tracking.pop(key, None)
                logger.info("Cleared cache namespace: %s (%d keys)", namespace, len(keys_to_delete))
        except Exception as e:
            logger.warning("Error clearing cache: %s", e)

    def exists(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        """Check if a key exists in cache."""
        try:
            namespaced_key = self._make_key(key, namespace)

            # Check if TTL has expired
            if namespaced_key in self._ttl_tracking:
                if time.time() > self._ttl_tracking[namespaced_key]:
                    # TTL expired
                    return False

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

        - Strings: Attempts JSON parsing, returns parsed dict/list or original string
        - Lists: Sorts and returns
        - Dicts: Sorts by keys and returns
        """
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                # Recursively normalize parsed JSON
                return self._normalize_for_hash(parsed)
            except (json.JSONDecodeError, ValueError):
                # Not JSON: return as-is
                return value
        elif isinstance(value, list):
            return sorted(value)
        elif isinstance(value, dict):
            return dict(sorted(value.items()))
        else:
            return value

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        try:
            # diskcache-rs doesn't provide volume() method, so we estimate from key count
            stats = {
                "cache_dir": str(self.cache_dir),
                "size": len(self._cache),
                "ttl_tracked_keys": len(self._ttl_tracking),
                "size_limit": self._size_limit,
                "eviction_policy": self._eviction_policy,
            }
            logger.debug("Cache stats: %s", stats)
            return stats
        except Exception as e:
            logger.warning("Error getting cache stats: %s", e)
            return {}

    def close(self) -> None:
        """Close the cache and flush to disk."""
        try:
            # diskcache-rs handles cleanup automatically, but we clear tracking
            self._ttl_tracking.clear()
            logger.info("Closed DiskCacheService")
        except Exception as e:
            logger.warning("Error closing cache: %s", e)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
