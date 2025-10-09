"""Registry for agent runtimes following the memory guideline."""

import logging
from typing import Any, Dict, Optional
from opentelemetry import trace
from ..config import Config

from ..agent import BaseAgent
from .service_registry import ServiceRegistry


logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class RuntimeRegistry:

    def __init__(self, settings: Config, service_registry: ServiceRegistry):
        self._runtimes: Dict[str, BaseAgent] = {}
        self._default_runtime: Optional[str] = None
        self._settings = settings
        self._service_registry = service_registry

    def register_runtime(
        self, name: str, runtime: BaseAgent, is_default: bool = False
    ) -> None:
        """Register a new agent runtime."""
        logger.info("Registering runtime: %s", name)
        self._runtimes[name] = runtime

        if is_default or self._default_runtime is None:
            self._default_runtime = name
            logger.info("Set %s as default runtime", name)

        # wire
        runtime.link_service_registry(self._service_registry)

    def get_runtime(self, name: Optional[str] = None) -> Optional[BaseAgent]:
        """Get a specific runtime by name, or the default runtime if no name provided."""
        if name is None:
            name = self._default_runtime

        if name is None:
            logger.warning("No default runtime set and no name provided")
            return None

        runtime = self._runtimes.get(name)
        if runtime is None:
            logger.warning("Runtime %s not found", name)

        return runtime

    def get_all_runtimes(self) -> Dict[str, BaseAgent]:
        """Get all registered runtimes."""
        return self._runtimes.copy()

    def get_default_runtime_name(self) -> Optional[str]:
        """Get the name of the default runtime."""
        return self._default_runtime

    async def process_with_runtime(
        self, runtime_name: Optional[str] = None, context: Any = None, **kwargs
    ) -> Any:
        """
        Process a request using the specified runtime or default runtime.

        Args:
            runtime_name: Name of the runtime to use, or None for default
            context: Processing context to pass to the runtime
            **kwargs: Additional keyword arguments to pass to the runtime's process_request

        Returns:
            The result from the runtime's process_request method

        Raises:
            ValueError: If no runtime is available or runtime not found
        """
        with tracer.start_as_current_span(
            "runtime_registry.process_with_runtime"
        ) as span:
            runtime = self.get_runtime(runtime_name)

            if runtime is None:
                error_msg = f"No runtime available (requested: {runtime_name})"
                logger.error(error_msg)
                span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                raise ValueError(error_msg)

            actual_name = runtime_name or self._default_runtime
            span.set_attribute("runtime.name", actual_name)

            logger.info(
                "Processing request with runtime %s",
                actual_name,
                extra={
                    "runtime_name": actual_name,
                    "has_context": context is not None,
                    "additional_kwargs": list(kwargs.keys()) if kwargs else [],
                },
            )

            try:
                result = await runtime.process_request(context=context, **kwargs)
                logger.info(
                    "Runtime %s processed request successfully",
                    actual_name,
                    extra={
                        "runtime_name": actual_name,
                        "has_result": result is not None,
                    },
                )
                return result

            except Exception as e:
                logger.error(
                    "Runtime %s failed to process request: %s",
                    actual_name,
                    str(e),
                    extra={"runtime_name": actual_name, "error": str(e)},
                    exc_info=True,
                )
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise

    async def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """Perform health checks on all registered runtimes."""
        with tracer.start_as_current_span("runtime_registry.health_check_all") as span:
            results = {}

            for name, runtime in self._runtimes.items():
                try:
                    health_result = await runtime.health_check()
                    results[name] = health_result
                    logger.info("Health check passed for runtime %s", name)
                except Exception as e:
                    logger.error("Health check failed for runtime %s: %s", name, str(e))
                    results[name] = {"status": "unhealthy", "error": str(e)}

            span.set_attribute("runtimes.count", len(self._runtimes))
            span.set_attribute(
                "runtimes.healthy_count",
                sum(1 for r in results.values() if r.get("status") == "healthy"),
            )

            return results

    def clear_runtimes(self) -> None:
        """Clear all registered runtimes (useful for testing)."""
        logger.info("Clearing all registered runtimes")
        self._runtimes.clear()
        self._default_runtime = None
