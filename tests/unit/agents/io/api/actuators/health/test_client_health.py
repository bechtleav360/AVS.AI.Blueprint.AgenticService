"""Unit tests for ClientHealthChecker."""

from unittest.mock import AsyncMock, MagicMock


from blueprint.agents.io.api.actuators.health.client_health import ClientHealthChecker
from blueprint.agents.models.api import ComponentHealth


def _make_client(status: str, message: str = "") -> MagicMock:
    """Return a mock ClientBase with predetermined health_check result."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.health_check = AsyncMock(return_value=ComponentHealth(status=status, message=message))
    return client


class TestClientHealthCheckerConnectBehavior:
    async def test_connect_is_called_before_health_check(self) -> None:
        client = _make_client("healthy", "ok")
        checker = ClientHealthChecker([client])
        await checker.health_check()
        client.connect.assert_awaited_once()

    async def test_connect_called_for_every_client(self) -> None:
        clients = [_make_client("healthy"), _make_client("healthy")]
        checker = ClientHealthChecker(clients)
        await checker.health_check()
        for c in clients:
            c.connect.assert_awaited_once()


class TestClientHealthCheckerAggregation:
    async def test_all_healthy_returns_healthy_status(self) -> None:
        clients = [_make_client("healthy", "conn ok"), _make_client("healthy", "conn ok")]
        checker = ClientHealthChecker(clients)
        result = await checker.health_check()
        assert result.status == "healthy"

    async def test_one_unhealthy_returns_unhealthy_status(self) -> None:
        clients = [_make_client("healthy", "ok"), _make_client("unhealthy", "timeout")]
        checker = ClientHealthChecker(clients)
        result = await checker.health_check()
        assert result.status == "unhealthy"

    async def test_all_unhealthy_returns_unhealthy_status(self) -> None:
        clients = [_make_client("unhealthy", "refused"), _make_client("unhealthy", "timeout")]
        checker = ClientHealthChecker(clients)
        result = await checker.health_check()
        assert result.status == "unhealthy"

    async def test_unhealthy_message_contains_unhealthy_client_messages(self) -> None:
        clients = [_make_client("unhealthy", "refused")]
        checker = ClientHealthChecker(clients)
        result = await checker.health_check()
        assert "refused" in result.message

    async def test_mixed_result_message_contains_both_parts(self) -> None:
        clients = [_make_client("healthy", "ok"), _make_client("unhealthy", "down")]
        checker = ClientHealthChecker(clients)
        result = await checker.health_check()
        assert "down" in result.message
        assert "ok" in result.message

    async def test_empty_client_list_returns_healthy(self) -> None:
        checker = ClientHealthChecker([])
        result = await checker.health_check()
        assert result.status == "healthy"
