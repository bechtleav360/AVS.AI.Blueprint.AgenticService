"""Health checker for service components."""

import logging
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

if TYPE_CHECKING:  # pragma: no cover
    from ...registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class _HealthChecker:
    """Performs health checks on service components."""

    def __init__(self, component_registry: "ComponentRegistry") -> None:
        self._component_registry: ComponentRegistry = component_registry

    async def check_runtimes(self) -> dict[str, dict[str, Any]]:
        """
        Perform health checks on all registered runtimes.

        Returns:
            Dictionary mapping runtime names to health results
        """
        with tracer.start_as_current_span("processing_service.runtime_health") as span:
            results = {}
            runtime_names = self._component_registry.list_agents()

            for name in runtime_names:
                runtime = self._component_registry.get_agent(name)
                try:
                    health_result = await runtime.health_check()
                    results[name] = health_result
                    # Only log successful health checks at debug level
                    logger.debug("Health check passed for runtime %s", name)
                except Exception as e:
                    # Log failures at error level
                    logger.error("Health check failed for runtime %s: %s", name, str(e))
                    results[name] = {"status": "unhealthy", "error": str(e)}

            span.set_attribute("runtimes.count", len(runtime_names))
            span.set_attribute(
                "runtimes.healthy_count",
                sum(1 for r in results.values() if r.get("status") == "healthy"),
            )

            return results

    def check_handlers(self) -> dict[str, Any]:
        """
        Check handler registration status.

        Returns:
            Dictionary with handler health information
        """
        handlers = self._component_registry.get_handlers()
        return {
            "status": "healthy" if handlers else "unhealthy",
            "count": len(handlers),
            "handlers": [{"name": h.get_name(), "priority": getattr(h, "_priority", 0)} for h in handlers],
        }
