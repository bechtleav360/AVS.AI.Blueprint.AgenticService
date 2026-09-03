"""Shared job-lifecycle base for sessions-service SSE handlers (issue #19).

`SessionsJobHandler` wraps the repetitive job lifecycle that every SSE-consuming
agent otherwise duplicates: fetch job detail, validate the payload, mark the job
running, run the agent-specific work, and report the result back — with a single
centralised error->status mapping and per-process idempotency.

Concrete handlers set three class vars (``JOB_TYPE``, ``PAYLOAD_MODEL``,
``RESULT_MODEL``) and implement the single abstract :meth:`process` method::

    class MyHandler(SessionsJobHandler):
        JOB_TYPE = "analyse.batch"
        PAYLOAD_MODEL = BatchPayload
        RESULT_MODEL = BatchResult

        async def process(self, payload: BatchPayload, context: dict) -> BatchResult:
            ...

Idempotency is two-stage (see :meth:`handle_event`): an in-flight guard for
concurrent duplicate notifications, plus a seen-set populated only on a
*terminal* outcome (complete / cancel / fail) to drop replays
of finished jobs. A job that fails before reaching a terminal state — transient
fetch/start error, or a post-start retryable/critical failure — is left in
neither set, so it stays eligible for redelivery rather than being silently
ignored.

Caveat: once ``start_job`` has moved a job PENDING->RUNNING, a redelivery that
re-enters this handler will call ``start_job`` again and svc-sessions rejects it
(RUNNING->RUNNING is not a valid transition -> 409). So post-start retryable
failures are *eligible* for redelivery but not yet cleanly *resumable* — true
post-start resume needs a svc-sessions re-pend/resume capability (tracked
separately). The ``_seen`` fix here removes the silent-ignore; it does not add a
resume path.

Outcome -> terminal-state mapping. svc-sessions reaches COMPLETED, CANCELLED, or
FAILED — the ``/fail`` endpoint (running->failed) has been live since 2026-06-24,
so a handler-signalled failure is recorded as FAILED rather than a COMPLETED job
carrying an error-shaped result:

====================================  =====================================
``process`` outcome                   Outcome
====================================  =====================================
``InvalidEventError``                 cancel_job (CANCELLED)
``RetryableHandlerError``             re-raised -> SessionsBus leaves PENDING
``OSError`` / ``TimeoutError``        wrapped -> RetryableHandlerError -> PENDING
``ValueError`` / other                fail_job (FAILED, exception-shaped error)
returns; ``failure_of`` -> JobError   fail_job (FAILED)
returns; ``failure_of`` -> None       complete_job (COMPLETED)
====================================  =====================================
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar
from uuid import UUID

import httpx

from pydantic import BaseModel, ValidationError as PydanticValidationError

from ..models import HandlerResult
from ..models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ..models.events import GenericCloudEvent
from ..models.sessions import JobError
from .event_handler_base import EventHandlerBase

logger = logging.getLogger(__name__)


class SessionsJobHandler(EventHandlerBase, ABC):
    """Abstract base wrapping the sessions-service job lifecycle.

    Subclasses MUST set :attr:`JOB_TYPE`, :attr:`PAYLOAD_MODEL`,
    :attr:`RESULT_MODEL` and implement :meth:`process`.
    """

    JOB_TYPE: ClassVar[str]
    PAYLOAD_MODEL: ClassVar[type[BaseModel]]
    RESULT_MODEL: ClassVar[type[BaseModel]]

    #: Attempts for a terminal write (``complete_job`` / ``fail_job``) on transient HTTP errors.
    TERMINAL_MAX_ATTEMPTS: ClassVar[int] = 3
    #: Backoff between terminal-write attempts, in seconds.
    TERMINAL_RETRY_BACKOFF_SECONDS: ClassVar[float] = 2.0

    @property
    def COMPLETE_MAX_ATTEMPTS(self) -> int:
        """Deprecated read-only alias of :attr:`TERMINAL_MAX_ATTEMPTS` (pre-0.7.0 name).

        Retained so code that *reads* the old name keeps working; it no longer accepts an
        override — tune :attr:`TERMINAL_MAX_ATTEMPTS` instead. ``TERMINAL_*`` is the single
        source of truth, so a stale ``COMPLETE_*`` override can't silently diverge from it.
        """
        return self.TERMINAL_MAX_ATTEMPTS

    @property
    def COMPLETE_RETRY_BACKOFF_SECONDS(self) -> float:
        """Deprecated read-only alias of :attr:`TERMINAL_RETRY_BACKOFF_SECONDS` (pre-0.7.0 name)."""
        return self.TERMINAL_RETRY_BACKOFF_SECONDS

    def __init__(self, priority: int = 100) -> None:
        super().__init__(priority=priority)
        self._agent_id: str | None = None
        # Concurrent duplicate guard; populated at entry, cleared in `finally`.
        self._in_flight: set[UUID] = set()
        # Replay guard; populated only on a terminal outcome (complete/cancel).
        self._seen: set[UUID] = set()

    async def on_startup(self) -> None:
        """Resolve the agent id from ``sessions_service`` config (required)."""
        sessions_config = self.config.get("sessions_service") or {}
        self._agent_id = sessions_config.get("agent_id")
        if not self._agent_id:
            raise ValueError("sessions_service.agent_id is required")

    async def on_shutdown(self) -> None:
        return None

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        """Handle only this subclass's job type; unknown types are ignored."""
        return event.type == f"sessions.job.created.{self.JOB_TYPE}"

    @abstractmethod
    async def process(self, payload: BaseModel, context: dict[str, Any]) -> BaseModel:
        """Run the agent-specific work for one validated job.

        Args:
            payload: The validated :attr:`PAYLOAD_MODEL` instance.
            context: The processing context dict (``session_id``, ``job_id``,
                ``session_key``, ``sessions_api_client``, ...).

        Returns:
            A :attr:`RESULT_MODEL` instance. A normally-returned result completes
            the job (``complete_job``) unless :meth:`failure_of` classifies it as a
            failure, in which case the job is failed (``fail_job``) instead.

        Raising:
            * ``InvalidEventError`` -> the job is cancelled.
            * ``RetryableHandlerError`` / ``OSError`` / ``TimeoutError`` -> the job
              is left pending for redelivery.
            * any other exception -> the job is failed (``fail_job``, FAILED).
        """

    def failure_of(self, result: BaseModel) -> JobError | None:
        """Classify a *normally-returned* result as a failure, or not (default).

        :meth:`process` can compute an internal failure and return it as an ordinary
        result instead of raising (e.g. a batch that caught every per-item error and
        recorded them on the result). Override this to route such a result to
        ``fail_job`` (svc-sessions ``FAILED``) instead of ``complete_job``.

        Return a :class:`JobError` (``{"message": str, "code": str | None}``) to fail
        the job, or ``None`` to complete it. The default returns ``None``, so every
        normally-returned result completes — identical to the behaviour before this
        hook existed. Only the no-exception path is affected; raising from ``process``
        is unchanged.
        """
        return None

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult | None:
        session_id = UUID(context["session_id"])
        job_id = UUID(context["job_id"])
        session_key: str = context["session_key"]
        api_client = context["sessions_api_client"]

        # --- Idempotency: synchronous check-and-add, no await in between. ---
        if job_id in self._in_flight or job_id in self._seen:
            logger.info(
                "Duplicate job notification ignored",
                extra={"session_id": str(session_id), "job_id": str(job_id), "job_type": self.JOB_TYPE, "status": "duplicate"},
            )
            return None
        self._in_flight.add(job_id)

        started = time.monotonic()
        try:
            # --- Fetch + validate (before start_job: never start a doomed job). ---
            try:
                job_detail = await api_client.get_job_detail(session_id, job_id, session_key)
            except httpx.RequestError as exc:
                # Transport-level only. HTTPStatusError (e.g. 403) propagates raw so
                # SessionsBus can run its session-key-refresh-and-retry recovery.
                raise RetryableHandlerError(status="fetch_failed", reason=f"get_job_detail failed: {exc}") from exc

            raw_payload = job_detail.get("payload", {}) if isinstance(job_detail, dict) else {}
            try:
                payload = self.PAYLOAD_MODEL.model_validate(raw_payload)
            except PydanticValidationError as exc:
                await self._cancel(
                    api_client, session_id, job_id, session_key, started, reason=f"invalid payload for {self.PAYLOAD_MODEL.__name__}: {exc}"
                )
                return None

            # --- Start. ---
            try:
                await api_client.start_job(session_id, job_id, self._agent_id, session_key)
            except httpx.RequestError as exc:
                raise RetryableHandlerError(status="start_failed", reason=f"start_job failed: {exc}") from exc

            # --- Process + map errors to terminal states. ---
            # NOTE: `_seen` (the redelivery guard) is populated ONLY on a terminal
            # outcome below — never merely because `start_job` succeeded. A job that
            # started but then re-raises (retryable / critical) must stay out of
            # `_seen` so a redelivery is not silently ignored.
            try:
                result = await self.process(payload, context)
            except (RetryableHandlerError, CriticalHandlerError):
                # Retryable -> SessionsBus leaves pending; Critical -> forces restart.
                # Both keep their framework semantics; never neutralise into a result.
                raise
            except InvalidEventError as exc:
                await self._cancel(api_client, session_id, job_id, session_key, started, reason=str(exc))
                return None
            except (OSError, TimeoutError) as exc:
                raise RetryableHandlerError(status="process_transient", reason=f"process transient error: {exc}") from exc
            except Exception as exc:  # ValueError + any other unrecoverable -> FAILED.
                await self._fail(
                    api_client,
                    session_id,
                    job_id,
                    session_key,
                    started,
                    {"message": str(exc), "code": type(exc).__name__},
                    status_log="failed",
                )
                return None

            # --- Terminal: fail if the handler signalled failure, else complete. ---
            failure = self.failure_of(result)
            if failure is not None:
                await self._fail(api_client, session_id, job_id, session_key, started, failure, status_log="failed")
            else:
                await self._complete(api_client, session_id, job_id, session_key, started, result.model_dump(), status_log="completed")
            return None
        finally:
            self._in_flight.discard(job_id)

    async def _complete(
        self,
        api_client: Any,
        session_id: UUID,
        job_id: UUID,
        session_key: str,
        started: float,
        result: dict[str, Any],
        *,
        status_log: str,
    ) -> None:
        """Terminal completion with shared retry, then mark seen."""
        await self._terminal_with_retry(
            session_id,
            job_id,
            verb="complete",
            call=lambda: api_client.complete_job(session_id=session_id, job_id=job_id, session_key=session_key, result=result),
        )
        self._seen.add(job_id)
        self._log(session_id, job_id, status_log, started)

    async def _fail(
        self,
        api_client: Any,
        session_id: UUID,
        job_id: UUID,
        session_key: str,
        started: float,
        error: JobError,
        *,
        status_log: str,
    ) -> None:
        """Terminal failure (fail_job) with shared retry, then mark seen."""
        await self._terminal_with_retry(
            session_id,
            job_id,
            verb="fail",
            call=lambda: api_client.fail_job(session_id=session_id, job_id=job_id, session_key=session_key, error=error),
        )
        self._seen.add(job_id)
        self._log(session_id, job_id, status_log, started)

    async def _cancel(
        self,
        api_client: Any,
        session_id: UUID,
        job_id: UUID,
        session_key: str,
        started: float,
        *,
        reason: str,
    ) -> None:
        """Terminal cancellation, then mark seen so a redelivery does not re-cancel."""
        await api_client.cancel_job(session_id=session_id, job_id=job_id, session_key=session_key, reason=reason)
        self._seen.add(job_id)
        self._log(session_id, job_id, "cancelled", started)

    async def _terminal_with_retry(
        self,
        session_id: UUID,
        job_id: UUID,
        *,
        verb: str,
        call: Callable[[], Awaitable[Any]],
    ) -> None:
        """Run a terminal write (``complete_job`` / ``fail_job``) with bounded retry.

        Only ``httpx.RequestError`` (transport-level) is retried; HTTP status errors
        propagate raw. Exhaustion raises ``RetryableHandlerError`` so the job stays
        eligible for redelivery rather than being lost.
        """
        max_attempts = self.TERMINAL_MAX_ATTEMPTS
        backoff = self.TERMINAL_RETRY_BACKOFF_SECONDS
        last_exc: httpx.RequestError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                await call()
                return
            except httpx.RequestError as exc:  # transport-level only; status errors propagate raw
                last_exc = exc
                logger.warning(
                    "%s_job attempt %d/%d failed: %s",
                    verb,
                    attempt,
                    max_attempts,
                    exc,
                    extra={"session_id": str(session_id), "job_id": str(job_id), "job_type": self.JOB_TYPE, "status": f"{verb}_retry"},
                )
                if attempt < max_attempts and backoff > 0:
                    await asyncio.sleep(backoff)
        raise RetryableHandlerError(
            status=f"{verb}_failed",
            reason=f"{verb}_job exhausted {max_attempts} attempts: {last_exc}",
        )

    def _log(self, session_id: UUID, job_id: UUID, status: str, started: float) -> None:
        logger.info(
            "sessions job %s",
            status,
            extra={
                "session_id": str(session_id),
                "job_id": str(job_id),
                "job_type": self.JOB_TYPE,
                "status": status,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            },
        )
