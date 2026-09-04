"""Unit tests for NATSClient."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
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
    async def test_close_drains_all_subscriptions(self, connected_nats_client: NATSClient) -> None:
        sub = MagicMock(drain=AsyncMock(), unsubscribe=AsyncMock())
        connected_nats_client._subscriptions = [sub]

        await connected_nats_client.close()

        sub.drain.assert_awaited_once()
        sub.unsubscribe.assert_not_awaited()

    async def test_close_clears_subscriptions_list(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._subscriptions = [MagicMock(drain=AsyncMock())]
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


class TestNATSClientMessageBoundary:
    """The transport boundary distinguishes an unusable payload from a failed dispatch.

    The two have opposite dispositions once P2 lands: a payload that cannot be decoded is
    terminal for that message, while a dispatch failure is retryable.
    """

    @staticmethod
    async def _handler_for(nats_client: NATSClient, mock_nats_core: MagicMock, callback) -> object:
        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("orders.created", callback)
        return mock_nats_core.subscribe.await_args.kwargs["cb"]

    async def test_undecodable_payload_is_not_dispatched(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        dispatched = []

        async def _callback(event: CloudEvent) -> None:
            dispatched.append(event)

        handler = await self._handler_for(nats_client, mock_nats_core, _callback)

        with caplog.at_level("ERROR"):
            await handler(MagicMock(data=b"not json at all"))

        assert dispatched == []
        assert "unparseable" in caplog.text
        assert "orders.created" in caplog.text

    async def test_valid_json_that_is_not_a_cloud_event_is_not_dispatched(self, nats_client: NATSClient, mock_nats_core: MagicMock) -> None:
        dispatched = []

        async def _callback(event: CloudEvent) -> None:
            dispatched.append(event)

        handler = await self._handler_for(nats_client, mock_nats_core, _callback)

        await handler(MagicMock(data=json.dumps({"not": "an event"}).encode()))

        assert dispatched == []

    async def test_dispatch_failure_is_logged_with_event_and_topic(
        self,
        nats_client: NATSClient,
        mock_nats_core: MagicMock,
        cloud_event: CloudEvent,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise RuntimeError("handler exploded")

        handler = await self._handler_for(nats_client, mock_nats_core, _callback)

        with caplog.at_level("ERROR"):
            await handler(MagicMock(data=json.dumps(dict(cloud_event)).encode()))

        assert "Handler failed" in caplog.text
        assert cloud_event.id in caplog.text
        assert "orders.created" in caplog.text

    async def test_neither_failure_escapes_into_the_broker_callback(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise RuntimeError("handler exploded")

        handler = await self._handler_for(nats_client, mock_nats_core, _callback)

        await handler(MagicMock(data=b"garbage"))
        await handler(MagicMock(data=json.dumps(dict(cloud_event)).encode()))

        assert nats_client.inflight_handlers == 0

    async def test_undecodable_payload_releases_the_inflight_slot(self, nats_client: NATSClient, mock_nats_core: MagicMock) -> None:
        async def _callback(event: CloudEvent) -> None:
            pass

        handler = await self._handler_for(nats_client, mock_nats_core, _callback)

        await handler(MagicMock(data=b"garbage"))

        assert nats_client.inflight_handlers == 0


class TestNATSClientAcknowledgement:
    """P2 -- a normal return acks, a raised exception does not (spec sec. 7.2)."""

    @staticmethod
    async def _js_handler(nats_client: NATSClient, mock_nats_jetstream: tuple, callback) -> object:
        mock_nc, _ = mock_nats_jetstream
        nats_client._nats_client = mock_nc
        nats_client._client = mock_nc
        nats_client._use_jetstream = True
        await nats_client._subscribe_one("orders.created", callback)
        return mock_nc.jetstream().subscribe.await_args.kwargs["cb"]

    @staticmethod
    def _msg(cloud_event: CloudEvent) -> MagicMock:
        return MagicMock(
            data=json.dumps(dict(cloud_event)).encode(),
            reply="$JS.ACK.x",
            ack=AsyncMock(),
            nak=AsyncMock(),
            term=AsyncMock(),
        )

    async def test_normal_return_acks(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        handler = await self._js_handler(nats_client, mock_nats_jetstream, AsyncMock())
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.ack.assert_awaited_once()
        msg.nak.assert_not_awaited()
        msg.term.assert_not_awaited()

    async def test_no_handler_found_still_acks(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        """An unmatched event has nothing to do, and redelivery cannot make a handler appear."""
        handler = await self._js_handler(nats_client, mock_nats_jetstream, AsyncMock(return_value=None))
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.ack.assert_awaited_once()

    async def test_retryable_error_naks(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise RetryableHandlerError(status="error", reason="upstream down")

        handler = await self._js_handler(nats_client, mock_nats_jetstream, _callback)
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.nak.assert_awaited_once()
        msg.ack.assert_not_awaited()

    async def test_invalid_event_error_terms(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise InvalidEventError(status="error", reason="no payload")

        handler = await self._js_handler(nats_client, mock_nats_jetstream, _callback)
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.term.assert_awaited_once()
        msg.nak.assert_not_awaited()

    async def test_critical_error_terms(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        """A critical error is not made less critical by being delivered again."""

        async def _callback(event: CloudEvent) -> None:
            raise CriticalHandlerError(status="error", reason="corrupt state")

        handler = await self._js_handler(nats_client, mock_nats_jetstream, _callback)
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.term.assert_awaited_once()

    async def test_unexpected_exception_naks(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise RuntimeError("boom")

        handler = await self._js_handler(nats_client, mock_nats_jetstream, _callback)
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.nak.assert_awaited_once()

    async def test_undecodable_payload_terms_without_dispatching(self, nats_client: NATSClient, mock_nats_jetstream: tuple) -> None:
        dispatched = []
        handler = await self._js_handler(nats_client, mock_nats_jetstream, lambda e: dispatched.append(e))
        msg = MagicMock(data=b"not json", reply="$JS.ACK.x", ack=AsyncMock(), nak=AsyncMock(), term=AsyncMock())
        await handler(msg)
        msg.term.assert_awaited_once()
        msg.ack.assert_not_awaited()
        assert dispatched == []

    async def test_core_nats_settles_nothing(self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent) -> None:
        """Core NATS is fire-and-forget; msg.ack() would raise NotJSMessageError there."""
        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("orders.created", AsyncMock())
        handler = mock_nats_core.subscribe.await_args.kwargs["cb"]
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.ack.assert_not_awaited()
        msg.nak.assert_not_awaited()
        msg.term.assert_not_awaited()

    async def test_failure_to_ack_does_not_escape_the_callback(
        self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The ack travels over the delivering connection, so it fails when that is gone."""
        handler = await self._js_handler(nats_client, mock_nats_jetstream, AsyncMock())
        msg = self._msg(cloud_event)
        msg.ack = AsyncMock(side_effect=Exception("connection closed"))
        with caplog.at_level("ERROR"):
            await handler(msg)
        assert "Could not ack" in caplog.text
        assert nats_client.inflight_handlers == 0

    async def test_dispatch_failure_log_names_the_disposition(
        self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise InvalidEventError(status="error", reason="no payload")

        handler = await self._js_handler(nats_client, mock_nats_jetstream, _callback)
        with caplog.at_level("ERROR"):
            await handler(self._msg(cloud_event))
        assert "will term" in caplog.text
        assert cloud_event.id in caplog.text


class TestNATSClientShutdownDrain:
    async def test_close_unsubscribes_when_drain_fails(self, connected_nats_client: NATSClient) -> None:
        sub = MagicMock(drain=AsyncMock(side_effect=Exception("broken")), unsubscribe=AsyncMock())
        connected_nats_client._subscriptions = [sub]

        await connected_nats_client.close()

        sub.unsubscribe.assert_awaited_once()

    async def test_close_marks_subscriptions_not_ready(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._subscriptions_ready = True
        await connected_nats_client.close()
        assert connected_nats_client.subscriptions_ready is False

    async def test_connection_stays_open_until_inflight_handler_finishes(
        self, connected_nats_client: NATSClient, mock_nats_core: MagicMock
    ) -> None:
        connected_nats_client._enter_handler()
        connection_closed_during_handler = []

        async def _finish_handler() -> None:
            await asyncio.sleep(0.05)
            connection_closed_during_handler.append(mock_nats_core.close.await_count > 0)
            connected_nats_client._exit_handler()

        finishing = asyncio.create_task(_finish_handler())
        await connected_nats_client.close()
        await finishing

        assert connection_closed_during_handler == [False]
        mock_nats_core.close.assert_awaited_once()

    async def test_close_gives_up_after_drain_timeout_and_still_closes(
        self, connected_nats_client: NATSClient, mock_nats_core: MagicMock
    ) -> None:
        connected_nats_client.config.get.side_effect = lambda key, default=None: 0.01 if key == "event_client_drain_timeout" else default
        connected_nats_client._enter_handler()

        await connected_nats_client.close()

        assert connected_nats_client.inflight_handlers == 1
        mock_nats_core.close.assert_awaited_once()

    async def test_close_does_not_wait_when_no_handler_is_running(self, connected_nats_client: NATSClient) -> None:
        assert connected_nats_client.inflight_handlers == 0
        await asyncio.wait_for(connected_nats_client.close(), timeout=1.0)

    async def test_handler_execution_is_counted_and_released(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        seen_during_handler = []

        async def _callback(event: CloudEvent) -> None:
            seen_during_handler.append(nats_client.inflight_handlers)

        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("orders.created", _callback)
        message_handler = mock_nats_core.subscribe.await_args.kwargs["cb"]

        msg = MagicMock(data=json.dumps(dict(cloud_event)).encode())
        await message_handler(msg)

        assert seen_during_handler == [1]
        assert nats_client.inflight_handlers == 0

    async def test_handler_count_is_released_when_callback_raises(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise RuntimeError("handler exploded")

        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("orders.created", _callback)
        message_handler = mock_nats_core.subscribe.await_args.kwargs["cb"]

        await message_handler(MagicMock(data=json.dumps(dict(cloud_event)).encode()))

        assert nats_client.inflight_handlers == 0


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


class TestNATSClientQueueGroup:
    """P1 -- every Core NATS subscription joins a queue group (spec C1, sec. 7.1)."""

    async def test_core_subscription_passes_queue_group(self, connected_nats_client: NATSClient, mock_nats_core: MagicMock) -> None:
        connected_nats_client._queue_group = "test-agent"
        await connected_nats_client._subscribe_one("topic.a", AsyncMock())
        assert mock_nats_core.subscribe.await_args.kwargs["queue"] == "test-agent"

    async def test_all_topics_share_one_queue_group(self, connected_nats_client: NATSClient, mock_nats_core: MagicMock) -> None:
        connected_nats_client._queue_group = "test-agent"
        await connected_nats_client._subscribe_one("topic.a", AsyncMock())
        await connected_nats_client._subscribe_one("topic.b", AsyncMock())
        queues = {call.kwargs["queue"] for call in mock_nats_core.subscribe.await_args_list}
        assert queues == {"test-agent"}

    async def test_subscribe_resolves_queue_group_from_app_name(self, nats_client: NATSClient) -> None:
        with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock):
            await nats_client.subscribe({"topic.a": AsyncMock()})
        assert nats_client.queue_group == "test-agent"

    async def test_explicit_queue_group_wins_over_app_name(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: {"app_name": "test-agent", "nats_queue_group": "orders"}.get(key, default)
        with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock):
            await nats_client.subscribe({"topic.a": AsyncMock()})
        assert nats_client.queue_group == "orders"

    async def test_subscribe_raises_when_no_name_can_be_derived(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: default
        with pytest.raises(ValueError, match="queue group"):
            await nats_client.subscribe({"topic.a": AsyncMock()})

    async def test_subscribe_raises_when_configured_name_is_blank(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """A blank name would reach NATS as no queue group at all -- silent fan-out."""
        mock_config.get.side_effect = lambda key, default=None: {"app_name": "  ", "nats_queue_group": ""}.get(key, default)
        with pytest.raises(ValueError, match="queue group"):
            await nats_client.subscribe({"topic.a": AsyncMock()})

    async def test_whitespace_in_name_raises_instead_of_reaching_nats(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """nats-py rejects a queue name containing a space; an app_name like this was legal before P1."""
        mock_config.get.side_effect = lambda key, default=None: {"app_name": "My Agent Service"}.get(key, default)
        with pytest.raises(ValueError, match="whitespace"):
            await nats_client.subscribe({"topic.a": AsyncMock()})

    async def test_whitespace_error_names_the_key_and_value(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: {"app_name": "My Agent Service"}.get(key, default)
        with pytest.raises(ValueError, match="'My Agent Service'.*'app_name'"):
            await nats_client.subscribe({"topic.a": AsyncMock()})

    async def test_surrounding_whitespace_is_trimmed_not_rejected(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: {"app_name": "  orders  "}.get(key, default)
        with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock):
            await nats_client.subscribe({"topic.a": AsyncMock()})
        assert nats_client.queue_group == "orders"

    async def test_dots_and_dashes_are_accepted(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Only whitespace is rejected -- NATS accepts these, and existing app_names use them."""
        mock_config.get.side_effect = lambda key, default=None: {"app_name": "my-agent_service.v1"}.get(key, default)
        with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock):
            await nats_client.subscribe({"topic.a": AsyncMock()})
        assert nats_client.queue_group == "my-agent_service.v1"

    async def test_failed_resolution_starts_no_retry_task(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """A config error must fail startup, not spin in the background retry loop forever."""
        mock_config.get.side_effect = lambda key, default=None: default
        with pytest.raises(ValueError):
            await nats_client.subscribe({"topic.a": AsyncMock()})
        assert nats_client._retry_task is None

    async def test_queue_group_is_empty_before_subscribe(self, nats_client: NATSClient) -> None:
        assert nats_client.queue_group == ""


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
