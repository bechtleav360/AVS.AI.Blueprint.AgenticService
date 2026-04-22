"""Unit tests for DaprClient."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from blueprint.agents.clients.io.dapr_client import DaprClient
from blueprint.agents.models.events import CloudEvent


class TestDaprClientConnection:
    def test_is_connected_false_when_client_none(self, dapr_client: DaprClient) -> None:
        assert dapr_client._is_connected() is False

    def test_is_connected_true_when_client_set(self, dapr_client: DaprClient) -> None:
        dapr_client._client = MagicMock()
        assert dapr_client._is_connected() is True

    async def test_connect_creates_httpx_async_client(self, dapr_client: DaprClient) -> None:
        with patch("blueprint.agents.clients.io.dapr_client.httpx.AsyncClient") as mock_cls:
            await dapr_client.connect()
        mock_cls.assert_called_once()
        assert dapr_client._client is mock_cls.return_value

    async def test_connect_is_idempotent(self, dapr_client: DaprClient) -> None:
        with patch("blueprint.agents.clients.io.dapr_client.httpx.AsyncClient") as mock_cls:
            await dapr_client.connect()
            await dapr_client.connect()
        mock_cls.assert_called_once()

    async def test_close_calls_aclose_and_clears_client(self, connected_dapr_client: DaprClient, mock_httpx_client: MagicMock) -> None:
        await connected_dapr_client.close()
        mock_httpx_client.aclose.assert_awaited_once()
        assert connected_dapr_client._client is None

    async def test_close_is_safe_when_client_none(self, dapr_client: DaprClient) -> None:
        await dapr_client.close()  # must not raise


class TestDaprClientSubscribe:
    async def test_subscribe_logs_warning_and_does_not_raise(self, connected_dapr_client: DaprClient) -> None:
        await connected_dapr_client.subscribe("topic", AsyncMock())


class TestDaprClientPublish:
    async def test_publish_posts_to_correct_url(
        self,
        connected_dapr_client: DaprClient,
        mock_httpx_client: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_dapr_client.publish("my-topic", cloud_event)
        url = mock_httpx_client.post.call_args[0][0]
        assert url == "http://localhost:3500/v1.0/publish/pubsub/my-topic"

    async def test_publish_sets_cloudevents_content_type(
        self,
        connected_dapr_client: DaprClient,
        mock_httpx_client: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_dapr_client.publish("topic", cloud_event)
        headers = mock_httpx_client.post.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/cloudevents+json"

    async def test_publish_serialises_event_as_json(
        self,
        connected_dapr_client: DaprClient,
        mock_httpx_client: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_dapr_client.publish("topic", cloud_event)
        body = mock_httpx_client.post.call_args[1]["content"]
        parsed = json.loads(body)
        assert parsed["id"] == "test-event-id"
        assert parsed["type"] == "test.event"

    async def test_publish_adds_routing_key_header_when_provided(
        self,
        connected_dapr_client: DaprClient,
        mock_httpx_client: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_dapr_client.publish("topic", cloud_event, routing_key="rk-123")
        headers = mock_httpx_client.post.call_args[1]["headers"]
        assert headers["metadata.routingKey"] == "rk-123"

    async def test_publish_omits_routing_key_header_when_not_provided(
        self,
        connected_dapr_client: DaprClient,
        mock_httpx_client: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_dapr_client.publish("topic", cloud_event)
        headers = mock_httpx_client.post.call_args[1]["headers"]
        assert "metadata.routingKey" not in headers

    async def test_publish_uses_custom_pubsub_name(
        self,
        connected_dapr_client: DaprClient,
        mock_httpx_client: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_dapr_client.publish("topic", cloud_event, pubsub_name="custom-bus")
        url = mock_httpx_client.post.call_args[0][0]
        assert "/custom-bus/" in url

    async def test_publish_raises_on_http_error(
        self,
        connected_dapr_client: DaprClient,
        mock_httpx_client: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        mock_httpx_client.post.return_value.raise_for_status.side_effect = Exception("404")
        with pytest.raises(Exception, match="404"):
            await connected_dapr_client.publish("topic", cloud_event)


class TestDaprClientHealthCheck:
    async def test_healthy_when_dapr_responds_200(self, connected_dapr_client: DaprClient, mock_httpx_client: MagicMock) -> None:
        result = await connected_dapr_client.health_check()
        assert result.status == "healthy"
        mock_httpx_client.get.assert_awaited_once_with("http://localhost:3500/v1.0/healthz")

    async def test_unhealthy_on_request_error(self, connected_dapr_client: DaprClient, mock_httpx_client: MagicMock) -> None:
        mock_httpx_client.get.side_effect = httpx.RequestError("unreachable")
        result = await connected_dapr_client.health_check()
        assert result.status == "unhealthy"
        assert "unreachable" in result.message

    async def test_unhealthy_on_unexpected_error(self, connected_dapr_client: DaprClient, mock_httpx_client: MagicMock) -> None:
        mock_httpx_client.get.side_effect = RuntimeError("unexpected")
        result = await connected_dapr_client.health_check()
        assert result.status == "unhealthy"

    async def test_healthy_when_health_check_disabled(self, dapr_client: DaprClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: False if key == "health_check_dapr" else default
        result = await dapr_client.health_check()
        assert result.status == "healthy"
        assert "disabled" in result.message
