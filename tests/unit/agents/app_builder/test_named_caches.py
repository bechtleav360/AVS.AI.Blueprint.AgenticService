"""Unit tests for ``AppBuilder.with_cache(name=...)``.

Two things are being pinned down. The first is compatibility: ``with_cache()``,
``with_cache(False)`` and ``with_cache(True, False)`` are written positionally in projects that
exist today, and adding ``name`` must not change what any of them means. The second is that a
named cache is a first-class registry entry -- its own store, its own registry name, closed by
the lifespan like any other service.

How a *backend* isolates one name from another belongs to ``CacheBackendFactory`` and is tested
in ``tests/unit/agents/services/infrastructure/test_cache_backend_factory.py``.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.component.registry import DEFAULT_CACHE_NAME, Registry
from blueprint.agents.config import Config
from blueprint.agents.models.config import CacheConfig
from blueprint.agents.services.infrastructure.cache_service import CacheService, DiskCacheService

from .conftest import realize


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "blueprint"


@pytest.fixture
def builder(cache_dir: Path) -> AppBuilder:
    """An ``AppBuilder`` whose cache configuration points at a real temporary directory.

    The config is a mock and the cache is not: ``with_cache`` builds a real
    ``DiskCacheService``, so the directory it chooses is observable on disk, which is the whole
    point of the per-name scoping.
    """
    config = MagicMock(spec=Config)
    config.get_cache_config.return_value = CacheConfig(cache_dir=str(cache_dir), backend="disk")
    config.get.return_value = ""
    # build() reads per-agent keys through Config.for_namespace(); the mock stands in for
    # both the loader and its views, so a test controls one object.
    config.for_namespace.return_value = config
    return AppBuilder(config)


def registry() -> Registry:
    assert Component.shared_registry is not None
    return Component.shared_registry


def entry_keys(builder: AppBuilder) -> list[str]:
    """The readiness entry names ``build()`` wired, in order."""
    assert builder._actuator_api is not None
    return [entry.key for entry in builder._actuator_api.health_entries]


def checkers(builder: AppBuilder) -> dict[str, Any]:
    """The wired checkers by readiness entry name."""
    assert builder._actuator_api is not None
    return {entry.key: entry.checker for entry in builder._actuator_api.health_entries}


class TestTheDefaultCacheIsUnchanged:
    def test_it_registers_under_the_default_name(self, builder: AppBuilder) -> None:
        realize(builder.with_cache())
        assert isinstance(registry().get_cache(DEFAULT_CACHE_NAME), CacheService)

    def test_it_keeps_the_configured_directory(self, builder: AppBuilder, cache_dir: Path) -> None:
        realize(builder.with_cache())
        cache = registry().get_cache()
        assert isinstance(cache, DiskCacheService)
        assert cache.cache_dir == cache_dir

    def test_it_keeps_the_derived_registry_name(self, builder: AppBuilder) -> None:
        """Renaming this would move a key that existing lookups and health entries use."""
        realize(builder.with_cache())
        assert registry().get_component("disk_cache_service") is registry().get_cache()

    def test_the_cache_service_alias_still_reads_it(self, builder: AppBuilder) -> None:
        realize(builder.with_cache())
        assert registry().cache_service is registry().get_cache()

    def test_it_works_as_the_first_builder_call(self, builder: AppBuilder) -> None:
        """A cache service is itself a Component, so it is what creates the shared registry."""
        Component.shared_registry = None
        realize(builder.with_cache())
        assert registry().has_cache()


class TestPositionalCompatibility:
    def test_disabled_registers_nothing(self, builder: AppBuilder) -> None:
        realize(builder.with_cache(False))
        assert Component.shared_registry is None or not Component.shared_registry.has_cache()

    def test_disabled_does_not_read_the_cache_config(self, builder: AppBuilder) -> None:
        realize(builder.with_cache(False))
        builder._config.get_cache_config.assert_not_called()  # type: ignore[attr-defined]

    def test_locking_is_still_the_second_positional(self, builder: AppBuilder) -> None:
        realize(builder.with_cache(True, False))
        cache = registry().get_cache()
        assert isinstance(cache, DiskCacheService)
        assert cache._enable_locking is False

    def test_returns_self_for_chaining(self, builder: AppBuilder) -> None:
        assert builder.with_cache() is builder


class TestNamedCaches:
    def test_a_named_cache_is_reachable_by_its_name(self, builder: AppBuilder) -> None:
        realize(builder.with_cache(name="sessions"))
        assert isinstance(registry().get_cache("sessions"), CacheService)

    def test_a_named_cache_gets_its_own_directory(self, builder: AppBuilder, cache_dir: Path) -> None:
        realize(builder.with_cache(name="sessions"))
        cache = registry().get_cache("sessions")
        assert isinstance(cache, DiskCacheService)
        assert cache.cache_dir == cache_dir / "sessions"

    def test_the_directory_is_inside_the_configured_one(self, builder: AppBuilder, cache_dir: Path) -> None:
        """A sibling of the configured directory is not writable when that directory is the mount."""
        realize(builder.with_cache(name="sessions"))
        assert (cache_dir / "sessions").is_dir()

    def test_a_named_cache_gets_its_own_registry_name(self, builder: AppBuilder) -> None:
        realize(builder.with_cache(name="sessions"))
        assert registry().get_component("cache_sessions") is registry().get_cache("sessions")

    def test_the_default_and_a_named_cache_coexist(self, builder: AppBuilder) -> None:
        """Both are Components: without distinct registry names the second would fail to register."""
        realize(builder.with_cache().with_cache(name="sessions"))
        assert registry().get_cache() is not registry().get_cache("sessions")
        assert sorted(registry().get_all_caches()) == ["default", "sessions"]

    def test_two_named_caches_do_not_share_a_directory(self, builder: AppBuilder) -> None:
        realize(builder.with_cache(name="sessions").with_cache(name="prompts"))
        sessions, prompts = registry().get_cache("sessions"), registry().get_cache("prompts")
        assert isinstance(sessions, DiskCacheService)
        assert isinstance(prompts, DiskCacheService)
        assert sessions.cache_dir != prompts.cache_dir

    def test_an_unregistered_name_is_an_error_not_the_default(self, builder: AppBuilder) -> None:
        realize(builder.with_cache())
        with pytest.raises(ValueError, match="No cache registered as 'sessions'"):
            registry().get_cache("sessions")

    def test_a_named_cache_is_closed_by_the_lifespan(self, builder: AppBuilder) -> None:
        """It is closed because it is a registered service; the lifespan drives get_services()."""
        realize(builder.with_cache(name="sessions"))
        assert registry().get_cache("sessions") in registry().get_services()


class TestCacheNameValidation:
    @pytest.mark.parametrize(
        "name",
        ["Sessions", "../evil", "a/b", "a\\b", "", " ", "a:b", ".hidden", "_leading", "-leading", "sess ions"],
    )
    def test_a_name_that_cannot_be_a_directory_is_refused(self, builder: AppBuilder, name: str) -> None:
        with pytest.raises(ValueError, match="not a legal cache name"):
            builder.with_cache(name=name)

    @pytest.mark.parametrize("name", ["sessions", "llm-responses", "v2.cache", "a_b"])
    def test_a_usable_name_is_accepted(self, builder: AppBuilder, name: str) -> None:
        assert builder.with_cache(name=name) is builder

    def test_nothing_is_registered_when_the_name_is_refused(self, builder: AppBuilder) -> None:
        with pytest.raises(ValueError):
            builder.with_cache(name="../evil")
        assert Component.shared_registry is None or not Component.shared_registry.get_all_caches()


class TestEveryCacheReachesReadiness:
    """A named cache is a real backend; one that nothing probes is an outage nobody is told about."""

    def test_the_default_cache_keeps_the_entry_name_it_has_always_had(self, builder: AppBuilder) -> None:
        builder.with_cache()

        with patch("blueprint.agents.app_builder.FastAPI"):
            builder.build()

        assert "cache" in entry_keys(builder)

    def test_a_named_cache_gets_its_own_entry(self, builder: AppBuilder) -> None:
        builder.with_cache().with_cache(name="sessions")

        with patch("blueprint.agents.app_builder.FastAPI"):
            builder.build()

        assert {"cache", "cache:sessions"} <= set(entry_keys(builder))

    def test_a_named_cache_alone_still_reaches_readiness(self, builder: AppBuilder) -> None:
        """Previously the probe was keyed on the default name, so this cache went unprobed."""
        builder.with_cache(name="sessions")

        with patch("blueprint.agents.app_builder.FastAPI"):
            builder.build()

        assert "cache:sessions" in entry_keys(builder)

    def test_each_entry_probes_its_own_cache(self, builder: AppBuilder) -> None:
        builder.with_cache().with_cache(name="sessions")

        with patch("blueprint.agents.app_builder.FastAPI"):
            builder.build()

        providers = checkers(builder)
        assert providers["cache"]._cache is registry().get_cache()
        assert providers["cache:sessions"]._cache is registry().get_cache("sessions")


class TestACacheBelongsToTheAgentThatDeclaredIt:
    """``with_cache()`` inside an agent's scope registers to that agent, and stores apart (D3)."""

    def test_it_is_registered_to_the_declaring_agent(self, builder: AppBuilder) -> None:
        with namespace_scope("orders"):
            builder.with_cache(name="sessions")
        realize(builder)

        assert isinstance(registry().get_cache("sessions", namespace="orders"), CacheService)
        assert registry().get_all_caches() == {}, "the root declared nothing"

    def test_its_directory_carries_the_agent(self, builder: AppBuilder, cache_dir: Path) -> None:
        with namespace_scope("orders"):
            builder.with_cache(name="sessions")
        realize(builder)

        cache = registry().get_cache("sessions", namespace="orders")
        assert isinstance(cache, DiskCacheService)
        assert cache.cache_dir == cache_dir / "orders.sessions"

    def test_two_agents_declaring_one_name_get_two_caches(self, builder: AppBuilder) -> None:
        with namespace_scope("orders"):
            builder.with_cache(name="sessions")
        with namespace_scope("billing"):
            builder.with_cache(name="sessions")
        realize(builder)

        orders = registry().get_cache("sessions", namespace="orders")
        billing = registry().get_cache("sessions", namespace="billing")
        assert orders is not billing
        assert isinstance(orders, DiskCacheService) and isinstance(billing, DiskCacheService)
        assert orders.cache_dir != billing.cache_dir

    def test_both_backends_still_register_as_components(self, builder: AppBuilder) -> None:
        """Two of one class collide on the derived registry name unless each is built in its own scope."""
        with namespace_scope("orders"):
            builder.with_cache()
        with namespace_scope("billing"):
            builder.with_cache()
        realize(builder)

        assert registry().get_component("orders_disk_cache_service") is registry().get_cache(namespace="orders")
        assert registry().get_component("billing_disk_cache_service") is registry().get_cache(namespace="billing")

    def test_the_backend_is_chosen_from_the_agents_own_configuration(self, builder: AppBuilder) -> None:
        """C5: one agent in a group may run on redis while its neighbour uses the disk."""
        with namespace_scope("orders"):
            builder.with_cache(name="sessions")
        realize(builder)

        builder._config.for_namespace.assert_any_call("orders")  # type: ignore[attr-defined]

    def test_a_readiness_entry_names_the_agent(self, builder: AppBuilder) -> None:
        """Two agents' default caches are two entries, not one that reports the last registered."""
        with namespace_scope("orders"):
            builder.with_cache().with_cache(name="sessions")
        builder.host_agent("orders")

        with patch("blueprint.agents.app_builder.FastAPI"):
            builder.build()

        providers = checkers(builder)
        assert {"orders.cache", "orders.cache:sessions"} <= set(providers)
        assert providers["orders.cache"]._cache is registry().get_cache(namespace="orders")
