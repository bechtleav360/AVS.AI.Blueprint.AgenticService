"""Unit tests for SessionsBus."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from blueprint.agents.io.api.eventing.sessions_bus import SessionsBus
from blueprint.agents.models.errors import InvalidEventError, RetryableHandlerError
from blueprint.agents.models.result import ProcessingResult, ProcessingStatus

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
def job_data() -> dict:
    return {
        "session_id": str(uuid4()),
        "job_id": str(uuid4()),
        "job_type": "transcription",
        "created_at": "2024-01-01T00:00:00Z",
    }


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


def _job_data_with_time(**overrides: str) -> dict:
    """Build minimal job data that includes the required created_at timestamp."""
    base = {
        "session_id": str(uuid4()),
        "job_id": str(uuid4()),
        "job_type": "transcription",
        "created_at": "2024-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


class TestConvertToCloudEvent:
    def test_event_type_includes_job_type(self, sessions_bus: SessionsBus) -> None:
        data = _job_data_with_time(job_type="analysis")
        event = sessions_bus._convert_to_cloud_event(data)
        assert event.type == "sessions.job.created.analysis"

    def test_event_id_is_job_id(self, sessions_bus: SessionsBus) -> None:
        job_id = str(uuid4())
        data = _job_data_with_time(job_id=job_id)
        event = sessions_bus._convert_to_cloud_event(data)
        assert event.id == job_id

    def test_subject_is_session_id(self, sessions_bus: SessionsBus) -> None:
        session_id = str(uuid4())
        data = _job_data_with_time(session_id=session_id)
        event = sessions_bus._convert_to_cloud_event(data)
        assert event.subject == session_id

    def test_source_is_sessions_service(self, sessions_bus: SessionsBus) -> None:
        data = _job_data_with_time()
        event = sessions_bus._convert_to_cloud_event(data)
        assert event.source == "/sessions-service"

    def test_data_payload_equals_job_data(self, sessions_bus: SessionsBus) -> None:
        data = _job_data_with_time(job_type="analysis")
        event = sessions_bus._convert_to_cloud_event(data)
        assert event.data == data


# ---------------------------------------------------------------------------
# _process_job_notification — error branches
# ---------------------------------------------------------------------------


class TestProcessJobNotification:
    async def test_no_handler_found_is_logged(
        self,
        started_sessions_bus: SessionsBus,
        job_data: dict,
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
            await started_sessions_bus._process_job_notification(job_data)

        assert "No handler found" in caplog.text

    async def test_invalid_event_error_cancels_job(
        self,
        started_sessions_bus: SessionsBus,
        job_data: dict,
    ) -> None:
        err = InvalidEventError(status="bad_data", reason="missing field")
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=err)  # type: ignore[method-assign]

        await started_sessions_bus._process_job_notification(job_data)

        started_sessions_bus._api_client.cancel_job.assert_awaited_once()
        call_kwargs = started_sessions_bus._api_client.cancel_job.call_args.kwargs
        assert call_kwargs["job_id"] == UUID(job_data["job_id"])

    async def test_invalid_event_error_cancel_failure_is_swallowed(
        self,
        started_sessions_bus: SessionsBus,
        job_data: dict,
    ) -> None:
        started_sessions_bus._dispatch_cloud_event = AsyncMock(  # type: ignore[method-assign]
            side_effect=InvalidEventError(status="bad", reason="reason")
        )
        started_sessions_bus._api_client.cancel_job = AsyncMock(side_effect=RuntimeError("cancel failed"))

        # Should not raise — cancel failures are swallowed
        await started_sessions_bus._process_job_notification(job_data)

    async def test_retryable_error_is_logged_not_raised(
        self,
        started_sessions_bus: SessionsBus,
        job_data: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        err = RetryableHandlerError(status="transient", reason="downstream unavailable")
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=err)  # type: ignore[method-assign]

        with caplog.at_level("WARNING"):
            await started_sessions_bus._process_job_notification(job_data)

        assert "Job remains pending" in caplog.text

    async def test_403_invalidates_cache_and_retries(
        self,
        started_sessions_bus: SessionsBus,
        job_data: dict,
        mock_registry: MagicMock,
    ) -> None:
        response_mock = MagicMock()
        response_mock.status_code = 403
        http_err = httpx.HTTPStatusError("403", request=MagicMock(), response=response_mock)
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=http_err)  # type: ignore[method-assign]
        mock_registry.get_service.return_value.process_event = AsyncMock(
            return_value=ProcessingResult(request_id="r", status=ProcessingStatus.PROCESSED)
        )

        await started_sessions_bus._process_job_notification(job_data)

        started_sessions_bus._key_provider.invalidate_cache.assert_called_once()
        mock_registry.get_service.return_value.process_event.assert_awaited_once()

    async def test_403_retry_failure_propagates_invalid_event_error(
        self,
        started_sessions_bus: SessionsBus,
        job_data: dict,
        mock_registry: MagicMock,
    ) -> None:
        """Exceptions raised inside an except clause propagate outside all peer handlers.

        When the 403 retry fails, `raise InvalidEventError(...)` is executed inside
        the `except httpx.HTTPStatusError` block. Python does not route this new
        exception to other except clauses at the same level — it propagates out of
        _process_job_notification entirely.
        """
        response_mock = MagicMock()
        response_mock.status_code = 403
        http_err = httpx.HTTPStatusError("403", request=MagicMock(), response=response_mock)
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=http_err)  # type: ignore[method-assign]
        mock_registry.get_service.return_value.process_event = AsyncMock(side_effect=RuntimeError("still broken"))

        with pytest.raises(InvalidEventError, match="Session key invalid"):
            await started_sessions_bus._process_job_notification(job_data)

    async def test_non_403_http_error_propagates(
        self,
        started_sessions_bus: SessionsBus,
        job_data: dict,
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
            await started_sessions_bus._process_job_notification(job_data)

    async def test_unexpected_error_is_logged_not_raised(
        self,
        started_sessions_bus: SessionsBus,
        job_data: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        started_sessions_bus._dispatch_cloud_event = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        with caplog.at_level("ERROR"):
            await started_sessions_bus._process_job_notification(job_data)

        assert "Unexpected error" in caplog.text
