"""Shared key/hash logic for cache service implementations."""

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class _CacheKeyMixin:
    """Mixin providing key normalization, hashing, and namespacing helpers.

    Used by cache backends to produce stable, consistent keys regardless of input
    type (string, list, dict). Mixed in alongside CacheService — the abstract
    ``hash`` method is satisfied via Python's MRO.
    """

    def hash(self, value: str | list[str] | dict[str, Any]) -> str:
        """Generate a SHA256 hash of a value.

        Handles different input types with consistent ordering:
        - Strings: Checks if JSON, converts to dict/list and sorts. Otherwise hashed directly.
        - Lists: Sorted before hashing to ensure consistent results
        - Dicts: Sorted by keys before hashing to ensure consistent results
        """
        try:
            normalized = self._normalize_for_hash(value)

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
                return self._normalize_for_hash(parsed)
            except (json.JSONDecodeError, ValueError):
                return value
        elif isinstance(value, list):
            filtered_list = [item for item in value if item is not None]
            return sorted(filtered_list)
        elif isinstance(value, dict):
            return dict(sorted(value.items()))
        else:
            return value
