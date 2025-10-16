"""Unit tests for EventPublishingService."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from base.src.config import Config
from base.src.services.event_publishing_service import EventPublishingService


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

        config.get_event_publishing_config.return_value = {
            "default_pubsub_name": "pubsub",
            "topic_mapping": {
                "agent.output.invoice.processed": "invoice.processed",
                "agent.output.document.classified": "document.classified",
                "agent.error.processing": "agent.errors",
                "agent.error.validation": "agent.errors",
                "agent.status.started": "agent.status",
                "agent.status.completed": "agent.status",
                "agent.status.failed": "agent.status",
            },
        }

        config.get_topic_for_event_type.side_effect = lambda event_type: {
            "agent.output.invoice.processed": "invoice.processed",
            "agent.output.document.classified": "document.classified",
            "agent.error.processing": "agent.errors",
            "agent.error.validation": "agent.errors",
            "agent.status.started": "agent.status",
            "agent.status.completed": "agent.status",
            "agent.status.failed": "agent.status",
        }.get(event_type)

        return config

    @pytest.fixture
    def service(self, mock_config):
        """Create an EventPublishingService instance."""
        return EventPublishingService(config=mock_config, dapr_http_port=3500)

    def test_initialization(self, service, mock_config):
        """Test service initialization."""
        assert service._dapr_http_port == 3500
        assert service._dapr_base_url == "http://localhost:3500"
        assert service._default_pubsub_name == "pubsub"
        assert len(service._topic_mapping) == 7

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
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await service.publish_event(
                event_type="agent.output.invoice.processed",
                data={"invoice_id": "INV-123", "status": "processed"},
                event_id="test-event-123",
                source="/test/source",
            )

            assert result["status"] == "published"
            assert result["topic"] == "invoice.processed"
            assert result["pubsub_name"] == "pubsub"
            assert result["event_id"] == "test-event-123"

            # Verify the HTTP call
            mock_post = mock_client.return_value.__aenter__.return_value.post
            mock_post.assert_called_once()
            call_args = mock_post.call_args

            # Check URL
            assert (
                call_args[0][0]
                == "http://localhost:3500/v1.0/publish/pubsub/invoice.processed"
            )

            # Check payload
            payload = call_args[1]["json"]
            assert payload["specversion"] == "1.0"
            assert payload["type"] == "agent.output.invoice.processed"
            assert payload["source"] == "/test/source"
            assert payload["id"] == "test-event-123"
            assert payload["data"]["invoice_id"] == "INV-123"

            # Check headers
            assert (
                call_args[1]["headers"]["Content-Type"]
                == "application/cloudevents+json"
            )

    @pytest.mark.asyncio
    async def test_publish_event_with_explicit_topic(self, service):
        """Test publishing with explicit topic override."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await service.publish_event(
                event_type="custom.event.type",
                data={"key": "value"},
                topic="custom.topic",  # Explicit topic
            )

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
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await service.publish_event(
                event_type="agent.output.invoice.processed",
                data={"key": "value"},
                pubsub_name="custom-pubsub",
            )

            assert result["pubsub_name"] == "custom-pubsub"

            # Verify URL uses custom pubsub
            mock_post = mock_client.return_value.__aenter__.return_value.post
            call_args = mock_post.call_args
            assert "custom-pubsub" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_publish_event_no_topic_mapping(self, service):
        """Test publishing event with no topic mapping raises error."""
        with pytest.raises(ValueError) as exc_info:
            await service.publish_event(
                event_type="unknown.event.type", data={"key": "value"}
            )

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
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(httpx.HTTPStatusError):
                await service.publish_event(
                    event_type="agent.output.invoice.processed", data={"key": "value"}
                )

    @pytest.mark.asyncio
    async def test_publish_event_auto_generated_id(self, service):
        """Test that event ID is auto-generated when not provided."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await service.publish_event(
                event_type="agent.output.invoice.processed",
                data={"key": "value"},
                # No event_id provided
            )

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
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            await service.publish_event(
                event_type="agent.output.invoice.processed",
                data={"key": "value"},
                # No source provided
            )

            # Verify payload has default source
            mock_post = mock_client.return_value.__aenter__.return_value.post
            payload = mock_post.call_args[1]["json"]
            assert payload["source"] == "/agent/test-agent"

    @pytest.mark.asyncio
    async def test_publish_agent_output(self, service):
        """Test convenience method for publishing agent output."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await service.publish_agent_output(
                output_data={"result": "success", "confidence": 0.95},
                event_subtype="invoice.processed",
                event_id="test-123",
            )

            assert result["status"] == "published"
            assert result["topic"] == "invoice.processed"

            # Verify event type was constructed correctly
            mock_post = mock_client.return_value.__aenter__.return_value.post
            payload = mock_post.call_args[1]["json"]
            assert payload["type"] == "agent.output.invoice.processed"
            assert payload["data"]["result"] == "success"

    @pytest.mark.asyncio
    async def test_publish_error_event(self, service):
        """Test convenience method for publishing error events."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await service.publish_error_event(
                error_data={"error": "validation failed", "details": "missing field"},
                error_type="validation",
                event_id="error-123",
            )

            assert result["status"] == "published"
            assert result["topic"] == "agent.errors"

            # Verify event type
            mock_post = mock_client.return_value.__aenter__.return_value.post
            payload = mock_post.call_args[1]["json"]
            assert payload["type"] == "agent.error.validation"
            assert payload["data"]["error"] == "validation failed"

    @pytest.mark.asyncio
    async def test_publish_status_event(self, service):
        """Test convenience method for publishing status events."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

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
    async def test_publish_multiple_events_to_same_topic(self, service):
        """Test that multiple event types can map to the same topic."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            # Both error types should go to same topic
            result1 = await service.publish_error_event(
                error_data={"error": "processing failed"}, error_type="processing"
            )

            result2 = await service.publish_error_event(
                error_data={"error": "validation failed"}, error_type="validation"
            )

            assert result1["topic"] == "agent.errors"
            assert result2["topic"] == "agent.errors"

            # Both should have been published
            assert mock_client.return_value.__aenter__.return_value.post.call_count == 2

    @pytest.mark.asyncio
    async def test_cloudevent_format_compliance(self, service):
        """Test that published events comply with CloudEvents specification."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            await service.publish_event(
                event_type="agent.output.invoice.processed",
                data={"test": "data"},
                event_id="test-123",
                source="/test/source",
            )

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
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            await service.publish_event(
                event_type="agent.output.invoice.processed", data={"test": "data"}
            )

            # Verify timeout is set
            mock_post = mock_client.return_value.__aenter__.return_value.post
            assert mock_post.call_args[1]["timeout"] == 5.0
