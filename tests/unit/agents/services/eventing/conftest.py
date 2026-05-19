"""Shared fixtures for eventing service unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.models.config import EventPublishingConfig, TopicConfig
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.services.eventing.event_processing_service import EventProcessingService
from blueprint.agents.services.eventing.event_publishing_service import EventPublishingService


@pytest.fixture
def cloud_event() -> CloudEvent:
    """Minimal valid CloudEvent for eventing tests."""
    return CloudEvent(id="evt-001", type="test.event", source="test-source")


@pytest.fixture
def pub_config() -> EventPublishingConfig:
    """EventPublishingConfig with two topic mappings."""
    return EventPublishingConfig(
        topic_mapping={
            "test.event": TopicConfig(topic="test-topic"),
            "other.event": TopicConfig(topic="other-topic", routing_key="rk-1"),
        }
    )


@pytest.fixture
def mock_io_client() -> MagicMock:
    """Mock IOClientBase with async publish."""
    client = MagicMock()
    client.publish = AsyncMock()
    return client


@pytest.fixture
def event_publishing_service(
    mock_registry: MagicMock,
    mock_config: MagicMock,
    pub_config: EventPublishingConfig,
    mock_io_client: MagicMock,
) -> EventPublishingService:
    """EventPublishingService with _pub_config and _client pre-set (bypasses on_startup)."""
    # config.get() is called for app_name inside publish_event / publish_handler_event;
    # it must return a string or CloudEvent source validation will fail.
    mock_config.get.return_value = "test-agent"
    svc = EventPublishingService()
    svc._pub_config = pub_config
    svc._client = mock_io_client
    return svc


@pytest.fixture
def event_processing_service(mock_registry: MagicMock, mock_config: MagicMock) -> EventProcessingService:
    """EventProcessingService with mocked registry and config."""
    return EventProcessingService()
