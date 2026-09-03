"""Unit tests for SessionsApiClient."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import httpx
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
# get_job_detail
# ---------------------------------------------------------------------------


class TestGetJobDetail:
    async def test_requests_correct_url(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.get_job_detail(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        url = mock_http_client.get.call_args[0][0]
        assert str(_SESSION_ID) in url
        assert str(_JOB_ID) in url

    async def test_passes_session_key_header(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.get_job_detail(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        headers = mock_http_client.get.call_args[1]["headers"]
        assert headers["X-Session-Key"] == _SESSION_KEY

    async def test_raises_when_not_initialized(self, api_client: SessionsApiClient) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.get_job_detail(_SESSION_ID, _JOB_ID, _SESSION_KEY)

    async def test_calls_raise_for_status(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.get_job_detail(_SESSION_ID, _JOB_ID, _SESSION_KEY)
        mock_http_client.get.return_value.raise_for_status.assert_called_once()


# ---------------------------------------------------------------------------
# start_job
# ---------------------------------------------------------------------------


class TestStartJob:
    async def test_posts_to_start_endpoint(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.start_job(_SESSION_ID, _JOB_ID, agent_id="agent-1", session_key=_SESSION_KEY)
        url = mock_http_client.post.call_args[0][0]
        assert "start" in url
        assert str(_JOB_ID) in url

    async def test_payload_contains_agent_id(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.start_job(_SESSION_ID, _JOB_ID, agent_id="my-agent", session_key=_SESSION_KEY)
        json_payload = mock_http_client.post.call_args[1]["json"]
        assert json_payload["agent_id"] == "my-agent"

    async def test_passes_session_key_header(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.start_job(_SESSION_ID, _JOB_ID, agent_id="agent-1", session_key=_SESSION_KEY)
        headers = mock_http_client.post.call_args[1]["headers"]
        assert headers["X-Session-Key"] == _SESSION_KEY

    async def test_raises_when_not_initialized(self, api_client: SessionsApiClient) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.start_job(_SESSION_ID, _JOB_ID, agent_id="agent-1", session_key=_SESSION_KEY)


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


# ---------------------------------------------------------------------------
# fail_job
# ---------------------------------------------------------------------------


class TestFailJob:
    async def test_posts_to_fail_endpoint(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.fail_job(_SESSION_ID, _JOB_ID, _SESSION_KEY, error={"message": "boom", "code": "ValueError"})
        url = mock_http_client.post.call_args[0][0]
        assert url.endswith(f"/sessions/{_SESSION_ID}/jobs/{_JOB_ID}/fail")

    async def test_error_wrapped_in_payload(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.fail_job(_SESSION_ID, _JOB_ID, _SESSION_KEY, error={"message": "boom", "code": "ValueError"})
        json_payload = mock_http_client.post.call_args[1]["json"]
        assert json_payload == {"error": {"message": "boom", "code": "ValueError"}}

    async def test_passes_session_key_header(self, started_api_client: SessionsApiClient, mock_http_client: AsyncMock) -> None:
        await started_api_client.fail_job(_SESSION_ID, _JOB_ID, _SESSION_KEY, error={"message": "boom"})
        headers = mock_http_client.post.call_args[1]["headers"]
        assert headers["X-Session-Key"] == _SESSION_KEY

    async def test_raises_when_not_initialized(self, api_client: SessionsApiClient) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.fail_job(_SESSION_ID, _JOB_ID, _SESSION_KEY, error={"message": "x"})


# ---------------------------------------------------------------------------
# register_agent
# ---------------------------------------------------------------------------


class TestRegisterAgent:
    async def test_posts_to_register_endpoint_with_body(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 201
        await started_api_client.register_agent("agent-1", "analyser", ["classify"])
        url = mock_http_client.post.call_args[0][0]
        payload = mock_http_client.post.call_args[1]["json"]
        assert url.endswith("/agents/register")
        assert payload == {"agent_id": "agent-1", "agent_type": "analyser", "capabilities": ["classify"]}

    async def test_201_returns_true(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 201
        assert await started_api_client.register_agent("a", "t", []) is True

    async def test_200_returns_true(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 200
        assert await started_api_client.register_agent("a", "t", []) is True

    async def test_404_returns_false_and_does_not_raise(self, started_api_client, mock_http_client, caplog) -> None:
        mock_http_client.post.return_value.status_code = 404
        with caplog.at_level("WARNING"):
            result = await started_api_client.register_agent("a", "t", [])
        assert result is False
        assert "legacy" in caplog.text.lower()
        mock_http_client.post.return_value.raise_for_status.assert_not_called()

    async def test_500_raises_and_logs_body(self, started_api_client, mock_http_client, caplog) -> None:
        resp = mock_http_client.post.return_value
        resp.status_code = 500
        resp.text = "internal error detail"
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("500", request=MagicMock(), response=resp)
        with caplog.at_level("ERROR"), pytest.raises(httpx.HTTPStatusError):
            await started_api_client.register_agent("a", "t", [])
        assert "internal error detail" in caplog.text

    async def test_optional_fields_included_when_given(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 201
        await started_api_client.register_agent("a", "t", [], version="1.2.3", metadata={"k": "v"})
        payload = mock_http_client.post.call_args[1]["json"]
        assert payload["version"] == "1.2.3"
        assert payload["metadata"] == {"k": "v"}

    async def test_agent_type_omitted_when_none(self, started_api_client, mock_http_client) -> None:
        mock_http_client.post.return_value.status_code = 201
        await started_api_client.register_agent("a", None, [])
        payload = mock_http_client.post.call_args[1]["json"]
        assert "agent_type" not in payload
        assert payload == {"agent_id": "a", "capabilities": []}

    async def test_raises_when_not_initialized(self, api_client) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.register_agent("a", "t", [])


# ---------------------------------------------------------------------------
# unregister_agent
# ---------------------------------------------------------------------------


class TestUnregisterAgent:
    async def test_deletes_agent_endpoint(self, started_api_client, mock_http_client) -> None:
        mock_http_client.delete.return_value.status_code = 204
        await started_api_client.unregister_agent("agent-1")
        url = mock_http_client.delete.call_args[0][0]
        assert url.endswith("/agents/agent-1")

    async def test_swallows_errors(self, started_api_client, mock_http_client, caplog) -> None:
        mock_http_client.delete.side_effect = httpx.ConnectError("boom")
        with caplog.at_level("WARNING"):
            await started_api_client.unregister_agent("agent-1")  # must not raise
        assert "unregister failed" in caplog.text.lower()

    async def test_swallows_uninitialized_client(self, api_client) -> None:
        await api_client.unregister_agent("agent-1")  # must not raise


# ---------------------------------------------------------------------------
# list_pending_jobs — reconnect catch-up
# ---------------------------------------------------------------------------


def _summary(job_id: str, job_type: str) -> dict:
    return {
        "id": job_id,
        "session_id": "00000000-0000-0000-0000-0000000000ff",
        "job_type": job_type,
        "status": "pending",
        "created_at": "2026-07-08T00:00:00Z",
        "updated_at": "2026-07-08T00:00:00Z",
    }


def _list_resp(payload: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


class TestListPendingJobs:
    async def test_queries_status_pending_once_per_capability(self, started_api_client, mock_http_client) -> None:
        mock_http_client.get = AsyncMock(side_effect=[_list_resp([_summary("j1", "a")]), _list_resp([_summary("j2", "b")])])

        jobs = await started_api_client.list_pending_jobs(["a", "b"])

        assert mock_http_client.get.await_count == 2
        # Every call targets /jobs with status=pending and one capability as job_type.
        seen_types = set()
        for call in mock_http_client.get.call_args_list:
            url = call[0][0]
            params = call[1]["params"]
            assert url.endswith("/jobs")
            assert params["status"] == "pending"
            seen_types.add(params["job_type"])
        assert seen_types == {"a", "b"}
        assert {j["id"] for j in jobs} == {"j1", "j2"}

    async def test_single_unfiltered_query_when_no_capabilities(self, started_api_client, mock_http_client) -> None:
        mock_http_client.get = AsyncMock(return_value=_list_resp([_summary("j1", "a")]))

        jobs = await started_api_client.list_pending_jobs([])

        assert mock_http_client.get.await_count == 1
        params = mock_http_client.get.call_args[1]["params"]
        assert params["status"] == "pending"
        assert "job_type" not in params
        assert [j["id"] for j in jobs] == ["j1"]

    async def test_merges_and_dedupes_by_id(self, started_api_client, mock_http_client) -> None:
        # A job returned under two capability queries appears once in the merged result.
        dup = _summary("dup", "a")
        mock_http_client.get = AsyncMock(side_effect=[_list_resp([dup]), _list_resp([dup, _summary("j2", "b")])])

        jobs = await started_api_client.list_pending_jobs(["a", "b"])

        ids = [j["id"] for j in jobs]
        assert sorted(ids) == ["dup", "j2"]

    async def test_calls_raise_for_status(self, started_api_client, mock_http_client) -> None:
        resp = _list_resp([])
        mock_http_client.get = AsyncMock(return_value=resp)
        await started_api_client.list_pending_jobs(["a"])
        resp.raise_for_status.assert_called_once()

    async def test_raises_when_not_initialized(self, api_client) -> None:
        with pytest.raises(ValueError, match="not initialized"):
            await api_client.list_pending_jobs(["a"])
