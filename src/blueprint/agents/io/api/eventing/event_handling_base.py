"""Base class for event-driven REST API components."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from ....component.component import traced
from ....models import ProcessingResult, ProcessingStatus
from ....models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ....models.events import CloudEvent
from ..rest_api_base import RestApiBase
from .cloud_event_processor_mixin import CloudEventProcessorMixin

logger = logging.getLogger(__name__)


class EventHandlingBase(RestApiBase, CloudEventProcessorMixin, ABC):
    """Base class for event-driven REST API components.

    Combines REST API routing (RestApiBase) with CloudEvent processing
    (CloudEventProcessorMixin) and adds structured error-handling and logging
    around the dispatch pipeline.
    """

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

    async def _process_cloud_event(
        self,
        cloud_event: CloudEvent[Any],
        context: dict[str, Any],
    ) -> ProcessingResult:
        """Process a CloudEvent with error handling and logging.

        Wraps ``_dispatch_cloud_event`` with structured logging and exception
        handling for the four known error types. All exceptions are re-raised
        after logging.

        Args:
            cloud_event: The CloudEvent to process
            context: Additional context for processing

        Returns:
            The processing result

        Raises:
            Exception: Re-raises all exceptions after logging
        """
        try:
            logger.debug("Processing CloudEvent: %s", cloud_event.id)
            return await self._dispatch_cloud_event(cloud_event, context)
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
