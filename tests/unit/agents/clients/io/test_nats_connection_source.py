"""Named connections from a connection source (named-connections plan, step 3a)."""

import asyncio
import contextvars
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nats.js import api as js_api

from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.clients.io.nats_connections import (
    ConnectionSpec,
    JetStreamBinding,
    current_connection,
    load_connection_source,
    mark_connection,
)
from blueprint.agents.io.api.eventing.nats import NatsEventing
from blueprint.agents.models.events import CloudEvent

SCOPED: contextvars.ContextVar[str | None] = contextvars.ContextVar("test_scoped", default=None)
AMBIENT: contextvars.ContextVar[str | None] = contextvars.ContextVar("test_ambient", default=None)


def _binding(prefix: str, *subjects: str) -> JetStreamBinding:
    return JetStreamBinding(
        subjects=subjects,
        stream=f"S_{prefix}",
        durable=f"d-{prefix}",
        deliver_subject=f"deliver.{prefix}",
        deliver_group="g",
        ack_wait=600.0,
        subject_prefix=f"t.{prefix}.",
        max_deliver=5,
        deliver_policy=js_api.DeliverPolicy.NEW,
    )


class FakeSource:
    """A deployment's source: two connections, and a scope that sets a ContextVar per connection."""

    def __init__(self, bindings: dict[str, JetStreamBinding | None], reject: Any = None, claimed: tuple[str, ...] | None = None) -> None:
        self.bindings = bindings
        self.reject = reject
        self.claimed = claimed  # None: every declared subject, as in the first consumer of named connections
        self.asked: list[tuple[str, tuple[str, ...], str]] = []

    def claims(self, agent: str, subjects: tuple[str, ...]) -> tuple[str, ...]:
        return subjects if self.claimed is None else self.claimed

    def connections(self) -> dict[str, ConnectionSpec]:
        return {name: ConnectionSpec(name=name, url="nats://localhost:4222") for name in self.bindings}

    def binding(self, agent: str, subjects: tuple[str, ...], connection: ConnectionSpec) -> JetStreamBinding | None:
        self.asked.append((agent, subjects, connection.name))
        return self.bindings[connection.name]

    def validate(self, connection: str, subject: str, event: CloudEvent[Any]) -> str | None:
        return self.reject(connection, subject, event) if self.reject else None

    def run_scope(self, connection: str) -> Any:
        @contextmanager
        def scope() -> Iterator[None]:
            token = SCOPED.set(connection)
            try:
                yield
            finally:
                SCOPED.reset(token)

        return scope()


def make_source(config: Any) -> FakeSource:
    """Factory for load_connection_source, as a deployment would write one."""
    return FakeSource({"A": _binding("A", "risk.>")})


def not_a_source(config: Any) -> object:
    return object()


async def _subscribed(nats_client: NATSClient, source: FakeSource, topics: tuple[str, ...]) -> dict[str, AsyncMock]:
    """subscribe() with the source, without starting any connection loop."""
    nats_client.set_connection_source(source)
    callbacks = {topic: AsyncMock() for topic in topics}
    with patch.object(nats_client, "_start_retry_task"), patch.object(nats_client, "_start_named_links"):
        await nats_client.subscribe(callbacks)
    return callbacks


def _delivery(cloud_event: CloudEvent, subject: str) -> MagicMock:
    msg = MagicMock(data=json.dumps(dict(cloud_event)).encode(), reply="$JS.ACK.x", subject=subject)
    for name in ("ack", "nak", "term", "in_progress"):
        setattr(msg, name, AsyncMock())
    msg.metadata.num_delivered = 1
    return msg


async def _bound_handler(nats_client: NATSClient, mock_nats_core: MagicMock, name: str) -> tuple[Any, Any]:
    """Bind the named binding ``name`` on a mocked link and return it with its broker callback."""
    binding = next(binding for binding in nats_client._named if binding.link.name == name)
    core = MagicMock(
        subscribe=AsyncMock(return_value=MagicMock(drain=AsyncMock(), unsubscribe=AsyncMock())), close=AsyncMock(), is_closed=False
    )
    binding.link.nats_client = core
    await nats_client._bind(binding)
    return binding, core.subscribe.await_args.kwargs["cb"]


async def _deliver(binding: Any, handler: Any, msg: MagicMock) -> None:
    await handler(msg)
    await asyncio.gather(*list(binding.runs), return_exceptions=True)


class TestLoadingTheSource:
    def test_unset_is_no_source(self) -> None:
        assert load_connection_source(None, MagicMock()) is None
        assert load_connection_source("  ", MagicMock()) is None

    def test_the_factory_is_called_with_the_config(self) -> None:
        source = load_connection_source(f"{__name__}:make_source", MagicMock())
        assert isinstance(source, FakeSource)

    @pytest.mark.parametrize(
        "path",
        ["no_colon_here", "no.such.module:factory", f"{__name__}:missing", f"{__name__}:not_a_source"],
        ids=["format", "import", "attribute", "not-a-source"],
    )
    def test_a_wrong_path_fails_naming_the_key(self, path: str) -> None:
        with pytest.raises(ValueError, match="nats_connection_source"):
            load_connection_source(path, MagicMock())


class TestConnectionSpec:
    def test_secrets_stay_out_of_its_repr(self) -> None:
        spec = ConnectionSpec(name="A", url="nats://h:4222", user="u", password="PLACEHOLDER")
        assert "PLACEHOLDER" not in repr(spec)
        assert spec.connect_options() == {"user": "u", "password": "PLACEHOLDER"}

    @pytest.mark.parametrize(
        "kwargs",
        [{"name": ""}, {"name": "a b"}, {"url": "http://h"}, {"user": "u"}],
        ids=["empty-name", "space-in-name", "not-nats", "user-without-password"],
    )
    def test_an_unusable_spec_is_refused(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            ConnectionSpec(**{"name": "A", "url": "nats://h:4222", **kwargs})


class TestPlanningTheBindings:
    async def test_claimed_subjects_never_go_to_the_default_connection(self, nats_client: NATSClient) -> None:
        source = FakeSource({"A": _binding("A", "risk.>", "issue.>"), "B": _binding("B", "risk.>"), "C": None})
        await _subscribed(nats_client, source, ("risk.>", "issue.>", "audit.>"))

        assert nats_client.named_connections == ("A", "B")
        assert list(nats_client._topic_callbacks) == [], "audit.> is claimed: served by no connection yet, but never by the default one"
        assert source.asked == [("test-agent", ("risk.>", "issue.>", "audit.>"), name) for name in ("A", "B", "C")]

    async def test_no_connection_yet_is_no_error_and_subscribes_nothing(self, nats_client: NATSClient) -> None:
        """A fresh environment without tenants: nothing to consume yet, nothing on the default connection."""
        await _subscribed(nats_client, FakeSource({}), ("risk.>", "issue.>"))
        assert nats_client.named_connections == ()
        assert list(nats_client._topic_callbacks) == []

    async def test_an_unclaimed_subject_fails_startup_by_default(self, nats_client: NATSClient) -> None:
        source = FakeSource({"A": _binding("A", "risk.>")}, claimed=("risk.>",))
        with pytest.raises(ValueError, match="scheduler.tick.*does not claim.*nats_unclaimed_subjects"):
            await _subscribed(nats_client, source, ("risk.>", "scheduler.tick"))

    async def test_the_hybrid_mode_must_be_asked_for(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        base = mock_config.get.side_effect
        mock_config.get.side_effect = lambda key, default=None: (
            "default_connection" if key == "nats_unclaimed_subjects" else base(key, default)
        )
        source = FakeSource({"A": _binding("A", "risk.>")}, claimed=("risk.>",))
        await _subscribed(nats_client, source, ("risk.>", "scheduler.tick"))
        assert list(nats_client._topic_callbacks) == ["scheduler.tick"]

    async def test_an_unknown_policy_is_refused(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        base = mock_config.get.side_effect
        mock_config.get.side_effect = lambda key, default=None: "hybrid" if key == "nats_unclaimed_subjects" else base(key, default)
        with pytest.raises(ValueError, match="nats_unclaimed_subjects"):
            await _subscribed(nats_client, FakeSource({}, claimed=("risk.>",)), ("risk.>", "x.>"))

    async def test_a_claim_names_declared_subjects_only(self, nats_client: NATSClient) -> None:
        with pytest.raises(ValueError, match="claims invented.>, which the agent does not declare"):
            await _subscribed(nats_client, FakeSource({}, claimed=("risk.>", "invented.>")), ("risk.>",))

    async def test_a_binding_serves_claimed_subjects_only(self, nats_client: NATSClient) -> None:
        source = FakeSource({"A": _binding("A", "invented.>")}, claimed=("risk.>",))
        with pytest.raises(ValueError, match="serves invented.>, which the source does not claim"):
            await _subscribed(nats_client, source, ("risk.>",))

    async def test_without_a_source_nothing_changes(self, nats_client: NATSClient) -> None:
        with patch.object(nats_client, "_start_retry_task"), patch.object(nats_client, "_start_named_links"):
            await nats_client.subscribe({"risk.>": AsyncMock()})
        assert nats_client.named_connections == ()
        assert list(nats_client._topic_callbacks) == ["risk.>"]

    async def test_result_publishing_is_refused_with_named_connections(self, nats_client: NATSClient, mock_config: MagicMock) -> None:
        """Plan D4: a result would leave the connection its event arrived on."""
        base = mock_config.get.side_effect
        mock_config.get.side_effect = lambda key, default=None: (
            {"x.done": {"topic": "out.done"}} if key == "event_publishing.topic_mapping" else base(key, default)
        )
        with pytest.raises(ValueError, match="topic_mapping"):
            await _subscribed(nats_client, FakeSource({"A": _binding("A", "risk.>")}), ("risk.>",))


class TestARunFromANamedConnection:
    async def test_it_runs_in_the_sources_scope_and_knows_its_connection(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        seen: dict[str, Any] = {}

        async def callback(event: CloudEvent, subject: str) -> None:
            seen.update(scoped=SCOPED.get(), connection=current_connection(), ambient=AMBIENT.get(), subject=subject)

        source = FakeSource({"A": _binding("A", "risk.>")})
        await _subscribed(nats_client, source, ("risk.>",))
        nats_client._named[0].topic_callbacks["risk.>"] = callback
        binding, handler = await _bound_handler(nats_client, mock_nats_core, "A")

        AMBIENT.set("leaked")  # set in the context the delivery arrives from
        msg = _delivery(cloud_event, "t.A.risk.created")
        await _deliver(binding, handler, msg)

        assert seen == {"scoped": "A", "connection": "A", "ambient": None, "subject": "risk.created"}
        assert SCOPED.get() is None, "the scope does not outlive the run"
        msg.ack.assert_awaited_once()

    async def test_a_rejected_delivery_is_termed_and_never_runs(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        source = FakeSource({"A": _binding("A", "risk.>")}, reject=lambda connection, subject, event: "tenant mismatch")
        callbacks = await _subscribed(nats_client, source, ("risk.>",))
        binding, handler = await _bound_handler(nats_client, mock_nats_core, "A")
        msg = _delivery(cloud_event, "t.A.risk.created")
        await _deliver(binding, handler, msg)
        callbacks["risk.>"].assert_not_awaited()
        msg.term.assert_awaited_once()
        msg.ack.assert_not_awaited()

    async def test_a_validator_that_raises_leaves_the_delivery_for_redelivery(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        def broken(connection: str, subject: str, event: CloudEvent) -> str | None:
            raise RuntimeError("bug in the deployment's hook")

        callbacks = await _subscribed(nats_client, FakeSource({"A": _binding("A", "risk.>")}, reject=broken), ("risk.>",))
        binding, handler = await _bound_handler(nats_client, mock_nats_core, "A")
        msg = _delivery(cloud_event, "t.A.risk.created")
        await _deliver(binding, handler, msg)
        callbacks["risk.>"].assert_not_awaited()
        msg.nak.assert_awaited_once()

    async def test_two_connections_never_share_a_run_context(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        seen: list[tuple[str | None, str | None]] = []
        gate = asyncio.Event()

        async def callback(event: CloudEvent, subject: str) -> None:
            await gate.wait()  # both runs are in flight at once
            seen.append((SCOPED.get(), current_connection()))

        await _subscribed(nats_client, FakeSource({"A": _binding("A", "risk.>"), "B": _binding("B", "risk.>")}), ("risk.>",))
        for binding in nats_client._named:
            binding.topic_callbacks["risk.>"] = callback
        a, handler_a = await _bound_handler(nats_client, mock_nats_core, "A")
        b, handler_b = await _bound_handler(nats_client, mock_nats_core, "B")
        await handler_a(_delivery(cloud_event, "t.A.risk.created"))
        await handler_b(_delivery(cloud_event, "t.B.risk.created"))
        await asyncio.sleep(0)
        gate.set()
        await asyncio.gather(*list(a.runs), *list(b.runs))
        assert sorted(seen) == [("A", "A"), ("B", "B")]

    async def test_the_default_connection_keeps_its_inherited_context(
        self, nats_client: NATSClient, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        """N6: a run on the default connection is started exactly as before."""
        seen: dict[str, Any] = {}

        async def callback(event: CloudEvent, subject: str) -> None:
            seen.update(ambient=AMBIENT.get(), connection=current_connection())

        nats_client._nats_client = mock_nats_core
        nats_client._client = mock_nats_core
        await nats_client._subscribe_one("risk.>", callback)
        handler = mock_nats_core.subscribe.await_args.kwargs["cb"]
        AMBIENT.set("inherited")
        await handler(_delivery(cloud_event, "risk.created"))
        await asyncio.gather(*list(nats_client._runs))
        assert seen == {"ambient": "inherited", "connection": None}


class TestTheHandlerContext:
    async def test_the_connection_reaches_the_handler_context_only_from_a_named_one(self) -> None:
        eventing = NatsEventing.__new__(NatsEventing)
        captured: list[dict] = []

        async def process(event: Any, context: dict, topic: str) -> Any:
            captured.append(dict(context))
            return MagicMock()

        eventing._process_cloud_event = process  # type: ignore[method-assign]
        callback = eventing._make_event_callback("risk.>")
        event = MagicMock()

        await callback(event, "risk.created")

        async def from_named() -> None:
            mark_connection("A")
            await callback(event, "risk.created")

        await asyncio.create_task(from_named(), context=contextvars.Context())
        assert "nats_connection" not in captured[0]
        assert captured[1]["nats_connection"] == "A"
        assert captured[1]["nats_topic"] == "risk.>"


class TestShutdown:
    async def test_close_drains_and_closes_every_named_link(self, nats_client: NATSClient, mock_nats_core: MagicMock) -> None:
        await _subscribed(nats_client, FakeSource({"A": _binding("A", "risk.>"), "B": _binding("B", "risk.>")}), ("risk.>",))
        links = []
        for name in ("A", "B"):
            binding, _ = await _bound_handler(nats_client, mock_nats_core, name)
            links.append((binding, binding.link.nats_client, binding.subscriptions[0]))
        await nats_client.close()
        for binding, client, sub in links:
            sub.drain.assert_awaited_once()
            client.close.assert_awaited_once()
            assert binding.link.nats_client is None
