"""Sessions service event bus implementation (framework-level).

This module provides the SessionsBus that connects to the sessions service via SSE,
receives job notifications, converts them to CloudEvents, and delegates to EventHandlers
for processing via the CloudEventProcessorMixin dispatch pipeline.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

import httpx
from httpx_sse import ServerSentEvent, SSEError, aconnect_sse
from opentelemetry import trace

from ....component.component import Component
from ....models.errors import InvalidEventError, RetryableHandlerError
from ....models.events import GenericCloudEvent
from ....models.sessions import JobNotification
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

        # In-flight job tasks (tracked so shutdown can drain them, not orphan them)
        self._inflight_tasks: set[asyncio.Task[None]] = set()

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
        """Stop the stream, drain in-flight jobs, then unregister.

        The order is deliberate: setting the shutdown event stops the consumer from
        accepting new jobs, in-flight jobs are given a bounded window to finish, and
        only then do we unregister — so the registration is never pulled out from
        under a job that is still reporting results.
        """
        logger.info("SessionsBus closing...")

        self._shutdown_event.set()

        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                logger.info("SSE task cancelled")

        await self._drain_inflight_jobs()

        if self._api_client is not None and self._agent_id:
            # Cleanup must never fail the shutdown; unregister_agent is best-effort but
            # guard here too so a mocked/overridden client cannot break teardown.
            try:
                await self._api_client.unregister_agent(self._agent_id)
            except Exception as e:
                logger.warning("Unregister on shutdown failed: %s", e)

        logger.info("SessionsBus closed")

    async def _drain_inflight_jobs(self) -> None:
        """Wait for in-flight job tasks to finish, bounded by ``job_timeout``.

        Jobs are launched fire-and-forget from the SSE loop; without this drain they
        would be orphaned on shutdown. Tasks still running after the timeout are
        cancelled so shutdown cannot hang.
        """
        if not self._inflight_tasks:
            return
        pending = list(self._inflight_tasks)
        logger.info("Draining %d in-flight job(s) (timeout=%ds)", len(pending), self._job_timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=self._job_timeout,
            )
        except TimeoutError:
            logger.warning("Drain timeout — cancelling %d in-flight job(s)", len(pending))
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

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
        """Register, then establish the SSE connection and consume events."""
        # v0.4.0 gates the stream on registration — register (idempotent) before every
        # connect attempt. On a legacy server this is a no-op (404 -> False); on a hard
        # failure it raises and the reconnect loop (in _consume_sse_stream) backs off.
        if self._agent_id is None:
            raise RuntimeError("SessionsBus not started: agent_id is not set")
        await self._require_api_client().register_agent(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            capabilities=self._capabilities,
        )

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
                try:
                    async for sse in event_source.aiter_sse():
                        if self._shutdown_event.is_set():
                            break
                        self._dispatch_sse_event(sse)
                except SSEError:
                    # aconnect_sse hides the real status when the server returns JSON (e.g. a
                    # 403 dispatch-gate rejection). Surface status + body before backing off.
                    resp = event_source.response
                    body = (await resp.aread()).decode(errors="replace")[:500]
                    logger.error("SSE stream rejected: status=%d body=%s", resp.status_code, body)
                    raise

    def _dispatch_sse_event(self, sse: ServerSentEvent) -> None:
        """Route a single SSE frame. Keepalive comment frames are ignored (#44)."""
        try:
            if sse.event == "connected":
                logger.info("SSE connected event received")

            elif sse.event == "job_created":
                notification = JobNotification.model_validate_json(sse.data)
                logger.info(
                    "Job notification received: job_id=%s, job_type=%s",
                    notification.job_id,
                    notification.job_type,
                )
                task = asyncio.create_task(self._handle_job_notification(notification))
                self._inflight_tasks.add(task)
                task.add_done_callback(self._inflight_tasks.discard)

            elif sse.event == "heartbeat":
                logger.debug("SSE heartbeat received")

            elif sse.event == "message" and not (sse.data or "").strip():
                # Server keepalive comment frame (`: keepalive`) surfaces as a default-type
                # `message` with empty data. Ignore it (#44) instead of warning every tick.
                logger.debug("SSE keepalive frame received")

            else:
                logger.warning("Unknown SSE event type: %s", sse.event)

        except Exception as e:
            logger.error("Error processing SSE event: %s", e, exc_info=True)

    async def _handle_job_notification(self, notification: JobNotification) -> None:
        """Handle job notification with concurrency control.

        Args:
            notification: Parsed job notification from the SSE stream
        """
        if self._semaphore is None:
            raise RuntimeError("Semaphore not initialized")
        async with self._semaphore:
            try:
                await asyncio.wait_for(
                    self._process_job_notification(notification),
                    timeout=self._job_timeout,
                )
            except TimeoutError:
                logger.error(
                    "Job processing timeout after %ds: job_id=%s",
                    self._job_timeout,
                    notification.job_id,
                )

    async def _process_job_notification(self, notification: JobNotification) -> None:
        """Convert the notification to a CloudEvent and dispatch it, applying
        sessions-specific error handling. Each recovery policy lives in its own
        helper so this method stays a thin dispatcher.
        """
        session_id = notification.session_id
        job_id = notification.job_id
        job_type = notification.job_type

        with tracer.start_as_current_span("sessions_bus.process_job") as span:
            span.set_attribute("job_id", str(job_id))
            span.set_attribute("session_id", str(session_id))
            span.set_attribute("job_type", job_type)

            event = self._convert_to_cloud_event(notification)

            try:
                session_key = await self._require_key_provider().get_session_key(session_id)
                context = self._build_context(session_id, job_id, session_key)
                result = await self._dispatch_cloud_event(event, context)

                if result.status.value == "no_handler_found":
                    logger.warning("No handler found for job type %s (job_id=%s)", job_type, job_id)

            except InvalidEventError as e:
                await self._cancel_invalid_job(session_id, job_id, e)

            except RetryableHandlerError as e:
                logger.warning("Retryable error for job %s: %s. Job remains pending.", job_id, e)

            except httpx.HTTPStatusError as e:
                if e.response.status_code != 403:
                    raise
                await self._retry_with_fresh_key(event, session_id, job_id, e)

            except Exception as e:
                logger.exception("Unexpected error processing job %s: %s", job_id, e)

    def _require_key_provider(self) -> SessionKeyProvider:
        if self._key_provider is None:
            raise RuntimeError("SessionKeyProvider not initialized")
        return self._key_provider

    def _require_api_client(self) -> SessionsApiClient:
        if self._api_client is None:
            raise RuntimeError("SessionsApiClient not initialized")
        return self._api_client

    def _build_context(self, session_id: UUID, job_id: UUID, session_key: str) -> dict[str, Any]:
        return {
            "session_id": str(session_id),
            "job_id": str(job_id),
            "session_key": session_key,
            "sessions_api_client": self._require_api_client(),
            "sessions_key_provider": self._require_key_provider(),
        }

    async def _cancel_invalid_job(self, session_id: UUID, job_id: UUID, error: InvalidEventError) -> None:
        logger.error("Invalid job %s: %s. Cancelling.", job_id, error)
        try:
            session_key = await self._require_key_provider().get_session_key(session_id)
            await self._require_api_client().cancel_job(
                session_id=session_id,
                job_id=job_id,
                session_key=session_key,
                reason=f"Invalid event: {error}",
            )
        except Exception as cancel_error:
            logger.error("Failed to cancel job %s: %s", job_id, cancel_error)

    async def _retry_with_fresh_key(
        self,
        event: GenericCloudEvent,
        session_id: UUID,
        job_id: UUID,
        original_error: httpx.HTTPStatusError,
    ) -> None:
        # A 403 from a handler means the cached session key is stale. Invalidate and retry
        # once through the SAME dispatch seam as the happy path (no separate code path).
        logger.warning("Stale session key for session %s; refreshing and retrying", session_id)
        key_provider = self._require_key_provider()
        key_provider.invalidate_cache(session_id)
        try:
            session_key = await key_provider.get_session_key(session_id)
            context = self._build_context(session_id, job_id, session_key)
            await self._dispatch_cloud_event(event, context)
        except Exception as retry_error:
            logger.error("Retry failed for job %s: %s", job_id, retry_error)
            # Report the original 403 in the reason (that is what the operator needs to see);
            # chain from retry_error so the proximate failure is preserved in the traceback.
            raise InvalidEventError(
                status="invalid_session_key",
                reason=f"Session key invalid: {original_error}",
            ) from retry_error

    def _convert_to_cloud_event(self, notification: JobNotification) -> GenericCloudEvent:
        """Convert a job notification to CloudEvent format.

        Args:
            notification: Parsed job notification

        Returns:
            GenericCloudEvent with the full job payload as ``data``
        """
        event_type = f"sessions.job.created.{notification.job_type}"
        kwargs: dict[str, Any] = {
            "specversion": "1.0",
            "id": str(notification.job_id),
            "type": event_type,
            "source": "/sessions-service",
            "subject": str(notification.session_id),
            "datacontenttype": "application/json",
            "data": notification.payload(),
        }
        # Only set `time` when present — GenericCloudEvent rejects a None time; omitting it
        # lets the model apply its default timestamp.
        if notification.created_at is not None:
            kwargs["time"] = notification.created_at
        return GenericCloudEvent(**kwargs)
