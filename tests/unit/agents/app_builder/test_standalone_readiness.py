"""A standalone agent's ``/health/ready`` has the shape it had before the namespace feature.

``policy`` and ``namespaces`` describe the agents of a group. A process that hosts no group gets
neither -- only ``status`` and ``components``, as in v0.8.1. Driven over HTTP through the real
lifespan, because what matters is the JSON a probe or a dashboard actually receives.
"""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.io.api.actuators.health import HealthCheckerBase
from blueprint.agents.io.telemetry.providers import reset_providers
from blueprint.agents.models.api import ComponentHealth
from blueprint.agents.services.service_base import ServiceBase


class SilentCheck(HealthCheckerBase):
    """A healthy check without a message, so the payload carries a ``null`` that must survive."""

    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(status="healthy", message=None)


class QuietService(ServiceBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _forget_providers() -> Iterator[None]:
    reset_providers()
    yield
    reset_providers()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text('[development]\napp_name = "standalone"\napp_port = 8000\napp_environment = "development"\n')
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


async def _ready(builder: AppBuilder) -> dict:
    app = builder.build()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health/ready")
    assert response.status_code == 200
    return response.json()


async def test_a_standalone_agent_gets_status_and_components_only(config: Config) -> None:
    body = await _ready(AppBuilder(config).with_health_checker("db", SilentCheck()))
    assert set(body) == {"status", "components"}


async def test_a_null_inside_components_is_kept(config: Config) -> None:
    """Only the two group fields are conditional; the rest serialises exactly as before."""
    body = await _ready(AppBuilder(config).with_health_checker("db", SilentCheck()))
    assert body["components"]["db"] == {"status": "healthy", "message": None, "details": None}


async def test_a_group_gets_the_policy_and_its_agents(config: Config) -> None:
    builder = AppBuilder(config)
    builder.host_agent("orders", critical=True)
    with namespace_scope("orders"):
        builder.with_service(QuietService)
    body = await _ready(builder)
    assert body["policy"] == "all"
    assert set(body["namespaces"]) == {"<root>", "orders"}


async def test_status_env_has_no_namespaces_key_when_standalone(config: Config) -> None:
    """The same rule for /status/env: the per-agent breakdown exists only in a group."""
    app = AppBuilder(config).build()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/status/env")
    assert response.status_code == 200
    assert "namespaces" not in response.json()


async def test_the_lifespan_shuts_telemetry_down_after_the_components(config: Config) -> None:
    """S22 -- the providers were left to their atexit hooks, which closed the shared export early."""
    from unittest.mock import AsyncMock

    builder = AppBuilder(config)
    app = builder.build()
    order: list[str] = []
    builder._telemetry_manager.on_shutdown = AsyncMock(side_effect=lambda: order.append("telemetry"))  # type: ignore[method-assign]
    registry_shutdown = Component.shared_registry.shutdown_executors
    Component.shared_registry.shutdown_executors = lambda: (order.append("executors"), registry_shutdown())  # type: ignore[method-assign]
    async with app.router.lifespan_context(app):
        pass
    assert order == ["executors", "telemetry"]


class _OwnCacheCheck(HealthCheckerBase):
    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(status="healthy", message="the application's own cache check")


def _cache_config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "standalone"\napp_port = 8000\napp_environment = "development"\n\n'
        f'[development.cache]\ncache_dir = "{(tmp_path / "cache").as_posix()}"\n'
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


class TestAUserCheckReplacesABuiltInOne:
    """S20 -- in 0.8 a user check named like a built-in replaced it; 0.9 refused the build."""

    def test_at_build(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        own = _OwnCacheCheck()
        builder = AppBuilder(_cache_config(tmp_path)).with_cache().with_health_checker("cache", own)
        with caplog.at_level("WARNING"):
            builder.build()
        entries = [entry for entry in builder._actuator_api._health_entries if entry.key == "cache"]  # type: ignore[union-attr]
        assert [entry.checker for entry in entries] == [own]
        assert any("replaces the framework's CacheHealthChecker" in message for message in caplog.messages)

    def test_after_build(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        own = _OwnCacheCheck()
        builder = AppBuilder(_cache_config(tmp_path)).with_cache()
        builder.build()
        with caplog.at_level("WARNING"):
            builder.with_health_checker("cache", own)
        entries = [entry for entry in builder._actuator_api._health_entries if entry.key == "cache"]  # type: ignore[union-attr]
        assert [entry.checker for entry in entries] == [own]

    def test_two_user_checks_under_one_name_are_still_refused(self, tmp_path: Path) -> None:
        builder = (
            AppBuilder(_cache_config(tmp_path)).with_health_checker("db", _OwnCacheCheck()).with_health_checker("db", _OwnCacheCheck())
        )
        with pytest.raises(ValueError, match="already taken"):
            builder.build()


class TestShutdownGoesOnPastAFailure:
    """N1 -- a failed recovery task and a failing actuator shutdown each aborted the rest of shutdown."""

    async def test_a_failed_recovery_task_does_not_abort_it(self, config: Config) -> None:
        import asyncio

        builder = AppBuilder(config)

        async def broken() -> None:
            raise RuntimeError("recovery bug")

        task = asyncio.create_task(broken())
        await asyncio.sleep(0)
        builder._recovery_tasks.append(task)

        await builder._stop_startup_recovery()

        assert builder._recovery_tasks == []

    async def test_a_failing_actuator_shutdown_is_logged_and_the_rest_runs(self, config: Config, caplog: pytest.LogCaptureFixture) -> None:
        from unittest.mock import AsyncMock

        builder = AppBuilder(config)
        app = builder.build()
        builder._telemetry_manager.on_shutdown = AsyncMock()  # type: ignore[method-assign]
        with caplog.at_level("ERROR"):
            async with app.router.lifespan_context(app):
                builder._actuator_api.on_shutdown = AsyncMock(side_effect=RuntimeError("cache scheduler"))  # type: ignore[method-assign, union-attr]
        builder._telemetry_manager.on_shutdown.assert_awaited_once()
        assert any("cache scheduler" in message for message in caplog.messages)
