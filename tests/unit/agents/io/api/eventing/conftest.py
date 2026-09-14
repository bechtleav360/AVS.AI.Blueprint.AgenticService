"""Shared fixtures for eventing unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.io.api.eventing.nats import NatsEventing
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.models.result import ProcessingResult, ProcessingStatus


@pytest.fixture
def cloud_event() -> CloudEvent:
    """Minimal valid CloudEvent for publish/handle tests."""
    return CloudEvent(id="evt-001", type="test.event", source="test-source")


@pytest.fixture
def processed_result() -> ProcessingResult:
    """A ProcessingResult with PROCESSED status."""
    return ProcessingResult(request_id="req-1", status=ProcessingStatus.PROCESSED)


@pytest.fixture
def unhandled_result() -> ProcessingResult:
    """A ProcessingResult with NO_HANDLER_FOUND status."""
    return ProcessingResult(
        request_id="req-2",
        status=ProcessingStatus.NO_HANDLER_FOUND,
        message="no handler",
    )


@pytest.fixture
def dapr_eventing(mock_registry: MagicMock, mock_config: MagicMock) -> DaprEventing:
    """DaprEventing instance with a mocked registry and a config that yields its defaults.

    The default ``side_effect`` returns whatever default the caller passed, so component
    code sees real defaults instead of a truthy MagicMock. Tests that need a specific
    value replace the ``side_effect``.
    """
    mock_config.get.side_effect = lambda key, default=None: default
    return DaprEventing()


@pytest.fixture
def nats_eventing(mock_registry: MagicMock) -> NatsEventing:
    """NatsEventing instance with a mocked registry."""
    return NatsEventing()


@pytest.fixture
def connected_nats_eventing(nats_eventing: NatsEventing) -> NatsEventing:
    """NatsEventing with _client pre-set to an async-capable mock."""
    mock_client = MagicMock()
    mock_client.subscribe = AsyncMock()
    mock_client.publish = AsyncMock()
    nats_eventing._client = mock_client
    return nats_eventing
