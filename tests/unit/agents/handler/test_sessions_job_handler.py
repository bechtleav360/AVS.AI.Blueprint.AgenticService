"""Unit tests for SessionsJobHandler (issue #19).

Covers the shared job-lifecycle base: happy path, two-stage idempotency
(in-flight guard + terminal-only seen-set), eligibility-for-redelivery on
transient pre-start AND post-start failures, payload validation -> cancel, the
process() error->status mapping, complete_job retry/exhaustion, and
unknown-job_type no-op.

All svc-sessions calls are mocked; these tests do NOT prove the live cancel path
(svc-sessions exposes no /cancel route — tracked as a separate follow-up).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest

from pydantic import BaseModel

from blueprint.agents.models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from blueprint.agents.models.events import GenericCloudEvent

# Module under test (does not exist yet — RED).
from blueprint.agents.handler.sessions_job_handler import SessionsJobHandler


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    """Build an HTTPStatusError like httpx.Response.raise_for_status() would."""
    request = httpx.Request("GET", "http://sessions/jobs")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"{status_code}", request=request, response=response)


# ---------------------------------------------------------------------------
# Test models + concrete handler
# ---------------------------------------------------------------------------


class _Payload(BaseModel):
    name: str


class _Result(BaseModel):
    ok: bool


class _Handler(SessionsJobHandler):
    """Concrete handler whose process() behaviour is injectable per test."""

    JOB_TYPE = "demo"
    PAYLOAD_MODEL = _Payload
    RESULT_MODEL = _Result

    # Zero backoff so retry tests don't sleep.
    COMPLETE_RETRY_BACKOFF_SECONDS = 0.0

    def __init__(self, *, process_impl: Any = None) -> None:
        super().__init__()
        self._process_impl = process_impl
        self.process_calls = 0

    async def process(self, payload: _Payload, context: dict[str, Any]) -> _Result:
        self.process_calls += 1
        if self._process_impl is not None:
            return await self._process_impl(payload, context)
        return _Result(ok=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_id() -> UUID:
    return uuid4()


@pytest.fixture
def job_id() -> UUID:
    return uuid4()


@pytest.fixture
def api_client() -> MagicMock:
    client = MagicMock()
    client.get_job_detail = AsyncMock(return_value={"payload": {"name": "alice"}})
    client.start_job = AsyncMock(return_value={})
    client.complete_job = AsyncMock(return_value={})
    client.cancel_job = AsyncMock(return_value={})
    return client


@pytest.fixture
def context(session_id: UUID, job_id: UUID, api_client: MagicMock) -> dict[str, Any]:
    return {
        "session_id": str(session_id),
        "job_id": str(job_id),
        "session_key": "sk-test",
        "sessions_api_client": api_client,
    }


@pytest.fixture
def event() -> GenericCloudEvent:
    return GenericCloudEvent(id="evt-1", type="sessions.job.created.demo", source="/sessions-service")


def _started(mock_config: MagicMock) -> _Handler:
    """Build a handler with agent_id configured and on_startup applied."""
    mock_config.get.return_value = {"agent_id": "test-agent"}
    return _Handler()


# ---------------------------------------------------------------------------
# can_handle_event — job_type routing (AC-5: unknown type ignored)
# ---------------------------------------------------------------------------


class TestCanHandleEvent:
    async def test_matches_own_job_type(self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent) -> None:
        handler = _started(mock_config)
        assert await handler.can_handle_event(event, {}) is True

    async def test_ignores_unknown_job_type(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        handler = _started(mock_config)
        other = GenericCloudEvent(id="e", type="sessions.job.created.other", source="/s")
        assert await handler.can_handle_event(other, {}) is False


# ---------------------------------------------------------------------------
# on_startup — agent_id resolution
# ---------------------------------------------------------------------------


class TestStartup:
    async def test_reads_agent_id_from_config(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        handler = _started(mock_config)
        await handler.on_startup()
        assert handler._agent_id == "test-agent"

    async def test_missing_agent_id_raises(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = {}
        handler = _Handler()
        with pytest.raises(ValueError, match="agent_id"):
            await handler.on_startup()


# ---------------------------------------------------------------------------
# Happy path — full lifecycle
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_runs_full_lifecycle(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        session_id: UUID,
        job_id: UUID,
    ) -> None:
        handler = _started(mock_config)
        await handler.on_startup()

        result = await handler.handle_event(event, context)

        assert result is None
        api_client.get_job_detail.assert_awaited_once_with(session_id, job_id, "sk-test")
        api_client.start_job.assert_awaited_once_with(session_id, job_id, "test-agent", "sk-test")
        assert handler.process_calls == 1
        api_client.complete_job.assert_awaited_once()
        # result payload is the dumped RESULT_MODEL
        _, kwargs = api_client.complete_job.call_args
        assert kwargs["result"] == {"ok": True}
        api_client.cancel_job.assert_not_awaited()
        assert job_id in handler._seen
        assert job_id not in handler._in_flight

    async def test_get_job_detail_runs_before_start_job(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        calls: list[str] = []
        api_client.get_job_detail = AsyncMock(side_effect=lambda *a, **k: calls.append("get") or {"payload": {"name": "x"}})
        api_client.start_job = AsyncMock(side_effect=lambda *a, **k: calls.append("start") or {})
        handler = _started(mock_config)
        await handler.on_startup()
        await handler.handle_event(event, context)
        assert calls == ["get", "start"]


# ---------------------------------------------------------------------------
# Idempotency — two-stage (AC-3 / analyser#13 AC-5)
# ---------------------------------------------------------------------------


class TestIdempotency:
    async def test_replayed_duplicate_after_start_is_noop(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        handler = _started(mock_config)
        await handler.on_startup()

        await handler.handle_event(event, context)
        # Second delivery of the same job_id is a no-op.
        await handler.handle_event(event, context)

        assert handler.process_calls == 1
        api_client.start_job.assert_awaited_once()
        api_client.complete_job.assert_awaited_once()

    async def test_concurrent_duplicate_is_noop(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        handler = _started(mock_config)
        await handler.on_startup()

        # Simulate a duplicate arriving while the first is mid-flight: pre-seed the
        # in-flight guard, then a fresh delivery for the same id must no-op.
        handler._in_flight.add(job_id)
        result = await handler.handle_event(event, context)

        assert result is None
        assert handler.process_calls == 0
        api_client.get_job_detail.assert_not_awaited()
        api_client.start_job.assert_not_awaited()

    async def test_transient_get_job_detail_failure_then_duplicate_proceeds(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        handler = _started(mock_config)
        await handler.on_startup()

        api_client.get_job_detail = AsyncMock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)

        # id stranded in neither set -> a later replay can proceed.
        assert job_id not in handler._in_flight
        assert job_id not in handler._seen

        api_client.get_job_detail = AsyncMock(return_value={"payload": {"name": "alice"}})
        await handler.handle_event(event, context)
        api_client.start_job.assert_awaited_once()
        assert handler.process_calls == 1

    async def test_transient_start_job_failure_then_duplicate_proceeds(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        handler = _started(mock_config)
        await handler.on_startup()

        api_client.start_job = AsyncMock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)

        assert job_id not in handler._in_flight
        assert job_id not in handler._seen

        api_client.start_job = AsyncMock(return_value={})
        await handler.handle_event(event, context)
        assert handler.process_calls == 1
        api_client.complete_job.assert_awaited_once()


# ---------------------------------------------------------------------------
# Payload validation -> cancel (AC-3)
# ---------------------------------------------------------------------------


class TestPayloadValidation:
    async def test_invalid_payload_cancels_and_does_not_start(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        session_id: UUID,
        job_id: UUID,
    ) -> None:
        api_client.get_job_detail = AsyncMock(return_value={"payload": {"wrong": "field"}})
        handler = _started(mock_config)
        await handler.on_startup()

        result = await handler.handle_event(event, context)

        assert result is None
        api_client.start_job.assert_not_awaited()
        assert handler.process_calls == 0
        api_client.cancel_job.assert_awaited_once()
        _, kwargs = api_client.cancel_job.call_args
        assert "reason" in kwargs


# ---------------------------------------------------------------------------
# process() error -> status mapping (AC-3)
# ---------------------------------------------------------------------------


class TestProcessErrorMapping:
    async def test_value_error_completes_with_failed_result(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise ValueError("bad business input")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        result = await handler.handle_event(event, context)

        assert result is None
        api_client.complete_job.assert_awaited_once()
        _, kwargs = api_client.complete_job.call_args
        assert kwargs["result"]["status"] == "failed"
        assert "bad business input" in kwargs["result"]["error"]
        api_client.cancel_job.assert_not_awaited()

    async def test_generic_exception_completes_with_failed_result(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise RuntimeError("kaboom")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        await handler.handle_event(event, context)

        api_client.complete_job.assert_awaited_once()
        _, kwargs = api_client.complete_job.call_args
        assert kwargs["result"]["status"] == "failed"

    async def test_oserror_raises_retryable_and_leaves_pending(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise OSError("disk gone")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)

        api_client.complete_job.assert_not_awaited()
        api_client.cancel_job.assert_not_awaited()

    async def test_invalid_event_error_from_process_cancels(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise InvalidEventError(status="bad", reason="unprocessable")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        result = await handler.handle_event(event, context)

        assert result is None
        api_client.cancel_job.assert_awaited_once()
        api_client.complete_job.assert_not_awaited()

    async def test_retryable_from_process_propagates(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise RetryableHandlerError(status="busy", reason="try later")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)
        api_client.complete_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# complete_job retry / exhaustion (AC-3)
# ---------------------------------------------------------------------------


class TestCompleteRetry:
    async def test_complete_retries_then_succeeds(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        api_client.complete_job = AsyncMock(side_effect=[httpx.ConnectError("x"), httpx.ConnectError("y"), {}])
        handler = _started(mock_config)
        await handler.on_startup()

        await handler.handle_event(event, context)

        assert api_client.complete_job.await_count == 3

    async def test_complete_exhaustion_raises_retryable(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        api_client.complete_job = AsyncMock(side_effect=httpx.ConnectError("always"))
        handler = _started(mock_config)
        await handler.on_startup()

        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)
        assert api_client.complete_job.await_count == 3


# ---------------------------------------------------------------------------
# HTTP status errors must propagate raw, NOT be wrapped as RetryableHandlerError.
# SessionsBus catches RetryableHandlerError *before* httpx.HTTPStatusError, so
# wrapping a 403 would swallow its session-key-refresh-and-retry recovery.
# ---------------------------------------------------------------------------


class TestHttpStatusErrorPropagation:
    async def test_get_job_detail_403_propagates_unwrapped(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        api_client.get_job_detail = AsyncMock(side_effect=_http_status_error(403))
        handler = _started(mock_config)
        await handler.on_startup()

        with pytest.raises(httpx.HTTPStatusError):
            await handler.handle_event(event, context)
        # Not started, and the id is stranded in neither set so SessionsBus can retry.
        api_client.start_job.assert_not_awaited()
        assert job_id not in handler._in_flight
        assert job_id not in handler._seen

    async def test_start_job_403_propagates_unwrapped(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        api_client.start_job = AsyncMock(side_effect=_http_status_error(403))
        handler = _started(mock_config)
        await handler.on_startup()

        with pytest.raises(httpx.HTTPStatusError):
            await handler.handle_event(event, context)
        assert job_id not in handler._in_flight
        assert job_id not in handler._seen

    async def test_complete_job_status_error_propagates_without_retry(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        api_client.complete_job = AsyncMock(side_effect=_http_status_error(403))
        handler = _started(mock_config)
        await handler.on_startup()

        with pytest.raises(httpx.HTTPStatusError):
            await handler.handle_event(event, context)
        # Status errors are not transient — no pointless retry loop.
        assert api_client.complete_job.await_count == 1


# ---------------------------------------------------------------------------
# CriticalHandlerError must keep its restart intent (not be neutralised into a
# complete-with-error result by the generic Exception bucket).
# ---------------------------------------------------------------------------


class TestCriticalHandlerError:
    async def test_critical_error_propagates(
        self, mock_config: MagicMock, mock_registry: MagicMock, event: GenericCloudEvent, context: dict[str, Any], api_client: MagicMock
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise CriticalHandlerError(status="fatal", reason="restart me")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        with pytest.raises(CriticalHandlerError):
            await handler.handle_event(event, context)
        api_client.complete_job.assert_not_awaited()
        api_client.cancel_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# Terminal-only seen-set: a job that STARTED but did not reach a terminal state
# (post-start retryable/critical failure) must stay out of `_seen`, so it is
# eligible for redelivery rather than silently ignored. `_seen` is populated
# only on terminal outcomes (complete / cancel / error-result-complete).
# ---------------------------------------------------------------------------


class TestTerminalSeenSemantics:
    async def test_retryable_from_process_leaves_job_unseen(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise RetryableHandlerError(status="busy", reason="later")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)
        api_client.start_job.assert_awaited_once()
        assert job_id not in handler._seen
        assert job_id not in handler._in_flight

    async def test_oserror_from_process_leaves_job_unseen(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise OSError("disk gone")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)
        assert job_id not in handler._seen

    async def test_timeout_error_from_process_leaves_job_unseen(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise TimeoutError("slow")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)
        assert job_id not in handler._seen

    async def test_critical_from_process_leaves_job_unseen(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise CriticalHandlerError(status="fatal", reason="restart")

        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        with pytest.raises(CriticalHandlerError):
            await handler.handle_event(event, context)
        assert job_id not in handler._seen

    async def test_complete_exhaustion_leaves_job_unseen(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        api_client.complete_job = AsyncMock(side_effect=httpx.ConnectError("always"))
        handler = _started(mock_config)
        await handler.on_startup()

        with pytest.raises(RetryableHandlerError):
            await handler.handle_event(event, context)
        assert job_id not in handler._seen

    async def test_terminal_outcomes_populate_seen(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        # Successful completion is terminal -> seen.
        handler = _started(mock_config)
        await handler.on_startup()
        await handler.handle_event(event, context)
        assert job_id in handler._seen

    async def test_cancel_is_terminal_and_seen(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        api_client.get_job_detail = AsyncMock(return_value={"payload": {"wrong": "field"}})
        handler = _started(mock_config)
        await handler.on_startup()
        await handler.handle_event(event, context)
        assert job_id in handler._seen
        # Replay of a cancelled job is a no-op (no second cancel).
        await handler.handle_event(event, context)
        api_client.cancel_job.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error-result completion shares the retry helper with the success path.
# ---------------------------------------------------------------------------


class TestErrorResultCompletionRetry:
    async def test_error_result_completion_retries_transient(
        self,
        mock_config: MagicMock,
        mock_registry: MagicMock,
        event: GenericCloudEvent,
        context: dict[str, Any],
        api_client: MagicMock,
        job_id: UUID,
    ) -> None:
        async def boom(_p: Any, _c: Any) -> _Result:
            raise ValueError("bad input")

        # First complete attempt fails transiently, second succeeds.
        api_client.complete_job = AsyncMock(side_effect=[httpx.ConnectError("x"), {}])
        handler = _Handler(process_impl=boom)
        mock_config.get.return_value = {"agent_id": "test-agent"}
        await handler.on_startup()

        await handler.handle_event(event, context)

        assert api_client.complete_job.await_count == 2
        _, kwargs = api_client.complete_job.call_args
        assert kwargs["result"]["status"] == "failed"
        assert job_id in handler._seen
