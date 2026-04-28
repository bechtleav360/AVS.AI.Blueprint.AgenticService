"""Unit tests for SessionsServiceHealthChecker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from blueprint.agents.io.api.actuators.health.sessions_health import SessionsServiceHealthChecker

_PATCH_TARGET = "blueprint.agents.io.api.actuators.health.sessions_health.httpx.AsyncClient"


@pytest.fixture
def checker() -> SessionsServiceHealthChecker:
    return SessionsServiceHealthChecker(
        base_url="http://sessions.local",
        api_key="test-api-key",
    )


@pytest.fixture
def mock_http(checker: SessionsServiceHealthChecker):
    """Patch httpx.AsyncClient with a default healthy 200 response.

    Tests that need error behaviour set mock_http.get.side_effect or
    mock_http.get.return_value.raise_for_status.side_effect directly.
    """
    ok_response = MagicMock()
    ok_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=ok_response)

    with patch(_PATCH_TARGET, return_value=mock_client):
        yield mock_client


# ---------------------------------------------------------------------------
# REST API check
# ---------------------------------------------------------------------------


class TestRestApiCheck:
    async def test_healthy_when_api_returns_200(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        result = await checker.health_check()
        assert result.status == "UP"

    async def test_rest_url_includes_health_endpoint(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        await checker.health_check()
        url = mock_http.get.call_args[0][0]
        assert url == "http://sessions.local/health"

    async def test_api_key_passed_in_header(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        await checker.health_check()
        headers = mock_http.get.call_args[1]["headers"]
        assert headers["X-Api-Key"] == "test-api-key"

    async def test_down_when_request_error(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        mock_http.get.side_effect = httpx.RequestError("connection refused")
        result = await checker.health_check()
        assert result.status == "DOWN"

    async def test_down_message_contains_error(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        mock_http.get.side_effect = httpx.RequestError("connection refused")
        result = await checker.health_check()
        assert "connection refused" in result.message

    async def test_down_details_show_disconnected(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        mock_http.get.side_effect = httpx.RequestError("unreachable")
        result = await checker.health_check()
        assert result.details["rest_api"] == "disconnected"


# ---------------------------------------------------------------------------
# SSE heartbeat tracking
# ---------------------------------------------------------------------------


class TestHeartbeatTracking:
    async def test_up_when_heartbeat_is_fresh(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        checker._last_heartbeat = datetime.now(UTC) - timedelta(seconds=10)
        result = await checker.health_check()
        assert result.status == "UP"
        assert result.details["sse_connection"] == "active"

    async def test_down_when_heartbeat_is_stale(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        checker._last_heartbeat = datetime.now(UTC) - timedelta(seconds=90)
        result = await checker.health_check()
        assert result.status == "DOWN"
        assert result.details["sse_connection"] == "stale"

    async def test_stale_message_contains_seconds_ago(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        checker._last_heartbeat = datetime.now(UTC) - timedelta(seconds=90)
        result = await checker.health_check()
        assert "ago" in result.message


class TestNoHeartbeat:
    async def test_up_when_no_heartbeat_yet(self, checker: SessionsServiceHealthChecker, mock_http: AsyncMock) -> None:
        result = await checker.health_check()
        assert result.status == "UP"
        assert result.details["sse_connection"] == "unknown"


# ---------------------------------------------------------------------------
# update_heartbeat
# ---------------------------------------------------------------------------


class TestUpdateHeartbeat:
    def test_sets_last_heartbeat(self, checker: SessionsServiceHealthChecker) -> None:
        assert checker._last_heartbeat is None
        checker.update_heartbeat()
        assert checker._last_heartbeat is not None

    def test_heartbeat_is_recent(self, checker: SessionsServiceHealthChecker) -> None:
        checker.update_heartbeat()
        age = (datetime.now(UTC) - checker._last_heartbeat).total_seconds()
        assert age < 1.0

    def test_heartbeat_updates_on_repeated_calls(self, checker: SessionsServiceHealthChecker) -> None:
        checker._last_heartbeat = datetime.now(UTC) - timedelta(seconds=30)
        first = checker._last_heartbeat
        checker.update_heartbeat()
        assert checker._last_heartbeat > first
