"""Abstract base class for health check providers."""

from abc import ABC, abstractmethod

from ...models.api import ComponentHealth


class HealthCheckerBase(ABC):
    """Abstract base class for all health check providers.

    All health check implementations must inherit from this class and implement
    the health_check() method to provide component-specific health status.

    Example:
        ```python
        class CustomHealthChecker(HealthCheckerBase):
            async def health_check(self) -> ComponentHealth:
                # Perform health check logic
                return ComponentHealth(status="UP", message="Service OK")
        ```
    """

    @abstractmethod
    async def health_check(self) -> ComponentHealth:
        """Perform health check and return component status.

        Returns:
            ComponentHealth: Status object with status ("UP" or "DOWN") and message.

        Raises:
            Exception: Any exceptions are caught by the caller and logged.
        """
        pass
