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
            runtimes = self._component_registry.get_all_runtimes()

            for name, runtime in runtimes.items():
                try:
                    health_result = await runtime.health_check()
                    results[name] = health_result
                    logger.info("Health check passed for runtime %s", name)
                except Exception as e:
                    logger.error("Health check failed for runtime %s: %s", name, str(e))
                    results[name] = {"status": "unhealthy", "error": str(e)}

            span.set_attribute("runtimes.count", len(runtimes))
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
            "handlers": [{"name": h.name, "priority": h.priority} for h in handlers],
        }
