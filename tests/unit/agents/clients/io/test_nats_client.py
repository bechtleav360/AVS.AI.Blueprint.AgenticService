"""Unit tests for NATSClient."""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nats.js import api as js_api

from blueprint.agents.clients.io.nats_client import ConsumerTuning, NATSClient
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
        return mock_nc.jetstream().subscribe_bind.await_args.kwargs["cb"]

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
        with pytest.raises(ValueError, match="'app_name'.*'My Agent Service'"):
            await nats_client.subscribe({"topic.a": AsyncMock()})

    async def test_wildcard_in_the_queue_group_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """It would also seed the default dead-letter subject '<queue group>.dead-letter'."""
        mock_config.get.side_effect = lambda key, default=None: {"app_name": "my*service"}.get(key, default)
        with pytest.raises(ValueError, match="cannot appear in a NATS subject"):
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


# ---------------------------------------------------------------------------
# P3 -- consumer tuning, stream/consumer provisioning, dead-lettering
# ---------------------------------------------------------------------------

_JS_CONFIG = {
    "app_name": "test-agent",
    "nats_use_jetstream": True,
    "nats_stream_name": "EVENTS",
}


def _js_config(**overrides: object):
    """Return a config.get side effect with JetStream on and the given keys overridden."""
    merged = {**_JS_CONFIG, **overrides}
    return lambda key, default=None: merged.get(key, default)


async def _prepare_js_client(
    nats_client: NATSClient,
    mock_config: MagicMock,
    mock_nats_jetstream: tuple,
    topics: list[str],
    **overrides: object,
) -> MagicMock:
    """Run subscribe() so tuning and durables resolve, then attach the JetStream mocks."""
    mock_config.get.side_effect = _js_config(**overrides)
    mock_nc, mock_js = mock_nats_jetstream
    with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock):
        await nats_client.subscribe({topic: AsyncMock() for topic in topics})
    nats_client._nats_client = mock_nc
    nats_client._client = mock_nc
    nats_client._use_jetstream = True
    return mock_js


class TestNATSClientConsumerTuning:
    """P3 -- ack_wait, max_ack_pending and max_deliver are configurable (spec sec. 7.3)."""

    async def test_core_nats_resolves_no_tuning(self, nats_client: NATSClient) -> None:
        """The settings describe a JetStream consumer; Core NATS has none."""
        with patch.object(nats_client, "_start_with_retry", new_callable=AsyncMock):
            await nats_client.subscribe({"topic.a": AsyncMock()})
        assert nats_client.consumer_tuning is None

    async def test_defaults_are_resolved_when_jetstream_is_on(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        assert nats_client.consumer_tuning == ConsumerTuning(
            ack_wait=300.0,
            max_ack_pending=16,
            max_deliver=5,
            dead_letter_subject="test-agent.dead-letter",
        )

    async def test_configured_values_win(self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple) -> None:
        await _prepare_js_client(
            nats_client,
            mock_config,
            mock_nats_jetstream,
            ["orders.created"],
            nats_ack_wait=45.0,
            nats_max_ack_pending=4,
            nats_max_deliver=2,
        )
        tuning = nats_client.consumer_tuning
        assert (tuning.ack_wait, tuning.max_ack_pending, tuning.max_deliver) == (45.0, 4, 2)

    async def test_zero_ack_wait_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = _js_config(nats_ack_wait=0)
        with pytest.raises(ValueError, match="nats_ack_wait"):
            await nats_client.subscribe({"orders.created": AsyncMock()})

    async def test_non_numeric_ack_wait_names_the_key(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = _js_config(nats_ack_wait="soon")
        with pytest.raises(ValueError, match="'nats_ack_wait' must be a number"):
            await nats_client.subscribe({"orders.created": AsyncMock()})

    async def test_zero_max_ack_pending_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = _js_config(nats_max_ack_pending=0)
        with pytest.raises(ValueError, match="nats_max_ack_pending"):
            await nats_client.subscribe({"orders.created": AsyncMock()})

    async def test_negative_max_ack_pending_other_than_unlimited_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = _js_config(nats_max_ack_pending=-2)
        with pytest.raises(ValueError, match="nats_max_ack_pending"):
            await nats_client.subscribe({"orders.created": AsyncMock()})

    async def test_unlimited_max_ack_pending_is_accepted(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_max_ack_pending=-1)
        assert nats_client.consumer_tuning.max_ack_pending == -1

    async def test_zero_max_deliver_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = _js_config(nats_max_deliver=0)
        with pytest.raises(ValueError, match="nats_max_deliver"):
            await nats_client.subscribe({"orders.created": AsyncMock()})

    async def test_unlimited_max_deliver_warns_that_nothing_is_dead_lettered(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_max_deliver=-1)
        assert "redelivered forever" in caplog.text

    async def test_a_bad_value_starts_no_retry_task(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Same reason as the queue group: a config error must fail startup, not loop in the background."""
        mock_config.get.side_effect = _js_config(nats_ack_wait=-1)
        with pytest.raises(ValueError):
            await nats_client.subscribe({"orders.created": AsyncMock()})
        assert nats_client._retry_task is None


class TestNATSClientDeadLetterSubject:
    """P3 -- where a message goes once the framework gives up on it (spec sec. 7.2)."""

    async def test_defaults_to_the_queue_group(self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple) -> None:
        """Derived from the agent's identity, exactly as the queue group is (C1)."""
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_queue_group="orders-agent")
        assert nats_client.consumer_tuning.dead_letter_subject == "orders-agent.dead-letter"

    async def test_configured_subject_wins(self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple) -> None:
        await _prepare_js_client(
            nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_dead_letter_subject="graveyard.orders"
        )
        assert nats_client.consumer_tuning.dead_letter_subject == "graveyard.orders"

    async def test_empty_string_disables_dead_lettering(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_dead_letter_subject="")
        assert nats_client.consumer_tuning.dead_letter_subject == ""

    async def test_wildcard_subject_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """It is published to, and a wildcard names no single subject to publish to."""
        mock_config.get.side_effect = _js_config(nats_dead_letter_subject="dead.*")
        with pytest.raises(ValueError, match="wildcard"):
            await nats_client.subscribe({"orders.created": AsyncMock()})

    async def test_whitespace_subject_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = _js_config(nats_dead_letter_subject="dead letters")
        with pytest.raises(ValueError, match="whitespace"):
            await nats_client.subscribe({"orders.created": AsyncMock()})

    async def test_subject_this_client_subscribes_to_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Dead-lettering onto a consumed subject turns one failure into an unbounded loop."""
        mock_config.get.side_effect = _js_config(nats_queue_group="orders")
        with pytest.raises(ValueError, match="come straight back"):
            await nats_client.subscribe({"orders.>": AsyncMock()})

    def test_subject_match_honours_single_token_wildcard(self, nats_client: NATSClient) -> None:
        assert nats_client._subject_matches("orders.*", "orders.created") is True
        assert nats_client._subject_matches("orders.*", "orders.created.v1") is False

    def test_subject_match_honours_multi_token_wildcard(self, nats_client: NATSClient) -> None:
        assert nats_client._subject_matches("orders.>", "orders.created.v1") is True
        assert nats_client._subject_matches("orders.>", "orders") is False

    def test_subject_match_is_exact_without_wildcards(self, nats_client: NATSClient) -> None:
        assert nats_client._subject_matches("orders.created", "orders.created") is True
        assert nats_client._subject_matches("orders.created", "orders") is False


class TestNATSClientDurableNames:
    """P3 -- a durable belongs to one filter subject, and NATS restricts what it may be called."""

    def test_dotted_topic_becomes_a_legal_consumer_name(self, nats_client: NATSClient) -> None:
        """NATS rejects '.' in a consumer name, so 'orders.created-durable' never worked."""
        assert nats_client._durable_for("orders.created") == "orders_created-durable"

    def test_wildcards_and_whitespace_are_replaced(self, nats_client: NATSClient) -> None:
        assert nats_client._durable_for("orders.*.v1") == "orders___v1-durable"
        assert nats_client._durable_for("orders.>") == "orders__-durable"

    async def test_each_topic_gets_its_own_durable(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created", "orders.shipped"])
        assert nats_client._durables == {
            "orders.created": "orders_created-durable",
            "orders.shipped": "orders_shipped-durable",
        }

    async def test_configured_durable_with_several_topics_raises(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = _js_config(nats_durable_name="shared")
        with pytest.raises(ValueError, match="one name cannot serve them all"):
            await nats_client.subscribe({"orders.created": AsyncMock(), "orders.shipped": AsyncMock()})

    async def test_configured_durable_with_one_topic_is_used(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_durable_name="shared")
        assert nats_client._durables == {"orders.created": "shared"}

    async def test_topics_colliding_after_sanitising_raise(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """'orders.created' and 'orders_created' both sanitise to one name."""
        mock_config.get.side_effect = _js_config()
        with pytest.raises(ValueError, match="both resolve to durable name"):
            await nats_client.subscribe({"orders.created": AsyncMock(), "orders_created": AsyncMock()})


class TestNATSClientStreamProvisioning:
    """P3 -- the stream must carry every subject a consumer filters on."""

    async def test_creates_stream_with_the_topic_itself(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """The old code stored only 'topic.>', which does not cover 'topic'."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        await nats_client._provision_stream()
        subjects = mock_js.add_stream.await_args.kwargs["subjects"]
        assert "orders.created" in subjects
        assert "orders.created.>" in subjects

    async def test_created_stream_carries_the_dead_letter_subject(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """A dead letter published to a subject no stream captures is not persisted at all."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        await nats_client._provision_stream()
        assert "test-agent.dead-letter" in mock_js.add_stream.await_args.kwargs["subjects"]

    async def test_every_topic_reaches_one_stream(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """Per-topic add_stream calls left every topic after the first uncaptured."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created", "orders.shipped"])
        await nats_client._provision_stream()
        subjects = mock_js.add_stream.await_args.kwargs["subjects"]
        assert {"orders.created", "orders.shipped"} <= set(subjects)
        assert mock_js.add_stream.await_count == 1

    async def test_wildcard_topic_gets_no_suffixed_form(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """'orders.>.>' is not a valid subject."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.>"])
        await nats_client._provision_stream()
        assert mock_js.add_stream.await_args.kwargs["subjects"] == ["orders.>", "test-agent.dead-letter"]

    async def test_existing_stream_is_widened_not_replaced(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        mock_js.stream_info = AsyncMock(return_value=MagicMock(config=js_api.StreamConfig(name="EVENTS", subjects=["legacy.subject"])))
        await nats_client._provision_stream()
        updated = mock_js.update_stream.await_args.args[0].subjects
        assert "legacy.subject" in updated
        assert "orders.created" in updated
        mock_js.add_stream.assert_not_awaited()

    async def test_covered_stream_is_left_alone(self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        mock_js.stream_info = AsyncMock(
            return_value=MagicMock(
                config=js_api.StreamConfig(name="EVENTS", subjects=["orders.created", "orders.created.>", "test-agent.dead-letter"])
            )
        )
        await nats_client._provision_stream()
        mock_js.update_stream.assert_not_awaited()

    async def test_failed_widening_is_reported_not_raised(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The consumer bind that follows fails anyway, and names the consumer too."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        mock_js.stream_info = AsyncMock(return_value=MagicMock(config=js_api.StreamConfig(name="EVENTS", subjects=[])))
        mock_js.update_stream = AsyncMock(side_effect=Exception("no permission"))
        with caplog.at_level("ERROR"):
            await nats_client._provision_stream()
        assert "could not be updated" in caplog.text

    async def test_subscribe_all_provisions_before_subscribing(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        await nats_client._subscribe_all()
        mock_js.add_stream.assert_awaited_once()
        mock_js.subscribe_bind.assert_awaited_once()


class TestNATSClientJetStreamConsumer:
    """P3 -- the durable is created explicitly so its deliver group and limits are enforced."""

    async def test_consumer_joins_the_queue_group(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """A durable without a deliver group hands every message to every replica."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        await nats_client._subscribe_one("orders.created", AsyncMock())
        assert mock_js.add_consumer.await_args.kwargs["config"].deliver_group == "test-agent"

    async def test_consumer_carries_the_tuning(self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple) -> None:
        mock_js = await _prepare_js_client(
            nats_client,
            mock_config,
            mock_nats_jetstream,
            ["orders.created"],
            nats_ack_wait=45.0,
            nats_max_ack_pending=4,
            nats_max_deliver=2,
        )
        await nats_client._subscribe_one("orders.created", AsyncMock())
        config = mock_js.add_consumer.await_args.kwargs["config"]
        assert (config.ack_wait, config.max_ack_pending, config.max_deliver) == (45.0, 4, 2)
        assert config.filter_subject == "orders.created"
        assert config.ack_policy is js_api.AckPolicy.EXPLICIT

    async def test_deliver_subject_is_derived_from_the_durable(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """Every replica must bind to the same deliver subject, so it cannot be a fresh inbox."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        await nats_client._subscribe_one("orders.created", AsyncMock())
        assert mock_js.add_consumer.await_args.kwargs["config"].deliver_subject == "_DELIVER.orders_created-durable"

    async def test_subscription_binds_to_the_named_consumer(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        await nats_client._subscribe_one("orders.created", AsyncMock())
        kwargs = mock_js.subscribe_bind.await_args.kwargs
        assert kwargs["stream"] == "EVENTS"
        assert kwargs["consumer"] == "orders_created-durable"
        assert kwargs["manual_ack"] is True

    async def test_existing_consumer_is_not_rewritten(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """A durable's filter and deliver group are broker state; recreating one replays or gaps."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        existing = js_api.ConsumerConfig(
            durable_name="orders_created-durable", filter_subject="orders.created", deliver_subject="_DELIVER.old"
        )
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=existing))
        await nats_client._subscribe_one("orders.created", AsyncMock())
        mock_js.add_consumer.assert_not_awaited()
        assert mock_js.subscribe_bind.await_args.kwargs["config"] is existing

    async def test_drift_from_an_existing_consumer_is_reported(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        existing = js_api.ConsumerConfig(
            durable_name="orders_created-durable", filter_subject="orders.created", deliver_subject="_DELIVER.old", ack_wait=30.0
        )
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=existing))
        with caplog.at_level("WARNING"):
            await nats_client._subscribe_one("orders.created", AsyncMock())
        assert "already exists with different settings" in caplog.text
        assert "deliver_group" in caplog.text
        assert "ack_wait" in caplog.text

    async def test_matching_existing_consumer_is_silent(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        existing = nats_client._consumer_config("orders.created", "orders_created-durable")
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=existing))
        with caplog.at_level("WARNING"):
            await nats_client._subscribe_one("orders.created", AsyncMock())
        assert "already exists" not in caplog.text


class TestNATSClientDeadLettering:
    """P3 -- a message the framework gives up on keeps its payload (spec sec. 7.2)."""

    @staticmethod
    def _msg(payload: bytes, num_delivered: int = 1) -> MagicMock:
        return MagicMock(
            data=payload,
            metadata=MagicMock(num_delivered=num_delivered),
            ack=AsyncMock(),
            nak=AsyncMock(),
            term=AsyncMock(),
        )

    @staticmethod
    async def _handler(nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, callback, **overrides):
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], **overrides)
        await nats_client._subscribe_one("orders.created", callback)
        mock_nc, _ = mock_nats_jetstream
        return mock_nc.jetstream().subscribe_bind.await_args.kwargs["cb"]

    async def test_terminal_failure_is_dead_lettered_then_termed(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise InvalidEventError(status="error", reason="no payload")

        _, mock_js = mock_nats_jetstream
        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, _callback)
        msg = self._msg(json.dumps(dict(cloud_event)).encode())
        await handler(msg)
        assert mock_js.publish.await_args.args[0] == "test-agent.dead-letter"
        msg.term.assert_awaited_once()

    async def test_original_bytes_are_republished_unchanged(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """An undecodable payload is exactly the one worth keeping, and it is not a CloudEvent."""
        _, mock_js = mock_nats_jetstream
        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, AsyncMock())
        await handler(self._msg(b"not json"))
        assert mock_js.publish.await_args.args[1] == b"not json"

    async def test_headers_name_the_reason_and_origin(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise CriticalHandlerError(status="error", reason="corrupt state")

        _, mock_js = mock_nats_jetstream
        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, _callback)
        await handler(self._msg(json.dumps(dict(cloud_event)).encode(), num_delivered=3))
        headers = mock_js.publish.await_args.kwargs["headers"]
        assert headers["Blueprint-Dead-Letter-Reason"] == "terminal-failure"
        assert headers["Blueprint-Original-Subject"] == "orders.created"
        assert headers["Blueprint-Delivery-Count"] == "3"
        assert headers["Blueprint-Event-Id"] == cloud_event.id

    async def test_retry_below_the_limit_naks_without_dead_lettering(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise RetryableHandlerError(status="error", reason="upstream down")

        _, mock_js = mock_nats_jetstream
        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, _callback, nats_max_deliver=3)
        msg = self._msg(json.dumps(dict(cloud_event)).encode(), num_delivered=2)
        await handler(msg)
        msg.nak.assert_awaited_once()
        msg.term.assert_not_awaited()
        mock_js.publish.assert_not_awaited()

    async def test_final_attempt_is_dead_lettered_instead_of_naked(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        """Naking the last attempt drops the message silently at max_deliver."""

        async def _callback(event: CloudEvent) -> None:
            raise RetryableHandlerError(status="error", reason="upstream down")

        _, mock_js = mock_nats_jetstream
        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, _callback, nats_max_deliver=3)
        msg = self._msg(json.dumps(dict(cloud_event)).encode(), num_delivered=3)
        await handler(msg)
        msg.nak.assert_not_awaited()
        msg.term.assert_awaited_once()
        assert mock_js.publish.await_args.kwargs["headers"]["Blueprint-Dead-Letter-Reason"] == "deliveries-exhausted"

    async def test_unlimited_max_deliver_never_exhausts(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise RetryableHandlerError(status="error", reason="upstream down")

        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, _callback, nats_max_deliver=-1)
        msg = self._msg(json.dumps(dict(cloud_event)).encode(), num_delivered=99)
        await handler(msg)
        msg.nak.assert_awaited_once()

    async def test_unreadable_metadata_costs_a_retry_not_a_payload(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent) -> None:
            raise RetryableHandlerError(status="error", reason="upstream down")

        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, _callback, nats_max_deliver=1)
        msg = self._msg(json.dumps(dict(cloud_event)).encode())
        msg.metadata = MagicMock(num_delivered="not a number")
        await handler(msg)
        msg.nak.assert_awaited_once()

    async def test_disabled_dead_lettering_warns_about_the_lost_payload(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        _, mock_js = mock_nats_jetstream
        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, AsyncMock(), nats_dead_letter_subject="")
        msg = self._msg(b"not json")
        with caplog.at_level("WARNING"):
            await handler(msg)
        assert "payload is lost" in caplog.text
        mock_js.publish.assert_not_awaited()
        msg.term.assert_awaited_once()

    async def test_failed_republish_still_settles_the_delivery(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Leaving it unsettled would redeliver a message already known to be unprocessable."""
        _, mock_js = mock_nats_jetstream
        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, AsyncMock())
        mock_js.publish = AsyncMock(side_effect=Exception("stream gone"))
        msg = self._msg(b"not json")
        with caplog.at_level("ERROR"):
            await handler(msg)
        assert "its payload is lost" in caplog.text
        msg.term.assert_awaited_once()

    async def test_a_normal_return_is_never_dead_lettered(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        _, mock_js = mock_nats_jetstream
        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, AsyncMock())
        msg = self._msg(json.dumps(dict(cloud_event)).encode())
        await handler(msg)
        msg.ack.assert_awaited_once()
        mock_js.publish.assert_not_awaited()


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


# ---------------------------------------------------------------------------
# P6 -- one connection per namespace (spec sec. 6)
# ---------------------------------------------------------------------------


_NAMESPACED_CONFIG = {
    "app_name": "test-agent",
    "nats_url": "nats://localhost:4222",
    "nats_use_jetstream": False,
}


def _namespaced_client(mock_config: MagicMock, namespace: str) -> NATSClient:
    """Return a NATSClient owned by a namespace, on a config with no durable name set."""
    mock_config.get.side_effect = lambda key, default=None: _NAMESPACED_CONFIG.get(key, default)
    return NATSClient(namespace=namespace)


class TestNATSClientNamespaceOwnership:
    """A client belongs to one namespace, and two of them coexist in one process."""

    def test_default_is_the_root_namespace(self, nats_client: NATSClient) -> None:
        assert nats_client.namespace == ""

    def test_root_client_keeps_the_unqualified_registry_name(self, nats_client: NATSClient) -> None:
        assert nats_client.name == "nats_client"

    def test_namespaced_client_registers_under_a_qualified_name(self, mock_config: MagicMock) -> None:
        assert _namespaced_client(mock_config, "orders").name == "orders_nats_client"

    def test_two_namespaces_coexist_in_one_registry(self, mock_config: MagicMock) -> None:
        """Registry.add_component rejects a duplicate name, so this used to raise."""
        orders = _namespaced_client(mock_config, "orders")
        invoice = _namespaced_client(mock_config, "invoice")
        assert orders.registry.get_component("orders_nats_client") is orders
        assert invoice.registry.get_component("invoice_nats_client") is invoice

    def test_surrounding_whitespace_is_rejected_rather_than_trimmed(self, mock_config: MagicMock) -> None:
        """Trimming would give one agent two names: the declared one and the registered one."""
        with pytest.raises(ValueError, match="surrounding whitespace"):
            _namespaced_client(mock_config, "  orders  ")


class TestNATSClientConsumerIdentityFollowsTheNamespace:
    """C1 -- broker-side identity derives from the agent, so co-hosted agents never merge."""

    async def test_queue_group_is_the_namespace(self, mock_config: MagicMock) -> None:
        client = _namespaced_client(mock_config, "orders")
        with patch.object(client, "_start_with_retry", new_callable=AsyncMock):
            await client.subscribe({"topic.a": AsyncMock()})
        assert client.queue_group == "orders"

    async def test_namespace_wins_over_the_configured_root_queue_group(self, mock_config: MagicMock) -> None:
        """'nats_queue_group' is the root namespace's key only."""
        mock_config.get.side_effect = lambda key, default=None: {"app_name": "test-agent", "nats_queue_group": "shared"}.get(key, default)
        client = NATSClient(namespace="orders")
        with patch.object(client, "_start_with_retry", new_callable=AsyncMock):
            await client.subscribe({"topic.a": AsyncMock()})
        assert client.queue_group == "orders"

    async def test_two_namespaces_on_one_topic_get_different_queue_groups(self, mock_config: MagicMock) -> None:
        """Sharing a group would make the broker deliver each event to one of the two agents."""
        orders = _namespaced_client(mock_config, "orders")
        invoice = _namespaced_client(mock_config, "invoice")
        with (
            patch.object(orders, "_start_with_retry", new_callable=AsyncMock),
            patch.object(invoice, "_start_with_retry", new_callable=AsyncMock),
        ):
            await orders.subscribe({"shared.topic": AsyncMock()})
            await invoice.subscribe({"shared.topic": AsyncMock()})
        assert orders.queue_group != invoice.queue_group

    def test_whitespace_is_rejected_at_construction_not_at_subscribe(self, mock_config: MagicMock) -> None:
        """A publish-only or Dapr namespace never subscribes, so a subscribe-time check misses it."""
        with pytest.raises(ValueError, match="cannot appear in it"):
            _namespaced_client(mock_config, "my orders")

    def test_durable_carries_the_namespace(self, mock_config: MagicMock) -> None:
        assert _namespaced_client(mock_config, "orders")._durable_for("orders.created") == "orders-orders_created-durable"

    def test_root_durable_is_unchanged(self, nats_client: NATSClient) -> None:
        """Renaming a durable is a consumer migration, so the root namespace keeps its name."""
        assert nats_client._durable_for("orders.created") == "orders_created-durable"

    def test_two_namespaces_on_one_topic_get_different_durables(self, mock_config: MagicMock) -> None:
        orders = _namespaced_client(mock_config, "orders")
        invoice = _namespaced_client(mock_config, "invoice")
        assert orders._durable_for("shared.topic") != invoice._durable_for("shared.topic")

    def test_dotted_namespace_is_rejected(self, mock_config: MagicMock) -> None:
        """A dot is a subject separator, so it cannot be silently rewritten into a consumer name."""
        with pytest.raises(ValueError, match="cannot appear in it"):
            _namespaced_client(mock_config, "orders.eu")

    def test_hyphenated_namespace_is_rejected_because_the_durable_would_collide(self, mock_config: MagicMock) -> None:
        """'orders-eu' on 'created' and 'orders' on 'eu-created' would name one consumer."""
        with pytest.raises(ValueError, match="separator in the JetStream durable name"):
            _namespaced_client(mock_config, "orders-eu")

    def test_the_namespace_reaches_the_durable_exactly_as_declared(self, mock_config: MagicMock) -> None:
        """Only the topic is rewritten, so the durable can be read back to its namespace."""
        durable = _namespaced_client(mock_config, "orders_eu")._durable_for("orders.created")
        assert durable == "orders_eu-orders_created-durable"
        assert durable.split("-", 1)[0] == "orders_eu"

    async def test_configured_durable_under_a_namespace_warns(self, mock_config: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        """A root-level durable name would make every namespace bind to one consumer."""
        mock_config.get.side_effect = lambda key, default=None: {
            "app_name": "test-agent",
            "nats_use_jetstream": True,
            "nats_durable_name": "shared-durable",
        }.get(key, default)
        client = NATSClient(namespace="orders")
        with caplog.at_level(logging.WARNING), patch.object(client, "_start_with_retry", new_callable=AsyncMock):
            await client.subscribe({"topic.a": AsyncMock()})
        assert "consume each other" in caplog.text


class TestConsumerIdentityIgnoresTheDeployment:
    """C1 -- regrouping must be invisible to the broker, so no deployment value may reach it.

    The two broker-side identifiers are the queue group and the durable name, and both derive
    from the namespace alone. A deployment identifier reaching either would make regrouping
    observable: a durable that picked up the group name becomes a *different* durable when the
    agent moves group, and a fresh consumer resumes according to its delivery policy -- so the
    agent either replays the stream from the start or silently skips whatever arrived while it
    was being renamed. This is the invariant the plan asks to be covered by a test, and it is
    why the connection name -- which does carry the group and the pod -- is kept away from both.

    Each case derives the two identifiers, changes the deployment, and derives them again from
    the same client, so what is asserted is the derivation rather than a cached value.
    """

    @staticmethod
    def _identities(client: NATSClient) -> tuple[str, str]:
        return client._resolve_queue_group(), client._durable_for("orders.created")

    def test_the_group_name_reaches_neither(self, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BLUEPRINT_GROUP", "group-a")
        monkeypatch.setenv("POD_NAME", "pod-1")
        client = _namespaced_client(mock_config, "orders")
        before = self._identities(client)

        monkeypatch.setenv("BLUEPRINT_GROUP", "group-b")

        assert self._identities(client) == before == ("orders", "orders-orders_created-durable")

    def test_the_pod_name_reaches_neither(self, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """A pod name in a durable would mean a new consumer on every restart."""
        monkeypatch.setenv("BLUEPRINT_GROUP", "group-a")
        monkeypatch.setenv("POD_NAME", "pod-1")
        client = _namespaced_client(mock_config, "orders")
        before = self._identities(client)

        monkeypatch.setenv("POD_NAME", "pod-2")

        assert self._identities(client) == before

    def test_the_connection_name_changes_while_they_do_not(self, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """The positive half: the deployment is visible, but only where attribution needs it."""
        monkeypatch.setenv("BLUEPRINT_GROUP", "group-a")
        monkeypatch.setenv("POD_NAME", "pod-1")
        client = _namespaced_client(mock_config, "orders")
        identities, connection = self._identities(client), client._resolve_connection_name()

        monkeypatch.setenv("BLUEPRINT_GROUP", "group-b")
        monkeypatch.setenv("POD_NAME", "pod-2")

        assert client._resolve_connection_name() != connection
        assert self._identities(client) == identities

    async def test_the_consumer_carries_the_namespace_and_not_the_deployment(
        self, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One durable per (namespace, topic), filtering that one subject.

        This is also what makes the plan's per-namespace ``filter_subjects`` set unnecessary: a
        filter set that followed the handler list would be rewritten whenever a handler was
        added, and a durable's filter is broker-side state that cannot be rewritten without
        replaying or gapping. Here the filter is one subject and never changes.
        """
        monkeypatch.setenv("BLUEPRINT_GROUP", "group-a")
        monkeypatch.setenv("POD_NAME", "pod-1")
        client = _namespaced_client(mock_config, "orders")
        with patch.object(client, "_start_with_retry", new_callable=AsyncMock):
            await client.subscribe({"orders.created": AsyncMock()})

        config = client._consumer_config("orders.created", client._durable_for("orders.created"))

        assert (config.durable_name, config.filter_subject, config.deliver_group) == (
            "orders-orders_created-durable",
            "orders.created",
            "orders",
        )
        assert "group-a" not in str(config) and "pod-1" not in str(config)


class TestNATSClientConnectionName:
    """Reason 3 -- attribution. nats.connect() used to be called with no name at all."""

    async def test_connect_passes_the_name_to_nats(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BLUEPRINT_GROUP", "billing")
        monkeypatch.setenv("POD_NAME", "billing-7d9f")
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        mock_nc.jetstream = MagicMock(return_value=None)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_nc
            await nats_client.connect()
        assert mock_connect.call_args[1]["name"] == "<root>.billing.billing-7d9f"

    def test_name_is_namespace_group_pod(self, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BLUEPRINT_GROUP", "billing")
        monkeypatch.setenv("POD_NAME", "billing-7d9f")
        assert _namespaced_client(mock_config, "orders")._resolve_connection_name() == "orders.billing.billing-7d9f"

    def test_empty_namespace_is_named_rather_than_left_blank(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BLUEPRINT_GROUP", "billing")
        monkeypatch.setenv("POD_NAME", "pod-1")
        assert nats_client._resolve_connection_name() == "<root>.billing.pod-1"

    def test_unset_group_is_named_rather_than_left_blank(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        monkeypatch.setenv("POD_NAME", "pod-1")
        assert nats_client._resolve_connection_name() == "<root>.<ungrouped>.pod-1"

    def test_pod_name_wins_over_hostname(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("POD_NAME", "from-downward-api")
        monkeypatch.setenv("HOSTNAME", "from-kubelet")
        assert nats_client._resolve_connection_name().endswith(".from-downward-api")

    def test_hostname_is_used_when_pod_name_is_absent(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.setenv("HOSTNAME", "from-kubelet")
        assert nats_client._resolve_connection_name().endswith(".from-kubelet")

    def test_falls_back_to_the_host_name(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)
        monkeypatch.setattr("blueprint.agents.deployment.socket.gethostname", lambda: "laptop")
        assert nats_client._resolve_connection_name().endswith(".laptop")

    def test_unresolvable_host_still_yields_a_name(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)

        def _raise() -> str:
            raise OSError("no host name")

        monkeypatch.setattr("blueprint.agents.deployment.socket.gethostname", _raise)
        assert nats_client._resolve_connection_name().endswith(".<unknown-pod>")

    def test_a_dotted_group_cannot_add_a_segment(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Four segments would misattribute the connection; the name is three by construction."""
        monkeypatch.setenv("BLUEPRINT_GROUP", "eu.west")
        monkeypatch.setenv("POD_NAME", "pod-1")
        name = nats_client._resolve_connection_name()
        assert name == "<root>.eu_west.pod-1"
        assert name.count(".") == 2

    def test_a_group_cannot_forge_a_placeholder(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """The brackets are what make the placeholders unforgeable, so they are stripped here."""
        monkeypatch.setenv("BLUEPRINT_GROUP", "<ungrouped>")
        monkeypatch.setenv("POD_NAME", "pod-1")
        assert nats_client._resolve_connection_name() == "<root>._ungrouped_.pod-1"

    def test_an_fqdn_hostname_stays_one_segment(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.setenv("HOSTNAME", "web-7.eu.internal")
        name = nats_client._resolve_connection_name()
        assert name.endswith(".web-7_eu_internal")
        assert name.count(".") == 2

    def test_connection_name_is_empty_before_connect(self, nats_client: NATSClient) -> None:
        assert nats_client.connection_name == ""

    async def test_connect_records_the_name_it_used(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BLUEPRINT_GROUP", "billing")
        monkeypatch.setenv("POD_NAME", "pod-1")
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        mock_nc.jetstream = MagicMock(return_value=None)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_nc
            await nats_client.connect()
        assert nats_client.connection_name == "<root>.billing.pod-1"

    async def test_deployment_identity_never_reaches_the_consumer_identity(
        self, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C1 -- the connection name carries the pod, so nothing broker-side may derive from it."""
        monkeypatch.setenv("BLUEPRINT_GROUP", "group-b")
        monkeypatch.setenv("POD_NAME", "pod-99")
        client = _namespaced_client(mock_config, "orders")
        with patch.object(client, "_start_with_retry", new_callable=AsyncMock):
            await client.subscribe({"orders.created": AsyncMock()})
        assert client.queue_group == "orders"
        assert "group-b" not in client._durable_for("orders.created")
        assert "pod-99" not in client._durable_for("orders.created")


class TestPausingADegradedAgent:
    """C4: readiness gates HTTP only, so a degraded agent has to be taken off its topics."""

    @pytest.fixture
    def subscribed(self, nats_client: NATSClient, mock_nats_core: MagicMock) -> NATSClient:
        """A connected client with one live subscription and one managed topic."""
        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        nats_client._subscriptions_managed = True
        nats_client._subscriptions_ready = True
        subscription = MagicMock()
        subscription.drain = AsyncMock()
        nats_client._subscriptions = [subscription]
        nats_client._topic_callbacks = {"orders.created": AsyncMock()}
        return nats_client

    async def test_a_client_starts_unpaused(self, nats_client: NATSClient) -> None:
        assert nats_client.consumption_paused is False

    async def test_pausing_drains_the_subscriptions(self, subscribed: NATSClient) -> None:
        """Drained, not unsubscribed: a queued message still reaches its handler and acks."""
        subscription = subscribed._subscriptions[0]
        await subscribed.pause_consumption()
        subscription.drain.assert_awaited_once()
        assert subscribed.consumption_paused is True
        assert subscribed.subscriptions_ready is False

    async def test_pausing_leaves_the_connection_open(self, subscribed: NATSClient, mock_nats_core: MagicMock) -> None:
        """A closed client reports itself unhealthy for ever, so the pause could never lift."""
        await subscribed.pause_consumption()
        mock_nats_core.close.assert_not_called()
        assert subscribed._nats_client is mock_nats_core

    async def test_pausing_twice_drains_once(self, subscribed: NATSClient) -> None:
        subscription = subscribed._subscriptions[0]
        await subscribed.pause_consumption()
        await subscribed.pause_consumption()
        subscription.drain.assert_awaited_once()

    async def test_the_pause_is_reported_with_its_agent(self, mock_config: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        client = _namespaced_client(mock_config, "orders")
        with caplog.at_level(logging.ERROR):
            await client.pause_consumption()
        assert "orders" in caplog.text
        assert "stopped consuming" in caplog.text

    async def test_a_paused_client_reports_healthy(self, subscribed: NATSClient) -> None:
        """The pause is a consequence of degradation, not a cause; latching it would be permanent."""
        await subscribed.pause_consumption()
        result = await subscribed.health_check()
        assert result.status == "healthy"
        assert "paused" in (result.message or "")

    async def test_resuming_resubscribes(self, subscribed: NATSClient) -> None:
        await subscribed.pause_consumption()
        with patch.object(subscribed, "_subscribe_all", new=AsyncMock()) as subscribe_all:
            await subscribed.resume_consumption()
        subscribe_all.assert_awaited_once()
        assert subscribed.consumption_paused is False
        assert subscribed.subscriptions_ready is True

    async def test_resuming_one_that_was_not_paused_does_nothing(self, subscribed: NATSClient) -> None:
        with patch.object(subscribed, "_subscribe_all", new=AsyncMock()) as subscribe_all:
            await subscribed.resume_consumption()
        subscribe_all.assert_not_awaited()

    async def test_a_failed_resume_stays_paused(self, subscribed: NATSClient) -> None:
        """The next health poll finds the agent healthy and calls this again; that is the retry."""
        await subscribed.pause_consumption()
        with patch.object(subscribed, "_subscribe_all", new=AsyncMock(side_effect=RuntimeError("no"))):
            await subscribed.resume_consumption()
        assert subscribed.consumption_paused is True
        assert subscribed.subscriptions_ready is False

    async def test_a_reconnect_does_not_undo_a_pause(self, subscribed: NATSClient) -> None:
        """Otherwise C4 would hold only until the next network blip."""
        subscribed._use_jetstream = True
        await subscribed.pause_consumption()
        with patch.object(subscribed, "_subscribe_all", new=AsyncMock()) as subscribe_all:
            await subscribed._on_reconnected()
        subscribe_all.assert_not_awaited()
        assert subscribed.subscriptions_ready is False
