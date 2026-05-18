"""Sessions service event bus implementation (framework-level).

This module provides the SessionsBus that connects to the sessions service via SSE,
receives job notifications, converts them to CloudEvents, and delegates to EventHandlers
for processing via the CloudEventProcessorMixin dispatch pipeline.
"""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import httpx
from httpx_sse import aconnect_sse
from opentelemetry import trace

from ....component.component import Component
from ....models.errors import InvalidEventError, RetryableHandlerError
from ....models.events import GenericCloudEvent
from ....services.eventing.event_processing_service import EventProcessingService
from ....services.sessions import SessionKeyProvider, SessionsApiClient
from .cloud_event_processor_mixin import CloudEventProcessorMixin

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class SessionsBus(Component, CloudEventProcessorMixin):
    """Implements job handling using sessions service SSE as the event source.

    Connects to an external SSE stream, receives job notifications, converts
    them to CloudEvents, and delegates to the processing pipeline via
    ``_dispatch_cloud_event``.

    Lifecycle is managed via ``on_startup`` / ``on_shutdown`` and integrates
    with the standard Component registry.
    """

    def __init__(self) -> None:
        """Initialize the sessions event bus."""
        super().__init__()

        # SSE connection
        self._sse_task: asyncio.Task[None] | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()

        # Services (resolved on startup)
        self._api_client: SessionsApiClient | None = None
        self._key_provider: SessionKeyProvider | None = None

        # Concurrency control
        self._semaphore: asyncio.Semaphore | None = None

        # Configuration (loaded on startup)
        self._base_url: str | None = None
        self._agent_id: str | None = None
        self._agent_type: str | None = None
        self._capabilities: list[str] = []
        self._api_key: str | None = None
        self._max_concurrent_jobs: int = 10
        self._job_timeout: int = 300
        self._reconnect_delay: int = 5
        self._max_reconnect_attempts: int = -1

    async def on_startup(self) -> None:
        """Connect to the sessions service SSE endpoint and start consuming events."""
        if self._sse_task is not None and not self._sse_task.done():
            logger.warning("SessionsBus already connected")
            return

        sessions_config = self.config.get("sessions_service")
        if not sessions_config:
            raise ValueError("sessions_service configuration not found")

        self._base_url = sessions_config.get("base_url")
        self._agent_id = sessions_config.get("agent_id")
        self._agent_type = sessions_config.get("agent_type")
        self._capabilities = sessions_config.get("capabilities", [])
        self._api_key = sessions_config.get("api_key")
        self._max_concurrent_jobs = sessions_config.get("max_concurrent_jobs", 10)
        self._job_timeout = sessions_config.get("job_timeout_seconds", 300)
        self._reconnect_delay = sessions_config.get("sse_reconnect_delay_seconds", 5)
        self._max_reconnect_attempts = sessions_config.get("sse_max_reconnect_attempts", -1)

        if not self._base_url:
            raise ValueError("sessions_service.base_url is required")
        if not self._agent_id:
            raise ValueError("sessions_service.agent_id is required")
        if not self._api_key:
            raise ValueError("sessions_service.api_key is required")

        self._api_client = self.registry.get_service(SessionsApiClient)
        self._key_provider = self.registry.get_service(SessionKeyProvider)

        self._semaphore = asyncio.Semaphore(self._max_concurrent_jobs)
        self._shutdown_event.clear()
        self._sse_task = asyncio.create_task(self._consume_sse_stream())

        logger.info(
            "SessionsBus connected: agent_id=%s, capabilities=%s, max_concurrent=%d",
            self._agent_id,
            self._capabilities,
            self._max_concurrent_jobs,
        )

    async def on_shutdown(self) -> None:
        """Close the SSE connection and clean up resources."""
        logger.info("SessionsBus closing...")

        self._shutdown_event.set()

        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                logger.info("SSE task cancelled")

        logger.info("SessionsBus closed")

    async def _consume_sse_stream(self) -> None:
        """Connect to the SSE endpoint and process events with reconnection logic."""
        attempt = 0

        while not self._shutdown_event.is_set():
            try:
                attempt += 1
                if self._max_reconnect_attempts > 0 and attempt > self._max_reconnect_attempts:
                    logger.error("Max SSE reconnection attempts reached (%d)", self._max_reconnect_attempts)
                    break

                logger.info("Connecting to SSE stream (attempt %d)...", attempt)
                await self._connect_and_consume()

            except asyncio.CancelledError:
                logger.info("SSE stream consumption cancelled")
                break

            except Exception as e:
                logger.error("SSE connection error: %s", e, exc_info=True)

                if self._shutdown_event.is_set():
                    break

                logger.info("Reconnecting in %d seconds...", self._reconnect_delay)
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self._reconnect_delay,
                    )
                except TimeoutError:
                    pass

    async def _connect_and_consume(self) -> None:
        """Establish SSE connection and consume events."""
        url = f"{self._base_url}/jobs/stream/sse"
        params: dict[str, Any] = {"agent_id": self._agent_id}

        if self._agent_type:
            params["agent_type"] = self._agent_type

        if self._capabilities:
            params["capabilities"] = ",".join(self._capabilities)

        headers = {"X-Api-Key": self._api_key}

        async with httpx.AsyncClient(timeout=None) as client:
            async with aconnect_sse(client, "GET", url, params=params, headers=headers) as event_source:
                logger.info("SSE connection established")

                async for sse in event_source.aiter_sse():
                    if self._shutdown_event.is_set():
                        break

                    try:
                        if sse.event == "connected":
                            logger.info("SSE connected event received")

                        elif sse.event == "job_created":
                            job_data = json.loads(sse.data)
                            logger.info(
                                "Job notification received: job_id=%s, job_type=%s",
                                job_data.get("job_id"),
                                job_data.get("job_type"),
                            )
                            asyncio.create_task(self._handle_job_notification(job_data))

                        elif sse.event == "heartbeat":
                            logger.debug("SSE heartbeat received")

                        else:
                            logger.warning("Unknown SSE event type: %s", sse.event)

                    except Exception as e:
                        logger.error("Error processing SSE event: %s", e, exc_info=True)

    async def _handle_job_notification(self, job_data: dict[str, Any]) -> None:
        """Handle job notification with concurrency control.

        Args:
            job_data: Job notification data from SSE
        """
        if self._semaphore is None:
            raise RuntimeError("Semaphore not initialized")
        async with self._semaphore:
            try:
                await asyncio.wait_for(
                    self._process_job_notification(job_data),
                    timeout=self._job_timeout,
                )
            except TimeoutError:
                logger.error(
                    "Job processing timeout after %ds: job_id=%s",
                    self._job_timeout,
                    job_data.get("job_id"),
                )

    async def _process_job_notification(self, job_data: dict[str, Any]) -> None:
        """Process a job notification by converting to CloudEvent and delegating to handlers.

        Uses the CloudEventProcessorMixin dispatch pipeline for the primary call.
        Applies sessions-specific error handling: permanent failures cancel the job,
        transient failures leave it pending, 403 auth errors invalidate the session key
        and retry once.

        Args:
            job_data: Job notification data from SSE
        """
        session_id = UUID(job_data["session_id"])
        job_id = UUID(job_data["job_id"])
        job_type = job_data["job_type"]

        with tracer.start_as_current_span("sessions_bus.process_job") as span:
            span.set_attribute("job_id", str(job_id))
            span.set_attribute("session_id", str(session_id))
            span.set_attribute("job_type", job_type)

            try:
                # Get session key from provider
                if self._key_provider is None:
                    raise RuntimeError("SessionKeyProvider not initialized")
                session_key = await self._key_provider.get_session_key(session_id)

                event = self._convert_to_cloud_event(job_data)

                context = {
                    "session_id": str(session_id),
                    "job_id": str(job_id),
                    "session_key": session_key,
                    "sessions_api_client": self._api_client,
                    "sessions_key_provider": self._key_provider,
                }

                result = await self._dispatch_cloud_event(event, context)

                if result.status.value == "no_handler_found":
                    logger.warning(
                        "No handler found for job type %s (job_id=%s)",
                        job_type,
                        job_id,
                    )

            except InvalidEventError as e:
                logger.error("Invalid job %s: %s. Cancelling.", job_id, e)
                try:
                    if self._key_provider is None:
                        raise RuntimeError("SessionKeyProvider not initialized")
                    if self._api_client is None:
                        raise RuntimeError("SessionsApiClient not initialized")
                    session_key = await self._key_provider.get_session_key(session_id)
                    await self._api_client.cancel_job(
                        session_id=session_id,
                        job_id=job_id,
                        session_key=session_key,
                        reason=f"Invalid event: {str(e)}",
                    )
                except Exception as cancel_error:
                    logger.error("Failed to cancel job %s: %s", job_id, cancel_error)

            except RetryableHandlerError as e:
                logger.warning(
                    "Retryable error for job %s: %s. Job remains pending.",
                    job_id,
                    e,
                )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    logger.error("Invalid session key for session %s", session_id)
                    if self._key_provider is None:
                        raise RuntimeError("SessionKeyProvider not initialized") from None
                    self._key_provider.invalidate_cache(session_id)

                    try:
                        session_key = await self._key_provider.get_session_key(session_id)
                        context["session_key"] = session_key
                        processing_service = self.registry.get_service(EventProcessingService)
                        await processing_service.process_event(event, context)
                    except Exception as retry_error:
                        logger.error("Retry failed for job %s: %s", job_id, retry_error)
                        raise InvalidEventError(
                            status="invalid_session_key",
                            reason=f"Session key invalid: {str(e)}",
                        ) from e
                else:
                    raise

            except Exception as e:
                logger.exception("Unexpected error processing job %s: %s", job_id, e)

    def _convert_to_cloud_event(self, job_data: dict[str, Any]) -> GenericCloudEvent:
        """Convert job notification to CloudEvent format.

        Args:
            job_data: Job notification data from SSE

        Returns:
            GenericCloudEvent with job data
        """
        job_type = job_data["job_type"]
        event_type = f"sessions.job.created.{job_type}"

        return GenericCloudEvent(
            specversion="1.0",
            id=job_data["job_id"],
            type=event_type,
            source="/sessions-service",
            subject=job_data["session_id"],
            time=job_data.get("created_at"),
            datacontenttype="application/json",
            data=job_data,
        )
