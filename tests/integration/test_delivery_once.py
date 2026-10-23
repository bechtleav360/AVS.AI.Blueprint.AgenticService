"""A message is handled once -- across replicas, and across a shutdown.

Chores 2 and 3 from `docs/plans/2026-09-11-broker-integration-tests.md`. Both are the same claim
seen from two sides, and both are what make a rolling deploy safe:

- **Across replicas.** Two processes of one agent share a queue group, so the broker delivers each
  message to one of them. This is the claim `replicaCount > 1` rests on, and before P1 it was
  false -- every replica processed everything.
- **Across a shutdown.** A handler already running when the process is told to stop finishes, and
  its acknowledgement reaches the broker *before* the connection closes. Wrong, and every deploy
  produces a duplicate: the handler's work is done, the ack is lost, and the message is redelivered
  to whichever replica is still up.

The second replica here is a raw nats-py subscription bound to **the names the framework derived**
-- its queue group, its durable, its deliver subject -- rather than a second process. That is the
part worth stating: a real replica is identical to the first, so what makes distribution work is
that both bind the *same* names, and binding them by hand is a sharper test of that than starting
another interpreter. A second process would additionally test process startup, which step 1
already covers.
"""

import asyncio
import uuid
from typing import Any

import pytest
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent

from .helpers import poll_until, wait_until


def an_event() -> GenericCloudEvent:
    return GenericCloudEvent(id=str(uuid.uuid4()), source="integration-test", type="thing.happened", data={})


@pytest.fixture
def slow_handler(subject_prefix: str) -> Any:
    """A handler that takes a measurable amount of time, and records when it started and ended.

    The shutdown test needs a handler it can be *inside* when the process is asked to stop, which
    a handler that returns immediately cannot provide.
    """

    def make(duration: float) -> dict[str, Any]:
        topic = f"{subject_prefix}.orders.created"
        started: list[str] = []
        finished: list[str] = []

        class SlowHandler(EventHandlerBase):
            async def on_startup(self) -> None:
                pass

            async def on_shutdown(self) -> None:
                pass

            def get_subscribed_topics(self) -> list[str]:
                return [topic]

            async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
                return True

            async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
                started.append(event.id)
                await asyncio.sleep(duration)
                finished.append(event.id)
                return None

        return {"handler": SlowHandler, "topic": topic, "started": started, "finished": finished}

    return make


class TestTwoReplicasShareTheWork:
    """One queue group, one delivery per message."""

    async def test_a_second_binder_does_not_double_the_deliveries(
        self, nats_app: Any, slow_handler: Any, jetstream: JetStreamContext, nats_connection: NatsClient
    ) -> None:
        """The claim `replicaCount > 1` rests on, and the one P1 fixed.

        The second subscriber joins the deliver subject and queue group the framework chose, which
        is exactly what a second replica of the same image does. Every message must arrive once
        in total across the two -- not once each.
        """
        work = slow_handler(0.0)
        second_replica: list[bytes] = []

        async def take(msg: Msg) -> None:
            second_replica.append(msg.data)
            await msg.ack()

        async with nats_app(work["handler"]) as (_, client):
            consumers = await jetstream.consumers_info(await_stream(client))
            deliver_subject = consumers[0].config.deliver_subject
            assert deliver_subject, "a push consumer without a deliver subject cannot have a replica"

            await nats_connection.subscribe(deliver_subject, queue=client.queue_group, cb=take)
            await nats_connection.flush()

            published = [an_event() for _ in range(6)]
            for event in published:
                await jetstream.publish(work["topic"], event.model_dump_json().encode())

            await wait_until(
                lambda: len(work["finished"]) + len(second_replica) >= len(published),
                timeout=20,
                description="every message to reach one of the two replicas",
            )
            await asyncio.sleep(1.5)  # a duplicate would arrive in this window

        total = len(work["finished"]) + len(second_replica)
        assert total == len(published), f"{len(published)} messages produced {total} deliveries across two replicas"


def await_stream(client: Any) -> str:
    """The stream name the client was configured with."""
    return str(client.config.get("nats_stream_name", "EVENTS"))


class TestShutdownDrainsBeforeItCloses:
    """A handler already running finishes, and its acknowledgement lands first."""

    async def test_an_in_flight_handler_finishes(self, nats_app: Any, slow_handler: Any, jetstream: JetStreamContext) -> None:
        """Leaving the lifespan is the shutdown. The handler is mid-`asyncio.sleep` when it
        begins, and must still be allowed to reach its end."""
        work = slow_handler(1.5)
        event = an_event()

        async with nats_app(work["handler"]):
            await jetstream.publish(work["topic"], event.model_dump_json().encode())
            await wait_until(lambda: bool(work["started"]), timeout=15, description="the handler to start")
            assert work["finished"] == [], "the handler finished before the shutdown began, so this proves nothing"

        assert work["finished"] == [event.id], "shutdown closed the connection with a handler still running"

    async def test_the_acknowledgement_arrives_before_the_connection_closes(
        self, nats_app: Any, slow_handler: Any, jetstream: JetStreamContext, jetstream_stream: str
    ) -> None:
        """The half that makes a deploy safe. The handler finishing is not enough -- if its ack
        is lost with the connection, the broker redelivers work that was already done, and every
        rolling deploy produces a duplicate.
        """
        work = slow_handler(1.0)

        async with nats_app(work["handler"]):
            await jetstream.publish(work["topic"], an_event().model_dump_json().encode())
            await wait_until(lambda: bool(work["started"]), timeout=15, description="the handler to start")

        # Read after the lifespan: the question is what the broker was told before it ended.
        consumers = await jetstream.consumers_info(jetstream_stream)
        consumer = consumers[0]

        assert consumer.num_ack_pending == 0, "the connection closed with an acknowledgement still outstanding"
        assert consumer.ack_floor.stream_seq == 1

    async def test_nothing_is_redelivered_to_the_next_process(
        self, nats_app: Any, slow_handler: Any, jetstream: JetStreamContext, jetstream_stream: str
    ) -> None:
        """The consequence, stated as a deploy: stop one process mid-handler, start another on
        the same durable, and the message must not come back."""
        first = slow_handler(1.0)
        event = an_event()

        async with nats_app(first["handler"]):
            await jetstream.publish(first["topic"], event.model_dump_json().encode())
            await wait_until(lambda: bool(first["started"]), timeout=15, description="the first process to start work")

        assert first["finished"] == [event.id]

        second = slow_handler(0.0)
        async with nats_app(second["handler"]):
            await asyncio.sleep(4.0)  # two ack_wait windows: a redelivery would land in here

            async def settled() -> bool:
                info = await jetstream.consumers_info(jetstream_stream)
                return bool(info and info[0].num_ack_pending == 0)

            await poll_until(settled, timeout=10, description="the consumer to be idle")

        assert second["started"] == [], "the message was redelivered to the next process after being acknowledged"
