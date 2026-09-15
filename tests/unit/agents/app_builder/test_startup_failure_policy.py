"""What a failing ``on_startup`` does to the rest of the group (spec sec. 9.1).

There is no partial build -- one process, one ``build()`` -- so the ``critical`` flag is read
*before* an agent is wired rather than after an exception. A critical agent's failure still ends
the startup, which aborts the lifespan before the port is bound; a non-critical agent's failure
takes that agent out of service and lets the rest of the process start.

Driven through the real lifespan against real components, because the interesting part is which
of the eight startup loops the failure came out of and what the actuator knew by then.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

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
