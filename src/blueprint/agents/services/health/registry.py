"""Registry for managing health check providers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..health_check_service import HealthCheckProvider

logger = logging.getLogger(__name__)


class HealthCheckerRegistry:
    """Registry for managing health check providers.

    Allows services to register custom health checkers in addition to defaults.
    """

    def __init__(self):
        """Initialize the registry."""
        self._checkers: dict[str, HealthCheckProvider] = {}

    def register(self, name: str, checker: HealthCheckProvider) -> None:
        """Register a health checker.

        Args:
            name: Unique identifier for the checker
            checker: Health checker instance implementing HealthCheckProvider

        Raises:
            ValueError: If checker with same name already registered
        """
        if name in self._checkers:
            raise ValueError(f"Health checker '{name}' already registered")

        logger.info("Registering health checker: %s", name)
        self._checkers[name] = checker

    def register_or_replace(self, name: str, checker: HealthCheckProvider) -> None:
        """Register a health checker, replacing if it exists.

        Args:
            name: Unique identifier for the checker
            checker: Health checker instance implementing HealthCheckProvider
        """
        if name in self._checkers:
            logger.info("Replacing health checker: %s", name)
        else:
            logger.info("Registering health checker: %s", name)

        self._checkers[name] = checker

    def get(self, name: str) -> HealthCheckProvider | None:
        """Get a registered health checker.

        Args:
            name: Unique identifier for the checker

        Returns:
            Health checker instance or None if not found
        """
        return self._checkers.get(name)

    def get_all(self) -> dict[str, HealthCheckProvider]:
        """Get all registered health checkers.

        Returns:
            Dictionary of all registered checkers
        """
        return dict(self._checkers)

    def has(self, name: str) -> bool:
        """Check if a health checker is registered.

        Args:
            name: Unique identifier for the checker

        Returns:
            True if checker is registered, False otherwise
        """
        return name in self._checkers

    def clear(self) -> None:
        """Clear all registered health checkers."""
        logger.info("Clearing all health checkers")
        self._checkers.clear()

    def list_names(self) -> list[str]:
        """List all registered checker names.

        Returns:
            List of checker names
        """
        return list(self._checkers.keys())
