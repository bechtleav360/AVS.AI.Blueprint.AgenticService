"""Per-connection state, nats_connections_readiness and the readiness refresh (named-connections plan, step 5)."""

import asyncio
from contextlib import nullcontext
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nats.js import api as js_api

from blueprint.agents.clients.io import nats_client as nats_client_module
from blueprint.agents.clients.io.nats_client import (
    CONNECTION_BOUND_GAUGE,
    PERMISSION_VIOLATIONS_COUNTER,
    NamedConnectionState,
    NATSClient,
)
from blueprint.agents.clients.io.nats_connections import ConnectionSpec, JetStreamBinding
from blueprint.agents.io.api.actuators.health import NamedConnectionsHealthChecker
from blueprint.agents.models.events import CloudEvent

PASSWORD = "PLACEHOLDER-not-a-secret"


def _binding(name: str) -> JetStreamBinding:
    return JetStreamBinding(
        subjects=("risk.>",),
        stream=f"S_{name}",
        durable=f"d-{name}",
        deliver_subject=f"deliver.{name}",
        deliver_group="g",
        ack_wait=600.0,
        subject_prefix=f"t.{name}.",
        max_deliver=5,
        deliver_policy=js_api.DeliverPolicy.NEW,
    )


class Source:
    """Every declared subject is a tenant subject; one connection per name given."""

    def __init__(self, *names: str) -> None:
        self.names = names

    def claims(self, agent: str, subjects: tuple[str, ...]) -> tuple[str, ...]:
        return subjects

    def connections(self) -> dict[str, ConnectionSpec]:
        return {name: ConnectionSpec(name=name, url=f"nats://u:{PASSWORD}@h:4222", user="u", password=PASSWORD) for name in self.names}

    def binding(self, agent: str, subjects: tuple[str, ...], connection: ConnectionSpec) -> JetStreamBinding | None:
        return _binding(connection.name)

    def validate(self, connection: str, subject: str, event: CloudEvent[Any]) -> str | None:
        return None

    def run_scope(self, connection: str) -> Any:
        return nullcontext()


class Broker:
    """Stands in for opening a named link; a connection listed in ``failing`` raises what is set there."""

    def __init__(self) -> None:
        self.failing: dict[str, BaseException] = {}
        self.denied: set[str] = set()
        self.cores: dict[str, MagicMock] = {}

    async def open(self, link: Any) -> None:
        if link.name in self.denied:
            link.permission_errors.append("nats: permissions violation for subscription to x")
        error = self.failing.get(link.name)
        if error is not None:
            raise error
        core = MagicMock(is_closed=False, is_reconnecting=False)
        core.subscribe = AsyncMock(return_value=MagicMock(drain=AsyncMock(), unsubscribe=AsyncMock()))
        core.close = AsyncMock()
        self.cores[link.name] = core
        link.nats_client = core


@pytest.fixture
def broker() -> Broker:
    return Broker()


@pytest.fixture
def configured(nats_client: NATSClient, mock_config: MagicMock) -> Any:
    """Override config keys of the nats_client fixture: configured(**{key: value})."""
    base = mock_config.get.side_effect

    def apply(**values: Any) -> None:
        merged = {"event_client_retry_delay": 0.01, **values}
        mock_config.get.side_effect = lambda key, default=None: merged[key] if key in merged else base(key, default)

    apply()
    return apply


@pytest.fixture(autouse=True)
def fake_broker(nats_client: NATSClient, broker: Broker, configured: Any) -> Any:
    with patch.object(nats_client, "_open_named_link", side_effect=broker.open):
        yield


async def _started(nats_client: NATSClient, *names: str) -> None:
    nats_client.set_connection_source(Source(*names))  # type: ignore[arg-type]
    with patch.object(nats_client, "_start_retry_task"):
        await nats_client.subscribe({"risk.>": AsyncMock()})
    for _ in range(20):
        await asyncio.sleep(0.01)


def _states(nats_client: NATSClient) -> dict[str, NamedConnectionState]:
    return {state.name: state for state in nats_client.named_connection_states()}


class TestTheStateOfEachConnection:
    async def test_a_bound_connection_reads_bound(self, nats_client: NATSClient) -> None:
        await _started(nats_client, "A")
        assert _states(nats_client)["A"] == NamedConnectionState("A", "bound")

    async def test_a_failing_connection_reads_retrying_with_its_error_redacted(self, nats_client: NATSClient, broker: Broker) -> None:
        broker.failing["B"] = ConnectionError(f"nats://u:{PASSWORD}@h:4222 refused: {PASSWORD}")
        await _started(nats_client, "A", "B")

        states = _states(nats_client)
        assert states["A"].bound
        assert states["B"].state == "retrying"
        assert states["B"].last_error.startswith("ConnectionError: nats://***@h:4222 refused")
        assert PASSWORD not in states["B"].describe()

    async def test_a_refused_permission_is_reported(self, nats_client: NATSClient, broker: Broker) -> None:
        broker.failing["B"] = TimeoutError("no response")
        broker.denied.add("B")
        with patch.object(nats_client_module, "PERMISSION_RETRY_SECONDS", 0.01):
            await _started(nats_client, "B")
        assert _states(nats_client)["B"].permission_denied
        assert "permission violation" in _states(nats_client)["B"].describe()

    async def test_the_error_is_cleared_once_it_binds(self, nats_client: NATSClient, broker: Broker) -> None:
        broker.failing["B"] = ConnectionError("down")
        await _started(nats_client, "B")
        del broker.failing["B"]
        for _ in range(20):
            await asyncio.sleep(0.01)
        assert _states(nats_client)["B"] == NamedConnectionState("B", "bound")

    async def test_a_refused_login_reads_retrying_although_connect_never_returns(self, nats_client: NATSClient) -> None:
        """With max_reconnect_attempts=-1 nats.connect() retries a refused login itself; only error_cb hears of it."""
        await _started(nats_client, "B")
        binding = nats_client._named[0]
        binding.subscriptions_ready = False
        link = binding.link
        link.nats_client = None
        connect = AsyncMock(return_value=MagicMock(is_closed=False, is_reconnecting=False))
        with (
            patch.object(nats_client_module.nats, "connect", connect),
            patch.object(nats_client, "_open_named_link", NATSClient._open_named_link.__get__(nats_client)),
        ):
            await nats_client._open_named_link(link)
            await connect.call_args.kwargs["error_cb"](Exception("nats: 'Authorization Violation'"))

        assert _states(nats_client)["B"] == NamedConnectionState("B", "retrying", "Exception: nats: 'Authorization Violation'")

    async def test_a_lost_broker_reads_reconnecting(self, nats_client: NATSClient, broker: Broker) -> None:
        await _started(nats_client, "A")
        nats_client._named[0].subscriptions_ready = False
        broker.cores["A"].is_reconnecting = True
        assert _states(nats_client)["A"].state == "reconnecting"

    async def test_a_paused_agent_reads_paused(self, nats_client: NATSClient) -> None:
        await _started(nats_client, "A")
        await nats_client.pause_consumption()
        assert _states(nats_client)["A"].state == "paused"


class TestTheReadinessMode:
    async def test_it_defaults_to_never(self, nats_client: NATSClient) -> None:
        await _started(nats_client, "A")
        assert nats_client.connections_readiness == "never"

    @pytest.mark.parametrize("raw, mode", [("any", "any"), ("ALL", "all"), (" never ", "never")])
    async def test_the_three_modes_are_accepted(self, nats_client: NATSClient, configured: Any, raw: str, mode: str) -> None:
        configured(nats_connections_readiness=raw)
        await _started(nats_client, "A")
        assert nats_client.connections_readiness == mode

    async def test_anything_else_fails_subscribe_naming_the_key(self, nats_client: NATSClient, configured: Any) -> None:
        configured(nats_connections_readiness="some")
        with pytest.raises(ValueError, match="nats_connections_readiness"):
            await _started(nats_client, "A")


class TestTheCheckerFollowsTheMode:
    @staticmethod
    def _client(mode: str, *states: NamedConnectionState) -> MagicMock:
        client = MagicMock(connections_readiness=mode)
        client.named_connection_states.return_value = states
        return client

    BOUND = NamedConnectionState("A", "bound")
    DOWN = NamedConnectionState("B", "retrying", "ConnectionError: refused")

    @pytest.mark.parametrize(
        "mode, states, status",
        [
            ("never", (DOWN,), "healthy"),
            ("never", (), "healthy"),
            ("any", (BOUND, DOWN), "healthy"),
            ("any", (DOWN,), "unhealthy"),
            ("any", (), "unhealthy"),
            ("all", (BOUND, DOWN), "unhealthy"),
            ("all", (BOUND,), "healthy"),
        ],
    )
    async def test_status(self, mode: str, states: tuple[NamedConnectionState, ...], status: str) -> None:
        result = await NamedConnectionsHealthChecker(self._client(mode, *states)).health_check()  # type: ignore[arg-type]
        assert result.status == status

    async def test_the_message_names_each_connection_and_why(self) -> None:
        result = await NamedConnectionsHealthChecker(self._client("all", self.BOUND, self.DOWN)).health_check()  # type: ignore[arg-type]
        assert result.message == "1/2 named connection(s) bound, readiness 'all': A=bound, B=retrying (ConnectionError: refused)"


class TestReadinessIsReEvaluatedAtOnce:
    async def test_a_reconnect_of_a_paused_agent_refreshes(self, nats_client: NATSClient) -> None:
        refresh = AsyncMock()
        nats_client.set_health_refresh(refresh)
        nats_client._subscriptions_managed = True
        nats_client._consumption_paused = True

        await nats_client._on_reconnected()
        await asyncio.sleep(0)

        refresh.assert_awaited_once()

    async def test_a_reconnect_of_a_serving_agent_does_not(self, nats_client: NATSClient) -> None:
        refresh = AsyncMock()
        nats_client.set_health_refresh(refresh)
        nats_client._subscriptions_managed = True

        await nats_client._on_reconnected()
        await asyncio.sleep(0)

        refresh.assert_not_awaited()

    async def test_a_named_connection_binding_refreshes_when_the_mode_reads_it(self, nats_client: NATSClient, configured: Any) -> None:
        configured(nats_connections_readiness="any")
        refresh = AsyncMock()
        nats_client.set_health_refresh(refresh)
        await _started(nats_client, "A")
        refresh.assert_awaited_once()

    async def test_under_never_it_does_not(self, nats_client: NATSClient) -> None:
        refresh = AsyncMock()
        nats_client.set_health_refresh(refresh)
        await _started(nats_client, "A")
        refresh.assert_not_awaited()

    async def test_a_failing_refresh_is_logged_with_the_agent(self, nats_client: NATSClient, caplog: pytest.LogCaptureFixture) -> None:
        nats_client.set_health_refresh(AsyncMock(side_effect=RuntimeError("poll broke")))
        nats_client._subscriptions_managed = True
        nats_client._consumption_paused = True

        await nats_client._on_reconnected()
        for _ in range(3):
            await asyncio.sleep(0)

        assert "re-evaluating readiness failed: poll broke" in caplog.text


class TestMetrics:
    async def test_the_bound_gauge_reports_each_connection(self, nats_client: NATSClient, broker: Broker) -> None:
        meter = MagicMock()
        broker.failing["B"] = ConnectionError("down")
        with patch.object(nats_client_module, "agent_meter", return_value=meter):
            await _started(nats_client, "A", "B")

        (name,), kwargs = meter.create_observable_gauge.call_args
        assert name == CONNECTION_BOUND_GAUGE
        observations = {o.attributes["connection"]: o.value for o in kwargs["callbacks"][0](MagicMock())}
        assert observations == {"A": 1, "B": 0}

    async def test_no_gauge_without_a_source(self, nats_client: NATSClient) -> None:
        meter = MagicMock()
        with patch.object(nats_client_module, "agent_meter", return_value=meter), patch.object(nats_client, "_start_retry_task"):
            await nats_client.subscribe({"risk.>": AsyncMock()})
        meter.create_observable_gauge.assert_not_called()

    async def test_a_permission_violation_is_counted(self, nats_client: NATSClient) -> None:
        meter = MagicMock()
        link = nats_client_module._Link(name="A", url="nats://h:4222")
        connect = AsyncMock(return_value=MagicMock(is_closed=False))
        with (
            patch.object(nats_client_module, "agent_meter", return_value=meter),
            patch.object(nats_client_module.nats, "connect", connect),
            patch.object(nats_client, "_open_named_link", NATSClient._open_named_link.__get__(nats_client)),
        ):
            await nats_client._open_named_link(link)
            await connect.call_args.kwargs["error_cb"](Exception("nats: Permissions Violation for Subscription to t.A.x"))

        assert meter.create_counter.call_args.kwargs["name"] == PERMISSION_VIOLATIONS_COUNTER
        meter.create_counter.return_value.add.assert_called_once_with(1, {"agent": "<root>", "connection": "A"})
        assert link.permission_errors
