"""The whole path, on a real broker: in, handled, out, acknowledged once.

Step 2 of `docs/plans/2026-09-11-broker-integration-tests.md`, and the test the exercise is for.
Everything the multi-agent work claims about delivery has until now been asserted against mocked
transports, which cannot tell you whether the broker agrees.

Four claims, each stated against the server rather than against the framework's own account of
itself:

1. an event published from outside the process reaches a handler inside it;
2. the handler's `HandlerResult` is published to the subject the configuration maps it to;
3. the inbound message is acknowledged **exactly once** -- read off the consumer, not inferred;
4. and it is not redelivered once `nats_ack_wait` has passed, which is the same claim from the
   other side and the one a mock can never make.

**The stream is pre-created over the whole test prefix**, by requesting the `jetstream` fixture.
That is not a convenience: the framework provisions a stream covering the subjects it
*subscribes*, and an outbound subject is not one of them -- see `TestWhatTheFrameworkProvisions`
at the bottom, where that is stated as its own failing test rather than hidden in a fixture.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from .conftest import OUTBOUND_EVENT_TYPE
from .helpers import poll_until, wait_until


@dataclass
class Validator:
    """A handler that records what it was given and returns a result to be published."""

    handler: type[EventHandlerBase]
    topic: str
    received: list[GenericCloudEvent] = field(default_factory=list)


@pytest.fixture
def validator(subject_prefix: str) -> Validator:
    """A handler on this test's inbound subject, returning a result for the mapped event type."""
    topic = f"{subject_prefix}.orders.created"
    received: list[GenericCloudEvent] = []

    class ValidatingHandler(EventHandlerBase):
        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return [topic]

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult:
            received.append(event)
            return HandlerResult(event_type=OUTBOUND_EVENT_TYPE, data={"order_id": event.data["order_id"]})

    return Validator(handler=ValidatingHandler, topic=topic, received=received)


def an_order(order_id: str = "order-1") -> GenericCloudEvent:
    return GenericCloudEvent(id=str(uuid.uuid4()), source="integration-test", type="orders.created", data={"order_id": order_id})


async def collect_from(connection: NatsClient, subject: str) -> asyncio.Queue[bytes]:
    """Subscribe to ``subject`` on Core NATS and queue what arrives.

    Core rather than a JetStream consumer on purpose: this is the test *watching* the process,
    and a durable of its own would be broker-side state the test then has to tear down -- and
    would consume from the same stream the application's own consumer is bound to.
    """
    received: asyncio.Queue[bytes] = asyncio.Queue()

    async def collect(msg: Msg) -> None:
        await received.put(msg.data)

    await connection.subscribe(subject, cb=collect)
    await connection.flush()
    return received


async def only_consumer(jetstream: JetStreamContext, stream: str) -> Any:
    """The one consumer the application created on this test's stream."""
    consumers = await jetstream.consumers_info(stream)
    assert len(consumers) == 1, f"expected one consumer, found {[consumer.name for consumer in consumers]}"
    return consumers[0]


class TestThePathEndToEnd:
    """Published from outside, handled inside, published back out."""

    async def test_the_handler_receives_what_was_published(self, nats_app: Any, validator: Validator, jetstream: JetStreamContext) -> None:
        event = an_order()

        async with nats_app(validator.handler):
            await jetstream.publish(validator.topic, event.model_dump_json().encode())
            await wait_until(
                lambda: bool(validator.received),
                timeout=10,
                description=f"the handler on '{validator.topic}' to be called",
            )

        assert [received.id for received in validator.received] == [event.id]
        assert validator.received[0].data == {"order_id": "order-1"}

    async def test_the_result_is_published_to_the_mapped_subject(
        self, nats_app: Any, validator: Validator, jetstream: JetStreamContext, nats_connection: NatsClient, outbound_subject: str
    ) -> None:
        """``HandlerResult(event_type=...)`` is resolved through ``event_publishing.topic_mapping``.

        The outbound event is a CloudEvent of its own -- new id, the configured ``app_name`` as
        its source -- carrying the handler's data. It is not the inbound event forwarded.
        """
        outbound = None

        async with nats_app(validator.handler):
            received = await collect_from(nats_connection, outbound_subject)
            await jetstream.publish(validator.topic, an_order("order-2").model_dump_json().encode())
            outbound = await asyncio.wait_for(received.get(), timeout=10)

        published = GenericCloudEvent.model_validate_json(outbound)
        assert published.type == OUTBOUND_EVENT_TYPE
        assert published.data == {"order_id": "order-2"}
        assert published.source == "blueprint-it"
        assert published.id != validator.received[0].id, "the outbound event reuses the inbound id"


class TestTheAcknowledgement:
    """A normal return acks, and acks once. Read off the consumer, not off the framework."""

    async def test_the_message_is_acknowledged(
        self, nats_app: Any, validator: Validator, jetstream: JetStreamContext, jetstream_stream: str
    ) -> None:
        """``num_ack_pending`` is the broker's own count of what it is still waiting to be told
        about. Zero, with the ack floor advanced, is the acknowledgement having actually landed
        rather than the handler merely having returned."""
        async with nats_app(validator.handler):
            await jetstream.publish(validator.topic, an_order().model_dump_json().encode())
            await wait_until(
                lambda: bool(validator.received),
                timeout=10,
                description="the handler to be called",
            )

            async def acknowledged() -> bool:
                consumer = await only_consumer(jetstream, jetstream_stream)
                return bool(consumer.num_ack_pending == 0 and consumer.ack_floor.stream_seq == 1)

            await poll_until(acknowledged, timeout=10, description="the broker to record the acknowledgement")
            consumer = await only_consumer(jetstream, jetstream_stream)

        assert consumer.num_ack_pending == 0, "the broker is still waiting for an acknowledgement"
        assert consumer.ack_floor.stream_seq == 1, "the acknowledgement did not advance the ack floor"
        assert consumer.num_pending == 0, "the stream still holds an undelivered message"

    async def test_it_is_delivered_once_and_not_redelivered(
        self, nats_app: Any, validator: Validator, jetstream: JetStreamContext, jetstream_stream: str
    ) -> None:
        """The same claim from the broker's side, and the one no mock can make.

        An unacknowledged message comes back after ``nats_ack_wait`` -- 2 seconds here -- so
        waiting the window out and finding the handler called once is the acknowledgement
        working. A test that only asserted ``num_ack_pending == 0`` would pass against a
        consumer that had acked and then been redelivered for another reason.
        """
        async with nats_app(validator.handler):
            await jetstream.publish(validator.topic, an_order().model_dump_json().encode())
            await wait_until(
                lambda: bool(validator.received),
                timeout=10,
                description="the handler to be called",
            )

            await asyncio.sleep(3.0)  # nats_ack_wait is 2.0

            consumer = await only_consumer(jetstream, jetstream_stream)

        assert len(validator.received) == 1, f"the handler ran {len(validator.received)} times"
        assert consumer.delivered.stream_seq == 1
        assert consumer.num_redelivered == 0, "the broker redelivered a message it had been told about"


class TestWhatTheFrameworkProvisions:
    """What the client puts in the stream when nothing else has created one."""

    async def test_the_subscribed_subject_is_covered(
        self, nats_app: Any, validator: Validator, jetstream_stream: str, nats_connection: NatsClient
    ) -> None:
        """The `jetstream` fixture is deliberately not requested, so the stream below is the
        framework's own work."""
        async with nats_app(validator.handler):
            info = await nats_connection.jetstream().stream_info(jetstream_stream)

        assert validator.topic in (info.config.subjects or [])

    async def test_the_outbound_subject_is_covered_too(
        self, nats_app, validator, jetstream_stream: str, nats_connection, outbound_subject: str
    ) -> None:
        """The client declares what it publishes, so the stream carries it.

        Before, `_stream_subjects` covered only what was subscribed: a JetStream publish to the
        outbound subject waited for an acknowledgement no stream would send, timed out, and was
        swallowed as a WARNING -- while a Core NATS subscriber still saw the message, so a live
        listener looked healthy and nothing was stored.
        """
        async with nats_app(validator.handler):
            info = await nats_connection.jetstream().stream_info(jetstream_stream)

        assert outbound_subject in (info.config.subjects or [])
