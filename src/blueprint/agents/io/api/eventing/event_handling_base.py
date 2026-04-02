import json
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

from ....component.component import traced
from ....models import ProcessingResult, ProcessingStatus
from ....models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ....models.events import CloudEvent
from ....services.eventing.event_processing_service import EventProcessingService
from ..rest_api_base import RestApiBase

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EventHandlingBase(RestApiBase, ABC):
    """
    Base class for event handling components that provides common CloudEvent processing logic and
    makes the pub/sub methods publicly available.
    """

    def __init__(self, should_register: bool = True) -> None:
        super().__init__(should_register)
        self.required_cloud_event_fields = {"specversion", "id", "source", "type"}

    @traced("topic", "cloud_event")
    async def handle_event(self, topic: str, cloud_event: CloudEvent[Any]) -> dict[str, Any]:
        processing_result = await self._process_cloud_event(cloud_event, {"topic": topic})
        if processing_result.status == ProcessingStatus.PROCESSED:
            return {"status": "SUCCESS"}
        else:
            failure_reason = processing_result.message or processing_result.status.value or "unknown_status"
            return {"status": "RETRY", "reason": failure_reason}

    @abstractmethod
    async def publish(self, topic: str, event: CloudEvent[Any]) -> dict[str, Any]:
        """Abstract method for publishing events (output)"""

        raise NotImplementedError()

    @abstractmethod
    async def subscribe(self, topic: str, queue_group: str | None = None) -> dict[str, Any]:
        """Abstract method for subscribing for events (input)"""

        raise NotImplementedError()

    async def _process_cloud_event(self, cloud_event: CloudEvent[Any], context: dict[str, Any]) -> ProcessingResult:
        """Process a CloudEvent with common error handling and tracing.

        Args:
            cloud_event: The CloudEvent to process
            context: Additional context for processing

        Returns:
            The processing result

        Raises:
            Exception: Re-raises unhandled exceptions after logging
        """
        span = trace.get_current_span()
        correlation_token = None
        try:
            logger.debug("Processing CloudEvent: %s", cloud_event.id)

            original_event_type = cloud_event.type
            correlation_token = self.registry.correlation_context.set(getattr(cloud_event, "id", None))

            # Unwrap nested CloudEvent if present
            cloud_event, was_unwrapped = self._unwrap_nested_cloud_event(cloud_event)
            if was_unwrapped:
                self.registry.correlation_context.reset(correlation_token)
                correlation_token = self.registry.correlation_context.set(getattr(cloud_event, "id", None))

            # Update context with event details
            context.update(
                {
                    "original_event_type": original_event_type,
                    "inner_event_type": cloud_event.type,
                    "was_unwrapped": was_unwrapped,
                }
            )

            span.set_attribute("event.original_type", original_event_type)
            span.set_attribute("event.inner_type", cloud_event.type)
            if was_unwrapped:
                span.set_attribute("event.unwrapped", True)

            # Process through the unified service
            processing_service = self.registry.get_service(EventProcessingService)

            processing_result = await processing_service.process_event(cloud_event, context)

            if not isinstance(processing_result, ProcessingResult):
                logger.error(
                    "Processing service returned unexpected result type %s",
                    type(processing_result),
                )
                raise ValueError("Invalid processing result type")

            return processing_result

        except RetryableHandlerError as exc:
            logger.error("Retrying event: %s", str(exc), exc_info=True)
            raise

        except InvalidEventError as exc:
            logger.error("Dropping invalid event: %s", str(exc), exc_info=True)
            raise

        except CriticalHandlerError as exc:
            logger.error("Critical error processing event: %s", str(exc), exc_info=True)
            raise

        except Exception as exc:
            logger.error("Processing service failed: %s", str(exc), exc_info=True)
            raise

        finally:
            if correlation_token is not None:
                self.registry.correlation_context.reset(correlation_token)

    def _unwrap_nested_cloud_event(self, event: CloudEvent[Any]) -> tuple[CloudEvent[Any], bool]:
        """Unwrap nested CloudEvents if present.

        Handles CloudEvents wrapped in envelopes, such as Dapr's "com.dapr.event.sent" type.

        Args:
            event: The CloudEvent to potentially unwrap

        Returns:
            Tuple of (unwrapped_event, was_unwrapped)
        """
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
            except Exception as exc:
                logger.warning("Failed to parse nested CloudEvent: %s", exc, exc_info=True)
                return event, False

        logger.debug("No nested CloudEvent detected inside envelope")
        return event, False
