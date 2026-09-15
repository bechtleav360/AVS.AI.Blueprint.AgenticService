"""Sessions service event bus implementation (framework-level).

This module provides the SessionsBus that connects to the sessions service via SSE,
receives job notifications, converts them to CloudEvents, and delegates to EventHandlers
for processing via the CloudEventProcessorMixin dispatch pipeline.
"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

import httpx
from httpx_sse import ServerSentEvent, SSEError, aconnect_sse
from opentelemetry import trace

from ....component.component import Component
from ....models.errors import InvalidEventError, RetryableHandlerError
from ....models.events import GenericCloudEvent
from ....models.sessions import JobNotification
from ....services.sessions import SessionKeyClaimConflictError, SessionKeyProvider, SessionsApiClient
from .cloud_event_processor_mixin import CloudEventProcessorMixin

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _is_retryable_http_status(status_code: int) -> bool:
    """5xx/408/429/401 — a transient or operator-fixable fault, not evidence the job
    itself is invalid. Shared by every place that classifies an ``httpx.HTTPStatusError``
    for cancel-vs-retry, so the decision can't drift between call sites the way it did
    between the main dispatch path and the 403-retry path (#95): 5xx/408/429 are
    the upstream-blip case (service-sessions deploy/restart, LB blip, rate limit); 401 is
    a missing/invalid ``X-Api-Key``, systemic across every job this agent handles rather
    than specific to this one, and canceling it wouldn't even take effect — ``cancel_job``
    would send the same bad key and 401 in turn. Canceling any of these turns a transient
    fault into permanent job loss, strictly worse than leaving it ``pending`` for
    redelivery to retry once the fault clears.
    """
    return status_code >= 500 or status_code in (401, 408, 429)


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

        # Last SSE event id seen, sent as `last_event_id` on reconnect so the server replays
        # events missed during a same-process stream gap from its ring buffer. None until the
        # first id-bearing frame (and after a process restart) — the REST catch-up covers that.
        self._last_event_id: int | None = None

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
        # Resume from the last id we saw so a same-process reconnect replays missed events
        # from the server ring buffer. Omitted on a cold start (None) — catch-up covers that.
        if self._last_event_id is not None:
            params["last_event_id"] = self._last_event_id

        headers = {"X-Api-Key": self._api_key}

        async with httpx.AsyncClient(timeout=None) as client:
            async with aconnect_sse(client, "GET", url, params=params, headers=headers) as event_source:
                logger.info("SSE connection established")
                # Subscribe-then-snapshot: the stream is open, so any job created from here on
                # arrives live. Reconcile jobs created *before* now (restart/redeploy/gap) via a
                # background REST catch-up; overlaps with replayed/live events are de-duplicated
                # by the job handler's idempotency guards. Runs off the consume loop so it never
                # blocks live delivery.
                self._spawn_tracked(self._run_catch_up())
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

    def _spawn_tracked(self, coro: Coroutine[Any, Any, None]) -> None:
        """Launch *coro* as a tracked background task so shutdown can drain it.

        Shared by the live ``job_created`` path and the reconnect catch-up so both feed the
        same in-flight set (and therefore the same shutdown drain).
        """
        task = asyncio.create_task(coro)
        self._inflight_tasks.add(task)
        task.add_done_callback(self._inflight_tasks.discard)

    def _track_event_id(self, sse: ServerSentEvent) -> None:
        """Advance the resume cursor from a frame's ``id`` (server ids are monotonic ints)."""
        raw = getattr(sse, "id", None)
        if not raw:
            return
        try:
            self._last_event_id = int(raw)
        except (TypeError, ValueError):
            logger.debug("Ignoring non-numeric SSE id: %r", raw)

    def _dispatch_sse_event(self, sse: ServerSentEvent) -> None:
        """Route a single SSE frame. Keepalive comment frames are ignored (#44)."""
        try:
            self._track_event_id(sse)

            if sse.event == "connected":
                logger.info("SSE connected event received")

            elif sse.event == "job_created":
                notification = JobNotification.model_validate_json(sse.data)
                logger.info(
                    "Job notification received: job_id=%s, job_type=%s",
                    notification.job_id,
                    notification.job_type,
                )
                self._spawn_tracked(self._handle_job_notification(notification))

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

    async def _run_catch_up(self) -> None:
        """Reconcile jobs created while the agent was disconnected (restart / redeploy / gap).

        SSE only delivers jobs created *while connected*; anything created before this stream
        opened is pending on the server but was never pushed. List those over REST and dispatch
        each through the same path as a live notification. Best-effort: a listing failure is
        logged and swallowed so it never disturbs the live stream, and each summary is parsed
        defensively so one bad row does not stop the rest. Overlap with replayed or live events
        is de-duplicated by the job handler's idempotency guards.
        """
        if self._shutdown_event.is_set():
            return
        try:
            summaries = await self._require_api_client().list_pending_jobs(self._capabilities)
        except Exception as e:
            logger.warning("Catch-up listing failed; missed jobs wait for the next reconnect: %s", e)
            return
        if not summaries:
            return
        logger.info("Catch-up: reconciling %d pending job(s) missed while disconnected", len(summaries))
        for summary in summaries:
            if self._shutdown_event.is_set():
                break
            try:
                notification = self._notification_from_summary(summary)
            except Exception as e:
                logger.error("Skipping unparseable pending-job summary %r: %s", summary, e)
                continue
            self._spawn_tracked(self._handle_job_notification(notification))

    def _notification_from_summary(self, summary: dict[str, Any]) -> JobNotification:
        """Build a JobNotification from a REST ``JobSummary`` dict (its ``id`` is the job id)."""
        return JobNotification(
            session_id=summary["session_id"],
            job_id=summary["id"],
            job_type=summary["job_type"],
            created_at=summary.get("created_at"),
        )

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

        Design note shared by every branch below (and by ``_retry_with_fresh_key``)
        that logs-and-cancels instead of re-raising: a `raise` inside one of these
        `except` clauses would propagate straight out of this method's try/except
        (peer `except` clauses are never consulted for it), and this coroutine only
        ever runs as a fire-and-forget task (``_spawn_tracked``) whose result
        nothing awaits — an escaping exception here becomes an unretrieved task
        exception, not a caller-visible failure. Confirmed as the actual mechanism
        behind #94's silent "job never progresses past pending" symptom.
        """
        session_id = notification.session_id
        job_id = notification.job_id
        job_type = notification.job_type

        with tracer.start_as_current_span("sessions_bus.process_job") as span:
            span.set_attribute("job_id", str(job_id))
            span.set_attribute("session_id", str(session_id))
            span.set_attribute("job_type", job_type)

            event = self._convert_to_cloud_event(notification)

            # Tracked across the whole try block (not just the happy path) so a cancel
            # triggered below can reuse an already-obtained key instead of blindly
            # repeating the fetch — including when that repeat would hit the exact
            # same failure the original error came from.
            session_key: str | None = None
            try:
                session_key = await self._require_key_provider().get_session_key(session_id, job_id=job_id)
                context = self._build_context(session_id, job_id, session_key, pipeline_id=notification.pipeline_id)
                result = await self._dispatch_cloud_event(event, context)

                if result.status.value == "no_handler_found":
                    logger.warning("No handler found for job type %s (job_id=%s)", job_type, job_id)

            except InvalidEventError as e:
                await self._cancel_invalid_job(session_id, job_id, e, session_key=session_key)

            except RetryableHandlerError as e:
                logger.warning("Retryable error for job %s: %s. Job remains pending.", job_id, e)

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                if status_code == 403:
                    await self._retry_with_fresh_key(event, session_id, job_id, e, pipeline_id=notification.pipeline_id)
                elif _is_retryable_http_status(status_code):
                    # Treat exactly like RetryableHandlerError: log and leave pending for
                    # redelivery to retry — an operator fixing the key or the upstream blip
                    # resolving both make the job recoverable on the next delivery. Canceling
                    # here would turn a passing 503 into permanent job loss on every upstream
                    # deploy, strictly worse than #94's original "stuck pending" symptom this
                    # whole except-block exists to fix.
                    logger.warning("Retryable upstream HTTP error for job %s: %s. Job remains pending.", job_id, e)
                else:
                    await self._cancel_on_terminal_http_error(session_id, job_id, e, session_key=session_key)

            except SessionKeyClaimConflictError as e:
                # Expected multi-consumer race, not a bug: another agent instance already
                # claimed this job's session key (409 from the "job" source). Logged at
                # `warning`, not `exception`/`critical` — there's nothing to cancel or
                # remediate here, the job is simply someone else's to process now.
                logger.warning("Job %s already claimed by another agent instance: %s", job_id, e)

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

    def _build_context(self, session_id: UUID, job_id: UUID, session_key: str, pipeline_id: str | None = None) -> dict[str, Any]:
        return {
            "session_id": str(session_id),
            "job_id": str(job_id),
            "session_key": session_key,
            "sessions_api_client": self._require_api_client(),
            "sessions_key_provider": self._require_key_provider(),
            "pipeline_id": pipeline_id,
        }

    async def _cancel_invalid_job(self, session_id: UUID, job_id: UUID, error: InvalidEventError, session_key: str | None = None) -> None:
        """Cancel *job_id*, reusing *session_key* if the caller already has one.

        Re-fetching unconditionally (the pre-fix behavior) meant that when the
        triggering error was itself a `get_session_key` failure, this method
        repeated that exact same call and hit the exact same failure — silently,
        under the generic `except Exception` below, indistinguishable from an
        ordinary transient cancel failure (reproduced against #94's own
        originating case: a 422 from the job-scoped key-fetch). When the caller
        passes `session_key=None`, this method still retries the fetch exactly
        once below — a concurrent job may have populated the cache since the
        caller's own attempt failed — rather than looping on the same failure
        again beyond that one reasonable retry. Only when that retry *also*
        fails is there truly no key available: service-sessions' cancel endpoint
        requires a real `X-Session-Key` (confirmed against
        avs.ai.idac.service-sessions' `cancel_job` route), so there is no way to
        authenticate a cancel here without a server-side change out of this
        client's scope. That's logged at `critical`, not the routine `error` level
        below, because it means the job is stuck at `pending` with no remaining
        remediation path in this pass, not just this one attempt failing.
        """
        logger.error("Invalid job %s: %s. Attempting cancellation.", job_id, error)
        if session_key is None:
            try:
                session_key = await self._require_key_provider().get_session_key(session_id, job_id=job_id)
            except Exception as key_error:
                logger.critical(
                    "Cannot cancel job %s: no session key could be obtained (%s). "
                    "Job remains pending with no remediation from this pass — a later "
                    "redelivery may still succeed if the key fetch failure was transient.",
                    job_id,
                    key_error,
                )
                return
        try:
            await self._require_api_client().cancel_job(
                session_id=session_id,
                job_id=job_id,
                session_key=session_key,
                reason=f"Invalid event: {error}",
            )
        except Exception as cancel_error:
            logger.error("Failed to cancel job %s: %s", job_id, cancel_error)

    async def _cancel_on_terminal_http_error(
        self,
        session_id: UUID,
        job_id: UUID,
        error: httpx.HTTPStatusError,
        session_key: str | None,
    ) -> None:
        """Log and cancel on a non-403, non-retryable ``httpx.HTTPStatusError``.

        Logging (rather than re-raising) here follows the same rationale as every
        other log-and-cancel branch in ``_process_job_notification`` — see that
        method's docstring for why raising would silently vanish as an unretrieved
        task exception instead of surfacing.

        No separate log call here for the error itself: ``_cancel_invalid_job``
        below already logs "Invalid job ... Cancelling." with this error's text in
        the reason, and logging it a second time up here produced two log lines
        per incident for no added information.
        """
        # Cancel rather than leave pending: a non-403, non-retryable HTTP error
        # from the key fetch (404 unknown/expired job, 409, 422 contract drift) is
        # not something a later SSE reconnect or retry will resolve on its own —
        # leaving the job pending forever just hides the failure one layer deeper
        # than before this fix. `session_key` is still None here when *this very
        # error* came from the get_session_key call above (rather than from
        # dispatch) — _cancel_invalid_job retries that fetch exactly once (a
        # concurrent job may have populated the cache since) and escalates at
        # `critical` if that also fails, rather than repeating the same failure
        # again beyond that one reasonable retry.
        await self._cancel_invalid_job(
            session_id,
            job_id,
            InvalidEventError(status="non_retryable_http_error", reason=f"Unexpected HTTP error: {error}"),
            session_key=session_key,
        )

    async def _retry_with_fresh_key(
        self,
        event: GenericCloudEvent,
        session_id: UUID,
        job_id: UUID,
        original_error: httpx.HTTPStatusError,
        pipeline_id: str | None = None,
    ) -> None:
        # A 403 from a handler means the cached session key is stale. Invalidate and retry
        # once through the SAME dispatch seam as the happy path (no separate code path).
        logger.warning("Stale session key for session %s; refreshing and retrying", session_id)
        key_provider = self._require_key_provider()
        key_provider.invalidate_cache(session_id)
        # Tracked across the try block for the same reason as _process_job_notification's
        # own `session_key` local: lets the cancel fallback below reuse it instead of
        # repeating a fetch that may have been the retry's own point of failure.
        session_key: str | None = None
        retryable = False
        # Python deletes an `except ... as name` binding when its suite exits, so the
        # caught exception is copied into this plain local to stay usable below.
        retry_error: Exception | None = None
        try:
            session_key = await key_provider.get_session_key(session_id, job_id=job_id)
            context = self._build_context(session_id, job_id, session_key, pipeline_id=pipeline_id)
            await self._dispatch_cloud_event(event, context)
            return
        except RetryableHandlerError as exc:
            retryable = True
            retry_error = exc
        except httpx.HTTPStatusError as exc:
            retryable = _is_retryable_http_status(exc.response.status_code)
            retry_error = exc
        except Exception as exc:
            retry_error = exc

        if retryable:
            # Same classification as the main dispatch path (#95): a retry that
            # hits a retryable error must stay pending, not cancel — canceling here would
            # turn a job that failed its retry on a transient fault into permanent job
            # loss, exactly the case the retryable/non-retryable split exists to prevent,
            # just on this sibling path instead.
            logger.warning("Retryable error on retry for job %s: %s. Job remains pending.", job_id, retry_error)
            return

        logger.error("Retry failed for job %s: %s", job_id, retry_error)
        # Cancel directly rather than raising InvalidEventError: this method is called
        # from inside _process_job_notification's `except httpx.HTTPStatusError` clause,
        # so the same unretrieved-task-exception trap applies here — see that method's
        # docstring. Report the original 403 in the reason (that is what the operator
        # needs to see).
        await self._cancel_invalid_job(
            session_id,
            job_id,
            InvalidEventError(
                status="invalid_session_key",
                reason=f"Session key invalid: {original_error}",
            ),
            session_key=session_key,
        )

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
