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
from unittest.mock import MagicMock

import pytest

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import DEFAULT_CACHE_NAME, Registry
from blueprint.agents.config import Config
from blueprint.agents.models.config import CacheConfig
from blueprint.agents.services.infrastructure.cache_service import CacheService, DiskCacheService


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
    return AppBuilder(config)


def registry() -> Registry:
    assert Component.shared_registry is not None
    return Component.shared_registry


class TestTheDefaultCacheIsUnchanged:
    def test_it_registers_under_the_default_name(self, builder: AppBuilder) -> None:
        builder.with_cache()
        assert isinstance(registry().get_cache(DEFAULT_CACHE_NAME), CacheService)

    def test_it_keeps_the_configured_directory(self, builder: AppBuilder, cache_dir: Path) -> None:
        builder.with_cache()
        cache = registry().get_cache()
        assert isinstance(cache, DiskCacheService)
        assert cache.cache_dir == cache_dir

    def test_it_keeps_the_derived_registry_name(self, builder: AppBuilder) -> None:
        """Renaming this would move a key that existing lookups and health entries use."""
        builder.with_cache()
        assert registry().get_component("disk_cache_service") is registry().get_cache()

    def test_the_cache_service_alias_still_reads_it(self, builder: AppBuilder) -> None:
        builder.with_cache()
        assert registry().cache_service is registry().get_cache()

    def test_it_works_as_the_first_builder_call(self, builder: AppBuilder) -> None:
        """A cache service is itself a Component, so it is what creates the shared registry."""
        Component.shared_registry = None
        builder.with_cache()
        assert registry().has_cache()


class TestPositionalCompatibility:
    def test_disabled_registers_nothing(self, builder: AppBuilder) -> None:
        builder.with_cache(False)
        assert Component.shared_registry is None or not Component.shared_registry.has_cache()

    def test_disabled_does_not_read_the_cache_config(self, builder: AppBuilder) -> None:
        builder.with_cache(False)
        builder._config.get_cache_config.assert_not_called()  # type: ignore[attr-defined]

    def test_locking_is_still_the_second_positional(self, builder: AppBuilder) -> None:
        builder.with_cache(True, False)
        cache = registry().get_cache()
        assert isinstance(cache, DiskCacheService)
        assert cache._enable_locking is False

    def test_returns_self_for_chaining(self, builder: AppBuilder) -> None:
        assert builder.with_cache() is builder


class TestNamedCaches:
    def test_a_named_cache_is_reachable_by_its_name(self, builder: AppBuilder) -> None:
        builder.with_cache(name="sessions")
        assert isinstance(registry().get_cache("sessions"), CacheService)

    def test_a_named_cache_gets_its_own_directory(self, builder: AppBuilder, cache_dir: Path) -> None:
        builder.with_cache(name="sessions")
        cache = registry().get_cache("sessions")
        assert isinstance(cache, DiskCacheService)
        assert cache.cache_dir == cache_dir / "sessions"

    def test_the_directory_is_inside_the_configured_one(self, builder: AppBuilder, cache_dir: Path) -> None:
        """A sibling of the configured directory is not writable when that directory is the mount."""
        builder.with_cache(name="sessions")
        assert (cache_dir / "sessions").is_dir()

    def test_a_named_cache_gets_its_own_registry_name(self, builder: AppBuilder) -> None:
        builder.with_cache(name="sessions")
        assert registry().get_component("cache_sessions") is registry().get_cache("sessions")

    def test_the_default_and_a_named_cache_coexist(self, builder: AppBuilder) -> None:
        """Both are Components: without distinct registry names the second would fail to register."""
        builder.with_cache().with_cache(name="sessions")
        assert registry().get_cache() is not registry().get_cache("sessions")
        assert sorted(registry().get_all_caches()) == ["default", "sessions"]

    def test_two_named_caches_do_not_share_a_directory(self, builder: AppBuilder) -> None:
        builder.with_cache(name="sessions").with_cache(name="prompts")
        sessions, prompts = registry().get_cache("sessions"), registry().get_cache("prompts")
        assert isinstance(sessions, DiskCacheService)
        assert isinstance(prompts, DiskCacheService)
        assert sessions.cache_dir != prompts.cache_dir

    def test_an_unregistered_name_is_an_error_not_the_default(self, builder: AppBuilder) -> None:
        builder.with_cache()
        with pytest.raises(ValueError, match="No cache registered as 'sessions'"):
            registry().get_cache("sessions")

    def test_a_named_cache_is_closed_by_the_lifespan(self, builder: AppBuilder) -> None:
        """It is closed because it is a registered service; the lifespan drives get_services()."""
        builder.with_cache(name="sessions")
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
