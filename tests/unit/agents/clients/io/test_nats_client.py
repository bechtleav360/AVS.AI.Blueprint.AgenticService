"""Unit tests for NATSClient."""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
from nats.errors import NoRespondersError
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js import api as js_api
from nats.js.errors import APIError, ServiceUnavailableError

from blueprint.agents.clients.io.io_client_base import subject_is_covered_by
from blueprint.agents.clients.io.nats_client import (
    DEVELOPMENT_NATS_URL,
    ConsumerTuning,
    JetStreamUnavailableError,
    NATSClient,
    _Binding,
    _Link,
    redact_url,
)
from blueprint.agents.models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from blueprint.agents.models.events import CloudEvent


def _until_settled(nats_client: NATSClient, handler):
    """The broker callback, awaited until the run it started has settled.

    The callback only starts the run as a task of its own (concurrent runs); these tests assert
    on what the run did, so they wait for it.
    """

    async def deliver(msg) -> None:
        await handler(msg)
        await asyncio.gather(*list(nats_client._runs), return_exceptions=True)

    return deliver


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
        mock_js.account_info = AsyncMock()
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


class TestNATSClientUrl:
    """M1 -- ``nats_url`` falls back to localhost in development only; elsewhere startup fails."""

    @staticmethod
    def _configure(mock_config: MagicMock, **values: object) -> None:
        mock_config.get.side_effect = lambda key, default=None: values.get(key, default)
        mock_config.envvar_prefix = "DYNACONF"

    async def test_a_configured_url_is_used(self, nats_client: NATSClient, mock_config: MagicMock, caplog) -> None:
        self._configure(mock_config, nats_url="nats://broker:4222", app_environment="production")
        with caplog.at_level(logging.WARNING, logger="blueprint.agents.clients.io.nats_client"):
            await nats_client.on_startup()
        assert nats_client._nats_url == "nats://broker:4222"
        assert caplog.records == []

    async def test_development_falls_back_to_localhost(self, nats_client: NATSClient, mock_config: MagicMock, caplog) -> None:
        self._configure(mock_config, app_environment="development")
        with caplog.at_level(logging.WARNING, logger="blueprint.agents.clients.io.nats_client"):
            await nats_client.on_startup()
        assert nats_client._nats_url == DEVELOPMENT_NATS_URL
        assert "'nats_url' is not set" in caplog.text

    async def test_an_unset_environment_is_development(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """``app_environment`` defaults to development, and this follows the same default."""
        self._configure(mock_config)
        await nats_client.on_startup()
        assert nats_client._nats_url == DEVELOPMENT_NATS_URL

    @pytest.mark.parametrize("url", [None, "", "   "])
    async def test_production_without_a_url_fails(self, nats_client: NATSClient, mock_config: MagicMock, url: str | None) -> None:
        self._configure(mock_config, nats_url=url, app_environment="production")
        with pytest.raises(ValueError, match=r"'nats_url' is not set \(app_environment is 'production'\).*DYNACONF_NATS_URL"):
            await nats_client.on_startup()

    async def test_the_message_names_an_unprefixed_variable(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, app_environment="production")
        mock_config.envvar_prefix = False
        with pytest.raises(ValueError, match="or as NATS_URL"):
            await nats_client.on_startup()

    async def test_connect_uses_the_url_resolved_at_startup(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, nats_url="nats://broker:4222", app_environment="production")
        await nats_client.on_startup()
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=mock_nc) as connect:
            await nats_client.connect()
        assert connect.call_args[0][0] == "nats://broker:4222"

    async def test_connect_without_startup_refuses_too(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """A client connected lazily, before any lifespan, must not reach localhost either."""
        self._configure(mock_config, app_environment="production")
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as connect:
            with pytest.raises(ValueError, match="'nats_url' is not set"):
                await nats_client.connect()
        connect.assert_not_awaited()


class TestNATSClientAuthentication:
    """M2 -- credentials and the inbox prefix reach ``nats.connect()`` from their own keys."""

    URL = "nats://broker:4222"

    @staticmethod
    def _configure(mock_config: MagicMock, **values: object) -> None:
        values.setdefault("nats_url", TestNATSClientAuthentication.URL)
        mock_config.get.side_effect = lambda key, default=None: values.get(key, default)
        mock_config.envvar_prefix = "DYNACONF"

    @staticmethod
    async def _connect_kwargs(client: NATSClient) -> dict:
        await client.on_startup()
        mock_nc = MagicMock(is_closed=False, is_connected=True)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=mock_nc) as connect:
            await client.connect()
        return connect.call_args.kwargs

    async def test_no_credentials_passes_none(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config)
        kwargs = await self._connect_kwargs(nats_client)
        assert not {"user", "password", "token", "user_credentials", "nkeys_seed_str", "inbox_prefix"} & kwargs.keys()

    async def test_user_and_password(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, nats_user="agent", nats_password="YOUR_PASSWORD_HERE")
        kwargs = await self._connect_kwargs(nats_client)
        assert (kwargs["user"], kwargs["password"]) == ("agent", "YOUR_PASSWORD_HERE")

    @pytest.mark.parametrize(("given", "missing"), [({"nats_user": "agent"}, "nats_password"), ({"nats_password": "x"}, "nats_user")])
    async def test_half_a_login_fails_startup(self, nats_client: NATSClient, mock_config: MagicMock, given: dict, missing: str) -> None:
        self._configure(mock_config, **given)
        with pytest.raises(ValueError, match=f"'{missing}' is not set"):
            await nats_client.on_startup()

    async def test_token(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, nats_token="YOUR_TOKEN_HERE")
        assert (await self._connect_kwargs(nats_client))["token"] == "YOUR_TOKEN_HERE"

    async def test_creds_file(self, nats_client: NATSClient, mock_config: MagicMock, tmp_path) -> None:
        creds = tmp_path / "agent.creds"
        creds.write_text("placeholder")
        self._configure(mock_config, nats_creds_file=str(creds))
        with patch("blueprint.agents.clients.io.nats_client.importlib.util.find_spec", return_value=object()):
            kwargs = await self._connect_kwargs(nats_client)
        assert kwargs["user_credentials"] == str(creds)

    async def test_a_creds_file_that_is_not_there_fails_startup(self, nats_client: NATSClient, mock_config: MagicMock, tmp_path) -> None:
        self._configure(mock_config, nats_creds_file=str(tmp_path / "missing.creds"))
        with pytest.raises(ValueError, match="not a file"):
            await nats_client.on_startup()

    async def test_nkey_seed(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, nats_nkey_seed="YOUR_SEED_HERE")
        with patch("blueprint.agents.clients.io.nats_client.importlib.util.find_spec", return_value=object()):
            kwargs = await self._connect_kwargs(nats_client)
        assert kwargs["nkeys_seed_str"] == "YOUR_SEED_HERE"

    async def test_a_seed_without_nkeys_installed_fails_startup(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, nats_nkey_seed="YOUR_SEED_HERE")
        with patch("blueprint.agents.clients.io.nats_client.importlib.util.find_spec", return_value=None):
            with pytest.raises(ValueError, match="needs the 'nkeys' package"):
                await nats_client.on_startup()

    @pytest.mark.parametrize(
        "values",
        [
            {"nats_user": "a", "nats_password": "b", "nats_token": "c"},
            {"nats_token": "c", "nats_nkey_seed": "d"},
            {"nats_url": "nats://a:b@broker:4222", "nats_token": "c"},
        ],
    )
    async def test_two_methods_fail_startup(self, nats_client: NATSClient, mock_config: MagicMock, values: dict) -> None:
        self._configure(mock_config, **values)
        with pytest.raises(ValueError, match="configured more than once"):
            await nats_client.on_startup()

    async def test_credentials_in_the_url_alone_still_work(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, nats_url="nats://a:b@broker:4222")
        await nats_client.on_startup()
        assert nats_client._connect_options == {}

    async def test_inbox_prefix(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, nats_inbox_prefix="_INBOX_risk")
        assert (await self._connect_kwargs(nats_client))["inbox_prefix"] == "_INBOX_risk"

    @pytest.mark.parametrize("prefix", ["_INBOX.*", "_INBOX.risk.", "has space"])
    async def test_an_unusable_inbox_prefix_fails_startup(self, nats_client: NATSClient, mock_config: MagicMock, prefix: str) -> None:
        self._configure(mock_config, nats_inbox_prefix=prefix)
        with pytest.raises(ValueError, match="nats_inbox_prefix"):
            await nats_client.on_startup()

    async def test_nothing_secret_is_logged(self, nats_client: NATSClient, mock_config: MagicMock, caplog) -> None:
        self._configure(mock_config, nats_url="nats://a:YOUR_PASSWORD_HERE@broker:4222")
        with caplog.at_level(logging.DEBUG, logger="blueprint.agents.clients.io.nats_client"):
            await self._connect_kwargs(nats_client)
        assert "YOUR_PASSWORD_HERE" not in caplog.text
        assert "***@broker:4222" in caplog.text


class TestRedactUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("nats://broker:4222", "nats://broker:4222"),
            ("nats://user:secret@broker:4222", "nats://***@broker:4222"),
            ("nats://tokenonly@broker", "nats://***@broker"),
        ],
    )
    def test_userinfo_is_removed(self, url: str, expected: str) -> None:
        assert redact_url(url) == expected

    async def test_the_health_message_does_not_carry_it(self, connected_nats_client: NATSClient) -> None:
        connected_nats_client._nats_client.connected_url = urlparse("nats://user:secret@broker:4222")
        result = await connected_nats_client.health_check()
        assert "secret" not in result.message
        assert "***@broker:4222" in result.message


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
        return _until_settled(nats_client, mock_nats_core.subscribe.await_args.kwargs["cb"])

    async def test_undecodable_payload_is_not_dispatched(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        dispatched = []

        async def _callback(event: CloudEvent, subject: str) -> None:
            dispatched.append(event)

        handler = await self._handler_for(nats_client, mock_nats_core, _callback)

        with caplog.at_level("ERROR"):
            await handler(MagicMock(data=b"not json at all"))

        assert dispatched == []
        assert "unparseable" in caplog.text
        assert "orders.created" in caplog.text

    async def test_the_delivery_subject_reaches_the_callback(self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event) -> None:
        """H1 -- a wildcard subscription passes on the concrete subject the broker routed."""
        received = []

        async def _callback(event: CloudEvent, subject: str) -> None:
            received.append(subject)

        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("t.*.risk.>", _callback)
        handler = _until_settled(nats_client, mock_nats_core.subscribe.await_args.kwargs["cb"])
        await handler(MagicMock(subject="t.T1.risk.created", data=json.dumps(dict(cloud_event)).encode()))

        assert received == ["t.T1.risk.created"]

    async def test_valid_json_that_is_not_a_cloud_event_is_not_dispatched(self, nats_client: NATSClient, mock_nats_core: MagicMock) -> None:
        dispatched = []

        async def _callback(event: CloudEvent, subject: str) -> None:
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
        async def _callback(event: CloudEvent, subject: str) -> None:
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
        async def _callback(event: CloudEvent, subject: str) -> None:
            raise RuntimeError("handler exploded")

        handler = await self._handler_for(nats_client, mock_nats_core, _callback)

        await handler(MagicMock(data=b"garbage"))
        await handler(MagicMock(data=json.dumps(dict(cloud_event)).encode()))

        assert nats_client.inflight_handlers == 0

    async def test_undecodable_payload_releases_the_inflight_slot(self, nats_client: NATSClient, mock_nats_core: MagicMock) -> None:
        async def _callback(event: CloudEvent, subject: str) -> None:
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
        return _until_settled(nats_client, mock_nc.jetstream().subscribe_bind.await_args.kwargs["cb"])

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
        async def _callback(event: CloudEvent, subject: str) -> None:
            raise RetryableHandlerError(status="error", reason="upstream down")

        handler = await self._js_handler(nats_client, mock_nats_jetstream, _callback)
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.nak.assert_awaited_once()
        msg.ack.assert_not_awaited()

    async def test_invalid_event_error_terms(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        async def _callback(event: CloudEvent, subject: str) -> None:
            raise InvalidEventError(status="error", reason="no payload")

        handler = await self._js_handler(nats_client, mock_nats_jetstream, _callback)
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.term.assert_awaited_once()
        msg.nak.assert_not_awaited()

    async def test_critical_error_terms(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        """A critical error is not made less critical by being delivered again."""

        async def _callback(event: CloudEvent, subject: str) -> None:
            raise CriticalHandlerError(status="error", reason="corrupt state")

        handler = await self._js_handler(nats_client, mock_nats_jetstream, _callback)
        msg = self._msg(cloud_event)
        await handler(msg)
        msg.term.assert_awaited_once()

    async def test_unexpected_exception_naks(self, nats_client: NATSClient, mock_nats_jetstream: tuple, cloud_event: CloudEvent) -> None:
        async def _callback(event: CloudEvent, subject: str) -> None:
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
        handler = _until_settled(nats_client, mock_nats_core.subscribe.await_args.kwargs["cb"])
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
        async def _callback(event: CloudEvent, subject: str) -> None:
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

        async def _callback(event: CloudEvent, subject: str) -> None:
            seen_during_handler.append(nats_client.inflight_handlers)

        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("orders.created", _callback)
        message_handler = _until_settled(nats_client, mock_nats_core.subscribe.await_args.kwargs["cb"])

        msg = MagicMock(data=json.dumps(dict(cloud_event)).encode())
        await message_handler(msg)

        assert seen_during_handler == [1]
        assert nats_client.inflight_handlers == 0

    async def test_handler_count_is_released_when_callback_raises(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent, subject: str) -> None:
            raise RuntimeError("handler exploded")

        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("orders.created", _callback)
        message_handler = _until_settled(nats_client, mock_nats_core.subscribe.await_args.kwargs["cb"])

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
        # The publish mode, not the consumption flag: this used to set _use_jetstream, which is
        # the coupling the two keys now separate.
        nats_client._publish_via_jetstream = True

        await nats_client.publish("js-topic", cloud_event)

        mock_js.publish.assert_awaited_once()
        topic_arg = mock_js.publish.call_args[0][0]
        assert topic_arg == "js-topic"

    async def test_durable_consumption_alone_does_not_make_publishing_durable(
        self,
        nats_client: NATSClient,
        mock_nats_jetstream: tuple,
        cloud_event: CloudEvent,
    ) -> None:
        """The separation, stated: `nats_use_jetstream` is about consumers. A client consuming
        durably and publishing fire-and-forget is a legitimate shape, and used to be unreachable.
        """
        mock_nc, mock_js = mock_nats_jetstream
        nats_client._nats_client = mock_nc
        nats_client._client = mock_nc
        nats_client._use_jetstream = True
        nats_client._publish_via_jetstream = False

        await nats_client.publish("core-topic", cloud_event)

        mock_js.publish.assert_not_awaited()
        mock_nc.publish.assert_awaited_once()

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

    async def test_unset_keys_leave_the_server_defaults(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """The framework used to set 300 s / 16 / 5 on every consumer; now it sets nothing unasked."""
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        assert nats_client.consumer_tuning == ConsumerTuning(
            ack_wait=None,
            max_ack_pending=None,
            max_deliver=None,
            dead_letter_subject="test-agent.dead-letter",
        )

    async def test_an_unset_value_is_left_out_of_the_consumer(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        sent = nats_client._consumer_config("orders.created", "orders_created-durable").as_dict()
        assert "max_deliver" not in sent
        assert "max_ack_pending" not in sent

    async def test_an_unset_max_deliver_never_exhausts(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        """The server's default is unlimited, so no delivery is ever the last one."""
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        msg = MagicMock()
        msg.metadata.num_delivered = 1000
        assert nats_client._deliveries_exhausted(msg) is False

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
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_ack_wait=300.0)
        existing = js_api.ConsumerConfig(
            durable_name="orders_created-durable",
            filter_subject="orders.created",
            deliver_subject="_DELIVER.old",
            deliver_group="another-group",
            ack_wait=30.0,
        )
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=existing))
        with caplog.at_level("WARNING"):
            await nats_client._subscribe_one("orders.created", AsyncMock())
        assert "already exists with different settings" in caplog.text
        assert "deliver_group" in caplog.text
        assert "ack_wait" in caplog.text
        assert "DEPRECATED" not in caplog.text

    @staticmethod
    def _pre_09_consumer() -> js_api.ConsumerConfig:
        """What js.subscribe(topic, durable=..., manual_ack=True) left behind before 0.9."""
        return js_api.ConsumerConfig(
            durable_name="orders-durable",
            filter_subject="orders",
            deliver_subject="_INBOX.abc123",
            ack_policy=js_api.AckPolicy.EXPLICIT,
        )

    async def test_a_pre_09_consumer_is_still_used_as_it_is(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders"])
        existing = self._pre_09_consumer()
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=existing))
        await nats_client._subscribe_one("orders", AsyncMock())
        mock_js.add_consumer.assert_not_awaited()
        assert mock_js.subscribe_bind.await_args.kwargs["config"] is existing
        assert mock_js.subscribe_bind.await_args.kwargs["consumer"] == "orders-durable"

    async def test_a_pre_09_consumer_is_announced_as_deprecated(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders"])
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=self._pre_09_consumer()))
        with caplog.at_level("WARNING", logger="blueprint.agents.clients.io.nats_client"):
            await nats_client._subscribe_one("orders", AsyncMock())
        deprecations = [message for message in caplog.messages if message.startswith("DEPRECATED")]
        assert len(deprecations) == 1
        assert "'orders-durable'" in deprecations[0]
        assert "will not be supported in a future release" in deprecations[0]
        # The missing deliver group is the deprecation; it is not reported a second time as drift.
        assert not any("already exists with different settings" in message for message in caplog.messages)

    async def test_an_unset_value_is_not_reported_as_drift(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Configuring nothing asks for nothing; the broker's value is not a difference."""
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        existing = nats_client._consumer_config("orders.created", "orders_created-durable")
        existing.ack_wait, existing.max_deliver = 30.0, 7
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=existing))
        with caplog.at_level("WARNING"):
            await nats_client._subscribe_one("orders.created", AsyncMock())
        assert "already exists" not in caplog.text

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
        return _until_settled(nats_client, mock_nc.jetstream().subscribe_bind.await_args.kwargs["cb"])

    async def test_terminal_failure_is_dead_lettered_then_termed(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent, subject: str) -> None:
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
        async def _callback(event: CloudEvent, subject: str) -> None:
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
        async def _callback(event: CloudEvent, subject: str) -> None:
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

        async def _callback(event: CloudEvent, subject: str) -> None:
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
        async def _callback(event: CloudEvent, subject: str) -> None:
            raise RetryableHandlerError(status="error", reason="upstream down")

        handler = await self._handler(nats_client, mock_config, mock_nats_jetstream, _callback, nats_max_deliver=-1)
        msg = self._msg(json.dumps(dict(cloud_event)).encode(), num_delivered=99)
        await handler(msg)
        msg.nak.assert_awaited_once()

    async def test_unreadable_metadata_costs_a_retry_not_a_payload(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def _callback(event: CloudEvent, subject: str) -> None:
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

    @staticmethod
    def _jetstream_client(client: NATSClient, mock_nats_jetstream: tuple) -> MagicMock:
        """A managed JetStream client whose broker connection replays its subscriptions, as nats-py does."""
        mock_nc, _ = mock_nats_jetstream
        mock_nc._subs = {}
        client._nats_client = mock_nc
        client._client = mock_nc
        client._use_jetstream = True
        client._subscriptions_managed = True
        client._subscriptions_ready = False
        client._topic_callbacks = {"topic.a": AsyncMock(), "topic.b": AsyncMock()}
        return mock_nc

    async def test_a_reconnect_subscribes_nothing_again_under_jetstream(
        self, connected_nats_client: NATSClient, mock_nats_jetstream: tuple
    ) -> None:
        """M1 -- nats-py replays every subscription in ``_subs``; subscribing again left an orphan per topic.

        The orphan joined the deliver group next to the replayed one, so it took a share of the
        deliveries, and no pause, drain or close knew of it.
        """
        mock_nc = self._jetstream_client(connected_nats_client, mock_nats_jetstream)
        mock_nc._subs = {1: "topic.a (replayed)", 2: "topic.b (replayed)"}

        with (
            patch.object(connected_nats_client, "_subscribe_one", new_callable=AsyncMock) as subscribe_one,
            patch.object(connected_nats_client, "_provision_stream", new_callable=AsyncMock) as provision,
            patch.object(connected_nats_client, "_ensure_consumer", new_callable=AsyncMock) as ensure_consumer,
        ):
            await connected_nats_client._on_reconnected()

        subscribe_one.assert_not_awaited()
        assert len(mock_nc._subs) == 2, "only nats-py's replayed subscriptions"
        provision.assert_awaited_once()
        assert [call.args[0] for call in ensure_consumer.await_args_list] == ["topic.a", "topic.b"]
        assert connected_nats_client.subscriptions_ready is True

    async def test_a_failed_recheck_after_a_reconnect_leaves_it_unready(
        self, connected_nats_client: NATSClient, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._jetstream_client(connected_nats_client, mock_nats_jetstream)
        with (
            patch.object(connected_nats_client, "_provision_stream", new_callable=AsyncMock, side_effect=OSError("stream gone")),
            caplog.at_level("ERROR"),
        ):
            await connected_nats_client._on_reconnected()

        assert connected_nats_client.subscriptions_ready is False
        assert "re-checking the JetStream stream and consumers after a reconnect failed" in caplog.text


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

    def test_a_standalone_agent_is_named_after_its_pod_alone(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """No namespace and no group exist for it, so the name implies neither."""
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        monkeypatch.setenv("POD_NAME", "pod-1")
        assert nats_client._resolve_connection_name() == "pod-1"

    def test_pod_name_wins_over_hostname(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        monkeypatch.setenv("POD_NAME", "from-downward-api")
        monkeypatch.setenv("HOSTNAME", "from-kubelet")
        assert nats_client._resolve_connection_name() == "from-downward-api"

    def test_hostname_is_used_when_pod_name_is_absent(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.setenv("HOSTNAME", "from-kubelet")
        assert nats_client._resolve_connection_name() == "from-kubelet"

    def test_falls_back_to_the_host_name(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)
        monkeypatch.setattr("blueprint.agents.deployment.socket.gethostname", lambda: "laptop")
        assert nats_client._resolve_connection_name() == "laptop"

    def test_an_unresolvable_host_sends_no_name_when_standalone(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Not a name made only of a placeholder: nothing, as before the namespace feature."""
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)

        def _raise() -> str:
            raise OSError("no host name")

        monkeypatch.setattr("blueprint.agents.deployment.socket.gethostname", _raise)
        assert nats_client._resolve_connection_name() == ""

    async def test_no_name_reaches_nats_then(self, nats_client: NATSClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)

        def _raise() -> str:
            raise OSError("no host name")

        monkeypatch.setattr("blueprint.agents.deployment.socket.gethostname", _raise)
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = MagicMock(is_closed=False, is_connected=True)
            await nats_client.connect()
        assert mock_connect.call_args[1]["name"] is None

    def test_an_agent_with_a_namespace_keeps_every_position(self, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """The spec's form, placeholders included, wherever a namespace or a group exists."""
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)

        def _raise() -> str:
            raise OSError("no host name")

        monkeypatch.setattr("blueprint.agents.deployment.socket.gethostname", _raise)
        assert _namespaced_client(mock_config, "orders")._resolve_connection_name() == "orders.<ungrouped>.<unknown-pod>"

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

    def test_an_fqdn_hostname_stays_one_segment(self, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.setenv("HOSTNAME", "web-7.eu.internal")
        name = _namespaced_client(mock_config, "orders")._resolve_connection_name()
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


class TestAPauseBeforeSubscribing:
    """C4 for an agent marked down in the client phase, before its endpoint subscribes (spec sec. 9.1).

    The pause used to be enforced only on a client that already had subscriptions to drain. A
    non-critical agent whose client failed ``on_startup`` is paused first and subscribed second,
    and the retry loop ignored the flag -- so the latched-down agent consumed events.
    """

    TOPICS = {"orders.created": AsyncMock()}

    @staticmethod
    def _configure(mock_config: MagicMock) -> None:
        values = {"app_name": "orders", "nats_url": "nats://broker:4222", "app_environment": "production"}
        mock_config.get.side_effect = lambda key, default=None: values.get(key, default)
        mock_config.envvar_prefix = "DYNACONF"

    @staticmethod
    def _broker() -> MagicMock:
        nc = MagicMock(is_closed=False, is_connected=True)
        nc.subscribe = AsyncMock(return_value=MagicMock())
        return nc

    async def test_a_paused_client_does_not_subscribe(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config)
        await nats_client.pause_consumption()
        nc = self._broker()
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=nc) as connect:
            await nats_client.subscribe(self.TOPICS)
            await asyncio.sleep(0)
        connect.assert_not_awaited()
        nc.subscribe.assert_not_awaited()
        assert nats_client._retry_task is None
        assert nats_client.subscriptions_ready is False

    async def test_releasing_it_connects_and_subscribes(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config)
        await nats_client.pause_consumption()
        nc = self._broker()
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=nc):
            await nats_client.subscribe(self.TOPICS)
            await nats_client.resume_consumption()
            await nats_client._retry_task
        nc.subscribe.assert_awaited_once()
        assert nats_client.subscriptions_ready is True

    async def test_a_pause_while_connecting_subscribes_nothing(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Marked down by a later component of the same agent while the loop is still connecting."""
        self._configure(mock_config)
        nc = self._broker()

        async def _slow_connect(*_args, **_kwargs):
            await nats_client.pause_consumption()
            return nc

        with patch("blueprint.agents.clients.io.nats_client.nats.connect", side_effect=_slow_connect):
            await nats_client.subscribe(self.TOPICS)
            await nats_client._retry_task
        nc.subscribe.assert_not_awaited()
        assert nats_client.subscriptions_ready is False

        await nats_client.resume_consumption()
        nc.subscribe.assert_awaited_once()
        assert nats_client.subscriptions_ready is True


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

    async def test_a_failed_resume_stays_paused_and_retries(self, subscribed: NATSClient) -> None:
        """M2 -- nothing else calls resume again: a paused client is healthy, so the supervisor sees no transition."""
        await subscribed.pause_consumption()
        with patch.object(subscribed, "_subscribe_all", new=AsyncMock(side_effect=RuntimeError("no"))):
            await subscribed.resume_consumption()
        assert subscribed.consumption_paused is True
        assert subscribed.subscriptions_ready is False
        assert subscribed._resume_retry is not None and not subscribed._resume_retry.done()
        await subscribed.close()

    @staticmethod
    def _fast_retries(mock_config: MagicMock) -> None:
        base = mock_config.get.side_effect
        mock_config.get.side_effect = lambda key, default=None: 0.01 if key == "event_client_retry_delay" else base(key, default)

    async def test_the_retry_resumes_once_subscribing_works(
        self, subscribed: NATSClient, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._fast_retries(mock_config)
        await subscribed.pause_consumption()
        partial = MagicMock(unsubscribe=AsyncMock())

        async def fail_after_one_subscription() -> None:
            subscribed._subscriptions.append(partial)
            raise RuntimeError("stream not there yet")

        outcomes = [fail_after_one_subscription, fail_after_one_subscription]

        async def subscribe_all() -> None:
            if outcomes:
                await outcomes.pop(0)()

        with patch.object(subscribed, "_subscribe_all", new=subscribe_all), caplog.at_level(logging.WARNING):
            await subscribed.resume_consumption()
            await asyncio.wait_for(subscribed._resume_retry, timeout=5)  # type: ignore[arg-type]

        assert subscribed.consumption_paused is False
        assert subscribed.subscriptions_ready is True
        assert partial.unsubscribe.await_count == 2, "each failed attempt drops what it subscribed"
        assert subscribed._subscriptions == []
        assert "attempt 1" in caplog.text and "attempt 2" in caplog.text

    async def test_a_pause_stops_the_retry(self, subscribed: NATSClient, mock_config: MagicMock) -> None:
        await subscribed.pause_consumption()
        with patch.object(subscribed, "_subscribe_all", new=AsyncMock(side_effect=RuntimeError("no"))):
            await subscribed.resume_consumption()
            retry = subscribed._resume_retry
            await subscribed.pause_consumption()
        assert retry is not None and retry.cancelled()
        assert subscribed._resume_retry is None
        assert subscribed.consumption_paused is True

    async def test_close_stops_the_retry(self, subscribed: NATSClient) -> None:
        await subscribed.pause_consumption()
        with patch.object(subscribed, "_subscribe_all", new=AsyncMock(side_effect=RuntimeError("no"))):
            await subscribed.resume_consumption()
            retry = subscribed._resume_retry
        await subscribed.close()
        assert retry is not None and retry.cancelled()

    async def test_the_supervisor_and_the_client_recover_together(self, subscribed: NATSClient, mock_config: MagicMock) -> None:
        """M2 end to end in the process: one health transition, a failed resume, and the agent consumes again."""
        from blueprint.agents.io.api.actuators.health.namespace_supervisor import NamespaceSupervisor

        self._fast_retries(mock_config)
        registry = MagicMock()
        registry.get_io_clients.side_effect = lambda namespace=None: [subscribed]
        registry.get_components_by_type.return_value = []
        supervisor = NamespaceSupervisor(registry, [""])
        failures = [RuntimeError("stream not there yet")]

        async def subscribe_all() -> None:
            if failures:
                raise failures.pop(0)

        with patch.object(subscribed, "_subscribe_all", new=subscribe_all):
            await supervisor.observe({"": False})
            assert subscribed.consumption_paused is True
            await supervisor.observe({"": True})
            assert (await subscribed.health_check()).status == "healthy", "green while it retries: the bug's disguise"
            await asyncio.wait_for(subscribed._resume_retry, timeout=5)  # type: ignore[arg-type]
            await supervisor.observe({"": True})  # no transition, so the supervisor itself does nothing more

        assert subscribed.consumption_paused is False
        assert subscribed.subscriptions_ready is True

    async def test_a_reconnect_does_not_undo_a_pause(self, subscribed: NATSClient) -> None:
        """Otherwise C4 would hold only until the next network blip."""
        subscribed._use_jetstream = True
        await subscribed.pause_consumption()
        with patch.object(subscribed, "_subscribe_all", new=AsyncMock()) as subscribe_all:
            await subscribed._on_reconnected()
        subscribe_all.assert_not_awaited()
        assert subscribed.subscriptions_ready is False


class TestNATSClientPublishMode:
    """Publishing and consuming are two decisions, and used to share one key.

    ``nats_use_jetstream`` exists so *consumers* can be durable. ``publish()`` read the same
    flag, so turning durability on for consumption silently made every outbound event a
    JetStream publish -- which stalls and is dropped when the subject is not in the stream.
    """

    def test_it_follows_the_consumption_flag_when_unset(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """No existing deployment changes: unset, the behaviour is exactly what it was."""
        mock_config.get.side_effect = lambda key, default=None: {"nats_publish_mode": None}.get(key, default)
        nats_client._use_jetstream = True

        assert nats_client._resolve_publish_mode() is True

    def test_core_can_be_chosen_while_consuming_durably(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """The case the split exists for: durable consumption, fire-and-forget notifications."""
        mock_config.get.side_effect = lambda key, default=None: {"nats_publish_mode": "core"}.get(key, default)
        nats_client._use_jetstream = True

        assert nats_client._resolve_publish_mode() is False

    def test_jetstream_can_be_chosen_while_consuming_from_core(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: {"nats_publish_mode": "JetStream "}.get(key, default)
        nats_client._use_jetstream = False

        assert nats_client._resolve_publish_mode() is True

    def test_an_unknown_mode_is_refused_with_both_meanings(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: {"nats_publish_mode": "durable"}.get(key, default)

        with pytest.raises(ValueError, match="must be 'core' or 'jetstream'"):
            nats_client._resolve_publish_mode()


class TestNATSClientPublishSubjects:
    """What the client declares it may publish to, and what the stream therefore carries."""

    @staticmethod
    def _config(mock_config: MagicMock, **values: object) -> None:
        mock_config.get.side_effect = lambda key, default=None: values.get(key, default)

    def test_the_configured_topic_mapping_is_the_source(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Where an outbound subject is already written down: a HandlerResult is routed by it."""
        self._config(
            mock_config,
            **{"event_publishing.topic_mapping": {"order.validated": {"topic": "orders.validated"}}},
        )

        assert nats_client._resolve_publish_subjects() == {"orders.validated"}

    def test_an_explicit_list_covers_what_the_mapping_cannot(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """``publish_event(topic=...)`` bypasses the mapping, so it needs somewhere to be said."""
        self._config(mock_config, nats_publish_subjects=["audit.trail"])

        assert nats_client._resolve_publish_subjects() == {"audit.trail"}

    def test_a_wildcard_topic_is_refused(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Published, a wildcard is taken literally: the message lands on a subject with an
        asterisk in it and no subscriber to the pattern receives it."""
        self._config(mock_config, **{"event_publishing.topic_mapping": {"order.validated": {"topic": "orders.*"}}})

        with pytest.raises(ValueError, match="only meaningful when subscribing"):
            nats_client._resolve_publish_subjects()

    def test_a_greater_than_wildcard_is_refused_too(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._config(mock_config, nats_publish_subjects=["orders.>"])

        with pytest.raises(ValueError, match="cannot be published to"):
            nats_client._resolve_publish_subjects()

    def test_whitespace_is_refused(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._config(mock_config, nats_publish_subjects=["orders validated"])

        with pytest.raises(ValueError, match="cannot be published to"):
            nats_client._resolve_publish_subjects()

    def test_the_stream_carries_what_is_published_durably(self, nats_client: NATSClient) -> None:
        """The defect this closes: the stream covered what was subscribed and nothing else, so a
        JetStream publish waited for an acknowledgement no stream would send."""
        nats_client._topic_callbacks = {"orders.created": AsyncMock()}
        nats_client._publish_subjects = {"orders.validated"}
        nats_client._publish_via_jetstream = True

        assert "orders.validated" in nats_client._stream_subjects()

    def test_the_stream_does_not_carry_them_when_publishing_is_fire_and_forget(self, nats_client: NATSClient) -> None:
        """Core publishing stores nothing, so widening the stream for it would claim subjects
        this deployment has no reason to own."""
        nats_client._topic_callbacks = {"orders.created": AsyncMock()}
        nats_client._publish_subjects = {"orders.validated"}
        nats_client._publish_via_jetstream = False

        assert "orders.validated" not in nats_client._stream_subjects()


class TestStreamSubjectCoverage:
    """A wildcard on the stream already carries the literals underneath it.

    Compared as strings they look absent, so the client asked the server to add them and the
    server refused the update as an overlap -- and the client then logged that consumers would
    fail to bind, when the wildcard means they bind fine. The message was the defect.
    """

    @pytest.mark.parametrize(
        ("subject", "pattern", "covered"),
        [
            ("orders.created", "orders.created", True),
            ("orders.created", "orders.>", True),
            ("orders.created", "orders.*", True),
            ("orders.created.eu", "orders.>", True),
            ("orders.created.eu", "orders.*", False),
            ("orders.created", "billing.>", False),
            ("orders", "orders.>", False),
            ("orders.created", "*.created", True),
            ("orders.created", "orders.created.>", False),
        ],
    )
    def test_coverage(self, subject: str, pattern: str, covered: bool) -> None:
        assert subject_is_covered_by(subject, pattern) is covered

    def test_a_wildcard_stream_needs_no_widening(self, nats_client: NATSClient) -> None:
        """The case the harness hits every run: an operator-provisioned `orders.>` stream, and a
        client subscribing a literal beneath it. Every subject it wants is already carried."""
        nats_client._topic_callbacks = {"orders.created": AsyncMock()}
        nats_client._tuning = None

        wanted = {subject for subject in nats_client._stream_subjects() if subject.startswith("orders.")}

        assert wanted, "the client wanted no subjects at all, so this asserts nothing"
        assert all(subject_is_covered_by(subject, "orders.>") for subject in wanted)


class TestTheDeclaredModeIsEnforced:
    """D -- nats_use_jetstream is a declaration: a server without JetStream fails the agent.

    It used to be a wish. connection.jetstream() asks the server nothing, and the rare failure it
    did catch fell back to Core NATS -- no durable consumers, no settlement -- without anyone
    deciding it.
    """

    @staticmethod
    def _configure(mock_config: MagicMock, *, jetstream: bool) -> None:
        values = {"app_name": "orders", "nats_url": "nats://broker:4222", "app_environment": "production", "nats_use_jetstream": jetstream}
        mock_config.get.side_effect = lambda key, default=None: values.get(key, default)
        mock_config.envvar_prefix = "DYNACONF"

    @staticmethod
    def _server(account_info: AsyncMock) -> MagicMock:
        js = MagicMock()
        js.account_info = account_info
        nc = MagicMock(is_closed=False, is_connected=True)
        nc.jetstream = MagicMock(return_value=js)
        nc.close = AsyncMock()
        return nc

    async def _connect(self, client: NATSClient, nc: MagicMock) -> None:
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=nc):
            await client.connect()

    @pytest.mark.parametrize(
        "answer",
        [
            ServiceUnavailableError(),
            NoRespondersError(),
            APIError(code=503, err_code=10039, description="jetstream not enabled for account"),
        ],
        ids=["no-jetstream-on-server", "no-responders", "not-enabled-for-account"],
    )
    async def test_a_server_without_jetstream_fails_the_connection(
        self, nats_client: NATSClient, mock_config: MagicMock, answer: Exception
    ) -> None:
        self._configure(mock_config, jetstream=True)
        nc = self._server(AsyncMock(side_effect=answer))
        with pytest.raises(JetStreamUnavailableError, match="nats_use_jetstream = true"):
            await self._connect(nats_client, nc)
        nc.close.assert_awaited_once()
        assert nats_client._nats_client is None
        assert nats_client._use_jetstream is True

    async def test_it_is_reported_by_the_health_check(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, jetstream=True)
        with pytest.raises(JetStreamUnavailableError):
            await self._connect(nats_client, self._server(AsyncMock(side_effect=ServiceUnavailableError())))
        health = await nats_client.health_check()
        assert health.status == "unhealthy"
        assert "does not offer JetStream" in (health.message or "")

    async def test_a_timeout_is_not_an_answer(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """No reply proves nothing; it stays an ordinary, retried connection failure."""
        self._configure(mock_config, jetstream=True)
        with pytest.raises(NatsTimeoutError):
            await self._connect(nats_client, self._server(AsyncMock(side_effect=NatsTimeoutError())))
        assert nats_client._jetstream_mismatch is None

    async def test_a_server_with_jetstream_connects(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, jetstream=True)
        await self._connect(nats_client, self._server(AsyncMock()))
        assert nats_client._js is not None

    async def test_core_asks_the_server_nothing(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Core NATS works on every server; JetStream being enabled there does not matter."""
        self._configure(mock_config, jetstream=False)
        info = AsyncMock()
        await self._connect(nats_client, self._server(info))
        info.assert_not_awaited()

    async def test_the_retry_loop_does_not_retry_it(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, jetstream=True)
        connect = AsyncMock(return_value=self._server(AsyncMock(side_effect=ServiceUnavailableError())))
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", connect):
            with pytest.raises(JetStreamUnavailableError):
                await nats_client._start_with_retry()
        connect.assert_awaited_once()

    async def test_startup_fails_when_a_poll_found_it_first(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """The actuator's first health poll connects every client before any component starts."""
        self._configure(mock_config, jetstream=True)
        nc = self._server(AsyncMock(side_effect=ServiceUnavailableError()))
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=nc):
            with pytest.raises(JetStreamUnavailableError):
                await nats_client.connect()
            with pytest.raises(JetStreamUnavailableError):
                await nats_client.on_startup()

    async def test_a_retried_startup_sees_a_fixed_server(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, jetstream=True)
        with pytest.raises(JetStreamUnavailableError):
            await self._connect(nats_client, self._server(AsyncMock(side_effect=ServiceUnavailableError())))
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=self._server(AsyncMock())):
            await nats_client.on_startup()
        assert nats_client._jetstream_mismatch is None

    async def test_after_startup_it_goes_to_the_fatal_handler_once(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, jetstream=True)
        handler = AsyncMock()
        nats_client.set_fatal_handler(handler)
        await nats_client.on_startup()
        for _ in range(3):
            with pytest.raises(JetStreamUnavailableError):
                await self._connect(nats_client, self._server(AsyncMock(side_effect=ServiceUnavailableError())))
        await asyncio.sleep(0)
        handler.assert_awaited_once()
        assert handler.await_args.args[0] == nats_client.namespace

    async def test_before_startup_it_is_left_to_on_startup(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        self._configure(mock_config, jetstream=True)
        handler = AsyncMock()
        nats_client.set_fatal_handler(handler)
        with pytest.raises(JetStreamUnavailableError):
            await self._connect(nats_client, self._server(AsyncMock(side_effect=ServiceUnavailableError())))
        await asyncio.sleep(0)
        handler.assert_not_awaited()


# ---------------------------------------------------------------------------
# A standalone agent logs what v0.8.1 logged
# ---------------------------------------------------------------------------


class TestStandaloneLogLines:
    """No connection name, no queue group, no durable, no '<root>' in a standalone agent's lines."""

    async def test_the_connect_line(self, nats_client: NATSClient, caplog: pytest.LogCaptureFixture) -> None:
        nc = MagicMock(is_closed=False, is_connected=True)
        with (
            patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=nc),
            caplog.at_level("INFO", logger="blueprint.agents.clients.io.nats_client"),
        ):
            await nats_client.connect()
        assert "Connected to NATS server (Core NATS) at nats://localhost:4222" in caplog.messages
        assert not any("<root>" in message for message in caplog.messages)

    async def test_the_subscribe_line(self, connected_nats_client: NATSClient, caplog: pytest.LogCaptureFixture) -> None:
        connected_nats_client._queue_group = "test-agent"
        with caplog.at_level("INFO", logger="blueprint.agents.clients.io.nats_client"):
            await connected_nats_client._subscribe_one("orders.created", AsyncMock())
        assert caplog.messages == ["Subscribed to Core NATS topic 'orders.created'"]


def _delivery(cloud_event: CloudEvent) -> MagicMock:
    """A JetStream delivery whose settlement and heartbeat calls are recorded in one order."""
    msg = MagicMock(data=json.dumps(dict(cloud_event)).encode(), reply="$JS.ACK.x", subject="orders.created")
    for name in ("ack", "nak", "term", "in_progress"):
        setattr(msg, name, AsyncMock())
    msg.metadata.num_delivered = 1
    return msg


async def _js_delivery_handler(nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, callback, **overrides: object):
    """The raw broker callback of one JetStream subscription, with the given config overrides."""
    await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], **overrides)
    await nats_client._subscribe_one("orders.created", callback)
    mock_nc, _ = mock_nats_jetstream
    return mock_nc.jetstream().subscribe_bind.await_args.kwargs["cb"]


class TestAPausedAgentRunsNothing:
    """N4 -- a delivery that reaches a paused agent is nak'd under JetStream, never run."""

    async def test_a_jetstream_delivery_is_nakd_without_running(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        ran: list[str] = []

        async def callback(event: CloudEvent, subject: str) -> None:
            ran.append(event.id)

        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, callback)
        nats_client._consumption_paused = True
        msg = _delivery(cloud_event)

        await handler(msg)
        await asyncio.gather(*list(nats_client._runs), return_exceptions=True)

        assert ran == []
        msg.nak.assert_awaited_once()
        msg.ack.assert_not_awaited()

    async def test_a_core_nats_message_in_the_buffer_still_runs(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        """Core NATS cannot nak; what the drain lets through is handled, as before."""
        ran: list[str] = []

        async def callback(event: CloudEvent, subject: str) -> None:
            ran.append(event.id)

        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("orders.created", callback)
        handler = _until_settled(nats_client, mock_nats_core.subscribe.await_args.kwargs["cb"])
        nats_client._consumption_paused = True

        await handler(MagicMock(subject="orders.created", data=json.dumps(dict(cloud_event)).encode()))

        assert ran == [cloud_event.id]


class TestConcurrentRuns:
    """Deliveries run as tasks of their own, up to nats_max_concurrent_runs per binding."""

    @staticmethod
    async def _started_while_blocked(
        handler, nats_client: NATSClient, cloud_event: CloudEvent, deliveries: int, gate: asyncio.Event, started: list
    ):
        callers = [asyncio.create_task(handler(_delivery(cloud_event))) for _ in range(deliveries)]
        for _ in range(20):
            await asyncio.sleep(0)
        running = len(started)
        gate.set()
        await asyncio.gather(*callers)
        await asyncio.gather(*list(nats_client._runs), return_exceptions=True)
        return running

    @staticmethod
    def _blocking_callback(gate: asyncio.Event, started: list):
        async def callback(event: CloudEvent, subject: str) -> None:
            started.append(event.id)
            await gate.wait()

        return callback

    async def test_runs_up_to_the_configured_number_at_once(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        gate, started = asyncio.Event(), []
        handler = await _js_delivery_handler(
            nats_client, mock_config, mock_nats_jetstream, self._blocking_callback(gate, started), nats_max_concurrent_runs=2
        )
        running = await self._started_while_blocked(handler, nats_client, cloud_event, 3, gate, started)
        assert running == 2
        assert len(started) == 3, "the third delivery runs once a slot is free"

    async def test_one_at_a_time_when_not_configured(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        gate, started = asyncio.Event(), []
        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, self._blocking_callback(gate, started))
        assert await self._started_while_blocked(handler, nats_client, cloud_event, 3, gate, started) == 1

    async def test_the_slot_is_freed_and_the_run_counted_out(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, AsyncMock(side_effect=RuntimeError("boom")))
        await _until_settled(nats_client, handler)(_delivery(cloud_event))
        assert nats_client.inflight_handlers == 0
        assert nats_client._binding.slots_for("orders.created").locked() is False

    async def test_unset_keeps_one_run_per_subscription(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        """Before the key existed each subscription ran one delivery at a time, independently of the others."""
        assert await self._two_topics_at_once(nats_client, mock_config, mock_nats_jetstream, cloud_event) == 2

    async def test_set_the_subscriptions_share_the_runs(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        assert await self._two_topics_at_once(nats_client, mock_config, mock_nats_jetstream, cloud_event, nats_max_concurrent_runs=1) == 1

    async def _two_topics_at_once(self, nats_client, mock_config, mock_nats_jetstream, cloud_event, **overrides) -> int:
        gate, started = asyncio.Event(), []
        callback = self._blocking_callback(gate, started)
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created", "orders.cancelled"], **overrides)
        mock_nc, _ = mock_nats_jetstream
        handlers = []
        for topic in ("orders.created", "orders.cancelled"):
            await nats_client._subscribe_one(topic, callback)
            handlers.append(mock_nc.jetstream().subscribe_bind.await_args.kwargs["cb"])
        callers = [asyncio.create_task(handler(_delivery(cloud_event))) for handler in handlers]
        for _ in range(20):
            await asyncio.sleep(0)
        running = len(started)
        gate.set()
        await asyncio.gather(*callers)
        await asyncio.gather(*list(nats_client._runs), return_exceptions=True)
        return running

    @pytest.mark.parametrize("value", [0, -1])
    async def test_fewer_than_one_run_is_refused(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, value: int
    ) -> None:
        with pytest.raises(ValueError, match="nats_max_concurrent_runs"):
            await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_max_concurrent_runs=value)


class TestHeartbeat:
    """A running JetStream delivery reports in_progress every third of the consumer's ack_wait."""

    async def test_a_long_run_reports_progress_and_stops_before_settling(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def slow(event: CloudEvent, subject: str) -> None:
            await asyncio.sleep(0.1)

        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, slow, nats_ack_wait=0.03)
        msg = _delivery(cloud_event)
        order = MagicMock()
        order.attach_mock(msg.in_progress, "in_progress")
        order.attach_mock(msg.ack, "ack")
        await _until_settled(nats_client, handler)(msg)

        calls = [name for name, _, _ in order.mock_calls]
        assert calls.count("in_progress") >= 2
        assert calls[-1] == "ack", "no heartbeat after the delivery is settled"

    async def test_a_short_run_sends_none(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, AsyncMock(), nats_ack_wait=30.0)
        msg = _delivery(cloud_event)
        await _until_settled(nats_client, handler)(msg)
        msg.in_progress.assert_not_awaited()

    async def test_it_can_be_switched_off(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def slow(event: CloudEvent, subject: str) -> None:
            await asyncio.sleep(0.1)

        handler = await _js_delivery_handler(
            nats_client, mock_config, mock_nats_jetstream, slow, nats_ack_wait=0.03, nats_heartbeat_enabled=False
        )
        msg = _delivery(cloud_event)
        await _until_settled(nats_client, handler)(msg)
        msg.in_progress.assert_not_awaited()
        msg.ack.assert_awaited_once()

    async def test_a_string_is_not_a_switch(self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple) -> None:
        """'false' as a string would read as true and keep the heartbeat the operator meant to switch off."""
        with pytest.raises(ValueError, match="nats_heartbeat_enabled"):
            await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_heartbeat_enabled="false")


class TestAClosedConnectionComesBack:
    """Review finding #10: after its reconnect attempts the client closed for good and never resubscribed."""

    async def test_reconnect_attempts_are_unlimited_by_default(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        base = mock_config.get.side_effect
        mock_config.get.side_effect = lambda key, default=None: default if key == "nats_max_reconnect_attempts" else base(key, default)
        connection = MagicMock(options={})
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=connection) as mock_connect:
            await nats_client.connect()
        assert connection.options["max_reconnect_attempts"] == -1, "reconnects of the established connection"
        assert mock_connect.await_args.kwargs["closed_cb"] == nats_client._on_closed

    async def test_the_first_connect_is_bounded_even_when_reconnects_are_not(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """N11 -- nats-py applies the count to the first connect too; unlimited, it never returned and startup hung."""
        base = mock_config.get.side_effect
        mock_config.get.side_effect = lambda key, default=None: default if key == "nats_max_reconnect_attempts" else base(key, default)
        with patch(
            "blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock, return_value=MagicMock(options={})
        ) as mock_connect:
            await nats_client.connect()
        assert mock_connect.await_args.kwargs["max_reconnect_attempts"] == 1

    @pytest.mark.parametrize(("configured", "first"), [(-1, 1), (0, 1), (5, 5)])
    def test_first_connect_attempts(self, configured: int, first: int) -> None:
        assert NATSClient._first_connect_attempts(configured) == first

    async def test_a_broker_that_is_not_there_fails_the_first_connect(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Against a port nobody listens on, connect() raises instead of retrying inside nats-py for ever."""
        base = mock_config.get.side_effect
        overrides = {"nats_reconnect_time_wait": 0}
        mock_config.get.side_effect = lambda key, default=None: (
            default if key == "nats_max_reconnect_attempts" else overrides.get(key, base(key, default))
        )
        nats_client._nats_url = "nats://127.0.0.1:1"
        with pytest.raises(Exception) as caught:
            await asyncio.wait_for(nats_client.connect(), timeout=20)
        assert not isinstance(caught.value, TimeoutError), "connect() never returned"

    async def test_a_closed_connection_restarts_the_retry_loop(self, nats_client: NATSClient) -> None:
        nats_client._subscriptions_managed = True
        nats_client._subscriptions_ready = True
        with patch.object(nats_client, "_start_retry_task") as start:
            await nats_client._on_closed()
        start.assert_called_once()
        assert nats_client.subscriptions_ready is False

    async def test_a_paused_agent_is_reconnected_too(self, nats_client: NATSClient) -> None:
        """Resume needs a healthy, connected client; the loop connects and subscribes nothing while paused."""
        nats_client._subscriptions_managed = True
        nats_client._consumption_paused = True
        with patch.object(nats_client, "_start_retry_task") as start:
            await nats_client._on_closed()
            await nats_client.connect()
        assert start.call_count == 2

    @pytest.mark.parametrize("state", ["closing", "unmanaged"])
    async def test_not_restarted_when_it_should_not_consume(self, nats_client: NATSClient, state: str) -> None:
        nats_client._subscriptions_managed = state != "unmanaged"
        nats_client._closing = state == "closing"
        nats_client._consumption_paused = state == "paused"
        with patch.object(nats_client, "_start_retry_task") as start:
            await nats_client._on_closed()
        start.assert_not_called()

    async def test_the_health_check_never_opens_a_connection_that_subscribes_to_nothing(self, nats_client: NATSClient) -> None:
        """Once subscriptions are managed, connect() from outside only makes sure the retry loop runs."""
        nats_client._subscriptions_managed = True
        with (
            patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as mock_connect,
            patch.object(nats_client, "_start_retry_task") as start,
        ):
            await nats_client.connect()
        mock_connect.assert_not_awaited()
        start.assert_called_once()


_SECRET = "PLACEHOLDER-SECRET-VALUE"


class TestNoCredentialOrPayloadInLogs:
    """B2/S4/N3 -- what a transport logs about a failure names where and what, never a value or a credential."""

    async def test_an_unparseable_payload_logs_the_field_not_the_value(self, caplog: pytest.LogCaptureFixture) -> None:
        payload = {"specversion": "1.0", "id": {"token": _SECRET}, "source": "s", "type": "t"}
        with caplog.at_level("DEBUG"):
            event = NATSClient._decode_message(MagicMock(data=json.dumps(payload).encode()), "orders.created")
        assert event is None
        assert _SECRET not in caplog.text
        assert "id: string_type" in caplog.text

    def test_a_link_and_its_binding_render_no_credential(self) -> None:
        link = _Link(name="A", url=f"nats://u:{_SECRET}@h:4222", connect_options={"user": "u", "password": _SECRET})
        assert _SECRET not in repr(link)
        assert _SECRET not in repr(_Binding(link=link))
        assert "name='A'" in repr(link)

    async def test_a_failed_attempt_of_the_default_connection_is_logged_redacted(
        self, nats_client: NATSClient, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_config.get.side_effect = lambda k, d=None: {"event_client_max_retries": 1, "event_client_retry_delay": 0.0}.get(k, d)
        nats_client._nats_url = f"nats://u:{_SECRET}@h:4222"
        nats_client._connect_options = {"token": "PLACEHOLDER-TOKEN"}
        failure = OSError(f"could not reach nats://u:{_SECRET}@h:4222 with PLACEHOLDER-TOKEN")
        nats_client._subscriptions_managed = True
        with (
            patch.object(nats_client, "_connect_and_subscribe", new_callable=AsyncMock, side_effect=failure),
            caplog.at_level("DEBUG"),
        ):
            task = asyncio.ensure_future(nats_client._start_with_retry())
            await asyncio.gather(task, return_exceptions=True)
            nats_client._on_retry_done(task)
        assert "attempt 1 failed" in caplog.text
        assert "permanently failed" in caplog.text
        assert _SECRET not in caplog.text
        assert "PLACEHOLDER-TOKEN" not in caplog.text

    async def test_an_error_on_a_named_connection_is_logged_redacted(
        self, nats_client: NATSClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        link = _Link(name="A", url="nats://h:4222", connect_options={"user": "u", "password": _SECRET})
        connect = AsyncMock(return_value=MagicMock(is_closed=False))
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", connect), caplog.at_level("DEBUG"):
            await nats_client._open_named_link(link)
            await connect.call_args.kwargs["error_cb"](Exception(f"authorization violation for u/{_SECRET}"))
        assert "error on named connection 'A'" in caplog.text
        assert _SECRET not in caplog.text

    async def test_a_failed_attempt_of_a_named_connection_is_logged_redacted(
        self, nats_client: NATSClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        binding = _Binding(link=_Link(name="A", url=f"nats://u:{_SECRET}@h:4222"))
        failure = OSError(f"could not reach nats://u:{_SECRET}@h:4222")
        with (
            patch.object(nats_client, "_open_named_link", new_callable=AsyncMock, side_effect=failure),
            patch("blueprint.agents.clients.io.nats_client.asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
            caplog.at_level("DEBUG"),
            pytest.raises(asyncio.CancelledError),
        ):
            await nats_client._run_named_link(binding)
        assert "named connection 'A' attempt 1 failed" in caplog.text
        assert _SECRET not in caplog.text


class TestADurableOfAnotherTopicIsNotBound:
    """S1 -- root topic 'orders-created' and agent 'orders' on 'created' name one durable; drift only warned."""

    async def test_a_consumer_filtering_another_subject_is_refused(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        from blueprint.agents.clients.io.nats_client import JetStreamBindingError

        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders-created"])
        theirs = js_api.ConsumerConfig(durable_name="orders-created-durable", filter_subject="created", deliver_group="orders")
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=theirs))

        with pytest.raises(JetStreamBindingError) as refused:
            await nats_client._subscribe_one("orders-created", AsyncMock())

        mock_js.subscribe_bind.assert_not_awaited()
        assert "'orders-created-durable'" in str(refused.value)
        assert "'created'" in str(refused.value)
        assert "'orders-created'" in str(refused.value)

    async def test_a_consumer_listing_the_subject_in_filter_subjects_is_bound(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple
    ) -> None:
        mock_js = await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        existing = js_api.ConsumerConfig(durable_name="orders_created-durable", filter_subjects=["orders.created"], deliver_group="g")
        mock_js.consumer_info = AsyncMock(return_value=MagicMock(config=existing))

        await nats_client._subscribe_one("orders.created", AsyncMock())

        assert mock_js.subscribe_bind.await_args.kwargs["config"] is existing


class TestTheRunSlotIsNotLeaked:
    """W4 -- a failure between taking the slot and starting the run held the slot for good."""

    async def test_a_run_that_cannot_be_started_frees_its_slot(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, AsyncMock())
        with (
            patch.object(nats_client, "_run_delivery", new=MagicMock(side_effect=RuntimeError("cannot start"))),
            pytest.raises(RuntimeError),
        ):
            await handler(_delivery(cloud_event))

        assert nats_client.inflight_handlers == 0
        assert nats_client._binding.slots_for("orders.created").locked() is False


class TestTheConsumerLineRendersAnUnsetAckWait:
    """N10 -- '%.1f' on an unset ack_wait (None) lost the whole INFO line to a logging error."""

    async def test_the_line_is_logged_with_the_server_default(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"])
        assert nats_client._consumer_config("orders.created", "orders_created-durable").ack_wait is None
        with caplog.at_level("INFO", logger="blueprint.agents.clients.io.nats_client"):
            await nats_client._subscribe_one("orders.created", AsyncMock())
        created = [message for message in caplog.messages if message.startswith("Created JetStream consumer")]
        assert len(created) == 1
        assert "ack_wait server default" in created[0]

    async def test_a_configured_ack_wait_is_shown_in_seconds(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, caplog: pytest.LogCaptureFixture
    ) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_ack_wait=45.0)
        with caplog.at_level("INFO", logger="blueprint.agents.clients.io.nats_client"):
            await nats_client._subscribe_one("orders.created", AsyncMock())
        assert any("ack_wait 45.0s" in message for message in caplog.messages)
