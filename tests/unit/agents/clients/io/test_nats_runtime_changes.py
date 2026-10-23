"""Named connections changed at runtime through ConnectionSource.watch (named-connections plan, step 4b)."""

import asyncio
import json
import logging
import threading
from contextlib import nullcontext
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nats.js import api as js_api

from blueprint.agents.clients.io import nats_client as nats_client_module
from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.clients.io.nats_connections import ConnectionSource, ConnectionSpec, JetStreamBinding
from blueprint.agents.models.errors import DeliveryRevokedError
from blueprint.agents.models.events import CloudEvent


def _binding(name: str, *subjects: str, ack_wait: float = 600.0) -> JetStreamBinding:
    return JetStreamBinding(
        subjects=subjects or ("risk.>",),
        stream=f"S_{name}",
        durable=f"d-{name}",
        deliver_subject=f"deliver.{name}",
        deliver_group="g",
        ack_wait=ack_wait,
        subject_prefix=f"t.{name}.",
        max_deliver=5,
        deliver_policy=js_api.DeliverPolicy.NEW,
    )


class WatchedSource:
    """A source whose connections the test changes, telling the client through watch()."""

    def __init__(self, **connections: JetStreamBinding) -> None:
        self.bindings = dict(connections)
        self.passwords: dict[str, str] = {}
        self.notifiers: list[Any] = []
        self.reads = 0

    def watch(self, notify: Any) -> None:
        self.notifiers.append(notify)

    def change(self, **connections: JetStreamBinding) -> None:
        self.bindings = dict(connections)
        self.notify()

    def notify(self) -> None:
        for notify in self.notifiers:
            notify()

    def claims(self, agent: str, subjects: tuple[str, ...]) -> tuple[str, ...]:
        return subjects  # every declared subject is a tenant subject, as in the first consumer of named connections

    def connections(self) -> dict[str, ConnectionSpec]:
        self.reads += 1
        return {
            name: ConnectionSpec(name=name, url="nats://h:4222", user="u", password=self.passwords.get(name, "PLACEHOLDER-1"))
            for name in self.bindings
        }

    def binding(self, agent: str, subjects: tuple[str, ...], connection: ConnectionSpec) -> JetStreamBinding | None:
        return self.bindings.get(connection.name)

    def validate(self, connection: str, subject: str, event: CloudEvent[Any]) -> str | None:
        return None

    def run_scope(self, connection: str) -> Any:
        return nullcontext()


class Broker:
    """Stands in for nats.connect: one mocked core client per opened link, in the order they were opened."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.links: dict[str, list[MagicMock]] = {}
        self.fail_next: dict[str, int] = {}

    async def open(self, link: Any) -> None:
        if self.fail_next.get(link.name, 0):
            self.fail_next[link.name] -= 1
            raise ConnectionError(f"{link.name} not reachable yet")
        core = MagicMock(is_closed=False, flush=AsyncMock())
        sub = MagicMock(drain=AsyncMock(), unsubscribe=AsyncMock())

        async def subscribe(*args: Any, **kwargs: Any) -> MagicMock:
            self.events.append(f"bind {link.name}#{len(self.links[link.name])}")
            return sub

        async def close() -> None:
            self.events.append(f"close {link.name}#{self.links[link.name].index(core) + 1}")

        core.subscribe = AsyncMock(side_effect=subscribe)
        core.close = AsyncMock(side_effect=close)
        core.sub = sub
        self.links.setdefault(link.name, []).append(core)
        link.nats_client = core


@pytest.fixture
def broker() -> Broker:
    return Broker()


@pytest.fixture
def configured(nats_client: NATSClient, mock_config: MagicMock) -> Any:
    """Override config keys of the nats_client fixture: configured(**{key: value})."""
    base = mock_config.get.side_effect

    def apply(**values: Any) -> None:
        mock_config.get.side_effect = lambda key, default=None: values[key] if key in values else base(key, default)

    apply(event_client_retry_delay=0.01, subscription_change_grace=0.05)
    return apply


async def _started(nats_client: NATSClient, source: WatchedSource, broker: Broker, topics: tuple[str, ...] = ("risk.>",)) -> None:
    nats_client.set_connection_source(source)  # type: ignore[arg-type]
    with patch.object(nats_client, "_start_retry_task"):
        await nats_client.subscribe({topic: AsyncMock() for topic in topics})
    await _settled(nats_client)


async def _settled(nats_client: NATSClient) -> None:
    for _ in range(50):
        await asyncio.sleep(0.01)
        busy = [t for t in nats_client._named_tasks.values() if not t.done()]
        reconcile = nats_client._reconcile_task
        if not busy and (reconcile is None or reconcile.done()) and not nats_client._retirements:
            return


def _delivery(name: str) -> MagicMock:
    event = CloudEvent(id=f"ev-{name}", type="risk.created", source="t")
    msg = MagicMock(data=json.dumps(dict(event)).encode(), reply="$JS.ACK.x", subject=f"t.{name}.risk.created")
    for verb in ("ack", "nak", "term", "in_progress"):
        setattr(msg, verb, AsyncMock())
    msg.metadata.num_delivered = 1
    return msg


@pytest.fixture(autouse=True)
def fake_broker(nats_client: NATSClient, broker: Broker, configured: Any) -> Any:
    with patch.object(nats_client, "_open_named_link", side_effect=broker.open):
        yield


class TestTheSourceStaysOptional:
    def test_a_source_without_watch_is_still_a_connection_source(self) -> None:
        class Static:
            def claims(self, agent: str, subjects: tuple) -> tuple:
                return subjects

            def connections(self) -> dict:
                return {}

            def binding(self, agent: str, subjects: tuple, connection: Any) -> None:
                return None

            def validate(self, connection: str, subject: str, event: Any) -> None:
                return None

            def run_scope(self, connection: str) -> Any:
                return nullcontext()

        assert isinstance(Static(), ConnectionSource)

    async def test_watch_is_registered_at_subscribe(self, nats_client: NATSClient, broker: Broker) -> None:
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        assert source.notifiers == [nats_client._connections_changed]


class TestAddRemoveChange:
    async def test_an_added_connection_is_bound_and_counted(self, nats_client: NATSClient, broker: Broker) -> None:
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        pairs = nats_client._pool.pairs

        source.change(A=_binding("A"), C=_binding("C"))
        await _settled(nats_client)

        assert nats_client.named_connections == ("A", "C")
        assert "bind C#1" in broker.events
        assert nats_client._pool.pairs == pairs + 1

    async def test_a_removed_connection_is_drained_and_closed(self, nats_client: NATSClient, broker: Broker) -> None:
        source = WatchedSource(A=_binding("A"), B=_binding("B"))
        await _started(nats_client, source, broker)
        pairs = nats_client._pool.pairs

        source.change(A=_binding("A"))
        await _settled(nats_client)

        assert nats_client.named_connections == ("A",)
        broker.links["B"][0].sub.drain.assert_awaited_once()
        assert "close B#1" in broker.events
        assert nats_client._pool.pairs == pairs - 1

    async def test_a_changed_connection_binds_the_new_link_before_closing_the_old(self, nats_client: NATSClient, broker: Broker) -> None:
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)

        source.passwords["A"] = "PLACEHOLDER-2"
        source.notify()
        await _settled(nats_client)

        assert broker.events == ["bind A#1", "bind A#2", "close A#1"]
        assert nats_client.named_connections == ("A",)
        assert nats_client._named[0].link.nats_client is broker.links["A"][1]

    async def test_the_old_link_keeps_serving_until_the_new_one_binds(self, nats_client: NATSClient, broker: Broker) -> None:
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        broker.fail_next["A"] = 3

        source.passwords["A"] = "PLACEHOLDER-2"
        source.notify()
        await asyncio.sleep(0.015)
        assert "close A#1" not in broker.events, "nothing closed while the new link cannot bind"
        await _settled(nats_client)
        assert broker.events[-2:] == ["bind A#2", "close A#1"]

    async def test_a_second_change_before_the_first_bound_still_retires_the_old_link(self, nats_client: NATSClient, broker: Broker) -> None:
        """M3 -- the middle binding never bound; chaining it left the first one consuming for good."""
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        broker.fail_next["A"] = 10_000
        source.passwords["A"] = "PLACEHOLDER-2"
        source.notify()
        await asyncio.sleep(0.05)
        source.passwords["A"] = "PLACEHOLDER-3"
        source.notify()
        await asyncio.sleep(0.05)
        assert "close A#1" not in broker.events, "the old link serves until the newest one binds"

        broker.fail_next["A"] = 0
        await _settled(nats_client)

        assert broker.events == ["bind A#1", "bind A#2", "close A#1"]
        assert [binding.link.nats_client for binding in nats_client._named] == [broker.links["A"][1]]

    async def test_a_removal_before_the_change_bound_retires_both(self, nats_client: NATSClient, broker: Broker) -> None:
        """M3 -- removing retired the pending binding only; the bound one it was to replace kept consuming."""
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        broker.fail_next["A"] = 10_000
        source.passwords["A"] = "PLACEHOLDER-2"
        source.notify()
        await asyncio.sleep(0.05)

        source.change()
        await _settled(nats_client)

        assert "close A#1" in broker.events
        assert nats_client._named == []

    async def test_a_reconnect_restores_readiness_only_for_a_bound_binding(self, nats_client: NATSClient, broker: Broker) -> None:
        """A binding whose bind failed has no subscription for nats-py to replay."""
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        binding = nats_client._named[0]
        binding.bound = False
        binding.subscriptions_ready = False
        assert binding.link.nats_client is not None

        with patch.object(nats_client_module.nats, "connect", new_callable=AsyncMock, return_value=MagicMock(is_closed=False)) as connect:
            binding.link.nats_client = None
            await NATSClient._open_named_link(nats_client, binding.link)
            await connect.call_args.kwargs["reconnected_cb"]()

        assert binding.subscriptions_ready is False

    async def test_an_unchanged_connection_is_left_alone(self, nats_client: NATSClient, broker: Broker) -> None:
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        source.notify()
        await _settled(nats_client)
        assert broker.events == ["bind A#1"]


class TestSkipped:
    async def test_an_undeclared_subject_skips_that_connection_only(
        self, nats_client: NATSClient, broker: Broker, caplog: pytest.LogCaptureFixture
    ) -> None:
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        with caplog.at_level(logging.ERROR):
            source.change(A=_binding("A"), C=_binding("C", "invented.>"))
            await _settled(nats_client)
        assert nats_client.named_connections == ("A",)
        assert any("connection 'C' skipped" in message for message in caplog.messages)

    async def test_an_agent_mapping_results_gains_no_connection(
        self, nats_client: NATSClient, broker: Broker, configured: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Plan D4 at runtime: a result would leave the connection its event arrived on."""
        configured(event_client_retry_delay=0.01, **{"event_publishing.topic_mapping": {"x": {"topic": "out"}}})
        source = WatchedSource()
        await _started(nats_client, source, broker)
        with caplog.at_level(logging.ERROR):
            source.change(A=_binding("A"))
            await _settled(nats_client)
        assert nats_client.named_connections == ()
        assert any("plan D4" in message for message in caplog.messages)


class TestRevocation:
    async def _in_flight(
        self, nats_client: NATSClient, broker: Broker, ack_wait: float = 600.0, publish: bool = True
    ) -> tuple[Any, MagicMock, asyncio.Event, list]:
        source = WatchedSource(A=_binding("A"), B=_binding("B", ack_wait=ack_wait))
        await _started(nats_client, source, broker)
        gate, outcome = asyncio.Event(), []

        async def handler(event: CloudEvent, subject: str) -> None:
            await gate.wait()
            if not publish:
                return
            try:
                await nats_client.publish("out.done", event)
            except DeliveryRevokedError as exc:
                outcome.append(exc)
                raise

        b = next(binding for binding in nats_client._named if binding.link.name == "B")
        b.topic_callbacks["risk.>"] = handler
        msg = _delivery("B")
        await broker.links["B"][0].subscribe.await_args.kwargs["cb"](msg)
        await asyncio.sleep(0)
        source.change(A=_binding("A"))
        return b, msg, gate, outcome

    async def test_a_run_outliving_the_grace_is_never_settled(self, nats_client: NATSClient, broker: Broker) -> None:
        b, msg, gate, outcome = await self._in_flight(nats_client, broker)
        await _settled(nats_client)
        assert b.revoked and b not in nats_client._named
        gate.set()
        await asyncio.gather(*list(b.runs), return_exceptions=True)
        for verb in ("ack", "nak", "term"):
            getattr(msg, verb).assert_not_awaited()

    async def test_publishing_from_a_revoked_run_is_refused(self, nats_client: NATSClient, broker: Broker) -> None:
        b, msg, gate, outcome = await self._in_flight(nats_client, broker)
        await _settled(nats_client)
        gate.set()
        await asyncio.gather(*list(b.runs), return_exceptions=True)
        assert len(outcome) == 1 and isinstance(outcome[0], DeliveryRevokedError)

    async def test_its_heartbeat_stops_at_revocation(self, nats_client: NATSClient, broker: Broker) -> None:
        b, msg, gate, outcome = await self._in_flight(nats_client, broker, ack_wait=0.03)
        await _settled(nats_client)
        beats = msg.in_progress.await_count
        await asyncio.sleep(0.05)
        assert msg.in_progress.await_count == beats, "no in_progress after revocation"
        gate.set()
        await asyncio.gather(*list(b.runs), return_exceptions=True)

    async def test_a_run_finishing_within_the_grace_is_settled_normally(
        self, nats_client: NATSClient, broker: Broker, configured: Any
    ) -> None:
        configured(event_client_retry_delay=0.01, subscription_change_grace=5.0)
        b, msg, gate, outcome = await self._in_flight(nats_client, broker, publish=False)
        await asyncio.sleep(0.02)
        gate.set()
        await _settled(nats_client)
        assert not b.revoked
        msg.ack.assert_awaited_once()


class TestScheduling:
    async def test_notifications_during_a_change_coalesce_into_one_more_pass(self, nats_client: NATSClient, broker: Broker) -> None:
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        reads = source.reads
        for _ in range(5):
            source.notify()
        await _settled(nats_client)
        assert source.reads - reads <= 2

    async def test_a_notify_from_another_thread_is_applied_on_the_loop(self, nats_client: NATSClient, broker: Broker) -> None:
        source = WatchedSource(A=_binding("A"))
        await _started(nats_client, source, broker)
        source.bindings["C"] = _binding("C")
        thread = threading.Thread(target=source.notify)
        thread.start()
        thread.join()
        await _settled(nats_client)
        assert nats_client.named_connections == ("A", "C")

    async def test_a_pause_waits_for_a_change_in_progress(self, nats_client: NATSClient, broker: Broker, configured: Any) -> None:
        configured(event_client_retry_delay=0.01, subscription_change_grace=0.2)
        source = WatchedSource(A=_binding("A"), B=_binding("B"))
        await _started(nats_client, source, broker)
        b = next(binding for binding in nats_client._named if binding.link.name == "B")
        b.enter_run()  # a run in flight keeps the retirement in its grace period
        source.change(A=_binding("A"))
        await asyncio.sleep(0.02)
        order: list[str] = []
        pause = asyncio.create_task(nats_client.pause_consumption())
        await asyncio.sleep(0.05)
        order.append("pause still waiting" if not pause.done() else "pause done")
        await pause
        order.append("pause done")
        assert order == ["pause still waiting", "pause done"]
        assert b not in nats_client._named

    async def test_close_during_a_change_cancels_it_and_cleans_up(self, nats_client: NATSClient, broker: Broker, configured: Any) -> None:
        configured(event_client_retry_delay=0.01, subscription_change_grace=10.0, event_client_drain_timeout=0.05)
        source = WatchedSource(A=_binding("A"), B=_binding("B"))
        await _started(nats_client, source, broker)
        b = next(binding for binding in nats_client._named if binding.link.name == "B")
        b.enter_run()
        source.change(A=_binding("A"))
        await asyncio.sleep(0.02)
        await asyncio.wait_for(nats_client.close(), timeout=2)
        assert nats_client._reconcile_task is not None and nats_client._reconcile_task.done()
        assert {"close A#1", "close B#1"} <= set(broker.events)


class TestPermissionViolations:
    async def test_a_refused_permission_fails_the_connection_and_says_so(
        self, nats_client: NATSClient, broker: Broker, caplog: pytest.LogCaptureFixture
    ) -> None:
        """D23: a missing grant is final -- not retried, reported CRITICAL naming the connection and the subject."""
        source = WatchedSource(A=_binding("A"))
        calls = 0

        async def denied(link: Any) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                link.permission_errors.append("nats: permissions violation for subscription to deliver.A")
                raise TimeoutError()
            await broker.open(link)

        with (
            patch.object(nats_client, "_open_named_link", side_effect=denied),
            caplog.at_level(logging.ERROR),
        ):
            nats_client._started = True
            await _started(nats_client, source, broker)
        critical = [r.getMessage() for r in caplog.records if r.levelno == logging.CRITICAL]
        assert any("named connection 'A'" in message and "deliver.A" in message for message in critical)
        assert calls == 1
        assert nats_client.named_connection_states()[0].state == "failed"

    async def test_the_error_callback_records_permission_violations(self, nats_client: NATSClient) -> None:
        from blueprint.agents.clients.io.nats_client import _Link

        link = _Link(name="A", url="nats://h:4222")
        with patch("blueprint.agents.clients.io.nats_client.nats.connect", new_callable=AsyncMock) as connect:
            await NATSClient._open_named_link(nats_client, link)
        await connect.await_args.kwargs["error_cb"](Exception("nats: permissions violation for publish to $JS.API.X"))
        await connect.await_args.kwargs["error_cb"](Exception("nats: unexpected EOF"))
        assert link.permission_errors == ["nats: permissions violation for publish to $JS.API.X"]
