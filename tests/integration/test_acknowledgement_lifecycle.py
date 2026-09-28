"""What the broker does with a delivery the framework could not complete.

Step 3 of `docs/plans/2026-09-11-broker-integration-tests.md`. Spec sec. 7.2 fixes one outcome
table for every transport, and the unit tests assert that the framework *decides* the right one.
These assert that the broker then *does* it -- which is a different claim, and the only one that
matters to a deployment:

| what the handler does            | disposition | what the broker does            |
|----------------------------------|-------------|---------------------------------|
| returns normally                 | ack         | nothing more                    |
| raises `RetryableHandlerError`   | nak         | redelivers after `nats_ack_wait`|
| raises `CriticalHandlerError`    | term        | never redelivers                |
| raises `InvalidEventError`       | term        | never redelivers                |
| no handler matches               | **ack**     | nothing more                    |
| payload is not a CloudEvent      | term        | never dispatched at all         |
| `nats_max_deliver` spent         | -           | dead-lettered, then termed      |

The two easiest to get backwards are the ones worth naming. **An event no handler matches is
acknowledged**: finding no work in an event is a normal outcome, and naking it would put it back
on the queue for ever. **A payload that does not parse is termed without being dispatched**: it
cannot become valid on a retry, so redelivering it is a loop with no exit.

`nats_ack_wait` is 2 seconds here (`integration_config`), which is what makes the redelivery
tests affordable.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from blueprint.agents.models.events import GenericCloudEvent

from .helpers import poll_until, wait_until


@dataclass
class Attempts:
    """A handler that fails in a chosen way, and the record of every time it was called."""

    handler: type[EventHandlerBase]
    topic: str
    seen: list[str] = field(default_factory=list)


@pytest.fixture
def failing(subject_prefix: str) -> Any:
    """Return a factory making a handler that raises what a test asks it to.

    The exception is what the framework classifies, so it is the only thing that varies between
    the cases below -- everything else about the handler is identical on purpose.
    """

    def make(error: BaseException | None, *, matches: bool = True) -> Attempts:
        topic = f"{subject_prefix}.orders.created"
        seen: list[str] = []

        class FailingHandler(EventHandlerBase):
            async def on_startup(self) -> None:
                pass

            async def on_shutdown(self) -> None:
                pass

            def get_subscribed_topics(self) -> list[str]:
                return [topic]

            async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
                return matches

            async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
                seen.append(event.id)
                if error is not None:
                    raise error
                return None

        return Attempts(handler=FailingHandler, topic=topic, seen=seen)

    return make


def an_order() -> GenericCloudEvent:
    return GenericCloudEvent(id=str(uuid.uuid4()), source="integration-test", type="orders.created", data={"order_id": "1"})


async def only_consumer(jetstream: JetStreamContext, stream: str) -> Any:
    consumers = await jetstream.consumers_info(stream)
    assert len(consumers) == 1, f"expected one consumer, found {[consumer.name for consumer in consumers]}"
    return consumers[0]


class TestARetryableFailureComesBack:
    """`nak` means "not now": the broker holds the message and redelivers it."""

    async def test_it_is_redelivered_after_the_ack_wait(self, nats_app: Any, failing: Any, jetstream: JetStreamContext) -> None:
        """The claim no mock can make. A nak returns the message to the consumer, and the
        handler runs again on the same event id -- which is also why a handler has to be safe
        to repeat, or dedup has to be switched on."""
        attempts = failing(RetryableHandlerError(status="failed", reason="not yet"))
        event = an_order()

        async with nats_app(attempts.handler):
            await jetstream.publish(attempts.topic, event.model_dump_json().encode())

            await wait_until(
                lambda: len(attempts.seen) >= 2,
                timeout=15,
                description="the nak'd event to be redelivered",
            )

        assert attempts.seen[0] == event.id
        assert attempts.seen[1] == event.id, "a different event came back, so this is not a redelivery"

    async def test_the_broker_counts_it_as_a_redelivery(
        self, nats_app: Any, failing: Any, jetstream: JetStreamContext, jetstream_stream: str
    ) -> None:
        attempts = failing(RetryableHandlerError(status="failed", reason="not yet"))

        async with nats_app(attempts.handler):
            await jetstream.publish(attempts.topic, an_order().model_dump_json().encode())
            await wait_until(lambda: len(attempts.seen) >= 2, timeout=15, description="a redelivery")

            consumer = await only_consumer(jetstream, jetstream_stream)

        assert consumer.num_redelivered >= 1


class TestATerminalFailureDoesNotComeBack:
    """`term` means "never again": the message is removed from the consumer."""

    @pytest.mark.parametrize(
        "error",
        [
            CriticalHandlerError(status="failed", reason="cannot continue"),
            InvalidEventError(status="failed", reason="not something this handler can read"),
        ],
        ids=["critical", "invalid"],
    )
    async def test_it_is_delivered_once(self, nats_app: Any, failing: Any, jetstream: JetStreamContext, error: BaseException) -> None:
        """Waiting past `nats_ack_wait` is the whole test: a nak would show up as a second call."""
        attempts = failing(error)

        async with nats_app(attempts.handler):
            await jetstream.publish(attempts.topic, an_order().model_dump_json().encode())
            await wait_until(lambda: bool(attempts.seen), timeout=10, description="the handler to be called")

            await asyncio.sleep(3.0)  # nats_ack_wait is 2.0

        assert len(attempts.seen) == 1, f"a termed delivery came back {len(attempts.seen)} times"

    async def test_it_is_dead_lettered_with_the_reason_in_the_headers(
        self, nats_app: Any, failing: Any, jetstream: JetStreamContext, nats_connection: NatsClient, subject_prefix: str
    ) -> None:
        """The payload is republished unchanged and what went wrong travels in headers, so a
        dead-letter consumer reading the body is not handed a corrupted one."""
        attempts = failing(CriticalHandlerError(status="failed", reason="cannot continue"))
        event = an_order()
        dead_letters: asyncio.Queue[Any] = asyncio.Queue()

        async def collect(msg: Any) -> None:
            await dead_letters.put(msg)

        async with nats_app(attempts.handler):
            await nats_connection.subscribe(f"{subject_prefix}.dead-letter", cb=collect)
            await nats_connection.flush()
            await jetstream.publish(attempts.topic, event.model_dump_json().encode())

            dead = await asyncio.wait_for(dead_letters.get(), timeout=15)

        assert GenericCloudEvent.model_validate_json(dead.data).id == event.id
        assert dead.headers["Blueprint-Dead-Letter-Reason"] == "terminal-failure"
        assert dead.headers["Blueprint-Original-Subject"] == attempts.topic
        assert dead.headers["Blueprint-Event-Id"] == event.id


class TestAnEventNobodyWantsIsAcknowledged:
    """Finding no work in an event is a normal outcome, not a failure."""

    async def test_it_is_not_redelivered(self, nats_app: Any, failing: Any, jetstream: JetStreamContext) -> None:
        """`can_handle_event` returning False for every handler must ack. Naking it would put a
        message nobody wants back on the queue for ever, at `ack_wait` intervals."""
        attempts = failing(None, matches=False)

        async with nats_app(attempts.handler):
            await jetstream.publish(attempts.topic, an_order().model_dump_json().encode())
            await asyncio.sleep(4.0)  # two ack_wait windows

        assert attempts.seen == [], "a handler that declined the event was called anyway"

    async def test_the_broker_has_nothing_left_pending(
        self, nats_app: Any, failing: Any, jetstream: JetStreamContext, jetstream_stream: str
    ) -> None:
        attempts = failing(None, matches=False)

        async with nats_app(attempts.handler):
            await jetstream.publish(attempts.topic, an_order().model_dump_json().encode())

            async def settled() -> bool:
                consumer = await only_consumer(jetstream, jetstream_stream)
                return bool(consumer.num_ack_pending == 0 and consumer.ack_floor.stream_seq == 1)

            await poll_until(settled, timeout=15, description="the unmatched event to be acknowledged")


class TestAPayloadThatIsNotACloudEventIsNeverDispatched:
    """It cannot become valid on a retry, so redelivering it is a loop with no exit."""

    async def test_the_handler_is_not_called(self, nats_app: Any, failing: Any, jetstream: JetStreamContext) -> None:
        attempts = failing(None)

        async with nats_app(attempts.handler):
            await jetstream.publish(attempts.topic, b"this is not a cloud event")
            await asyncio.sleep(4.0)  # two ack_wait windows

        assert attempts.seen == [], "an undecodable payload reached a handler"

    async def test_it_is_dead_lettered_with_its_bytes_unchanged(
        self, nats_app: Any, failing: Any, jetstream: JetStreamContext, nats_connection: NatsClient, subject_prefix: str
    ) -> None:
        """The message boundary P0 drew: an undecodable payload is distinguished from a failed
        dispatch, and the original bytes are what is kept -- there is no event id to put in a
        header, because nothing parsed."""
        attempts = failing(None)
        dead_letters: asyncio.Queue[Any] = asyncio.Queue()

        async def collect(msg: Any) -> None:
            await dead_letters.put(msg)

        async with nats_app(attempts.handler):
            await nats_connection.subscribe(f"{subject_prefix}.dead-letter", cb=collect)
            await nats_connection.flush()
            await jetstream.publish(attempts.topic, b"this is not a cloud event")

            dead = await asyncio.wait_for(dead_letters.get(), timeout=15)

        assert dead.data == b"this is not a cloud event"
        assert dead.headers["Blueprint-Dead-Letter-Reason"] == "terminal-failure"


class TestRedeliveriesRunOut:
    """`nats_max_deliver` is 3 here, so the third failure is the last."""

    async def test_the_handler_stops_being_called(self, nats_app: Any, failing: Any, jetstream: JetStreamContext) -> None:
        attempts = failing(RetryableHandlerError(status="failed", reason="never works"))

        async with nats_app(attempts.handler):
            await jetstream.publish(attempts.topic, an_order().model_dump_json().encode())
            await wait_until(
                lambda: len(attempts.seen) >= 3,
                timeout=20,
                description="the delivery attempts to be spent",
            )
            await asyncio.sleep(4.0)  # two more ack_wait windows

        assert len(attempts.seen) == 3, f"max_deliver is 3 and the handler ran {len(attempts.seen)} times"

    async def test_the_exhausted_message_is_dead_lettered(
        self, nats_app: Any, failing: Any, jetstream: JetStreamContext, nats_connection: NatsClient, subject_prefix: str
    ) -> None:
        """A different reason from a terminal failure, because the two are different operational
        problems: one handler is broken, the other rejected this particular event."""
        attempts = failing(RetryableHandlerError(status="failed", reason="never works"))
        dead_letters: asyncio.Queue[Any] = asyncio.Queue()

        async def collect(msg: Any) -> None:
            await dead_letters.put(msg)

        async with nats_app(attempts.handler):
            await nats_connection.subscribe(f"{subject_prefix}.dead-letter", cb=collect)
            await nats_connection.flush()
            await jetstream.publish(attempts.topic, an_order().model_dump_json().encode())

            dead = await asyncio.wait_for(dead_letters.get(), timeout=25)

        assert dead.headers["Blueprint-Dead-Letter-Reason"] == "deliveries-exhausted"
        assert dead.headers["Blueprint-Delivery-Count"] == "3"
