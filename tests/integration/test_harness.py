"""The harness, tested before anything is tested with it.

Step 1 of `docs/plans/2026-09-11-broker-integration-tests.md`. Every later broker test rests on
three claims made by `conftest.py`, and a failure in any of them would otherwise surface as a
confusing failure inside the test that used it:

1. there is a reachable NATS server with JetStream, and a test can publish and receive on it;
2. a test's stream is its own and is gone afterwards, so no two tests -- and no two runs --
   share broker-side state;
3. a real `AppBuilder` application starts against that server and gets as far as *subscribed*.

The third is the one worth having for its own sake. It is the first time in this repository that
the framework's NATS path runs against a broker rather than a mock, and it stops where step 2
begins: the application is connected, on its topics and receiving, and nothing here asserts what
it does with an acknowledgement.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.errors import NotFoundError

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent

from .helpers import wait_until


@dataclass
class Recorder:
    """The three things a test needs about its handler, kept together rather than unpacked."""

    handler: type[EventHandlerBase]
    topic: str
    received: list[GenericCloudEvent] = field(default_factory=list)


def subject_prefix_of(stream_name: str) -> str:
    """The subject prefix a stream name was derived from -- see the ``jetstream_stream`` fixture."""
    return stream_name.removeprefix("IT_").lower()


async def stream_names(js: JetStreamContext) -> AsyncIterator[str]:
    """Every stream currently on the server."""
    for stream in await js.streams_info():
        yield stream.config.name


class TestTheBroker:
    """There is a server, and this directory's fixtures can talk to it."""

    async def test_a_message_published_is_a_message_received(self, nats_connection: NatsClient, subject_prefix: str) -> None:
        """Core NATS, no framework involved: the plainest statement that the harness works.

        If this fails, nothing else in this directory means anything -- which is why it is the
        first test in the file.
        """
        subject = f"{subject_prefix}.ping"
        received: asyncio.Queue[bytes] = asyncio.Queue()

        async def collect(msg: Msg) -> None:
            await received.put(msg.data)

        subscription = await nats_connection.subscribe(subject, cb=collect)
        await nats_connection.flush()
        await nats_connection.publish(subject, b"hello")

        assert await asyncio.wait_for(received.get(), timeout=5) == b"hello"
        await subscription.unsubscribe()

    async def test_jetstream_is_enabled(self, jetstream: JetStreamContext, jetstream_stream: str) -> None:
        """Without ``--jetstream`` the server accepts the connection and refuses the stream.

        Every subscription then falls back to Core NATS, where there are no durables, no
        redelivery and no ``max_deliver`` -- so steps 2 and 3 would be asserting against a
        transport that cannot exhibit what they test.
        """
        info = await jetstream.stream_info(jetstream_stream)

        assert info.config.name == jetstream_stream
        assert info.config.subjects == [f"{subject_prefix_of(jetstream_stream)}.>"]


class TestTheStreamIsThisTestsOwn:
    """A durable outliving its test carries a delivery count and a filter subject into the next.

    The first two run in file order, which is what makes the pair meaningful: tests above this
    class create streams through the fixture, and the second test here asserts that no ``IT_``
    stream from any of them is still on the server. A teardown that stopped working fails it.
    """

    async def test_a_stream_is_created_for_this_test(self, jetstream: JetStreamContext, jetstream_stream: str) -> None:
        info = await jetstream.stream_info(jetstream_stream)

        assert info.state.messages == 0, "a stream named for this test already had messages in it"

    async def test_no_stream_from_an_earlier_test_survived_it(self, nats_connection: NatsClient, jetstream_stream: str) -> None:
        js = nats_connection.jetstream()

        surviving = [name async for name in stream_names(js) if name.startswith("IT_") and name != jetstream_stream]

        assert surviving == [], f"streams from earlier tests are still on the server: {surviving}"

    async def test_a_name_that_was_never_created_is_simply_absent(self, nats_connection: NatsClient) -> None:
        """The teardown swallows an exception for a test that failed before creating its stream.
        This pins what that swallowed exception actually is."""
        with pytest.raises(NotFoundError):
            await nats_connection.jetstream().stream_info(f"IT_{uuid.uuid4().hex[:12].upper()}")


class TestAnApplicationOnTheRealBroker:
    """The framework's own NATS path, against a server rather than a mock."""

    @pytest.fixture
    def recorder(self, subject_prefix: str) -> Recorder:
        """A handler class subscribed to a subject belonging to this test alone.

        Defined per test rather than at module level because ``with_handler`` is given the
        *class* -- the framework constructs it -- so the subject and the list it records into
        have to be closed over rather than passed in. A module-level class would carry both
        from one test into the next.
        """
        topic = f"{subject_prefix}.orders.created"
        received: list[GenericCloudEvent] = []

        class HarnessHandler(EventHandlerBase):
            async def on_startup(self) -> None:
                pass

            async def on_shutdown(self) -> None:
                pass

            def get_subscribed_topics(self) -> list[str]:
                return [topic]

            async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
                return True

            async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
                received.append(event)
                return None

        return Recorder(handler=HarnessHandler, topic=topic, received=received)

    async def test_it_connects_and_subscribes(self, nats_app: Any, recorder: Recorder) -> None:
        """``subscriptions_ready`` is what the readiness probe gates on, and it is set by the
        background retry task rather than by ``subscribe()`` -- so this asserts that the task got
        all the way through connect, stream creation and consumer creation."""
        async with nats_app(recorder.handler) as (_, client):
            assert client.subscriptions_ready

    async def test_the_client_reports_healthy(self, nats_app: Any, recorder: Recorder) -> None:
        async with nats_app(recorder.handler) as (_, client):
            health = await client.health_check()

        assert health.status == "healthy", health.message

    async def test_the_queue_group_is_the_agents_identity(self, nats_app: Any, recorder: Recorder, subject_prefix: str) -> None:
        """C1: the name derives from the agent, not from the deployment.

        The agent here is the root namespace, so ``_resolve_queue_group`` falls through to
        ``nats_queue_group`` -- which the fixture sets per test, because the dead-letter subject
        derives from it and a shared one makes two tests' streams overlap.
        """
        async with nats_app(recorder.handler) as (_, client):
            assert client.queue_group == subject_prefix

    async def test_the_framework_creates_the_stream_it_was_told_to_use(
        self, nats_app: Any, recorder: Recorder, jetstream_stream: str, nats_connection: NatsClient
    ) -> None:
        """``_ensure_stream`` creates the stream named by ``nats_stream_name`` when it is missing
        and widens it to cover every subscribed subject. Nothing here creates it -- the
        ``jetstream`` fixture is deliberately not requested -- so its existence afterwards is the
        framework's doing, and ``jetstream_stream`` still removes it."""
        async with nats_app(recorder.handler):
            info = await nats_connection.jetstream().stream_info(jetstream_stream)

        assert recorder.topic in (info.config.subjects or [])

    async def test_a_subscribed_agent_receives_what_is_published_to_its_topic(
        self, nats_app: Any, recorder: Recorder, nats_connection: NatsClient
    ) -> None:
        """The harness's purpose in its smallest form: published from outside the process,
        dispatched to a handler inside it.

        Step 2 is this plus the acknowledgement and the outbound result. It is here so that a
        step-2 failure reads as being about those, rather than about whether anything arrives.
        """
        event = GenericCloudEvent(
            id=str(uuid.uuid4()),
            source="integration-test",
            type="orders.created",
            data={"order_id": "1"},
        )

        async with nats_app(recorder.handler) as (_, client):
            await nats_connection.jetstream().publish(recorder.topic, event.model_dump_json().encode())

            await wait_until(
                lambda: bool(recorder.received),
                timeout=10,
                description=f"the handler subscribed to '{recorder.topic}' to be called",
            )
            assert client.inflight_handlers == 0

        assert [received.id for received in recorder.received] == [event.id]
