"""Unit tests for SessionsApiClient."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from blueprint.agents.services.sessions.api_client import SessionsApiClient

_SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
_JOB_ID = UUID("00000000-0000-0000-0000-000000000002")
_SESSION_KEY = "test-session-key"
_PATCH_TARGET = "blueprint.agents.services.sessions.api_client.httpx.AsyncClient"


# ---------------------------------------------------------------------------
# on_startup
# ---------------------------------------------------------------------------


class TestOnStartup:
    async def test_sets_base_url_and_api_key(self, api_client: SessionsApiClient, mock_config: MagicMock, sessions_config: dict) -> None:
        mock_config.get.return_value = sessions_config
        with patch(_PATCH_TARGET):
            await api_client.on_startup()
        assert api_client._base_url == "http://sessions.local:8000"
        assert api_client._api_key == "test-api-key"

    async def test_initializes_http_client(self, api_client: SessionsApiClient, mock_config: MagicMock, sessions_config: dict) -> None:
        mock_config.get.return_value = sessions_config
        with patch(_PATCH_TARGET) as mock_cls:
            await api_client.on_startup()
        mock_cls.assert_called_once()
        assert api_client._client is not None

    async def test_raises_when_sessions_service_config_missing(self, api_client: SessionsApiClient, mock_config: MagicMock) -> None:
        mock_config.get.return_value = None
        with pytest.raises(ValueError, match="sessions_service configuration not found"):
            await api_client.on_startup()

    async def test_raises_when_base_url_missing(self, api_client: SessionsApiClient, mock_config: MagicMock) -> None:
        mock_config.get.return_value = {"api_key": "key"}
        with pytest.raises(ValueError, match="base_url is required"):
            await api_client.on_startup()

    async def test_raises_when_api_key_missing(self, api_client: SessionsApiClient, mock_config: MagicMock) -> None:
        mock_config.get.return_value = {"base_url": "http://sessions.local:8000"}
        with pytest.raises(ValueError, match="api_key is required"):
            await api_client.on_startup()


# ---------------------------------------------------------------------------
# on_shutdown
# ---------------------------------------------------------------------------


class TestOnShutdown:
    async def test_closes_http_client(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.on_shutdown()
        mock_http_client.aclose.assert_awaited_once()

    async def test_noop_when_client_not_initialized(self, api_client: SessionsApiClient) -> None:
        await api_client.on_shutdown()  # Should not raise


# ---------------------------------------------------------------------------
# get_job_details
# ---------------------------------------------------------------------------


class TestGetJobDetails:
    async def test_requests_correct_url(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.get_job_details(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        url = mock_http_client.get.call_args[0][0]
        assert str(_SESSION_ID) in url
        assert str(_JOB_ID) in url

    async def test_passes_session_key_header(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.get_job_details(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        headers = mock_http_client.get.call_args[1]["headers"]
        assert headers["X-Session-Key"] == _SESSION_KEY

    async def test_raises_when_not_initialized(self, api_client: SessionsApiClient) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.get_job_details(_SESSION_ID, _JOB_ID, _SESSION_KEY)

    async def test_calls_raise_for_status(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.get_job_details(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        mock_http_client.get.return_value.raise_for_status.assert_called_once()


# ---------------------------------------------------------------------------
# start_job
# ---------------------------------------------------------------------------


class TestStartJob:
    async def test_posts_to_start_endpoint(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.start_job(_SESSION_ID, _JOB_ID, agent_id="agent-1")
        url = mock_http_client.post.call_args[0][0]
        assert "start" in url
        assert str(_JOB_ID) in url

    async def test_payload_contains_agent_id(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.start_job(_SESSION_ID, _JOB_ID, agent_id="my-agent")
        json_payload = mock_http_client.post.call_args[1]["json"]
        assert json_payload["agent_id"] == "my-agent"

    async def test_raises_when_not_initialized(self, api_client: SessionsApiClient) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.start_job(_SESSION_ID, _JOB_ID, agent_id="agent-1")


# ---------------------------------------------------------------------------
# complete_job
# ---------------------------------------------------------------------------


class TestCompleteJob:
    async def test_posts_to_complete_endpoint(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.complete_job(_SESSION_ID, _JOB_ID, _SESSION_KEY, result={"output": "done"})
        url = mock_http_client.post.call_args[0][0]
        assert "complete" in url

    async def test_passes_session_key_header(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.complete_job(_SESSION_ID, _JOB_ID, _SESSION_KEY, result={})
        headers = mock_http_client.post.call_args[1]["headers"]
        assert headers["X-Session-Key"] == _SESSION_KEY

    async def test_raises_when_not_initialized(self, api_client: SessionsApiClient) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.complete_job(_SESSION_ID, _JOB_ID, _SESSION_KEY, result={})


# ---------------------------------------------------------------------------
# cancel_job
# ---------------------------------------------------------------------------


class TestCancelJob:
    async def test_posts_to_cancel_endpoint(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.cancel_job(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        url = mock_http_client.post.call_args[0][0]
        assert "cancel" in url

    async def test_passes_session_key_header(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.cancel_job(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        headers = mock_http_client.post.call_args[1]["headers"]
        assert headers["X-Session-Key"] == _SESSION_KEY

    async def test_reason_included_in_payload_when_given(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.cancel_job(_SESSION_ID, _JOB_ID, _SESSION_KEY, reason="timeout")
        json_payload = mock_http_client.post.call_args[1]["json"]
        assert json_payload["reason"] == "timeout"

    async def test_empty_payload_when_no_reason(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.cancel_job(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        json_payload = mock_http_client.post.call_args[1]["json"]
        assert json_payload == {}

    async def test_raises_when_not_initialized(self, api_client: SessionsApiClient) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.cancel_job(_SESSION_ID, _JOB_ID, _SESSION_KEY)
