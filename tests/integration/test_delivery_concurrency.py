"""Concurrent runs, the heartbeat, the hard limit and the run pool, against a real broker.

The unit tests assert what the client decides; these assert what a broker then does with it:
that runs really overlap, that a long run is not redelivered while it still runs, that a hung run is
cut and comes back, and that a pair's first run is never held back by the process pool. Every case
here runs in seconds: ack waits and limits are scaled down, and the waits are on observed state.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from nats.aio.client import Client as NatsClient

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent

from .conftest import base_settings
from .helpers import wait_until


@dataclass
class Runs:
    """What a recording handler saw: which events started and finished, and a gate it waits on."""

    started: list[str] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)
    gate: asyncio.Event = field(default_factory=asyncio.Event)


def recording_handler(topics: list[str], runs: Runs, *, duration: float = 0.0, gated: bool = False, hang: str | None = None) -> type:
    """A handler that records its runs; it may wait on the gate, sleep, or hang on one label."""

    class Recording(EventHandlerBase):
        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return topics

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
            label = str((event.data or {}).get("label"))
            runs.started.append(label)
            if label == hang:
                await asyncio.Event().wait()  # never set: only the hard limit ends this run
            if gated:
                await runs.gate.wait()
            if duration:
                await asyncio.sleep(duration)
            runs.finished.append(label)
            return None

    return Recording


async def publish(connection: NatsClient, subject: str, label: str) -> None:
    event = GenericCloudEvent(id=str(uuid.uuid4()), source="integration-test", type="thing.happened", data={"label": label})
    await connection.jetstream().publish(subject, event.model_dump_json().encode())


async def stays(predicate: Any, seconds: float = 0.3) -> bool:
    """Whether ``predicate`` holds for ``seconds`` -- a limit must not merely be reached, it must hold."""
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while loop.time() < end:
        if not predicate():
            return False
        await asyncio.sleep(0.05)
    return True


class TestConcurrentRuns:
    async def test_up_to_k_runs_at_once_on_one_subscription(
        self, settings_group: Any, nats_url: str, jetstream_stream: str, subject_prefix: str, nats_connection: NatsClient
    ) -> None:
        runs, topic = Runs(), f"{subject_prefix}.orders.created"
        agent = f"orders_{subject_prefix}"
        settings = base_settings(nats_url, jetstream_stream, "nats_max_concurrent_runs = 3\n")
        async with settings_group(settings, {agent: recording_handler([topic], runs, gated=True)}):
            for n in range(5):
                await publish(nats_connection, topic, f"e{n}")
            await wait_until(lambda: len(runs.started) == 3, timeout=10, description="three runs to start")
            assert await stays(lambda: len(runs.started) == 3), "never more than K runs at once"
            runs.gate.set()
            await wait_until(lambda: len(runs.finished) == 5, timeout=10, description="all five runs to finish")

    async def test_unset_one_run_per_subscription_and_subscriptions_in_parallel(
        self, settings_group: Any, nats_url: str, jetstream_stream: str, subject_prefix: str, nats_connection: NatsClient
    ) -> None:
        runs = Runs()
        created, cancelled = f"{subject_prefix}.orders.created", f"{subject_prefix}.orders.cancelled"
        agent = f"orders_{subject_prefix}"
        async with settings_group(
            base_settings(nats_url, jetstream_stream), {agent: recording_handler([created, cancelled], runs, gated=True)}
        ):
            for subject in (created, created, cancelled, cancelled):
                await publish(nats_connection, subject, subject.rsplit(".", 1)[1])
            await wait_until(lambda: len(runs.started) == 2, timeout=10, description="one run per subscription to start")
            assert await stays(lambda: len(runs.started) == 2)
            assert sorted(runs.started) == ["cancelled", "created"], "the two subscriptions run in parallel, one run each"
            runs.gate.set()
            await wait_until(lambda: len(runs.finished) == 4, timeout=10, description="all four runs to finish")


class TestHeartbeat:
    async def test_a_run_longer_than_ack_wait_is_delivered_once(
        self, settings_group: Any, nats_url: str, jetstream_stream: str, subject_prefix: str, nats_connection: NatsClient
    ) -> None:
        runs, topic = Runs(), f"{subject_prefix}.orders.created"
        settings = base_settings(nats_url, jetstream_stream, "nats_ack_wait = 1.0\n")
        async with settings_group(settings, {f"orders_{subject_prefix}": recording_handler([topic], runs, duration=2.5)}):
            await publish(nats_connection, topic, "long")
            await wait_until(lambda: runs.finished == ["long"], timeout=10, description="the long run to finish")
            assert await stays(lambda: runs.started == ["long"], 1.5), "a live run is never redelivered"

    async def test_switched_off_a_long_run_is_redelivered_while_it_runs(
        self, settings_group: Any, nats_url: str, jetstream_stream: str, subject_prefix: str, nats_connection: NatsClient
    ) -> None:
        runs, topic = Runs(), f"{subject_prefix}.orders.created"
        settings = base_settings(
            nats_url, jetstream_stream, "nats_ack_wait = 1.0\nnats_heartbeat_enabled = false\nnats_max_concurrent_runs = 2\n"
        )
        async with settings_group(settings, {f"orders_{subject_prefix}": recording_handler([topic], runs, duration=2.5)}):
            await publish(nats_connection, topic, "long")
            await wait_until(lambda: runs.started.count("long") >= 2, timeout=6, description="the redelivery of the live run")


class TestHardLimit:
    async def test_a_hung_run_is_cut_and_redelivered_and_the_others_flow(
        self, settings_group: Any, nats_url: str, jetstream_stream: str, subject_prefix: str, nats_connection: NatsClient
    ) -> None:
        runs, topic = Runs(), f"{subject_prefix}.orders.created"
        settings = base_settings(nats_url, jetstream_stream, "nats_handler_timeout = 0.5\nnats_ack_wait = 10.0\nnats_max_deliver = 3\n")
        async with settings_group(settings, {f"orders_{subject_prefix}": recording_handler([topic], runs, hang="hung")}):
            await publish(nats_connection, topic, "hung")
            for n in range(3):
                await publish(nats_connection, topic, f"ok{n}")
            await wait_until(lambda: sorted(runs.finished) == ["ok0", "ok1", "ok2"], timeout=10, description="the other events to run")
            await wait_until(lambda: runs.started.count("hung") >= 2, timeout=10, description="the cut run to be redelivered at once (nak)")
            assert "hung" not in runs.finished


class TestRunPool:
    async def test_a_pairs_first_run_is_never_held_back_by_an_exhausted_pool(
        self, settings_group: Any, nats_url: str, jetstream_stream: str, subject_prefix: str, nats_connection: NatsClient
    ) -> None:
        busy, idle = Runs(), Runs()
        busy_topic, idle_topic = f"{subject_prefix}.busy.created", f"{subject_prefix}.idle.created"
        settings = base_settings(nats_url, jetstream_stream, "nats_max_concurrent_runs = 3\nnats_extra_runs_per_process = 1\n")
        agents = {
            f"busy_{subject_prefix}": recording_handler([busy_topic], busy, gated=True),
            f"idle_{subject_prefix}": recording_handler([idle_topic], idle, gated=True),
        }
        async with settings_group(settings, agents):
            for n in range(3):
                await publish(nats_connection, busy_topic, f"b{n}")
            await wait_until(lambda: len(busy.started) == 2, timeout=10, description="the busy pair's guaranteed run plus the pool's one")
            assert await stays(lambda: len(busy.started) == 2), "the pool of one is exhausted"
            await publish(nats_connection, idle_topic, "i0")
            await wait_until(lambda: idle.started == ["i0"], timeout=10, description="the idle pair's first run, despite the pool")
            busy.gate.set()
            idle.gate.set()
            await wait_until(lambda: len(busy.finished) == 3 and idle.finished == ["i0"], timeout=10, description="everything to finish")
