"""A JetStream run sees which attempt it is: ``nats_delivery_attempt`` and ``nats_max_deliver``.

Against a real broker, so the attempt is the broker's own ``num_delivered``: a handler that fails
once (nak) is redelivered and sees attempt 2; the control -- a handler that succeeds -- sees 1 and
nothing else. ``nats_max_deliver`` is 3 in the integration settings.
"""

import uuid
from typing import Any

from nats.js import JetStreamContext

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.errors import RetryableHandlerError
from blueprint.agents.models.events import GenericCloudEvent

from .helpers import wait_until


def _recording(topic: str, seen: list[tuple[Any, Any]], fail_first: bool) -> type:
    class Recording(EventHandlerBase):
        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return [topic]

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
            seen.append((context.get("nats_delivery_attempt"), context.get("nats_max_deliver")))
            if fail_first and len(seen) == 1:
                raise RetryableHandlerError(status="retry", reason="first attempt fails on purpose")
            return None

    return Recording


def _event() -> bytes:
    return GenericCloudEvent(id=str(uuid.uuid4()), source="integration-test", type="orders.created", data={}).model_dump_json().encode()


class TestTheAttemptInTheHandlerContext:
    async def test_a_redelivered_message_shows_attempt_2(self, nats_app: Any, jetstream: JetStreamContext, subject_prefix: str) -> None:
        topic = f"{subject_prefix}.orders.created"
        seen: list[tuple[Any, Any]] = []
        async with nats_app(_recording(topic, seen, fail_first=True)):
            await jetstream.publish(topic, _event())
            await wait_until(lambda: len(seen) >= 2, timeout=15, description="the redelivery after the nak")
        assert seen == [(1, 3), (2, 3)]

    async def test_control_a_first_delivery_shows_attempt_1(self, nats_app: Any, jetstream: JetStreamContext, subject_prefix: str) -> None:
        topic = f"{subject_prefix}.orders.created"
        seen: list[tuple[Any, Any]] = []
        async with nats_app(_recording(topic, seen, fail_first=False)):
            await jetstream.publish(topic, _event())
            await wait_until(lambda: bool(seen), timeout=10, description="the delivery")
        assert seen == [(1, 3)]
