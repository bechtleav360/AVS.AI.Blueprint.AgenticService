"""What an agent upgrading from 0.8 finds on the broker, and what it does with it.

0.8 subscribed with ``js.subscribe(topic, durable=f"{topic}-durable", manual_ack=True)``, which
left a durable consumer delivering to a random inbox with no deliver group. 0.9 creates its own
consumers with a named deliver subject and a deliver group, so every replica can share one -- but
it must not touch a consumer that already exists: recreating a durable replays or gaps. These
assert, against the real broker, that an existing 0.8 consumer is used exactly as it is and is
announced as deprecated, and they pin the broker behaviour the upgrade path relies on.
"""

import uuid
from typing import Any

import pytest
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from nats.js import api as js_api
from nats.js.errors import APIError

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent

from .helpers import wait_until


@pytest.fixture
def undotted_topic(subject_prefix: str) -> str:
    """A topic without a dot, so 0.8 and 0.9 derive the same durable name for it."""
    return f"{subject_prefix}_orders"


def recording_handler(topic: str, seen: list[str]) -> type[EventHandlerBase]:
    class RecordingHandler(EventHandlerBase):
        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return [topic]

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
            seen.append(event.id)

    return RecordingHandler


async def a_08_consumer(nats_connection: NatsClient, stream: str, topic: str) -> js_api.ConsumerConfig:
    """Create the stream and the durable exactly as 0.8's js.subscribe left them."""
    js = nats_connection.jetstream()
    await js.add_stream(name=stream, subjects=[topic])
    config = js_api.ConsumerConfig(
        durable_name=f"{topic}-durable",
        filter_subject=topic,
        deliver_subject=nats_connection.new_inbox(),
        ack_policy=js_api.AckPolicy.EXPLICIT,
    )
    await js.add_consumer(stream, config=config)
    return config


class TestAnExistingConsumerFrom08:
    async def test_it_is_used_as_it_is(
        self, nats_app: Any, nats_connection: NatsClient, jetstream_stream: str, undotted_topic: str
    ) -> None:
        before = await a_08_consumer(nats_connection, jetstream_stream, undotted_topic)
        seen: list[str] = []
        event = GenericCloudEvent(id=str(uuid.uuid4()), source="integration-test", type="orders.created", data={})

        async with nats_app(recording_handler(undotted_topic, seen)):
            js: JetStreamContext = nats_connection.jetstream()
            await js.publish(undotted_topic, event.model_dump_json().encode())
            await wait_until(lambda: event.id in seen, timeout=15, description="the 0.8 consumer to deliver")

            consumers = await js.consumers_info(jetstream_stream)
            after = await js.consumer_info(jetstream_stream, f"{undotted_topic}-durable")

        assert [consumer.name for consumer in consumers] == [f"{undotted_topic}-durable"], "no second consumer was created"
        assert after.config.deliver_subject == before.deliver_subject
        assert not after.config.deliver_group

    async def test_it_is_announced_as_deprecated(
        self,
        nats_app: Any,
        nats_connection: NatsClient,
        jetstream_stream: str,
        undotted_topic: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        await a_08_consumer(nats_connection, jetstream_stream, undotted_topic)
        with caplog.at_level("WARNING", logger="blueprint.agents.clients.io.nats_client"):
            async with nats_app(recording_handler(undotted_topic, [])):
                pass
        assert any(message.startswith("DEPRECATED") and f"'{undotted_topic}-durable'" in message for message in caplog.messages)


class TestTheBrokerRefusesADottedConsumerName:
    """Why a 0.8 durable for a topic with a dot cannot exist: 0.8 derived ``orders.created-durable``.

    0.9 derives ``orders_created-durable`` for the same topic. That rename orphans nothing only if
    the server never accepted the dotted name -- which is what this pins.
    """

    async def test_the_name_is_rejected(self, nats_connection: NatsClient, jetstream: JetStreamContext, subject_prefix: str) -> None:
        stream = f"IT_{subject_prefix.upper()}"
        topic = f"{subject_prefix}.orders.created"
        # Refused by the server, or by nats-py before it gets there -- 0.8 went through nats-py too.
        with pytest.raises((APIError, ValueError)):
            await jetstream.add_consumer(
                stream,
                config=js_api.ConsumerConfig(
                    durable_name=f"{topic}-durable",
                    filter_subject=topic,
                    deliver_subject=nats_connection.new_inbox(),
                    ack_policy=js_api.AckPolicy.EXPLICIT,
                ),
            )
