"""What happens when one agent of a group stops serving (C3, C4, C7).

The supervisor turns one piece of state -- is this agent serving -- into three things: the
signal (gauge plus ERROR event), the consequence (it stops consuming), and the input to the
readiness verdict. These cases cover the first two; the third is
``test_readiness_policy.py``.
"""

import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.io.api.actuators.health.namespace_supervisor import NamespaceSupervisor
from blueprint.agents.io.telemetry.providers import reset_providers


@pytest.fixture(autouse=True)
def _forget_providers() -> Iterator[None]:
    """The gauges are created on module-level providers, which are process state."""
    reset_providers()
    yield
    reset_providers()


def _client() -> MagicMock:
    """A transport client that records whether it was paused."""
    client = MagicMock()
    client.pause_consumption = AsyncMock()
    client.resume_consumption = AsyncMock()
    return client


@pytest.fixture
def registry() -> MagicMock:
    """A registry whose IO clients are keyed by namespace, as the real one is."""
    clients: dict[str, list[MagicMock]] = {"": [], "orders": [_client()], "billing": [_client()]}
    registry = MagicMock()
    registry.get_io_clients.side_effect = lambda namespace=None: clients.get(namespace, [])
    registry.clients = clients
    return registry


@pytest.fixture
def supervisor(registry: MagicMock) -> NamespaceSupervisor:
    return NamespaceSupervisor(registry, ["", "orders", "billing"], critical=["orders"])


class TestInitialState:
    def test_every_hosted_agent_starts_up(self, supervisor: NamespaceSupervisor) -> None:
        """An agent with no health check of its own is present and serving, not absent."""
        assert supervisor.status == {"": True, "orders": True, "billing": True}

    def test_an_unknown_agent_counts_as_up(self, supervisor: NamespaceSupervisor) -> None:
        assert supervisor.is_up("nobody") is True

    def test_the_critical_set_is_kept(self, supervisor: NamespaceSupervisor) -> None:
        assert supervisor.critical_namespaces == frozenset({"orders"})


class TestDegradation:
    async def test_a_failing_agent_is_recorded_as_down(self, supervisor: NamespaceSupervisor) -> None:
        await supervisor.observe({"": True, "orders": False, "billing": True})
        assert supervisor.is_up("orders") is False
        assert supervisor.is_up("billing") is True

    async def test_a_failing_agent_stops_consuming(self, supervisor: NamespaceSupervisor, registry: MagicMock) -> None:
        """C4: readiness gates HTTP only, so a degraded agent must be taken off its topics."""
        await supervisor.observe({"": True, "orders": False, "billing": True})
        registry.clients["orders"][0].pause_consumption.assert_awaited_once()
        registry.clients["billing"][0].pause_consumption.assert_not_awaited()

    async def test_the_transition_is_reported_at_error_level_with_the_deployment(
        self, supervisor: NamespaceSupervisor, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """C7: grouping removed the pod restart that used to be the alert."""
        monkeypatch.setenv("BLUEPRINT_GROUP", "finance")
        monkeypatch.setenv("POD_NAME", "pod-3")
        supervisor = NamespaceSupervisor(supervisor._registry, ["", "orders"])
        with caplog.at_level(logging.ERROR):
            await supervisor.observe({"": True, "orders": False})
        assert "orders" in caplog.text
        assert "finance" in caplog.text
        assert "pod-3" in caplog.text

    async def test_a_continuing_failure_is_reported_once(
        self, supervisor: NamespaceSupervisor, caplog: pytest.LogCaptureFixture, registry: MagicMock
    ) -> None:
        """An alert repeated every poll stops being read, and the client is already paused."""
        with caplog.at_level(logging.ERROR):
            await supervisor.observe({"orders": False})
            await supervisor.observe({"orders": False})
        assert caplog.text.count("has stopped serving") == 1
        registry.clients["orders"][0].pause_consumption.assert_awaited_once()

    async def test_the_root_degrading_pauses_only_the_root(self, supervisor: NamespaceSupervisor, registry: MagicMock) -> None:
        """An omitted namespace on the application registry means every namespace."""
        await supervisor.observe({"": False})
        registry.get_io_clients.assert_called_with(namespace="")
        registry.clients["orders"][0].pause_consumption.assert_not_awaited()


class TestRecovery:
    async def test_an_agent_that_passes_again_resumes_consuming(self, supervisor: NamespaceSupervisor, registry: MagicMock) -> None:
        await supervisor.observe({"orders": False})
        await supervisor.observe({"orders": True})
        registry.clients["orders"][0].resume_consumption.assert_awaited_once()
        assert supervisor.is_up("orders") is True

    async def test_a_latched_agent_does_not_recover_on_its_own(self, supervisor: NamespaceSupervisor, registry: MagicMock) -> None:
        """A component whose on_startup raised can still answer a health check."""
        await supervisor.mark_down("orders", "its service 'db' failed to start")
        await supervisor.observe({"orders": True})
        assert supervisor.is_up("orders") is False
        registry.clients["orders"][0].resume_consumption.assert_not_awaited()

    async def test_releasing_the_latch_lets_health_decide_again(self, supervisor: NamespaceSupervisor) -> None:
        await supervisor.mark_down("orders", "boom")
        await supervisor.clear_forced_down("orders")
        await supervisor.observe({"orders": True})
        assert supervisor.is_up("orders") is True

    def test_the_latch_reason_is_readable(self, supervisor: NamespaceSupervisor) -> None:
        assert supervisor.forced_down_reason("orders") is None


class TestFailureIsolation:
    async def test_a_client_that_cannot_be_paused_does_not_stop_the_poll(self, registry: MagicMock) -> None:
        registry.clients["orders"][0].pause_consumption.side_effect = RuntimeError("no")
        supervisor = NamespaceSupervisor(registry, ["", "orders", "billing"])
        await supervisor.observe({"orders": False, "billing": False})
        registry.clients["billing"][0].pause_consumption.assert_awaited_once()
