"""Generic Dapr pub/sub endpoints for the agent service (framework-level)."""

import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, status
from opentelemetry import trace

from ..models import ProcessingResult, ProcessingStatus
from ..models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ..models.events import CloudEvent

if TYPE_CHECKING:  # pragma: no cover
    from ..registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class DaprApi:
    """Encapsulates all Dapr-related endpoints and logic."""

    def __init__(self, component_registry: "ComponentRegistry") -> None:
        self._component_registry = component_registry
        self._correlation_context = component_registry.get_correlation_context()
        self.router = APIRouter()
        self._register_routes()
        self.required_cloud_event_fields = {"specversion", "id", "source", "type"}

    def _register_routes(self) -> None:
        self.router.add_api_route("/dapr/subscribe", self.dapr_subscribe, methods=["GET"])
        self.router.add_api_route("/events/{topic}", self.handle_dapr_event, methods=["POST"])

    async def dapr_subscribe(self) -> list[dict[str, Any]]:
        """
        Dapr subscription discovery endpoint.

        Implementations can override this by adding their own router with the same
        path to provide real topics and routes.

        Note: this complements subscription resources defined in kubernetes
        (you can choose your approach)

        """

        # Framework default: no subscriptions declared.
        # Example structure:
        # return [
        #     {"pubsubname": "pubsub", "topic": "events.topic1", "route": "/events/topic1"}
        # ]
        return []

    async def handle_dapr_event(self, topic: str, cloud_event: CloudEvent[Any]) -> dict[str, Any]:
        """
        Generic Dapr event handler that processes events through the unified service.
        """

        with tracer.start_as_current_span("dapr.handle_event") as span:
            correlation_token = None
            span.set_attribute("dapr.topic", topic)
            try:
                logger.debug("Received Dapr event on topic %s", topic)

                original_event_type = cloud_event.type
                correlation_token = self._correlation_context.set(getattr(cloud_event, "id", None))
                cloud_event, was_unwrapped = self._unwrap_nested_cloud_event(cloud_event)
                if was_unwrapped:
                    self._correlation_context.reset(correlation_token)
                    correlation_token = self._correlation_context.set(getattr(cloud_event, "id", None))

                context = {
                    "dapr_topic": topic,
                    "dapr_original_event_type": original_event_type,
                    "dapr_inner_event_type": cloud_event.type,
                }

                span.set_attribute("dapr.original_event_type", original_event_type)
                if was_unwrapped:
                    logger.debug(
                        "Unwrapped nested CloudEvent of type %s from Dapr envelope",
                        cloud_event.type,
                    )
                    context["dapr_unwrapped"] = "true"
                    span.set_attribute("dapr.unwrapped", True)
                    span.set_attribute("dapr.event_type", cloud_event.type or "")

                # Process through the unified service
                processing_service = self._component_registry.get_processing_service()
                try:
                    processing_result = await processing_service.process_event(cloud_event, context)

                except RetryableHandlerError as exc:
                    logger.error(
                        "Retrying message for topic %s: %s",
                        topic,
                        str(exc),
                        exc_info=True,
                    )
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                    return {"status": "RETRY", "reason": exc.reason}

                except InvalidEventError as exc:
                    logger.error(
                        "Dropping message for topic %s: %s",
                        topic,
                        str(exc),
                        exc_info=True,
                    )
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                    return {"status": "DROP", "reason": exc.reason}

                except CriticalHandlerError as exc:
                    logger.error(
                        "Critical error for topic %s: %s",
                        topic,
                        str(exc),
                        exc_info=True,
                    )
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                    return {"status": "RETRY", "reason": exc.reason}

                except Exception as exc:  # pragma: no cover - integration behaviour
                    logger.error(
                        "Processing service failed for Dapr topic %s: %s",
                        topic,
                        str(exc),
                        exc_info=True,
                    )
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                    return {"status": "RETRY", "reason": "processing_failed"}

                if not isinstance(processing_result, ProcessingResult):
                    logger.error(
                        "Processing service returned unexpected result type %s",
                        type(processing_result),
                    )
                    return {"status": "RETRY", "reason": "invalid_processing_result"}

                # Return Dapr-compatible response based on result status
                result_status = processing_result.status

                if result_status is ProcessingStatus.PROCESSED:
                    return {"status": "SUCCESS"}

                logger.warning(
                    "Processing service returned non-success status %s for topic %s",
                    result_status.value,
                    topic,
                )
                failure_reason = processing_result.message or result_status.value or "unknown_status"
                return {"status": "RETRY", "reason": failure_reason}

            except Exception as e:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                logger.error("Dapr event handling failed: %s", str(e), exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Dapr event handling failed",
                ) from e
            finally:
                self._correlation_context.reset(correlation_token)

    def _unwrap_nested_cloud_event(self, event: CloudEvent[Any]) -> tuple[CloudEvent[Any], bool]:
        """Return inner CloudEvent when wrapped by Dapr envelope."""

        if event.type != "com.dapr.event.sent":
            return event, False

        nested_payload: Any = event.data

        if isinstance(nested_payload, str):
            try:
                nested_payload = json.loads(nested_payload)
            except json.JSONDecodeError:
                logger.debug("Nested payload is not valid JSON, skipping unwrap")
                return event, False

        if isinstance(nested_payload, dict) and self.required_cloud_event_fields.issubset(nested_payload.keys()):
            try:
                return CloudEvent(**nested_payload), True
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Failed to parse nested CloudEvent: %s", exc, exc_info=True)
                return event, False

        logger.debug("No nested CloudEvent detected inside Dapr envelope")
        return event, False
