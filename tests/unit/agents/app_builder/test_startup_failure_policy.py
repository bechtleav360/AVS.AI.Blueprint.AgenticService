"""What a failing ``on_startup`` does to the rest of the group (spec sec. 9.1).

There is no partial build -- one process, one ``build()`` -- so the ``critical`` flag is read
*before* an agent is wired rather than after an exception. A critical agent's failure still ends
the startup, which aborts the lifespan before the port is bound; a non-critical agent's failure
takes that agent out of service and lets the rest of the process start.

Driven through the real lifespan against real components, because the interesting part is which
of the eight startup loops the failure came out of and what the actuator knew by then.
"""

import asyncio
import signal
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.io.telemetry.providers import reset_providers
from blueprint.agents.services.service_base import ServiceBase


class QuietService(ServiceBase):
    """A service that starts without complaint."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class BrokenService(ServiceBase):
    """A service whose ``on_startup`` raises, which is what spec sec. 9.1 is about."""

    async def on_startup(self) -> None:
        raise RuntimeError("its database is unreachable")

    async def on_shutdown(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _forget_providers() -> Iterator[None]:
    reset_providers()
    yield
    reset_providers()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A group's configuration with no event bus, so nothing needs a broker to start."""
    settings = tmp_path / "settings.toml"
    settings.write_text('[development]\napp_name = "group"\napp_port = 8000\napp_environment = "development"\n')
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


def build(config: Config, *, critical: bool) -> tuple[FastAPI, AppBuilder]:
    """One healthy agent and one whose service raises, hosted with the given flag.

    The builder comes back with the application because the supervisor is reached through the
    actuator it created, and nothing mounted on a FastAPI application exposes it.
    """
    builder = AppBuilder(config)
    builder.host_agent("orders", critical=True)
    builder.host_agent("billing", critical=critical)
    with namespace_scope("orders"):
        builder.with_service(QuietService)
    with namespace_scope("billing"):
        builder.with_service(BrokenService)
    return builder.build(), builder


def supervisor_of(builder: AppBuilder) -> Any:
    """The running supervisor, or an assertion if the actuator never started one."""
    actuator = builder._actuator_api
    assert actuator is not None and actuator.supervisor is not None
    return actuator.supervisor


class TestACriticalAgent:
    async def test_its_failure_ends_the_startup(self, config: Config) -> None:
        """Aborting the lifespan is what stops the port being bound, so Kubernetes crash-loops."""
        app, _ = build(config, critical=True)
        with pytest.raises(RuntimeError, match="database is unreachable"):
            async with app.router.lifespan_context(app):
                pass

    async def test_the_root_is_critical_whatever_anyone_says(self, config: Config) -> None:
        """It holds the shared infrastructure; there is no rest of the process without it."""
        builder = AppBuilder(config)
        builder.with_service(BrokenService)
        app = builder.build()
        with pytest.raises(RuntimeError, match="database is unreachable"):
            async with app.router.lifespan_context(app):
                pass


class TestANonCriticalAgent:
    async def test_the_process_starts_without_it(self, config: Config) -> None:
        app, _ = build(config, critical=False)
        async with app.router.lifespan_context(app):
            pass

    async def test_it_is_taken_out_of_service(self, config: Config) -> None:
        app, builder = build(config, critical=False)
        async with app.router.lifespan_context(app):
            supervisor = supervisor_of(builder)
            assert supervisor.is_up("billing") is False
            assert supervisor.is_up("orders") is True

    async def test_the_reason_names_the_component(self, config: Config) -> None:
        app, builder = build(config, critical=False)
        async with app.router.lifespan_context(app):
            reason = supervisor_of(builder).forced_down_reason("billing")
        assert reason is not None
        assert "billing_broken_service" in reason
        assert "database is unreachable" in reason

    async def test_being_down_is_latched_against_a_later_health_poll(self, config: Config) -> None:
        """Its components can still answer a health check while the agent is unusable."""
        app, builder = build(config, critical=False)
        async with app.router.lifespan_context(app):
            supervisor = supervisor_of(builder)
            await supervisor.observe({"billing": True})
            assert supervisor.is_up("billing") is False

    async def test_the_rest_of_the_group_is_untouched(self, config: Config) -> None:
        app, builder = build(config, critical=False)
        async with app.router.lifespan_context(app):
            status = supervisor_of(builder).status
        assert status["orders"] is True
        assert status["billing"] is False


class TestTheCriticalSet:
    def test_an_unflagged_agent_is_critical(self, config: Config) -> None:
        builder = AppBuilder(config)
        builder.host_agent("orders")
        assert builder.critical_namespaces == ("orders",)

    def test_a_flag_of_false_keeps_it_out(self, config: Config) -> None:
        builder = AppBuilder(config)
        builder.host_agent("orders", critical=False)
        assert builder.namespaces == ("orders",)
        assert builder.critical_namespaces == ()


# ---------------------------------------------------------------------------
# Recovery: a latched agent is retried until it starts, and readiness shows the latch
# ---------------------------------------------------------------------------


class FlakyService(ServiceBase):
    """Fails ``failures`` times, then starts. Class state, because the registry constructs it."""

    failures = 1
    calls = 0

    async def on_startup(self) -> None:
        type(self).calls += 1
        if type(self).calls <= type(self).failures:
            raise RuntimeError(f"not reachable yet (call {type(self).calls})")

    async def on_shutdown(self) -> None:
        pass


class CountingService(ServiceBase):
    """Starts fine, and counts how often it was asked to."""

    calls = 0

    async def on_startup(self) -> None:
        type(self).calls += 1

    async def on_shutdown(self) -> None:
        pass


@pytest.fixture
def fast_retry(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "group"\napp_port = 8000\napp_environment = "development"\nstartup_retry_interval_seconds = 0.01\n'
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


@pytest.fixture(autouse=True)
def _reset_counters() -> Iterator[None]:
    FlakyService.failures, FlakyService.calls, CountingService.calls = 1, 0, 0
    yield


def build_with(config: Config, *services: type[ServiceBase]) -> tuple[FastAPI, AppBuilder]:
    builder = AppBuilder(config)
    builder.host_agent("orders", critical=True)
    builder.host_agent("billing", critical=False)
    with namespace_scope("orders"):
        builder.with_service(QuietService)
    with namespace_scope("billing"):
        for service in services:
            builder.with_service(service)
    return builder.build(), builder


async def readiness(builder: AppBuilder) -> Any:
    assert builder._actuator_api is not None and builder._actuator_api._health_cache is not None
    return await builder._actuator_api._health_cache.get_health_status()


async def settle(predicate, attempts: int = 200) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


class TestReadinessShowsTheLatch:
    """#3 -- a latched agent was paused and reported 0 on the gauge, yet /health/ready said UP."""

    async def test_the_agent_is_down_in_the_payload_with_its_reason(self, config: Config) -> None:
        app, builder = build(config, critical=False)
        async with app.router.lifespan_context(app):
            response = await readiness(builder)
        assert response.namespaces["billing"].status == "DOWN"
        assert "database is unreachable" in (response.namespaces["billing"].reason or "")
        assert response.namespaces["orders"].status == "UP"
        assert response.namespaces["orders"].reason is None

    async def test_the_default_policy_takes_the_pod_out_of_rotation(self, config: Config) -> None:
        app, builder = build(config, critical=False)
        async with app.router.lifespan_context(app):
            assert (await readiness(builder)).status == "DOWN"


class TestRecovery:
    async def test_a_transient_failure_recovers_without_a_restart(self, fast_retry: Config) -> None:
        app, builder = build_with(fast_retry, FlakyService)
        async with app.router.lifespan_context(app):
            supervisor = supervisor_of(builder)
            await settle(lambda: supervisor.is_up("billing"))
            assert supervisor.forced_down_reason("billing") is None
            response = await readiness(builder)
        assert response.status == "UP"
        assert response.namespaces["billing"].reason is None
        assert FlakyService.calls == 2

    async def test_a_persistent_failure_stays_down_and_keeps_saying_why(self, fast_retry: Config, caplog) -> None:
        app, builder = build_with(fast_retry, BrokenService)
        with caplog.at_level("WARNING", logger="blueprint.agents.app_builder"):
            async with app.router.lifespan_context(app):
                await settle(lambda: "attempt 2" in caplog.text)
                supervisor = supervisor_of(builder)
                assert supervisor.is_up("billing") is False
                assert "database is unreachable" in (supervisor.forced_down_reason("billing") or "")
        assert "still out of service" in caplog.text

    async def test_it_never_ends_the_process(self, fast_retry: Config) -> None:
        """A deterministic failure would crash-loop the pod and every healthy agent in it."""
        app, builder = build_with(fast_retry, BrokenService)
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.1)
            assert supervisor_of(builder).is_up("orders") is True

    async def test_a_later_component_waits_for_the_one_before_it(self, fast_retry: Config) -> None:
        """Retried in start order, stopping at the first that fails again: it may be a dependency."""
        FlakyService.failures = 3
        app, builder = build_with(fast_retry, FlakyService, CountingService)
        async with app.router.lifespan_context(app):
            await settle(lambda: supervisor_of(builder).is_up("billing"))
        # CountingService started once at startup (it did not fail) and is never retried.
        assert (FlakyService.calls, CountingService.calls) == (4, 1)

    async def test_shutdown_stops_the_recovery(self, fast_retry: Config) -> None:
        app, builder = build_with(fast_retry, BrokenService)
        async with app.router.lifespan_context(app):
            assert builder._recovery_tasks
            tasks = list(builder._recovery_tasks)
        assert all(task.done() for task in tasks)
        assert builder._recovery_tasks == []

    @pytest.mark.parametrize("value", ["0", "-5", '"soon"'])
    async def test_a_bad_interval_fails_startup(self, tmp_path: Path, value: str) -> None:
        settings = tmp_path / "settings.toml"
        settings.write_text(
            f'[development]\napp_name = "group"\napp_port = 8000\napp_environment = "development"\n'
            f"startup_retry_interval_seconds = {value}\n"
        )
        app, _ = build_with(Config(settings_files=[str(settings)], root_path=str(tmp_path)), QuietService)
        with pytest.raises(ValueError, match="startup_retry_interval_seconds"):
            async with app.router.lifespan_context(app):
                pass


class TestAFatalTransportErrorAfterStartup:
    """D -- the startup failure policy, for a failure that surfaced after startup."""

    @staticmethod
    def _builder(config: Config) -> AppBuilder:
        builder = AppBuilder(config)
        builder.host_agent("orders", critical=True)
        builder.host_agent("billing", critical=False)
        builder._critical_namespaces = ["orders"]
        return builder

    @pytest.mark.parametrize("namespace", ["", "orders"], ids=["root", "critical"])
    async def test_the_root_or_a_critical_agent_ends_the_process(self, config: Config, namespace: str, caplog) -> None:
        builder = self._builder(config)
        with patch("blueprint.agents.app_builder.signal.raise_signal") as raise_signal, caplog.at_level("CRITICAL"):
            await builder._on_transport_fatal(namespace, RuntimeError("no JetStream"))
        raise_signal.assert_called_once_with(signal.SIGTERM)
        assert "the process is shut down" in caplog.text

    async def test_a_non_critical_agent_is_marked_down(self, config: Config) -> None:
        builder = self._builder(config)
        builder._mark_agent_down = AsyncMock()  # type: ignore[method-assign]
        with patch("blueprint.agents.app_builder.signal.raise_signal") as raise_signal:
            await builder._on_transport_fatal("billing", RuntimeError("no JetStream"))
        raise_signal.assert_not_called()
        builder._mark_agent_down.assert_awaited_once_with("billing", "no JetStream")
