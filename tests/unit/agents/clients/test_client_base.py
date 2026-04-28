"""Unit tests for ClientBase lifecycle and lazy-connection logic."""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from blueprint.agents.clients.client_base import ClientBase
from blueprint.agents.models.api import ComponentHealth
from blueprint.agents.models.events import CloudEvent


class _ConcreteClient(ClientBase):
    """Minimal concrete ClientBase for testing the base-class logic."""

    def _is_connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        self._client = MagicMock()

    async def close(self) -> None:
        self._client = None

    async def subscribe(self, topic: str, callback: Callable[[CloudEvent[Any]], Awaitable[None]]) -> None:
        pass

    async def publish(self, topic: str, event: CloudEvent[Any], routing_key: str | None = None) -> None:
        pass

    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(status="healthy")


@pytest.fixture
def client() -> _ConcreteClient:
    return _ConcreteClient()


class TestClientBaseLifecycle:
    async def test_on_startup_is_noop(self, client: _ConcreteClient) -> None:
        await client.on_startup()  # must not raise

    async def test_on_shutdown_delegates_to_close(self, client: _ConcreteClient) -> None:
        client._client = MagicMock()
        await client.on_shutdown()
        assert client._client is None


class TestClientBaseConnection:
    async def test_get_connected_client_connects_when_not_connected(self, client: _ConcreteClient) -> None:
        assert client._client is None
        result = await client._get_connected_client()
        assert client._client is not None
        assert result is client._client

    async def test_get_connected_client_skips_connect_when_already_connected(self, client: _ConcreteClient) -> None:
        existing = MagicMock()
        client._client = existing
        result = await client._get_connected_client()
        assert result is existing

    async def test_client_property_returns_coroutine_that_resolves_to_client(self, client: _ConcreteClient) -> None:
        resolved = await client.client
        assert resolved is client._client

    def test_client_initialises_as_none(self, client: _ConcreteClient) -> None:
        assert client._client is None
