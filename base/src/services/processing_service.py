"""Unified processing service that coordinates handlers and runtimes."""

import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from opentelemetry import trace

from ..models.events import CloudEvent
from ..registry import handler_registry, runtime_registry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ProcessingService:
    """
    Unified service for processing requests through handlers and runtimes.
    
    This service provides a consistent interface for all API endpoints
    (REST, Events, Dapr) to process requests using the registered handlers
    and agent runtimes.
    """

    def __init__(self):
        self._handler_registry = handler_registry
        self._runtime_registry = runtime_registry

    async def process_event(
        self, 
        event: CloudEvent, 
        context: Optional[Dict[str, Any]] = None,
        runtime_name: Optional[str] = None
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
            
            if hasattr(event, 'id'):
                span.set_attribute("event.id", event.id)

            logger.info(
                "Starting event processing for request %s", 
                request_id,
                extra={
                    "request_id": request_id,
                    "event_type": event.type,
                    "event_source": event.source,
                    "event_id": getattr(event, 'id', None),
                    "runtime_name": runtime_name
                }
            )

            try:
                # Step 1: Process through handler chain
                handler_result = await self._handler_registry.process_event(event, context)
                
                # Step 2: If handlers indicate agent processing is needed, use runtime
                should_use_agent = context.get("use_agent", False)
                agent_result = None
                
                if should_use_agent or handler_result is None:
                    logger.info(
                        "Processing with agent runtime for request %s", 
                        request_id,
                        extra={
                            "request_id": request_id,
                            "reason": "handler_requested" if should_use_agent else "no_handler_result",
                            "runtime_name": runtime_name
                        }
                    )
                    
                    # Prepare context for agent
                    agent_context = {
                        "event": event,
                        "handler_result": handler_result,
                        **context
                    }
                    
                    try:
                        agent_result = await self._runtime_registry.process_with_runtime(
                            runtime_name=runtime_name,
                            **agent_context
                        )
                        span.set_attribute("agent.processed", True)
                        
                    except Exception as e:
                        logger.error(
                            "Agent processing failed for request %s: %s", 
                            request_id, 
                            str(e),
                            extra={
                                "request_id": request_id,
                                "error": str(e),
                                "runtime_name": runtime_name
                            },
                            exc_info=True
                        )
                        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                        # Continue with handler result if agent fails
                        agent_result = None

                # Step 3: Prepare final result
                final_result = {
                    "request_id": request_id,
                    "status": "processed",
                    "handler_result": handler_result,
                    "agent_result": agent_result,
                    "processed_by": []
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
                        "has_agent_result": agent_result is not None
                    }
                )

                return final_result

            except Exception as e:
                logger.error(
                    "Event processing failed for request %s: %s", 
                    request_id, 
                    str(e),
                    extra={
                        "request_id": request_id,
                        "error": str(e)
                    },
                    exc_info=True
                )
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise

    async def process_rest_request(
        self,
        payload: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        runtime_name: Optional[str] = None
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
            data=payload
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
                runtime_health = await self._runtime_registry.health_check_all()
                
                # Check handlers (basic check - they're registered)
                handlers = self._handler_registry.get_handlers()
                handler_health = {
                    "status": "healthy" if handlers else "unhealthy",
                    "count": len(handlers),
                    "handlers": [{"name": h.name, "priority": h.priority} for h in handlers]
                }

                overall_healthy = (
                    handler_health["status"] == "healthy" and
                    any(r.get("status") == "healthy" for r in runtime_health.values())
                )

                result = {
                    "status": "healthy" if overall_healthy else "unhealthy",
                    "handlers": handler_health,
                    "runtimes": runtime_health
                }

                span.set_attribute("health.status", result["status"])
                span.set_attribute("handlers.count", len(handlers))
                span.set_attribute("runtimes.count", len(runtime_health))

                return result

            except Exception as e:
                logger.error("Health check failed: %s", str(e), exc_info=True)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                return {
                    "status": "unhealthy",
                    "error": str(e)
                }


# Global singleton instance
processing_service = ProcessingService()
