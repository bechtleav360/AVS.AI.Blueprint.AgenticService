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
