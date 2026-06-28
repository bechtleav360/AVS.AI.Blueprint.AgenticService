"""Unit tests for DaprClient."""

import json
import logging
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

    async def test_close_cancels_retry_task(self, dapr_client: DaprClient) -> None:
        import asyncio

        async def _never() -> None:
            await asyncio.sleep(9999)

        task = asyncio.create_task(_never())
        dapr_client._retry_task = task
        await dapr_client.close()
        assert task.cancelled()


class TestDaprClientSubscribe:
    async def test_subscribe_stores_mapping_and_starts_task(self, dapr_client: DaprClient) -> None:
        callback = AsyncMock()
        with patch.object(dapr_client, "_start_with_retry", new_callable=AsyncMock) as mock_retry:
            await dapr_client.subscribe({"topic.a": callback})
        assert dapr_client._topic_callbacks == {"topic.a": callback}
        assert dapr_client._subscriptions_managed is True
        mock_retry.assert_called_once()  # coroutine was created and scheduled, not directly awaited

    async def test_subscribe_returns_immediately(self, dapr_client: DaprClient) -> None:
        with patch.object(dapr_client, "_start_with_retry", new_callable=AsyncMock):
            await dapr_client.subscribe({"t": AsyncMock()})

    async def test_subscriptions_ready_false_before_retry_completes(self, dapr_client: DaprClient) -> None:
        with patch.object(dapr_client, "_start_with_retry", new_callable=AsyncMock):
            await dapr_client.subscribe({"t": AsyncMock()})
        assert dapr_client.subscriptions_ready is False


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

    async def test_unhealthy_when_subscriptions_managed_but_not_ready(self, connected_dapr_client: DaprClient) -> None:
        connected_dapr_client._subscriptions_managed = True
        connected_dapr_client._subscriptions_ready = False
        result = await connected_dapr_client.health_check()
        assert result.status == "unhealthy"
        assert "subscriptions" in result.message

    async def test_healthy_when_subscriptions_ready_and_sidecar_up(
        self, connected_dapr_client: DaprClient, mock_httpx_client: MagicMock
    ) -> None:
        connected_dapr_client._subscriptions_managed = True
        connected_dapr_client._subscriptions_ready = True
        result = await connected_dapr_client.health_check()
        assert result.status == "healthy"


class TestDaprClientRetryLoop:
    async def test_success_on_first_attempt_sets_ready(self, dapr_client: DaprClient) -> None:
        dapr_client._subscriptions_managed = True
        with patch.object(dapr_client, "_connect_and_subscribe", new_callable=AsyncMock):
            await dapr_client._start_with_retry()
        assert dapr_client.subscriptions_ready is True

    async def test_max_retries_zero_raises_immediately_on_failure(self, dapr_client: DaprClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda k, d=None: {"event_client_max_retries": 0, "event_client_retry_delay": 0.0}.get(k, d)
        dapr_client._subscriptions_managed = True
        with patch.object(dapr_client, "_connect_and_subscribe", new_callable=AsyncMock, side_effect=OSError("refused")):
            with pytest.raises(OSError):
                await dapr_client._start_with_retry()
        assert dapr_client.subscriptions_ready is False

    async def test_max_retries_2_calls_connect_three_times_then_raises(self, dapr_client: DaprClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda k, d=None: {"event_client_max_retries": 2, "event_client_retry_delay": 0.0}.get(k, d)
        dapr_client._subscriptions_managed = True
        mock_connect = AsyncMock(side_effect=OSError("refused"))
        with patch.object(dapr_client, "_connect_and_subscribe", mock_connect):
            with pytest.raises(OSError):
                await dapr_client._start_with_retry()
        assert mock_connect.await_count == 3

    async def test_max_retries_2_succeeds_on_third_attempt(self, dapr_client: DaprClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda k, d=None: {"event_client_max_retries": 2, "event_client_retry_delay": 0.0}.get(k, d)
        dapr_client._subscriptions_managed = True
        mock_connect = AsyncMock(side_effect=[OSError("fail"), OSError("fail"), None])
        with patch.object(dapr_client, "_connect_and_subscribe", mock_connect):
            await dapr_client._start_with_retry()
        assert mock_connect.await_count == 3
        assert dapr_client.subscriptions_ready is True

    async def test_done_callback_logs_error_on_permanent_failure(self, dapr_client: DaprClient) -> None:
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = OSError("final failure")
        with patch.object(logging.getLogger("blueprint.agents.clients.io.dapr_client"), "error") as mock_log:
            dapr_client._on_retry_done(task)
        mock_log.assert_called_once()

    async def test_done_callback_silent_on_cancellation(self, dapr_client: DaprClient) -> None:
        task = MagicMock()
        task.cancelled.return_value = True
        with patch.object(logging.getLogger("blueprint.agents.clients.io.dapr_client"), "error") as mock_log:
            dapr_client._on_retry_done(task)
        mock_log.assert_not_called()

    async def test_connect_and_subscribe_pings_sidecar(
        self, dapr_client: DaprClient, mock_config: MagicMock, mock_httpx_client: MagicMock
    ) -> None:
        mock_config.get.side_effect = lambda k, d=None: {
            "health_check_dapr": True,
            "dapr_url": "http://localhost:3500",
        }.get(k, d)
        dapr_client._client = mock_httpx_client
        await dapr_client._connect_and_subscribe()
        mock_httpx_client.get.assert_awaited_once_with("http://localhost:3500/v1.0/healthz")

    async def test_sidecar_unreachable_leaves_ready_false(
        self, dapr_client: DaprClient, mock_config: MagicMock, mock_httpx_client: MagicMock
    ) -> None:
        """Sidecar ping fails → _connect_and_subscribe raises → subscriptions_ready stays False."""
        mock_config.get.side_effect = lambda k, d=None: {
            "event_client_max_retries": 0,
            "event_client_retry_delay": 0.0,
            "health_check_dapr": True,
            "dapr_url": "http://localhost:3500",
        }.get(k, d)
        mock_httpx_client.get.return_value.raise_for_status.side_effect = Exception("503")
        dapr_client._client = mock_httpx_client
        dapr_client._subscriptions_managed = True
        with patch.object(dapr_client, "_connect_and_subscribe", side_effect=OSError("sidecar down")):
            with pytest.raises(OSError):
                await dapr_client._start_with_retry()
        assert dapr_client.subscriptions_ready is False
