"""Unit tests for SessionsBus."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from httpx_sse import SSEError

from blueprint.agents.io.api.eventing.sessions_bus import SessionsBus
from blueprint.agents.models.errors import InvalidEventError, RetryableHandlerError
from blueprint.agents.models.result import ProcessingResult, ProcessingStatus
from blueprint.agents.models.sessions import JobNotification

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_sessions_config(
    *,
    base_url: str | None = "http://sessions-svc",
    agent_id: str | None = "agent-001",
    api_key: str | None = "secret",
) -> dict:
    return {
        "base_url": base_url,
        "agent_id": agent_id,
        "api_key": api_key,
        "agent_type": "transcription",
        "capabilities": ["transcribe"],
        "max_concurrent_jobs": 5,
        "job_timeout_seconds": 60,
        "sse_reconnect_delay_seconds": 2,
        "sse_max_reconnect_attempts": 3,
    }


@pytest.fixture
def sessions_bus(mock_registry: MagicMock) -> SessionsBus:
    """SessionsBus instance with an injected mock registry."""
    return SessionsBus()


@pytest.fixture
def started_sessions_bus(sessions_bus: SessionsBus) -> SessionsBus:
    """SessionsBus with service clients pre-set (simulates post-startup state)."""
    sessions_bus._api_client = MagicMock()
    sessions_bus._api_client.cancel_job = AsyncMock()
    sessions_bus._key_provider = MagicMock()
    sessions_bus._key_provider.get_session_key = AsyncMock(return_value="test-session-key")
    sessions_bus._key_provider.invalidate_cache = MagicMock()
    return sessions_bus


@pytest.fixture
def notification() -> JobNotification:
    return JobNotification(
        session_id=uuid4(),
        job_id=uuid4(),
        job_type="transcription",
        created_at="2024-01-01T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# on_startup
# ---------------------------------------------------------------------------


class TestOnStartup:
    async def test_raises_when_sessions_service_config_missing(self, sessions_bus: SessionsBus, mock_config: MagicMock) -> None:
        mock_config.get.return_value = None
        with pytest.raises(ValueError, match="sessions_service configuration not found"):
            await sessions_bus.on_startup()

    async def test_raises_when_base_url_missing(self, sessions_bus: SessionsBus, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = _make_sessions_config(base_url=None)
        with pytest.raises(ValueError, match="base_url is required"):
            await sessions_bus.on_startup()

    async def test_raises_when_agent_id_missing(self, sessions_bus: SessionsBus, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = _make_sessions_config(agent_id=None)
        with pytest.raises(ValueError, match="agent_id is required"):
            await sessions_bus.on_startup()

    async def test_raises_when_api_key_missing(self, sessions_bus: SessionsBus, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = _make_sessions_config(api_key=None)
        with pytest.raises(ValueError, match="api_key is required"):
            await sessions_bus.on_startup()

    async def test_skips_if_already_started(self, sessions_bus: SessionsBus, mock_config: MagicMock) -> None:
        mock_task = MagicMock(spec=asyncio.Task)
        mock_task.done.return_value = False
        sessions_bus._sse_task = mock_task

        await sessions_bus.on_startup()

        mock_config.get.assert_not_called()

    async def test_creates_sse_task_on_success(self, sessions_bus: SessionsBus, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = _make_sessions_config()
        mock_registry.get_service.return_value = MagicMock()

        with patch.object(sessions_bus, "_consume_sse_stream", new=AsyncMock()):
            await sessions_bus.on_startup()

        assert sessions_bus._sse_task is not None
        sessions_bus._sse_task.cancel()


# ---------------------------------------------------------------------------
# on_shutdown
# ---------------------------------------------------------------------------


class TestOnShutdown:
    async def test_no_op_when_no_task(self, sessions_bus: SessionsBus) -> None:
        assert sessions_bus._sse_task is None
        await sessions_bus.on_shutdown()  # must not raise

    async def test_cancels_running_task(self, sessions_bus: SessionsBus) -> None:
        sessions_bus._sse_task = asyncio.create_task(asyncio.sleep(999))

        await sessions_bus.on_shutdown()

        assert sessions_bus._sse_task.done()


# ---------------------------------------------------------------------------
# _convert_to_cloud_event
# ---------------------------------------------------------------------------


class TestConvertToCloudEvent:
    def _n(self, **overrides) -> JobNotification:
        base = {
            "session_id": uuid4(),
            "job_id": uuid4(),
            "job_type": "transcription",
            "created_at": "2024-01-01T00:00:00Z",
        }
        base.update(overrides)
        return JobNotification(**base)

    def test_event_type_includes_job_type(self, sessions_bus: SessionsBus) -> None:
        event = sessions_bus._convert_to_cloud_event(self._n(job_type="analysis"))
        assert event.type == "sessions.job.created.analysis"

    def test_event_id_is_job_id(self, sessions_bus: SessionsBus) -> None:
        job_id = uuid4()
        event = sessions_bus._convert_to_cloud_event(self._n(job_id=job_id))
        assert event.id == str(job_id)

    def test_subject_is_session_id(self, sessions_bus: SessionsBus) -> None:
        session_id = uuid4()
        event = sessions_bus._convert_to_cloud_event(self._n(session_id=session_id))
        assert event.subject == str(session_id)

    def test_source_is_sessions_service(self, sessions_bus: SessionsBus) -> None:
        event = sessions_bus._convert_to_cloud_event(self._n())
        assert event.source == "/sessions-service"

    def test_data_payload_contains_job_fields(self, sessions_bus: SessionsBus) -> None:
        n = self._n(job_type="analysis")
        event = sessions_bus._convert_to_cloud_event(n)
        assert event.data["job_type"] == "analysis"
        assert event.data["session_id"] == str(n.session_id)


# ---------------------------------------------------------------------------
# _process_job_notification — error branches
# ---------------------------------------------------------------------------


class TestProcessJobNotification:
    async def test_no_handler_found_is_logged(
        self,
        started_sessions_bus: SessionsBus,
        notification: JobNotification,
        mock_registry: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        result = ProcessingResult(
            request_id="r1",
            status=ProcessingStatus.NO_HANDLER_FOUND,
            message="no handler",
        )
        started_sessions_bus._dispatch_cloud_event = AsyncMock(return_value=result)  # type: ignore[method-assign]

        with caplog.at_level("WARNING"):
            await started_sessions_bus._process_job_notification(notification)

        assert "No handler found" in caplog.text

    async def test_invalid_event_error_cancels_job(
        self,
        started_sessions_bus: SessionsBus,
        notification: JobNotification,
    ) -> None:
        err = InvalidEventError(status="bad_data", reason="missing field")
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=err)  # type: ignore[method-assign]

        await started_sessions_bus._process_job_notification(notification)

        started_sessions_bus._api_client.cancel_job.assert_awaited_once()
        call_kwargs = started_sessions_bus._api_client.cancel_job.call_args.kwargs
        assert call_kwargs["job_id"] == notification.job_id

    async def test_invalid_event_error_cancel_failure_is_swallowed(
        self,
        started_sessions_bus: SessionsBus,
        notification: JobNotification,
    ) -> None:
        started_sessions_bus._dispatch_cloud_event = AsyncMock(  # type: ignore[method-assign]
            side_effect=InvalidEventError(status="bad", reason="reason")
        )
        started_sessions_bus._api_client.cancel_job = AsyncMock(side_effect=RuntimeError("cancel failed"))

        # Should not raise — cancel failures are swallowed
        await started_sessions_bus._process_job_notification(notification)

    async def test_retryable_error_is_logged_not_raised(
        self,
        started_sessions_bus: SessionsBus,
        notification: JobNotification,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        err = RetryableHandlerError(status="transient", reason="downstream unavailable")
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=err)  # type: ignore[method-assign]

        with caplog.at_level("WARNING"):
            await started_sessions_bus._process_job_notification(notification)

        assert "Job remains pending" in caplog.text

    async def test_403_invalidates_cache_and_retries(self, started_sessions_bus: SessionsBus, notification: JobNotification) -> None:
        response_mock = MagicMock()
        response_mock.status_code = 403
        http_err = httpx.HTTPStatusError("403", request=MagicMock(), response=response_mock)
        processed = ProcessingResult(request_id="r", status=ProcessingStatus.PROCESSED)
        # First dispatch raises 403; the retry (same seam) succeeds.
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=[http_err, processed])  # type: ignore[method-assign]

        await started_sessions_bus._process_job_notification(notification)

        started_sessions_bus._key_provider.invalidate_cache.assert_called_once()
        assert started_sessions_bus._dispatch_cloud_event.await_count == 2

    async def test_403_retry_failure_propagates_invalid_event_error(
        self, started_sessions_bus: SessionsBus, notification: JobNotification
    ) -> None:
        response_mock = MagicMock()
        response_mock.status_code = 403
        http_err = httpx.HTTPStatusError("403", request=MagicMock(), response=response_mock)
        started_sessions_bus._dispatch_cloud_event = AsyncMock(  # type: ignore[method-assign]
            side_effect=[http_err, RuntimeError("still broken")]
        )
        with pytest.raises(InvalidEventError, match="Session key invalid"):
            await started_sessions_bus._process_job_notification(notification)

    async def test_non_403_http_error_propagates(
        self,
        started_sessions_bus: SessionsBus,
        notification: JobNotification,
    ) -> None:
        """Non-403 HTTPStatusError is re-raised and escapes _process_job_notification.

        The `else: raise` inside `except httpx.HTTPStatusError` re-raises the original
        exception. Since it is executed inside an except clause, it propagates outside
        the entire try/except block (peer except handlers are not consulted).
        """
        response_mock = MagicMock()
        response_mock.status_code = 500
        http_err = httpx.HTTPStatusError("500", request=MagicMock(), response=response_mock)
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=http_err)  # type: ignore[method-assign]

        with pytest.raises(httpx.HTTPStatusError):
            await started_sessions_bus._process_job_notification(notification)

    async def test_unexpected_error_is_logged_not_raised(
        self,
        started_sessions_bus: SessionsBus,
        notification: JobNotification,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        with caplog.at_level("ERROR"):
            await started_sessions_bus._process_job_notification(notification)

        assert "Unexpected error" in caplog.text


# ---------------------------------------------------------------------------
# _connect_and_consume — registration gate
# ---------------------------------------------------------------------------


class TestRegisterBeforeConnect:
    async def test_registers_before_opening_stream(self, started_sessions_bus: SessionsBus) -> None:
        bus = started_sessions_bus
        bus._base_url = "http://sessions-svc"
        bus._agent_id = "agent-001"
        bus._agent_type = "transcription"
        bus._capabilities = ["transcribe"]
        bus._api_key = "secret"
        bus._api_client.register_agent = AsyncMock(side_effect=RuntimeError("register-first"))

        with patch("blueprint.agents.io.api.eventing.sessions_bus.aconnect_sse") as mock_sse:
            with pytest.raises(RuntimeError, match="register-first"):
                await bus._connect_and_consume()
            mock_sse.assert_not_called()  # stream is never opened when registration fails

        bus._api_client.register_agent.assert_awaited_once_with(
            agent_id="agent-001", agent_type="transcription", capabilities=["transcribe"]
        )


# ---------------------------------------------------------------------------
# _dispatch_sse_event
# ---------------------------------------------------------------------------


class TestDispatchSseEvent:
    def test_keepalive_message_frame_is_debug_not_warning(self, sessions_bus: SessionsBus, caplog: pytest.LogCaptureFixture) -> None:
        sse = SimpleNamespace(event="message", data="")
        with caplog.at_level("DEBUG"):
            sessions_bus._dispatch_sse_event(sse)
        assert "keepalive" in caplog.text.lower()
        assert "Unknown SSE event type" not in caplog.text

    def test_named_unknown_event_with_payload_warns(self, sessions_bus: SessionsBus, caplog: pytest.LogCaptureFixture) -> None:
        sse = SimpleNamespace(event="surprise", data="{}")
        with caplog.at_level("WARNING"):
            sessions_bus._dispatch_sse_event(sse)
        assert "Unknown SSE event type: surprise" in caplog.text

    async def test_job_created_creates_tracked_task(self, started_sessions_bus: SessionsBus) -> None:
        # async so a running event loop exists for asyncio.create_task; the assertion runs
        # before the loop yields to the scheduled coroutine, so the task is still tracked.
        started_sessions_bus._handle_job_notification = AsyncMock()  # type: ignore[method-assign]
        payload = (
            '{"session_id": "00000000-0000-0000-0000-000000000001", ' '"job_id": "00000000-0000-0000-0000-000000000002", "job_type": "t"}'
        )
        sse = SimpleNamespace(event="job_created", data=payload)
        started_sessions_bus._dispatch_sse_event(sse)
        assert len(started_sessions_bus._inflight_tasks) == 1

    def test_malformed_job_payload_is_logged_and_skipped(self, started_sessions_bus: SessionsBus, caplog: pytest.LogCaptureFixture) -> None:
        sse = SimpleNamespace(event="job_created", data='{"missing": "ids"}')
        with caplog.at_level("ERROR"):
            started_sessions_bus._dispatch_sse_event(sse)
        assert "Error processing SSE event" in caplog.text
        assert len(started_sessions_bus._inflight_tasks) == 0

    def test_message_event_with_data_warns(self, sessions_bus: SessionsBus, caplog: pytest.LogCaptureFixture) -> None:
        # A `message` frame WITH a payload is not a keepalive — it should still warn.
        sse = SimpleNamespace(event="message", data='{"x": 1}')
        with caplog.at_level("WARNING"):
            sessions_bus._dispatch_sse_event(sse)
        assert "Unknown SSE event type: message" in caplog.text


# ---------------------------------------------------------------------------
# on_shutdown — drain + unregister
# ---------------------------------------------------------------------------


class TestShutdownDrainAndUnregister:
    async def test_unregisters_after_draining(self, started_sessions_bus: SessionsBus) -> None:
        bus = started_sessions_bus
        bus._agent_id = "agent-001"
        bus._api_client.unregister_agent = AsyncMock()

        async def _job() -> None:
            await asyncio.sleep(0.01)

        task = asyncio.create_task(_job())
        bus._inflight_tasks.add(task)
        task.add_done_callback(bus._inflight_tasks.discard)

        await bus.on_shutdown()

        assert task.done()
        bus._api_client.unregister_agent.assert_awaited_once_with("agent-001")

    async def test_drain_timeout_cancels_and_still_unregisters(self, started_sessions_bus: SessionsBus) -> None:
        bus = started_sessions_bus
        bus._agent_id = "agent-001"
        bus._job_timeout = 0  # force immediate drain timeout
        bus._api_client.unregister_agent = AsyncMock()

        async def _slow_job() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(_slow_job())
        bus._inflight_tasks.add(task)
        task.add_done_callback(bus._inflight_tasks.discard)

        await bus.on_shutdown()

        assert task.cancelled()
        bus._api_client.unregister_agent.assert_awaited_once()

    async def test_unregister_failure_does_not_raise(self, started_sessions_bus: SessionsBus) -> None:
        bus = started_sessions_bus
        bus._agent_id = "agent-001"
        bus._api_client.unregister_agent = AsyncMock(side_effect=RuntimeError("boom"))
        # on_shutdown must never propagate a cleanup failure.
        await bus.on_shutdown()


# ---------------------------------------------------------------------------
# _connect_and_consume — end-to-end register/connect lifecycle
# ---------------------------------------------------------------------------


class _EmptyAsyncIter:
    """An async iterator that yields no SSE events (a clean, immediately-closed stream)."""

    def __aiter__(self) -> "_EmptyAsyncIter":
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _RaisingAsyncIter:
    """An async iterator whose first iteration raises (simulates a rejected stream)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __aiter__(self) -> "_RaisingAsyncIter":
        return self

    async def __anext__(self):
        raise self._exc


def _mock_sse_context(event_source: MagicMock) -> MagicMock:
    """Build an async-context-manager stand-in for aconnect_sse(...) yielding event_source."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=event_source)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _connectable_bus(bus: SessionsBus) -> SessionsBus:
    bus._base_url = "http://sessions-svc"
    bus._agent_id = "agent-001"
    bus._agent_type = "transcription"
    bus._capabilities = ["transcribe"]
    bus._api_key = "secret"
    return bus


class TestConnectLifecycle:
    async def test_reconnect_re_registers(self, started_sessions_bus: SessionsBus) -> None:
        # The reconnect loop re-invokes _connect_and_consume; each invocation must re-register.
        bus = _connectable_bus(started_sessions_bus)
        bus._api_client.register_agent = AsyncMock(return_value=True)

        event_source = MagicMock()
        event_source.aiter_sse = lambda: _EmptyAsyncIter()

        with patch("blueprint.agents.io.api.eventing.sessions_bus.aconnect_sse", return_value=_mock_sse_context(event_source)):
            await bus._connect_and_consume()
            await bus._connect_and_consume()

        assert bus._api_client.register_agent.await_count == 2

    async def test_legacy_server_still_opens_stream(self, started_sessions_bus: SessionsBus) -> None:
        # A legacy (< v0.4.0) server returns 404 -> register_agent returns False; the stream still opens.
        bus = _connectable_bus(started_sessions_bus)
        bus._api_client.register_agent = AsyncMock(return_value=False)

        event_source = MagicMock()
        event_source.aiter_sse = lambda: _EmptyAsyncIter()

        with patch("blueprint.agents.io.api.eventing.sessions_bus.aconnect_sse", return_value=_mock_sse_context(event_source)) as mock_sse:
            await bus._connect_and_consume()

        mock_sse.assert_called_once()

    async def test_sse_rejection_logs_status_and_body(self, started_sessions_bus: SessionsBus, caplog: pytest.LogCaptureFixture) -> None:
        # A non-event-stream response (e.g. the 403 dispatch-gate JSON) raises SSEError; the real
        # status and body must be logged before the error propagates into the reconnect backoff.
        bus = _connectable_bus(started_sessions_bus)
        bus._api_client.register_agent = AsyncMock(return_value=True)

        response = MagicMock()
        response.status_code = 403
        response.aread = AsyncMock(return_value=b'{"detail": "agent not registered"}')
        event_source = MagicMock()
        event_source.response = response
        event_source.aiter_sse = lambda: _RaisingAsyncIter(SSEError("bad content-type"))

        with patch("blueprint.agents.io.api.eventing.sessions_bus.aconnect_sse", return_value=_mock_sse_context(event_source)):
            with caplog.at_level("ERROR"), pytest.raises(SSEError):
                await bus._connect_and_consume()

        assert "SSE stream rejected: status=403" in caplog.text
        assert "agent not registered" in caplog.text
