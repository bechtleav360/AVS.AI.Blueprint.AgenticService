"""Unit tests for NATSClient."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.models.events import CloudEvent


class TestNATSClientInit:
    def test_nats_client_initialises_as_none(self, nats_client: NATSClient) -> None:
        assert nats_client._nats_client is None

    def test_js_initialises_as_none(self, nats_client: NATSClient) -> None:
        assert nats_client._js is None

    def test_use_jetstream_initialises_as_false(self, nats_client: NATSClient) -> None:
        assert nats_client._use_jetstream is False

    def test_subscriptions_initialises_as_empty_list(self, nats_client: NATSClient) -> None:
        assert nats_client._subscriptions == []

    def test_subscriptions_ready_initialises_as_false(self, nats_client: NATSClient) -> None:
        assert nats_client.subscriptions_ready is False

    def test_subscriptions_managed_initialises_as_false(self, nats_client: NATSClient) -> None:
        assert nats_client._subscriptions_managed is False


class TestNATSClientIsConnected:
    def test_false_when_nats_client_none(self, nats_client: NATSClient) -> None:
        assert nats_client._is_connected() is False

    def test_false_when_nats_client_closed(self, nats_client: NATSClient) -> None:
        mock_nc = MagicMock()
        mock_nc.is_closed = True
        mock_nc.is_connected = True
        nats_client._nats_client = mock_nc
        assert nats_client._is_connected() is False

    def test_false_when_nats_client_not_connected(self, nats_client: NATSClient) -> None:
        mock_nc = MagicMock()
        mock_nc.is_closed = False
        mock_nc.is_connected = False
        nats_client._nats_client = mock_nc
        assert nats_client._is_connected() is False

    def test_true_when_open_and_connected(self, nats_client: NATSClient) -> None:
        mock_nc = MagicMock()
        mock_nc.is_closed = False
        mock_nc.is_connected = True
        nats_client._nats_client = mock_nc
        assert nats_client._is_connected() is True


class TestNATSClientConnect:
    async def test_connect_calls_nats_connect_with_url(self, nats_client: NATSClient) -> None:
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        mock_nc.jetstream = MagicMock(return_value=None)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_nc
            await nats_client.connect()
        mock_connect.assert_awaited_once()
        assert mock_connect.call_args[0][0] == "nats://localhost:4222"

    async def test_connect_passes_disconnect_and_reconnect_callbacks(self, nats_client: NATSClient) -> None:
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        mock_nc.jetstream = MagicMock(return_value=None)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_nc
            await nats_client.connect()
        kwargs = mock_connect.call_args[1]
        assert callable(kwargs["disconnected_cb"])
        assert kwargs["disconnected_cb"].__func__.__name__ == "_on_disconnected"
        assert callable(kwargs["reconnected_cb"])
        assert kwargs["reconnected_cb"].__func__.__name__ == "_on_reconnected"

    async def test_connect_sets_nats_client_and_client(self, nats_client: NATSClient) -> None:
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        mock_nc.jetstream = MagicMock(return_value=None)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_nc
            await nats_client.connect()
        assert nats_client._nats_client is mock_nc
        assert nats_client._client is mock_nc

    async def test_connect_is_idempotent(self, nats_client: NATSClient) -> None:
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        mock_nc.jetstream = MagicMock(return_value=None)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_nc
            await nats_client.connect()
            await nats_client.connect()
        mock_connect.assert_awaited_once()

    async def test_connect_enables_jetstream_when_configured(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: (
            True if key == "nats_use_jetstream" else {"nats_url": "nats://localhost:4222"}.get(key, default)
        )
        mock_js = MagicMock()
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        mock_nc.jetstream = MagicMock(return_value=mock_js)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_nc
            await nats_client.connect()
        assert nats_client._use_jetstream is True
        assert nats_client._js is mock_js

    async def test_connect_raises_on_nats_error(self, nats_client: NATSClient) -> None:
        with patch(
            "blueprint.agents.clients.io.nats_client.nats.connect",
            new_callable=AsyncMock,
            side_effect=Exception("refused"),
        ):
            with pytest.raises(Exception, match="refused"):
                await nats_client.connect()


class TestNATSClientClose:
    async def test_close_unsubscribes_all_subscriptions(self, connected_nats_client: NATSClient) -> None:
        sub = MagicMock()
        sub.unsubscribe = AsyncMock()
        connected_nats_client._subscriptions = [sub]

        await connected_nats_client.close()

        sub.unsubscribe.assert_awaited_once()

    async def test_close_clears_subscriptions_list(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._subscriptions = [MagicMock(unsubscribe=AsyncMock())]
        await connected_nats_client.close()
        assert connected_nats_client._subscriptions == []

    async def test_close_calls_nats_close(self, connected_nats_client: NATSClient, mock_nats_core: MagicMock) -> None:
        await connected_nats_client.close()
        mock_nats_core.close.assert_awaited_once()

    async def test_close_clears_client_references(self, connected_nats_client: NATSClient) -> None:
        await connected_nats_client.close()
        assert connected_nats_client._nats_client is None
        assert connected_nats_client._client is None
        assert connected_nats_client._js is None

    async def test_close_cancels_retry_task(self, nats_client: NATSClient) -> None:

        async def _never() -> None:
            await asyncio.sleep(9999)

        task = asyncio.create_task(_never())
        nats_client._retry_task = task
        nats_client._nats_client = None
        await nats_client.close()
        assert task.cancelled()


class TestNATSClientPublish:
    async def test_publish_sends_json_encoded_event_via_core_nats(
        self,
        connected_nats_client: NATSClient,
        mock_nats_core: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_nats_client.publish("my-topic", cloud_event)

        mock_nats_core.publish.assert_awaited_once()
        topic_arg, data_arg = mock_nats_core.publish.call_args[0]
        assert topic_arg == "my-topic"
        parsed = json.loads(data_arg.decode())
        assert parsed["id"] == "test-event-id"

    async def test_publish_uses_jetstream_when_enabled(
        self,
        nats_client: NATSClient,
        mock_nats_jetstream: tuple,
        cloud_event: CloudEvent,
    ) -> None:
        mock_nc, mock_js = mock_nats_jetstream
        nats_client._nats_client = mock_nc
        nats_client._client = mock_nc
        nats_client._use_jetstream = True

        await nats_client.publish("js-topic", cloud_event)

        mock_js.publish.assert_awaited_once()
        topic_arg = mock_js.publish.call_args[0][0]
        assert topic_arg == "js-topic"

    async def test_publish_raises_on_nats_error(
        self,
        connected_nats_client: NATSClient,
        mock_nats_core: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        mock_nats_core.publish.side_effect = Exception("publish failed")
        with pytest.raises(Exception, match="publish failed"):
            await connected_nats_client.publish("topic", cloud_event)


class TestNATSClientHealthCheck:
    async def test_healthy_when_connected_without_managed_subscriptions(self, connected_nats_client: NATSClient) -> None:
        result = await connected_nats_client.health_check()
        assert result.status == "healthy"

    async def test_healthy_message_contains_server_url(self, connected_nats_client: NATSClient) -> None:
        result = await connected_nats_client.health_check()
        assert "nats://localhost:4222" in result.message

    async def test_unhealthy_when_not_connected(self, nats_client: NATSClient) -> None:
        result = await nats_client.health_check()
        assert result.status == "unhealthy"

    async def test_unhealthy_when_client_closed(self, nats_client: NATSClient) -> None:
        mock_nc = MagicMock(is_closed=True, is_connected=False)
        nats_client._nats_client = mock_nc
        result = await nats_client.health_check()
        assert result.status == "unhealthy"

    async def test_unhealthy_when_connected_but_subscriptions_not_ready(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._subscriptions_managed = True
        connected_nats_client._subscriptions_ready = False
        result = await connected_nats_client.health_check()
        assert result.status == "unhealthy"
        assert "subscriptions" in result.message

    async def test_healthy_when_connected_and_subscriptions_ready(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._subscriptions_managed = True
        connected_nats_client._subscriptions_ready = True
        result = await connected_nats_client.health_check()
        assert result.status == "healthy"


class TestNATSClientManagedSubscriptions:
    async def test_subscribe_stores_mapping_and_starts_task(self, nats_client: NATSClient) -> None:
        callback = AsyncMock()
        with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock) as mock_retry:
            await nats_client.subscribe({"topic.a": callback})
        assert nats_client._topic_callbacks == {"topic.a": callback}
        assert nats_client._subscriptions_managed is True
        mock_retry.assert_called_once()  # coroutine was created and scheduled, not directly awaited

    async def test_subscribe_returns_immediately(self, nats_client: NATSClient) -> None:
        """subscribe() must be non-blocking — the retry runs as a background task."""
        with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock):
            await nats_client.subscribe({"t": AsyncMock()})
        # reaching here means subscribe() returned without awaiting the retry

    async def test_subscriptions_ready_false_before_retry_completes(self, nats_client: NATSClient) -> None:
        with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock):
            await nats_client.subscribe({"t": AsyncMock()})
        assert nats_client.subscriptions_ready is False


class TestNATSClientRetryLoop:
    async def test_success_on_first_attempt_sets_ready(self, nats_client: NATSClient) -> None:
        nats_client._subscriptions_managed = True
        with patch.object(nats_client, "_connect_and_subscribe", new_callable=AsyncMock):
            await nats_client._start_with_retry()
        assert nats_client.subscriptions_ready is True

    async def test_max_retries_zero_raises_immediately_on_failure(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda k, d=None: {"event_client_max_retries": 0, "event_client_retry_delay": 0.0}.get(k, d)
        nats_client._subscriptions_managed = True
        with patch.object(nats_client, "_connect_and_subscribe", new_callable=AsyncMock, side_effect=OSError("refused")):
            with pytest.raises(OSError, match="refused"):
                await nats_client._start_with_retry()
        assert nats_client.subscriptions_ready is False

    async def test_max_retries_2_calls_connect_three_times_then_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda k, d=None: {"event_client_max_retries": 2, "event_client_retry_delay": 0.0}.get(k, d)
        nats_client._subscriptions_managed = True
        mock_connect = AsyncMock(side_effect=OSError("refused"))
        with patch.object(nats_client, "_connect_and_subscribe", mock_connect):
            with pytest.raises(OSError):
                await nats_client._start_with_retry()
        assert mock_connect.await_count == 3

    async def test_max_retries_2_succeeds_on_third_attempt(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda k, d=None: {"event_client_max_retries": 2, "event_client_retry_delay": 0.0}.get(k, d)
        nats_client._subscriptions_managed = True
        mock_connect = AsyncMock(side_effect=[OSError("fail"), OSError("fail"), None])
        with patch.object(nats_client, "_connect_and_subscribe", mock_connect):
            await nats_client._start_with_retry()
        assert mock_connect.await_count == 3
        assert nats_client.subscriptions_ready is True

    async def test_done_callback_logs_error_on_permanent_failure(self, nats_client: NATSClient) -> None:
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = OSError("final failure")
        import logging

        with patch.object(logging.getLogger("blueprint.agents.clients.io.nats_client"), "error") as mock_log:
            nats_client._on_retry_done(task)
        mock_log.assert_called_once()

    async def test_done_callback_silent_on_cancellation(self, nats_client: NATSClient) -> None:
        task = MagicMock()
        task.cancelled.return_value = True
        import logging

        with patch.object(logging.getLogger("blueprint.agents.clients.io.nats_client"), "error") as mock_log:
            nats_client._on_retry_done(task)
        mock_log.assert_not_called()

    async def test_broker_connects_but_subscription_fails_leaves_ready_false(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Connect succeeds; subscribe raises — readiness must stay False."""
        mock_config.get.side_effect = lambda k, d=None: {"event_client_max_retries": 0, "event_client_retry_delay": 0.0}.get(k, d)
        nats_client._subscriptions_managed = True

        async def connect_ok_subscribe_fails() -> None:
            # Simulate a successful broker connect without a real network call
            nats_client._nats_client = MagicMock(is_closed=False, is_connected=True)
            nats_client._client = nats_client._nats_client
            raise OSError("subscription failed")

        with patch.object(nats_client, "_connect_and_subscribe", side_effect=connect_ok_subscribe_fails):
            with pytest.raises(OSError):
                await nats_client._start_with_retry()
        assert nats_client.subscriptions_ready is False


class TestNATSClientReconnect:
    async def test_disconnected_callback_clears_ready_flag(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._subscriptions_ready = True
        await connected_nats_client._on_disconnected()
        assert connected_nats_client.subscriptions_ready is False

    async def test_reconnected_callback_restores_ready_flag_for_core_nats(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._subscriptions_managed = True
        connected_nats_client._subscriptions_ready = False
        connected_nats_client._use_jetstream = False
        await connected_nats_client._on_reconnected()
        assert connected_nats_client.subscriptions_ready is True

    async def test_reconnected_callback_no_op_without_managed_subscriptions(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._subscriptions_managed = False
        connected_nats_client._subscriptions_ready = False
        await connected_nats_client._on_reconnected()
        assert connected_nats_client.subscriptions_ready is False

    async def test_reconnected_resubscribes_jetstream_topics(self, connected_nats_client: NATSClient, mock_nats_jetstream: tuple) -> None:
        mock_nc, mock_js = mock_nats_jetstream
        connected_nats_client._nats_client = mock_nc
        connected_nats_client._client = mock_nc
        connected_nats_client._use_jetstream = True
        connected_nats_client._subscriptions_managed = True
        connected_nats_client._subscriptions_ready = False
        connected_nats_client._topic_callbacks = {"topic.a": AsyncMock(), "topic.b": AsyncMock()}

        with patch.object(connected_nats_client, "_subscribe_one", new_callable=AsyncMock) as mock_sub:
            await connected_nats_client._on_reconnected()

        assert mock_sub.await_count == 2
        assert connected_nats_client.subscriptions_ready is True


# ---------------------------------------------------------------------------
# asyncio import needed by the non-blocking subscribe test
# ---------------------------------------------------------------------------
