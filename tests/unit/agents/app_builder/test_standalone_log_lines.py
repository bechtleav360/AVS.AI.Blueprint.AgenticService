"""A standalone agent logs what it logged before the namespace feature (v0.8.1).

The namespace feature must not change what a single-agent application emits. Every line checked
here existed in v0.8.1 and was reworded when agents gained namespaces -- with ``<root>`` standing in
for the empty namespace. For a standalone agent the old wording is restored; a grouped process keeps
the new one, which names the agent.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.io.telemetry.providers import reset_providers


class QuietHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event, context) -> bool:  # type: ignore[no-untyped-def]
        return False

    async def handle_event(self, event, context) -> None:  # type: ignore[no-untyped-def]
        return None


@pytest.fixture(autouse=True)
def _forget_providers() -> Iterator[None]:
    reset_providers()
    yield
    reset_providers()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        f'[development]\napp_name = "standalone"\napp_port = 8000\napp_environment = "development"\n\n'
        f'[development.cache]\ncache_dir = "{(tmp_path / "cache").as_posix()}"\n'
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


def test_caching_disabled(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="blueprint.agents.app_builder"):
        AppBuilder(config).with_cache(False)
    assert "Caching disabled" in caplog.messages


def test_the_cache_is_registered(config: Config, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        AppBuilder(config).with_cache().build()
    assert f"Registered DiskCacheService with cache_dir={(tmp_path / 'cache').as_posix()} (locking=True)" in caplog.messages
    assert "Registering cache service: DiskCacheService" in caplog.messages


def test_handlers_without_an_event_bus(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="blueprint.agents.app_builder"):
        AppBuilder(config).with_handler(QuietHandler).build()
    assert (
        "Event handlers are registered but no valid event_bus configured ('dapr', 'nats', or 'sessions'). Event handling will be disabled."
    ) in caplog.messages


async def test_the_eventing_endpoint_starts(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    builder = AppBuilder(config)
    endpoint = MagicMock(namespace="")
    endpoint.on_startup = AsyncMock()
    with caplog.at_level("INFO", logger="blueprint.agents.app_builder"):
        await builder._start_component("Eventing component", endpoint, endpoint.namespace)
    assert caplog.messages == ["Eventing component startup completed"]


def test_the_configuration_line(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    settings = tmp_path / "settings.toml"
    settings.write_text('[development]\napp_name = "standalone"\n')
    with caplog.at_level("INFO", logger="blueprint.agents.config.config"):
        Config(settings_files=[str(settings)], root_path=str(tmp_path))
    assert "Loading configuration properties for environment: development" in caplog.messages


def test_building_a_standalone_agent_names_no_root(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        AppBuilder(config).with_cache().with_handler(QuietHandler).build()
    assert [record.getMessage() for record in caplog.records if "<root>" in record.getMessage()] == []
