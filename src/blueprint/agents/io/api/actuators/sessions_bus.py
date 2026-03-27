"""Sessions service event bus implementation for the agent service (framework-level).

This module provides the SessionsBus that connects to the sessions service via SSE,
receives job notifications, converts them to CloudEvents, and delegates to EventHandlers
for processing.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from httpx_sse import aconnect_sse
from opentelemetry import trace

from ....config import Config
from ....models.errors import InvalidEventError, RetryableHandlerError
from ....models.events import GenericCloudEvent
from ....services.eventing.event_processing_service import EventProcessingService
from ....services.sessions import SessionKeyProvider, SessionsApiClient

if TYPE_CHECKING:
    from ....component.registry import Registry

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class SessionsBus:
    """Implements job handling using sessions service SSE as the event source.

    Similar to NatsEventBus, this class:
    - Connects to an external event source (sessions service SSE)
    - Receives events (job notifications)
    - Converts to CloudEvents
    - Delegates to ProcessingService/EventHandlers for processing
    """

    def __init__(self, component_registry: "Registry", config: Config) -> None:
        """Initialize the sessions event bus.

        Args:
            component_registry: The component registry to get processing service from
            config: Configuration object containing sessions service settings
        """
        self._component_registry = component_registry
        self._correlation_context = component_registry.correlation_context
        self._config = config

        # SSE connection
        self._sse_task: asyncio.Task[None] | None = None
        self._shutdown_event: asyncio.Event = asyncio.Event()

        # Services (will be resolved on connect)
        self._api_client: SessionsApiClient | None = None
        self._key_provider: SessionKeyProvider | None = None

        # Concurrency control
        self._semaphore: asyncio.Semaphore | None = None

        # Configuration
        self._base_url: str | None = None
        self._agent_id: str | None = None
        self._agent_type: str | None = None
        self._capabilities: list[str] = []
        self._api_key: str | None = None
        self._max_concurrent_jobs: int = 10
        self._job_timeout: int = 300
        self._reconnect_delay: int = 5
        self._max_reconnect_attempts: int = -1

    async def connect(self) -> None:
        """Connect to sessions service SSE endpoint and start consuming events."""
        if self._sse_task is not None and not self._sse_task.done():
            logger.warning("SessionsBus already connected")
            return

        # Load configuration
        sessions_config = self._config.get("sessions_service")
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

        # Get services from registry
        self._api_client = self._component_registry.get_service(SessionsApiClient)  # type: ignore[assignment]
        self._key_provider = self._component_registry.get_service(SessionKeyProvider)  # type: ignore[assignment]

        # Initialize concurrency control
        self._semaphore = asyncio.Semaphore(self._max_concurrent_jobs)

        # Reset shutdown event
        self._shutdown_event.clear()

        # Start SSE connection task
        self._sse_task = asyncio.create_task(self._consume_sse_stream())

        logger.info(
            "SessionsBus connected: agent_id=%s, capabilities=%s, max_concurrent=%d",
            self._agent_id,
            self._capabilities,
            self._max_concurrent_jobs,
        )

    async def close(self) -> None:
        """Close SSE connection and clean up resources."""
        logger.info("SessionsBus closing...")

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel SSE task
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                logger.info("SSE task cancelled")

        logger.info("SessionsBus closed")

    async def _consume_sse_stream(self) -> None:
        """Connect to SSE endpoint and process events with reconnection logic."""
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

                # Wait before reconnecting
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
        params: dict[str, Any] = {
            "agent_id": self._agent_id,
        }

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

                            # Process job asynchronously with concurrency control
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
        assert self._semaphore is not None, "Semaphore not initialized"
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
        """Process job notification by converting to CloudEvent and delegating to handlers.

        This is similar to NatsEventBus._handle_nats_message() - it converts the
        incoming event to CloudEvent format and delegates to ProcessingService.

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
                assert self._key_provider is not None, "SessionKeyProvider not initialized"
                session_key = await self._key_provider.get_session_key(session_id)

                # Convert to CloudEvent
                event = self._convert_to_cloud_event(job_data)

                # Build context with session key and job metadata
                context = {
                    "session_id": str(session_id),
                    "job_id": str(job_id),
                    "session_key": session_key,
                    "sessions_api_client": self._api_client,
                    "sessions_key_provider": self._key_provider,
                }

                # Get ProcessingService and delegate to handlers
                processing_service = self._component_registry.get_service(EventProcessingService)
                result = await processing_service.process_event(event, context)  # type: ignore[attr-defined]

                # Check if any handler processed it
                if result.status.value == "no_handler_found":
                    logger.warning(
                        "No handler found for job type %s (job_id=%s)",
                        job_type,
                        job_id,
                    )

            except InvalidEventError as e:
                # Permanent failure - cancel job
                logger.error("Invalid job %s: %s. Cancelling.", job_id, e)
                try:
                    assert self._key_provider is not None, "SessionKeyProvider not initialized"
                    assert self._api_client is not None, "SessionsApiClient not initialized"
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
                # Transient failure - log and leave job pending
                logger.warning(
                    "Retryable error for job %s: %s. Job remains pending.",
                    job_id,
                    e,
                )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    # Invalid session key - invalidate cache and retry once
                    logger.error("Invalid session key for session %s", session_id)
                    assert self._key_provider is not None, "SessionKeyProvider not initialized"
                    self._key_provider.invalidate_cache(session_id)

                    try:
                        session_key = await self._key_provider.get_session_key(session_id)
                        context["session_key"] = session_key
                        processing_service = self._component_registry.get_service(EventProcessingService)
                        await processing_service.process_event(event, context)  # type: ignore[attr-defined]
                    except Exception as retry_error:
                        logger.error("Retry failed for job %s: %s", job_id, retry_error)
                        raise InvalidEventError(status="invalid_session_key", reason=f"Session key invalid: {str(e)}") from e
                else:
                    raise

            except Exception as e:
                # Unexpected error - log and continue
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
