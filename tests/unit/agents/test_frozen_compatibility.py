"""The frozen compatibility suite: what an existing single-agent project already does.

**Never update this file to accommodate an API change.** That is the whole of its value, and it
is spec sec. 10.2's requirement in one sentence: if a case here needs editing, a break shipped,
and the break is the finding -- not the test. A deliberate break is recorded in the changelog and
released with notes (sec. 10.1); anything else is a regression to fix in the framework.

Every case below is written the way a project in `examples/` writes it today -- instance forms
included, because four of the seven examples pass constructed objects
(``.with_rest_api(InventoryApi())``) -- and asserts the observable thing that project depends on:
the paths it serves, the registry names its lookups use, the readiness entries its probe reports,
the cache its services share. Nothing here mentions a namespace, a group, or an agent, because a
single-agent application has none of those and must not have to learn about them.

Scope: what unit tests can hold. The generated-project smoke test sec. 10.2 also asks for --
``asbs setup``, then build and start the result unchanged -- needs Docker and is not written; see
the changelog's open points.
"""

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from blueprint.agents import AppBuilder, Config
from blueprint.agents.component.component import Component
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.io.api.actuators.health.health_base import HealthCheckerBase
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.models.api import ComponentHealth
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.services.infrastructure.cache_service import CacheService
from blueprint.agents.services.service_base import ServiceBase

# ---------------------------------------------------------------------------
# A project, written the way the examples are
# ---------------------------------------------------------------------------


class InventoryService(ServiceBase):
    async def on_startup(self) -> None:
        self.cache = self.registry.cache_service

    async def on_shutdown(self) -> None:
        pass


class PricingService(ServiceBase):
    async def on_startup(self) -> None:
        self.cache = self.registry.cache_service

    async def on_shutdown(self) -> None:
        pass


class InventoryApi(RestApiBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/inventory", tags=["inventory"])
    async def list_inventory(self) -> list[str]:
        return []


class StockHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    def get_subscribed_topics(self) -> list[str]:
        return ["stock.changed"]

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        return None


class DatabaseChecker(HealthCheckerBase):
    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(status="healthy", message="ok")


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    """One process per case, as a deployment has one.

    Test infrastructure, not an accommodation: ``Component`` holds the registry and the
    configuration for the life of a process, and a test file is many processes in one.
    """
    yield
    Component.reset_shared_state()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """An example project's settings.toml, key for key."""
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[default]\napp_name = "Inventory API"\napp_port = 8000\napp_environment = "development"\n'
        'log_level = "INFO"\n\n'
        f'[default.cache]\ncache_dir = "{(tmp_path / ".cache" / "inventory").as_posix()}"\nsize_limit = 100000000\n'
        "default_ttl = 300\n"
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


def registry() -> Any:
    assert Component.shared_registry is not None
    return Component.shared_registry


def paths(app: FastAPI) -> list[str]:
    return sorted(app.openapi()["paths"])


class TestTheShapeEveryExampleUses:
    """``AppBuilder(config)...build()`` in one expression, assigned to ``app``."""

    def test_a_service_an_api_and_a_cache(self, config: Config) -> None:
        app = AppBuilder(config).with_service(InventoryService).with_rest_api(InventoryApi()).with_cache().build()

        assert isinstance(app, FastAPI)

    def test_a_chain_of_handlers_and_services(self, config: Config) -> None:
        app = AppBuilder(config).with_service(InventoryService).with_handler(StockHandler).with_rest_api(InventoryApi).with_cache().build()

        assert isinstance(app, FastAPI)

    def test_an_instance_is_accepted(self, config: Config) -> None:
        """Four of the seven examples pass a constructed object. Standalone, that is supported."""
        AppBuilder(config).with_rest_api(InventoryApi()).with_cache().build()

        assert registry().get_component("inventory_api") is not None

    def test_the_builder_is_still_fluent(self, config: Config) -> None:
        builder = AppBuilder(config)

        assert builder.with_service(InventoryService) is builder


class TestPositionalCacheArguments:
    """Spec sec. 10.1 names these two calls explicitly. They are written positionally in the wild."""

    def test_with_cache_disabled(self, config: Config) -> None:
        AppBuilder(config).with_service(InventoryService).with_cache(False).build()

        assert registry().get_all_caches() == {}

    def test_with_cache_without_locking(self, config: Config) -> None:
        AppBuilder(config).with_service(InventoryService).with_cache(True, False).build()

        cache = registry().get_cache()
        assert cache._enable_locking is False

    def test_with_cache_default(self, config: Config) -> None:
        AppBuilder(config).with_service(InventoryService).with_cache().build()

        assert isinstance(registry().get_cache(), CacheService)


class TestTheRegistryNamesLookupsUse:
    def test_a_component_keeps_its_derived_name(self, config: Config) -> None:
        """No namespace, so no prefix: ``get_component("inventory_service")`` still resolves."""
        AppBuilder(config).with_service(InventoryService).with_cache().build()

        assert registry().get_component("inventory_service") is not None

    def test_an_explicit_name_is_kept_verbatim(self, config: Config) -> None:
        AppBuilder(config).with_service(InventoryService, name="stock").with_cache().build()

        assert registry().get_component("stock") is not None

    def test_the_default_cache_keeps_its_backend_name(self, config: Config) -> None:
        AppBuilder(config).with_service(InventoryService).with_cache().build()

        assert registry().get_component("disk_cache_service") is registry().get_cache()

    def test_the_cache_service_alias_reads_the_default_cache(self, config: Config) -> None:
        AppBuilder(config).with_service(InventoryService).with_cache().build()

        assert registry().cache_service is registry().get_cache()

    def test_two_services_share_one_cache(self, config: Config) -> None:
        """The shared-cache example's whole point: what one service writes, the other reads."""
        AppBuilder(config).with_service(InventoryService).with_service(PricingService).with_cache().build()

        first = registry().get_service(InventoryService)
        second = registry().get_service(PricingService)
        assert first.registry.cache_service is second.registry.cache_service


class TestThePathsAProjectServes:
    def test_a_rest_api_is_mounted_under_api(self, config: Config) -> None:
        app = AppBuilder(config).with_rest_api(InventoryApi()).build()

        assert "/api/inventory" in paths(app)

    def test_its_tags_are_not_rewritten(self, config: Config) -> None:
        app = AppBuilder(config).with_rest_api(InventoryApi()).build()

        operations = app.openapi()["paths"]["/api/inventory"]
        assert sorted({tag for operation in operations.values() for tag in operation.get("tags", [])}) == ["inventory"]

    def test_the_cache_endpoints_are_unprefixed(self, config: Config) -> None:
        app = AppBuilder(config).with_service(InventoryService).with_cache().build()

        assert "/api/cache/stats" in paths(app)

    def test_the_actuators_are_where_they_were(self, config: Config) -> None:
        app = AppBuilder(config).with_service(InventoryService).build()

        assert {"/health/ready", "/health/live", "/info"} <= set(paths(app))


class TestTheReadinessPayload:
    def test_the_default_cache_is_the_entry_called_cache(self, config: Config) -> None:
        builder = AppBuilder(config).with_service(InventoryService).with_cache()

        builder.build()

        assert "cache" in [entry.key for entry in builder._actuator_api.health_entries]

    def test_a_custom_checker_keeps_its_bare_name(self, config: Config) -> None:
        """Sec. 10: ``with_health_checker`` keys are unchanged at the root."""
        builder = AppBuilder(config).with_health_checker("database", DatabaseChecker())

        builder.build()

        assert "database" in [entry.key for entry in builder._actuator_api.health_entries]


class TestComponentsNeedNoChange:
    def test_a_service_takes_no_new_constructor_argument(self, config: Config) -> None:
        """Sec. 4.3: a project's component is written exactly as before, ``super().__init__()``."""
        Component.configure(config)

        service = InventoryService()

        assert (service.name, service.namespace) == ("inventory_service", "")

    def test_a_component_resolves_the_registry_and_config_it_always_did(self, config: Config) -> None:
        Component.configure(config)

        service = InventoryService()

        assert service.registry is Component.shared_registry
        assert service.config is config
