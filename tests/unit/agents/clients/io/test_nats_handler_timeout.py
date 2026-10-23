"""nats_handler_timeout: a run that reaches the limit is cancelled and nak'd (named-connections plan D9, step 3c)."""

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.models.events import CloudEvent
from tests.unit.agents.clients.io.test_nats_client import _delivery, _js_delivery_handler, _prepare_js_client, _until_settled
from tests.unit.agents.clients.io.test_nats_connection_source import FakeSource, _binding, _bound_handler, _deliver, _subscribed
from tests.unit.agents.clients.io.test_nats_connection_source import _delivery as _named_delivery

LOGGER = "blueprint.agents.clients.io.nats_client"


class TestTheLimit:
    async def test_a_run_at_the_limit_is_cancelled_and_nakd(
        self,
        nats_client: NATSClient,
        mock_config: MagicMock,
        mock_nats_jetstream: tuple,
        cloud_event: CloudEvent,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        finished: list[bool] = []

        async def hangs(event: CloudEvent, subject: str) -> None:
            await asyncio.sleep(10)
            finished.append(True)

        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, hangs, nats_handler_timeout=0.05)
        msg = _delivery(cloud_event)
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await asyncio.wait_for(_until_settled(nats_client, handler)(msg), timeout=5)
        msg.nak.assert_awaited_once()
        msg.ack.assert_not_awaited()
        assert finished == [], "the handler does not continue past the limit"
        assert any("exceeded nats_handler_timeout" in message for message in caplog.messages)
        assert nats_client.inflight_handlers == 0

    async def test_the_heartbeat_stops_before_the_nak(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def hangs(event: CloudEvent, subject: str) -> None:
            await asyncio.sleep(10)

        handler = await _js_delivery_handler(
            nats_client, mock_config, mock_nats_jetstream, hangs, nats_ack_wait=0.03, nats_handler_timeout=0.1
        )
        msg = _delivery(cloud_event)
        order = MagicMock()
        order.attach_mock(msg.in_progress, "in_progress")
        order.attach_mock(msg.nak, "nak")
        await _until_settled(nats_client, handler)(msg)
        calls = [name for name, _, _ in order.mock_calls]
        assert calls.count("in_progress") >= 1
        assert calls[-1] == "nak"

    async def test_a_timeout_error_of_the_handlers_own_is_an_ordinary_failure(
        self,
        nats_client: NATSClient,
        mock_config: MagicMock,
        mock_nats_jetstream: tuple,
        cloud_event: CloudEvent,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        async def own_timeout(event: CloudEvent, subject: str) -> None:
            raise TimeoutError("the backend did not answer")

        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, own_timeout, nats_handler_timeout=10)
        msg = _delivery(cloud_event)
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await _until_settled(nats_client, handler)(msg)
        assert not any("exceeded nats_handler_timeout" in message for message in caplog.messages)
        assert any("Handler failed for event" in message for message in caplog.messages)

    async def test_unset_a_run_is_never_cut(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, cloud_event: CloudEvent
    ) -> None:
        async def slow(event: CloudEvent, subject: str) -> None:
            await asyncio.sleep(0.2)

        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, slow)
        msg = _delivery(cloud_event)
        await _until_settled(nats_client, handler)(msg)
        msg.ack.assert_awaited_once()
        msg.nak.assert_not_awaited()

    async def test_a_handler_that_swallows_the_cancellation_holds_its_slot_and_is_nakd(
        self,
        nats_client: NATSClient,
        mock_config: MagicMock,
        mock_nats_jetstream: tuple,
        cloud_event: CloudEvent,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        held: list[int] = []

        async def stubborn(event: CloudEvent, subject: str) -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.1)  # carries on after being cancelled
                held.append(nats_client.inflight_handlers)

        handler = await _js_delivery_handler(nats_client, mock_config, mock_nats_jetstream, stubborn, nats_handler_timeout=0.05)
        msg = _delivery(cloud_event)
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await _until_settled(nats_client, handler)(msg)
        assert held == [1], "the slot stays taken while the handler runs on"
        msg.nak.assert_awaited_once()
        assert any("swallowed the cancellation" in message for message in caplog.messages)

    @pytest.mark.parametrize("value", [0, -1, "x", True], ids=["zero", "negative", "text", "bool"])
    async def test_anything_but_a_positive_number_is_refused(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple, value: Any
    ) -> None:
        with pytest.raises(ValueError, match="nats_handler_timeout"):
            await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_handler_timeout=value)

    async def test_a_number_as_text_is_read(self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_jetstream: tuple) -> None:
        await _prepare_js_client(nats_client, mock_config, mock_nats_jetstream, ["orders.created"], nats_handler_timeout="2.5")
        assert nats_client._handler_timeout == 2.5


class TestOnANamedConnection:
    async def test_the_limit_applies_and_the_connection_is_named(
        self,
        nats_client: NATSClient,
        mock_config: MagicMock,
        mock_nats_core: MagicMock,
        cloud_event: CloudEvent,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        base = mock_config.get.side_effect
        mock_config.get.side_effect = lambda key, default=None: 0.05 if key == "nats_handler_timeout" else base(key, default)

        async def hangs(event: CloudEvent, subject: str) -> None:
            await asyncio.sleep(10)

        await _subscribed(nats_client, FakeSource({"A": _binding("A", "risk.>")}), ("risk.>",))
        nats_client._named[0].topic_callbacks["risk.>"] = hangs
        binding, handler = await _bound_handler(nats_client, mock_nats_core, "A")
        msg = _named_delivery(cloud_event, "t.A.risk.created")
        with caplog.at_level(logging.ERROR, logger=LOGGER):
            await asyncio.wait_for(_deliver(binding, handler, msg), timeout=5)
        msg.nak.assert_awaited_once()
        assert any("from connection 'A'" in message and "exceeded nats_handler_timeout" in message for message in caplog.messages)
