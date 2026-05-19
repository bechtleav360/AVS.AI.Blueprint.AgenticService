"""Session key provider for managing session keys from various sources.

This module provides the SessionKeyProvider service that abstracts session key
retrieval from multiple sources (environment variables, configuration files,
external vaults). It includes caching with TTL and invalidation support.
"""

import logging
import os
from uuid import UUID

import httpx

from cachetools import TTLCache

from ..service_base import ServiceBase

logger = logging.getLogger(__name__)


class SessionKeyProvider(ServiceBase):
    """Provides session keys from configured source.

    Supports multiple sources:
    - Environment variables (Phase 1)
    - Configuration files
    - External vault (Phase 2 - HashiCorp Vault, Azure Key Vault)
    - Per-session keys passed via context (Phase 3)

    Includes caching with TTL and 403-based invalidation for performance.

    Configuration (settings.toml):
        [sessions_service]
        session_key_source = "env"  # Options: env, vault, context
        session_key_env_var = "SESSION_KEY"
        session_key_cache_ttl_seconds = 3600
    """

    def __init__(self) -> None:
        super().__init__()
        self._cache: TTLCache[str, str] | None = None
        self._source: str = "env"
        self._env_var: str = "SESSION_KEY"
        self._cache_ttl: int = 3600
        self._remote_url: str = ""
        self._api_key: str = ""

    async def on_startup(self) -> None:
        """Initialize the session key provider with configuration."""
        config = self.config.get("sessions_service")
        if not config:
            raise ValueError("sessions_service configuration not found")

        self._source = config.get("session_key_source", "env")
        self._env_var = config.get("session_key_env_var", "SESSION_KEY")
        self._cache_ttl = config.get("session_key_cache_ttl_seconds", 3600)
        self._remote_url = config.get("session_key_remote_url", "")
        self._api_key = config.get("api_key", "")

        # Initialize cache
        self._cache = TTLCache(maxsize=1000, ttl=self._cache_ttl)

        logger.info(
            "SessionKeyProvider initialized: source=%s, cache_ttl=%ds",
            self._source,
            self._cache_ttl,
        )

    async def on_shutdown(self) -> None:
        """Clean up resources."""
        if self._cache is not None:
            self._cache.clear()
        logger.info("SessionKeyProvider shut down")

    async def get_session_key(self, session_id: UUID | None = None) -> str:
        """Get session key for a specific session or default key.

        Args:
            session_id: Optional session ID for per-session keys

        Returns:
            Session key string

        Raises:
            ValueError: If session key cannot be retrieved
        """
        cache_key = str(session_id) if session_id else "default"

        # Check cache first
        if self._cache is not None and cache_key in self._cache:
            logger.debug("Session key cache hit: session_id=%s", session_id)
            return self._cache[cache_key]

        # Fetch from source
        if self._source == "env":
            session_key = self._get_from_env()
        elif self._source == "config":
            session_key = self._get_from_config()
        elif self._source == "vault":
            session_key = await self._get_from_vault(session_id)
        elif self._source == "remote":
            session_key = await self._get_from_remote(session_id)
        else:
            raise ValueError(f"Unknown session key source: {self._source}")

        # Cache the key
        if self._cache is not None:
            self._cache[cache_key] = session_key
            logger.debug("Session key cached: session_id=%s", session_id)

        return session_key

    def invalidate_cache(self, session_id: UUID | None = None) -> None:
        """Invalidate cached session key (e.g., after 403 error).

        Args:
            session_id: Optional session ID to invalidate, or None for default
        """
        if self._cache is None:
            return

        cache_key = str(session_id) if session_id else "default"
        if cache_key in self._cache:
            del self._cache[cache_key]
            logger.info("Session key cache invalidated: session_id=%s", session_id)

    def _get_from_env(self) -> str:
        """Get session key from environment variable.

        Returns:
            Session key from environment

        Raises:
            ValueError: If environment variable not set
        """
        session_key = os.getenv(self._env_var)
        if not session_key:
            raise ValueError(f"Environment variable {self._env_var} not set")

        logger.debug("Session key retrieved from environment variable: %s", self._env_var)
        return session_key

    def _get_from_config(self) -> str:
        """Get session key from configuration file.

        Returns:
            Session key from config

        Raises:
            ValueError: If session key not in config
        """
        config = self.config.get("sessions_service")
        session_key = config.get("session_key")

        if not session_key:
            raise ValueError("sessions_service.session_key not found in configuration")

        logger.debug("Session key retrieved from configuration")
        return session_key

    async def _get_from_vault(self, session_id: UUID | None = None) -> str:
        """Get session key from external vault (Phase 2 implementation).

        Args:
            session_id: Optional session ID for per-session keys

        Returns:
            Session key from vault

        Raises:
            NotImplementedError: Vault integration not yet implemented
        """
        # TODO: Implement vault integration in Phase 2
        # - HashiCorp Vault
        # - Azure Key Vault
        # - AWS Secrets Manager
        raise NotImplementedError("Vault integration not yet implemented. " "Use session_key_source='env' or 'config' for now.")

    async def _get_from_remote(self, session_id: UUID | None) -> str:
        """Fetch session key from a remote key vault endpoint.

        Args:
            session_id: Session ID to look up.

        Returns:
            Session key string.

        Raises:
            ValueError: If session_id is None or remote_url not configured.
            httpx.HTTPStatusError: If the remote returns a non-2xx response.
        """
        if not session_id:
            raise ValueError("session_id required for remote source")
        if not self._remote_url:
            raise ValueError("sessions_service.session_key_remote_url not configured")

        url = f"{self._remote_url}/{session_id}/key"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers={"X-Api-Key": self._api_key})
            response.raise_for_status()
            data = response.json()

        logger.debug("Session key retrieved from remote: session_id=%s", session_id)
        return data["session_key"]
