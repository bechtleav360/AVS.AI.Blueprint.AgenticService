"""Unified processing service that coordinates handlers and runtimes."""

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING
from uuid import uuid4

from opentelemetry import trace

from base.src.config import Config

from ..models.events import CloudEvent

if TYPE_CHECKING:  # pragma: no cover
    from ..registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ProcessingService:
    """
    Unified service for processing requests through handlers and runtimes.

    This service provides a consistent interface for all API endpoints
    (REST, Events, Dapr) to process requests using the registered handlers
    and agent runtimes.
    """

    def __init__(
        self,
        settings: Config,
        component_registry: "ComponentRegistry",
    ) -> None:
        self._settings = settings
        self._component_registry = component_registry

    async def process_event(
        self,
        event: CloudEvent,
        context: Optional[Dict[str, Any]] = None,
        runtime_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a CloudEvent through the handler chain and optionally through an agent runtime.

        Args:
            event: The CloudEvent to process
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default

        Returns:
            A dictionary containing the processing result
        """
        if context is None:
            context = {}

        request_id = str(uuid4())
        context["request_id"] = request_id

        with tracer.start_as_current_span("processing_service.process_event") as span:
            span.set_attribute("request_id", request_id)
            span.set_attribute("event.type", event.type)
            span.set_attribute("event.source", event.source)

            if hasattr(event, "id"):
                span.set_attribute("event.id", event.id)

            logger.info(
                "Starting event processing for request %s",
                request_id,
                extra={
                    "request_id": request_id,
                    "event_type": event.type,
                    "event_source": event.source,
                    "event_id": getattr(event, "id", None),
                    "runtime_name": runtime_name,
                },
            )

            try:
                # Step 1: Process through handler chain and get runtime name
                handler_result, requested_runtime = await self._process_through_handlers(event, context)

                # Step 2: Use agent if handler returned a runtime name
                agent_result = None

                if requested_runtime is not None:
                    # Empty string means use default runtime
                    actual_runtime = requested_runtime if requested_runtime else runtime_name
                    
                    logger.info(
                        "Processing with agent runtime for request %s",
                        request_id,
                        extra={
                            "request_id": request_id,
                            "runtime_name": actual_runtime,
                            "handler_specified": bool(requested_runtime),
                        },
                    )

                    # Prepare context for agent
                    agent_context = {
                        "event": event,
                        "handler_result": handler_result,
                        **context,
                    }

                    try:
                        agent_result = await self._process_with_runtime(
                            runtime_name=actual_runtime, **agent_context
                        )
                        span.set_attribute("agent.processed", True)
                        span.set_attribute("agent.name", actual_runtime)

                    except Exception as e:
                        logger.error(
                            "Agent processing failed for request %s: %s",
                            request_id,
                            str(e),
                            extra={
                                "request_id": request_id,
                                "error": str(e),
                                "runtime_name": runtime_name,
                            },
                            exc_info=True,
                        )
                        span.record_exception(e)
                        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        raise

                # Step 3: Prepare final result
                final_result = {
                    "request_id": request_id,
                    "status": "processed",
                    "handler_result": handler_result,
                    "agent_result": agent_result,
                    "processed_by": [],
                }

                if handler_result is not None:
                    final_result["processed_by"].append("handlers")
                if agent_result is not None:
                    final_result["processed_by"].append("agent")

                if not final_result["processed_by"]:
                    final_result["status"] = "no_processor_found"
                    final_result["message"] = "No handler or agent processed this event"

                logger.info(
                    "Event processing completed for request %s",
                    request_id,
                    extra={
                        "request_id": request_id,
                        "status": final_result["status"],
                        "processed_by": final_result["processed_by"],
                        "has_handler_result": handler_result is not None,
                        "has_agent_result": agent_result is not None,
                    },
                )

                return final_result

            except Exception as e:
                logger.error(
                    "Event processing failed for request %s: %s",
                    request_id,
                    str(e),
                    extra={"request_id": request_id, "error": str(e)},
                    exc_info=True,
                )
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise

    async def process_rest_request(
        self,
        payload: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        runtime_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a REST request by converting it to a CloudEvent and processing.

        Args:
            payload: The REST request payload
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default

        Returns:
            A dictionary containing the processing result
        """
        # Convert REST payload to CloudEvent format
        event = CloudEvent(
            specversion="1.0",
            id=str(uuid4()),
            source="/api/rest",
            type="rest.request",
            data=payload,
        )

        return await self.process_event(event, context, runtime_name)

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a comprehensive health check of the processing service.

        Returns:
            Health check results for handlers and runtimes
        """
        with tracer.start_as_current_span("processing_service.health_check") as span:
            try:
                # Check runtimes
                runtime_health = await self._health_check_runtimes()

                # Check handlers (basic check - they're registered)
                handlers = self._component_registry.get_handlers()
                handler_health = {
                    "status": "healthy" if handlers else "unhealthy",
                    "count": len(handlers),
                    "handlers": [
                        {"name": h.name, "priority": h.priority} for h in handlers
                    ],
                }

                overall_healthy = handler_health["status"] == "healthy" and any(
                    r.get("status") == "healthy" for r in runtime_health.values()
                )

                result = {
                    "status": "healthy" if overall_healthy else "unhealthy",
                    "handlers": handler_health,
                    "runtimes": runtime_health,
                }

                span.set_attribute("health.status", result["status"])
                span.set_attribute("handlers.count", len(handlers))
                span.set_attribute("runtimes.count", len(runtime_health))

                return result

            except Exception as e:
                logger.error("Health check failed: %s", str(e), exc_info=True)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                return {"status": "unhealthy", "error": str(e)}

    # ========================================================================
    # Private Helper Methods (Business Logic)
    # ========================================================================

    async def _process_through_handlers(
        self, event: CloudEvent, context: Dict[str, Any]
    ) -> tuple[Optional[Any], Optional[str]]:
        """
        Process an event through all registered handlers.

        Returns:
            Tuple of (handler_result, runtime_name) where:
            - handler_result: Result from the first handler that processes the event, or None
            - runtime_name: Runtime name from handler's get_runtime_name(), or None to skip agent
        """
        handlers = self._component_registry.get_handlers()
        runtime_name = None

        with tracer.start_as_current_span("processing_service.handler_chain") as span:
            span.set_attribute("event.type", event.type)
            span.set_attribute("handlers.count", len(handlers))

            logger.info(
                "Processing event through %d handlers",
                len(handlers),
                extra={
                    "event_type": event.type,
                    "event_id": getattr(event, "id", None),
                    "handlers_count": len(handlers),
                },
            )

            for handler in handlers:
                try:
                    if await handler.can_handle(event, context):
                        logger.info(
                            "Handler %s can handle event %s",
                            handler.name,
                            event.type,
                            extra={
                                "handler_name": handler.name,
                                "event_type": event.type,
                                "event_id": getattr(event, "id", None),
                            },
                        )

                        result = await handler.handle(event, context)
                        
                        # Get runtime name from handler
                        runtime_name = handler.get_runtime_name(event, context)
                        
                        logger.debug(
                            "Handler %s specified runtime: %s",
                            handler.name,
                            runtime_name if runtime_name else "None (no agent)"
                        )

                        if result is not None:
                            logger.info(
                                "Handler %s processed event %s and returned result",
                                handler.name,
                                event.type,
                                extra={
                                    "handler_name": handler.name,
                                    "event_type": event.type,
                                    "event_id": getattr(event, "id", None),
                                    "has_result": True,
                                    "runtime_name": runtime_name,
                                },
                            )
                            span.set_attribute("handler.processed_by", handler.name)
                            if runtime_name is not None:
                                span.set_attribute("handler.runtime_name", runtime_name)
                            return result, runtime_name
                        else:
                            logger.info(
                                "Handler %s processed event %s but passed to next handler",
                                handler.name,
                                event.type,
                                extra={
                                    "handler_name": handler.name,
                                    "event_type": event.type,
                                    "event_id": getattr(event, "id", None),
                                    "has_result": False,
                                    "runtime_name": runtime_name,
                                },
                            )
                            # Continue to next handler but keep the runtime_name

                except Exception as e:
                    logger.error(
                        "Handler %s failed to process event %s: %s",
                        handler.name,
                        event.type,
                        str(e),
                        extra={
                            "handler_name": handler.name,
                            "event_type": event.type,
                            "event_id": getattr(event, "id", None),
                            "error": str(e),
                        },
                        exc_info=True,
                    )
                    span.record_exception(e)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                    raise

            logger.warning(
                "No handler processed event %s",
                event.type,
                extra={
                    "event_type": event.type,
                    "event_id": getattr(event, "id", None),
                    "handlers_count": len(handlers),
                },
            )
            return None, runtime_name

    async def _process_with_runtime(
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
            "processing_service.runtime_execution"
        ) as span:
            runtime = self._component_registry.get_runtime(runtime_name)

            if runtime is None:
                error_msg = "No runtime available (requested: %s)" % runtime_name
                logger.error(error_msg)
                span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                raise ValueError(error_msg)

            actual_name = runtime_name or self._component_registry.get_default_runtime_name()
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

    async def _health_check_runtimes(self) -> Dict[str, Dict[str, Any]]:
        """Perform health checks on all registered runtimes."""
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
