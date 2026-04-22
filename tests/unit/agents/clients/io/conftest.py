"""Shared fixtures for IO client unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.clients.io.dapr_client import DaprClient
from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.models.events import CloudEvent

_DAPR_CONFIG = {
    "dapr_url": "http://localhost:3500",
    "dapr_pubsub_name": "pubsub",
    "health_check_dapr": True,
}

_NATS_CONFIG = {
    "nats_url": "nats://localhost:4222",
    "nats_max_reconnect_attempts": 5,
    "nats_reconnect_time_wait": 2,
    "nats_use_jetstream": False,
    "nats_stream_name": "EVENTS",
    "nats_durable_name": "test-durable",
}


@pytest.fixture
def cloud_event() -> CloudEvent:
    """Return a minimal valid CloudEvent for publish tests."""
    return CloudEvent(id="test-event-id", type="test.event", source="test-source")


# ---------------------------------------------------------------------------
# Dapr
# ---------------------------------------------------------------------------


@pytest.fixture
def dapr_client(mock_config: MagicMock) -> DaprClient:
    mock_config.get.side_effect = lambda key, default=None: _DAPR_CONFIG.get(key, default)
    return DaprClient()


@pytest.fixture
def mock_httpx_client() -> MagicMock:
    """Return an async-mock httpx client with sensible defaults."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock.post = AsyncMock(return_value=mock_response)
    mock.get = AsyncMock(return_value=mock_response)
    mock.aclose = AsyncMock()
    return mock


@pytest.fixture
def connected_dapr_client(dapr_client: DaprClient, mock_httpx_client: MagicMock) -> DaprClient:
    """Return a DaprClient with _client already set, bypassing connect()."""
    dapr_client._client = mock_httpx_client
    return dapr_client


# ---------------------------------------------------------------------------
# NATS
# ---------------------------------------------------------------------------


@pytest.fixture
def nats_client(mock_config: MagicMock) -> NATSClient:
    mock_config.get.side_effect = lambda key, default=None: _NATS_CONFIG.get(key, default)
    return NATSClient()


@pytest.fixture
def mock_nats_core() -> MagicMock:
    """Return a mock NATS core client (no JetStream)."""
    mock = MagicMock()
    mock.is_closed = False
    mock.is_connected = True
    mock.connected_url = "nats://localhost:4222"
    mock.publish = AsyncMock()
    mock.subscribe = AsyncMock(return_value=MagicMock(unsubscribe=AsyncMock()))
    mock.close = AsyncMock()
    mock.jetstream = MagicMock(return_value=None)
    return mock


@pytest.fixture
def mock_nats_jetstream() -> tuple[MagicMock, MagicMock]:
    """Return a (nats_client_mock, jetstream_mock) pair with JetStream enabled."""
    mock_js = MagicMock()
    mock_js.subscribe = AsyncMock(return_value=MagicMock(unsubscribe=AsyncMock()))
    mock_js.publish = AsyncMock(return_value=MagicMock(seq=1))
    mock_js.add_stream = AsyncMock()

    mock_nc = MagicMock()
    mock_nc.is_closed = False
    mock_nc.is_connected = True
    mock_nc.connected_url = "nats://localhost:4222"
    mock_nc.publish = AsyncMock()
    mock_nc.close = AsyncMock()
    mock_nc.jetstream = MagicMock(return_value=mock_js)

    return mock_nc, mock_js


@pytest.fixture
def connected_nats_client(nats_client: NATSClient, mock_nats_core: MagicMock) -> NATSClient:
    """Return a NATSClient with _nats_client/_client already set (Core NATS)."""
    nats_client._nats_client = mock_nats_core
    nats_client._client = mock_nats_core
    return nats_client
