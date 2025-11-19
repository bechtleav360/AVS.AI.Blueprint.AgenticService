"""Unit tests for EventPublishingService."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import textwrap

from blueprint.agents.config import Config
from blueprint.agents.models import CloudEvent
from blueprint.agents.models.config import EventPublishingConfig, TopicConfig
from blueprint.agents.services.event_publishing_service import EventPublishingService


class TestEventPublishingService:
    """Test suite for EventPublishingService."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = MagicMock(spec=Config)
        config.get.side_effect = lambda key, default=None: {
            "app_name": "test-agent",
            "dapr_http_port": 3500,
        }.get(key, default)

        config.get_event_publishing_config.return_value = EventPublishingConfig(
            default_pubsub_name="pubsub",
            topic_mapping={
                "agent.output.invoice.processed": TopicConfig(topic="invoice.processed"),
                "agent.output.document.classified": TopicConfig(topic="document.classified"),
                "agent.error.processing": TopicConfig(topic="agent.errors"),
                "agent.error.validation": TopicConfig(topic="agent.errors"),
                "agent.status.started": TopicConfig(topic="agent.status"),
                "agent.status.completed": TopicConfig(topic="agent.status"),
                "agent.status.failed": TopicConfig(topic="agent.status"),
            },
        )

        return config

    @pytest.fixture
    def service(self, mock_config):
        """Create an EventPublishingService instance."""
        return EventPublishingService(config=mock_config)

    def test_initialization(self, service, mock_config):
        """Test service initialization."""
        assert service._dapr_http_port == 3500
        assert service._dapr_base_url == "http://localhost:3500"
        assert service._default_pubsub_name == "pubsub"
        assert len(service._topic_mapping) == 7

    def test_topic_mapping_parsing_from_string(self):
        """Topic mapping should be parsed from string-based env override."""

        mapping_string = textwrap.dedent(
            """{
                'invoice.validated': { topic: 'test.connection', routing_key: 'valid' },
                'invoice.invalidated': { topic: 'test.connection', routing_key: 'invalid' },
                'invoice.analysis.error': { topic: 'test.connection', routing_key: 'error' }
            }"""
        )

        config = EventPublishingConfig(topic_mapping=mapping_string)

        assert config.topic_mapping["invoice.validated"].topic == "test.connection"
        assert config.topic_mapping["invoice.validated"].routing_key == "valid"
        assert config.topic_mapping["invoice.invalidated"].topic == "test.connection"
        assert config.topic_mapping["invoice.invalidated"].routing_key == "invalid"
        assert config.topic_mapping["invoice.analysis.error"].routing_key == "error"

    def test_topic_mapping_parsing_from_map_strings(self):
        """Topic mapping should be parsed from map[...] style env vars."""

        mapping_dict = {
            "ITEM_FILTERED_EVENT": "map[routing_key:filtered topic:test.connection]",
            "ITEM_FILTERED_EVENT_ERROR": "map[routing_key:error topic:test.connection]",
        }

        config = EventPublishingConfig(topic_mapping=mapping_dict)

        assert config.topic_mapping["ITEM_FILTERED_EVENT"].topic == "test.connection"
        assert config.topic_mapping["ITEM_FILTERED_EVENT"].routing_key == "filtered"
        assert config.topic_mapping["ITEM_FILTERED_EVENT_ERROR"].topic == "test.connection"
        assert config.topic_mapping["ITEM_FILTERED_EVENT_ERROR"].routing_key == "error"

    def test_get_topic_for_event_type(self, service):
        """Test getting topic for event type."""
        # Known event type
        topic = service.get_topic_for_event_type("agent.output.invoice.processed")
        assert topic == "invoice.processed"

        # Unknown event type
        topic = service.get_topic_for_event_type("unknown.event.type")
        assert topic is None

    def test_get_available_event_types(self, service):
        """Test getting list of available event types."""
        event_types = service.get_available_event_types()
        assert len(event_types) == 7
        assert "agent.output.invoice.processed" in event_types
        assert "agent.error.processing" in event_types
        assert "agent.status.completed" in event_types

    @pytest.mark.asyncio
    async def test_publish_event_success(self, service, mock_config):
        """Test successful event publication."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            event = CloudEvent(
                type="agent.output.invoice.processed",
                id="test-event-123",
                data={"invoice_id": "INV-123", "status": "processed"},
                source="/test/source",
            )
            result = await service.publish_event(event)

            assert result["status"] == "published"
            assert result["topic"] == "invoice.processed"
            assert result["pubsub_name"] == "pubsub"
            assert result["event_id"] == "test-event-123"

            # Verify the HTTP call
            mock_post = mock_client.return_value.__aenter__.return_value.post
            mock_post.assert_called_once()
            call_args = mock_post.call_args

            # Check URL
            assert call_args[0][0] == "http://localhost:3500/v1.0/publish/pubsub/invoice.processed"

            # Check payload
            payload = call_args[1]["json"]
            assert payload["specversion"] == "1.0"
            assert payload["type"] == "agent.output.invoice.processed"
            assert payload["source"] == "/test/source"
            assert payload["id"] == "test-event-123"
            assert payload["data"]["invoice_id"] == "INV-123"

            # Check headers
            assert call_args[1]["headers"]["Content-Type"] == "application/cloudevents+json"

    @pytest.mark.asyncio
    async def test_publish_event_with_explicit_topic(self, service):
        """Test publishing with explicit topic override."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            event = CloudEvent(type="custom.event.type", id="test-event-123", data={"key": "value"})
            result = await service.publish_event(event, topic="custom.topic")  # Explicit topic

            assert result["status"] == "published"
            assert result["topic"] == "custom.topic"

            # Verify URL uses explicit topic
            mock_post = mock_client.return_value.__aenter__.return_value.post
            call_args = mock_post.call_args
            assert "custom.topic" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_publish_event_with_explicit_pubsub(self, service):
        """Test publishing with explicit pubsub component."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            event = CloudEvent(type="agent.output.invoice.processed", id="test-event-123", data={"key": "value"})
            result = await service.publish_event(event, pubsub_name="custom-pubsub")

            assert result["pubsub_name"] == "custom-pubsub"

            # Verify URL uses custom pubsub
            mock_post = mock_client.return_value.__aenter__.return_value.post
            call_args = mock_post.call_args
            assert "custom-pubsub" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_publish_event_no_topic_mapping(self, service):
        """Test publishing event with no topic mapping raises error."""
        with pytest.raises(ValueError) as exc_info:
            event = CloudEvent(type="unknown.event.type", id="test-event-123", data={"key": "value"})
            await service.publish_event(event)

        assert "No topic mapping found" in str(exc_info.value)
        assert "unknown.event.type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_publish_event_http_error(self, service):
        """Test handling of HTTP errors during publication."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            with pytest.raises(httpx.HTTPStatusError):
                event = CloudEvent(type="agent.output.invoice.processed", id="test-event-123", data={"key": "value"})
                await service.publish_event(event)

    @pytest.mark.asyncio
    async def test_publish_event_auto_generated_id(self, service):
        """Test that event ID is auto-generated when not provided."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            event = CloudEvent(type="agent.output.invoice.processed", id="", data={"key": "value"})  # No event_id provided
            result = await service.publish_event(event)

            # Should have auto-generated ID
            assert result["event_id"] is not None
            assert len(result["event_id"]) > 0

            # Verify payload has the generated ID
            mock_post = mock_client.return_value.__aenter__.return_value.post
            payload = mock_post.call_args[1]["json"]
            assert payload["id"] == result["event_id"]

    @pytest.mark.asyncio
    async def test_publish_event_default_source(self, service):
        """Test that source is auto-generated when not provided."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            event = CloudEvent(type="agent.output.invoice.processed", id="test-event-123", data={"key": "value"})
            await service.publish_event(event)

            # Verify payload has default source
            mock_post = mock_client.return_value.__aenter__.return_value.post
            payload = mock_post.call_args[1]["json"]
            assert payload["source"] == "/agent/test-agent"

    @pytest.mark.asyncio
    async def test_publish_status_event(self, service):
        """Test convenience method for publishing status events."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            result = await service.publish_status_event(
                status_data={"task_id": "task-123", "progress": 100},
                status="completed",
                event_id="status-123",
            )

            assert result["status"] == "published"
            assert result["topic"] == "agent.status"

            # Verify event type
            mock_post = mock_client.return_value.__aenter__.return_value.post
            payload = mock_post.call_args[1]["json"]
            assert payload["type"] == "agent.status.completed"
            assert payload["data"]["progress"] == 100

    @pytest.mark.asyncio
    async def test_cloudevent_format_compliance(self, service):
        """Test that published events comply with CloudEvents specification."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            event = CloudEvent(type="agent.output.invoice.processed", id="test-123", data={"key": "value"}, source="/test/source")
            await service.publish_event(event)

            # Verify CloudEvents format
            mock_post = mock_client.return_value.__aenter__.return_value.post
            payload = mock_post.call_args[1]["json"]

            # Required CloudEvents fields
            assert payload["specversion"] == "1.0"
            assert "id" in payload
            assert "source" in payload
            assert "type" in payload
            assert payload["datacontenttype"] == "application/json"
            assert "data" in payload

            # Verify header
            headers = mock_post.call_args[1]["headers"]
            assert headers["Content-Type"] == "application/cloudevents+json"

    @pytest.mark.asyncio
    async def test_timeout_configuration(self, service):
        """Test that HTTP timeout is configured."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            event = CloudEvent(type="agent.output.invoice.processed", id="test-event-123", data={"test": "data"})
            await service.publish_event(event)

            # Verify timeout is set
            mock_post = mock_client.return_value.__aenter__.return_value.post
            assert mock_post.call_args[1]["timeout"] == 5.0
