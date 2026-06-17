"""Base class for event-driven REST API components."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from contextlib import suppress
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

    Subclasses implement ``_connect_and_subscribe`` to perform the actual
    broker connection and topic subscription. ``on_startup`` launches this
    in a background task with configurable retry logic so the service enters
    a live state immediately even when the broker is temporarily unavailable.

    Config keys:
        event_client_max_retries (int, default -1): Number of retries after
            the first failure. ``-1`` retries indefinitely. ``0`` makes a
            single attempt and raises on failure.
        event_client_retry_delay (float, default 5.0): Seconds between retries.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._retry_task: asyncio.Task | None = None

    async def on_startup(self) -> None:
        self._retry_task = asyncio.ensure_future(self._start_with_retry())

    async def on_shutdown(self) -> None:
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._retry_task

    @abstractmethod
    async def _connect_and_subscribe(self) -> None:
        """Perform the broker connection and topic subscriptions.

        Called by the retry loop. Raise any exception to trigger a retry.
        Must be idempotent — it may be called more than once if earlier
        attempts fail.
        """
        raise NotImplementedError()

    async def _start_with_retry(self) -> None:
        max_retries: int = self.config.get("event_client_max_retries", -1)
        delay: float = float(self.config.get("event_client_retry_delay", 5.0))
        attempt = 0
        while True:
            try:
                await self._connect_and_subscribe()
                logger.info("%s connected successfully", type(self).__name__)
                return
            except Exception as e:
                attempt += 1
                if max_retries != -1 and attempt > max_retries:
                    logger.error(
                        "%s permanently failed to connect after %d attempt(s): %s",
                        type(self).__name__,
                        attempt,
                        e,
                        exc_info=e,
                    )
                    raise
                logger.warning(
                    "%s connect attempt %d failed, retrying in %.1fs: %s",
                    type(self).__name__,
                    attempt,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)

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
