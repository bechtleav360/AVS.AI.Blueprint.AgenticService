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
*terminal* outcome (complete / cancel / error-result-complete) to drop replays
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

Error -> terminal-state mapping (svc-sessions can only reach COMPLETED/CANCELLED;
there is no reachable ``failed`` state):

================================  =====================================
``process`` raises                Outcome
================================  =====================================
``InvalidEventError``             cancel_job (CANCELLED)
``RetryableHandlerError``         re-raised -> SessionsBus leaves PENDING
``OSError`` / ``TimeoutError``    wrapped -> RetryableHandlerError -> PENDING
``ValueError`` / other            complete_job with error-shaped result
================================  =====================================
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar
from uuid import UUID

import httpx

from pydantic import BaseModel, ValidationError as PydanticValidationError

from ..models import HandlerResult
from ..models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ..models.events import GenericCloudEvent
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

    #: Attempts for the terminal ``complete_job`` call on transient HTTP errors.
    COMPLETE_MAX_ATTEMPTS: ClassVar[int] = 3
    #: Backoff between ``complete_job`` attempts, in seconds.
    COMPLETE_RETRY_BACKOFF_SECONDS: ClassVar[float] = 2.0

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
            A :attr:`RESULT_MODEL` instance whose ``model_dump()`` is submitted
            via ``complete_job``.

        Raising:
            * ``InvalidEventError`` -> the job is cancelled.
            * ``RetryableHandlerError`` / ``OSError`` / ``TimeoutError`` -> the job
              is left pending for redelivery.
            * any other exception -> the job is completed with an error result.
        """

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
            except Exception as exc:  # ValueError + any other -> complete with error result.
                await self._complete(
                    api_client,
                    session_id,
                    job_id,
                    session_key,
                    started,
                    {"status": "failed", "error": str(exc)},
                    status_log="completed_failed",
                )
                return None

            # --- Complete (success). ---
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
        """Terminal completion (success or error-result) with shared retry, then mark seen."""
        await self._complete_with_retry(api_client, session_id, job_id, session_key, result)
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

    async def _complete_with_retry(
        self,
        api_client: Any,
        session_id: UUID,
        job_id: UUID,
        session_key: str,
        result: dict[str, Any],
    ) -> None:
        last_exc: httpx.RequestError | None = None
        for attempt in range(1, self.COMPLETE_MAX_ATTEMPTS + 1):
            try:
                await api_client.complete_job(session_id=session_id, job_id=job_id, session_key=session_key, result=result)
                return
            except httpx.RequestError as exc:  # transport-level only; status errors propagate raw
                last_exc = exc
                logger.warning(
                    "complete_job attempt %d/%d failed: %s",
                    attempt,
                    self.COMPLETE_MAX_ATTEMPTS,
                    exc,
                    extra={"session_id": str(session_id), "job_id": str(job_id), "job_type": self.JOB_TYPE, "status": "complete_retry"},
                )
                if attempt < self.COMPLETE_MAX_ATTEMPTS and self.COMPLETE_RETRY_BACKOFF_SECONDS > 0:
                    await asyncio.sleep(self.COMPLETE_RETRY_BACKOFF_SECONDS)
        raise RetryableHandlerError(
            status="complete_failed",
            reason=f"complete_job exhausted {self.COMPLETE_MAX_ATTEMPTS} attempts: {last_exc}",
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
