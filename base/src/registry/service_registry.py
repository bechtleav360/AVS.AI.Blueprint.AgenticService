"""Service registry implementation for the base agent services."""

from typing import Dict, Optional, TYPE_CHECKING

from ..config import Config

if TYPE_CHECKING:  # pragma: no cover
    from ..registry.handler_registry import HandlerRegistry
    from ..registry.runtime_registry import RuntimeRegistry


class ServiceRegistry:
    """Factory-backed registry that owns shared service instances."""

    def __init__(self, settings: Config) -> None:
        self._settings = settings
        self._services: Dict[str, object] = {}
        self._handler_registry: Optional["HandlerRegistry"] = None
        self._runtime_registry: Optional["RuntimeRegistry"] = None

    def configure(
        self,
        handler_registry: "HandlerRegistry",
        runtime_registry: "RuntimeRegistry",
    ) -> None:
        self._handler_registry = handler_registry
        self._runtime_registry = runtime_registry

    def get_processing_service(self) -> "ProcessingService":
        """Return the shared `ProcessingService` instance, creating it lazily."""

        if self._handler_registry is None or self._runtime_registry is None:
            raise RuntimeError("ServiceRegistry dependencies not configured")

        if "processing_service" not in self._services:
            from ..services.processing_service import ProcessingService

            self._services["processing_service"] = ProcessingService(
                settings=self._settings,
                handler_registry=self._handler_registry,
                runtime_registry=self._runtime_registry,
            )
        return self._services["processing_service"]  # type: ignore[return-value]

    def clear(self) -> None:
        """Remove all registered services. Useful for tests."""

        self._services.clear()
