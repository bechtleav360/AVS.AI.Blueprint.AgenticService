"""``HandlerResult.skipped`` on a real broker: acknowledged once, nothing published, nobody else asked.

A handler that is responsible for an event but finds it needs nothing returns
``HandlerResult.skipped(reason)``. Four claims, each read off the broker or the process rather
than off the framework's own account:

1. the inbound message is acknowledged -- ``num_ack_pending`` 0, ack floor advanced;
2. it is not redelivered once ``nats_ack_wait`` has passed;
3. nothing is published to the subject the outbound event type is mapped to;
4. the chain stops: a second, later handler that would also accept the event is never called.

The control for claim 4 is the ordinary ``None`` return, which does pass the event on.
"""

import asyncio
import uuid
from typing import Any

import pytest
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from .conftest import OUTBOUND_EVENT_TYPE
from .helpers import poll_until, wait_until
from .test_event_path import collect_from, only_consumer


def _handlers(topic: str, first_returns: Any, calls: list[str]) -> tuple[type[EventHandlerBase], type[EventHandlerBase]]:
    """Two handlers on ``topic``: the first returns ``first_returns``, the second would publish."""

    class First(EventHandlerBase):
        def __init__(self) -> None:
            super().__init__(priority=10)

        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return [topic]

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> Any:
            calls.append("first")
            return first_returns

    class Second(EventHandlerBase):
        def __init__(self) -> None:
            super().__init__(priority=20)

        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return [topic]

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult:
            calls.append("second")
            return HandlerResult(event_type=OUTBOUND_EVENT_TYPE, data={"from": "second"})

    return First, Second


def _an_order() -> bytes:
    event = GenericCloudEvent(id=str(uuid.uuid4()), source="integration-test", type="orders.created", data={"order_id": "o-1"})
    return event.model_dump_json().encode()


class TestASkippedEvent:
    async def test_it_is_acknowledged_once_publishes_nothing_and_asks_nobody_else(
        self,
        nats_app: Any,
        subject_prefix: str,
        jetstream: JetStreamContext,
        jetstream_stream: str,
        nats_connection: NatsClient,
        outbound_subject: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        topic = f"{subject_prefix}.orders.created"
        calls: list[str] = []
        first, second = _handlers(topic, HandlerResult.skipped("status unchanged"), calls)

        with caplog.at_level("INFO"):
            async with nats_app(first, second):
                outbound = await collect_from(nats_connection, outbound_subject)
                await jetstream.publish(topic, _an_order())
                await wait_until(lambda: bool(calls), timeout=10, description="the first handler to be called")

                async def acknowledged() -> bool:
                    consumer = await only_consumer(jetstream, jetstream_stream)
                    return bool(consumer.num_ack_pending == 0 and consumer.ack_floor.stream_seq == 1)

                await poll_until(acknowledged, timeout=10, description="the broker to record the acknowledgement")
                await asyncio.sleep(3.0)  # nats_ack_wait is 2.0: an unacknowledged message would be back by now
                consumer = await only_consumer(jetstream, jetstream_stream)

        assert calls == ["first"], f"the chain went on after the skip: {calls}"
        assert outbound.empty(), "a skipped event published something"
        assert consumer.num_ack_pending == 0
        assert consumer.num_redelivered == 0, "the broker redelivered a skipped event"
        skipped = [r for r in caplog.records if "skipped event" in r.getMessage()]
        assert skipped and skipped[0].levelname == "INFO" and "status unchanged" in skipped[0].getMessage()
        assert not [r for r in caplog.records if "No handler processed event" in r.getMessage()]

    async def test_control_a_none_return_passes_the_event_to_the_next_handler(
        self,
        nats_app: Any,
        subject_prefix: str,
        jetstream: JetStreamContext,
        nats_connection: NatsClient,
        outbound_subject: str,
    ) -> None:
        """The same two handlers with ``None`` instead of a skip: the second one runs and publishes."""
        topic = f"{subject_prefix}.orders.created"
        calls: list[str] = []
        first, second = _handlers(topic, None, calls)

        async with nats_app(first, second):
            outbound = await collect_from(nats_connection, outbound_subject)
            await jetstream.publish(topic, _an_order())
            published = await asyncio.wait_for(outbound.get(), timeout=10)

        assert calls == ["first", "second"]
        assert GenericCloudEvent.model_validate_json(published).data == {"from": "second"}
