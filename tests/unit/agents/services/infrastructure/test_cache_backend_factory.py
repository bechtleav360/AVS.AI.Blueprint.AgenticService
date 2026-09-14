"""Unit tests for CacheBackendFactory.

Two concerns. The first is ``enable_locking`` propagation through the Redis-to-Disk fallback
paths, which was previously dropped silently. The second is that a cache *name* buys isolated
storage: the factory is where a backend is chosen, so it is where each backend answers how it
separates one named cache from another -- a directory for disk, a key prefix for Redis.
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.component.registry import DEFAULT_CACHE_NAME
from blueprint.agents.models.config import CacheConfig
from blueprint.agents.services.infrastructure.cache_backend_factory import CacheBackendFactory
from blueprint.agents.services.infrastructure.cache_service import DiskCacheService


@pytest.fixture
def disk_config(tmp_path) -> CacheConfig:
    return CacheConfig(backend="disk", cache_dir=str(tmp_path / "cache"))


@pytest.fixture
def redis_fallback_config(tmp_path) -> CacheConfig:
    return CacheConfig(
        backend="redis",
        redis_url="redis://localhost:6379/0",
        fallback_to_local=True,
        cache_dir=str(tmp_path / "cache"),
    )


def test_disk_backend_respects_enable_locking_false(disk_config: CacheConfig) -> None:
    service = CacheBackendFactory.create(disk_config, enable_locking=False)

    assert isinstance(service, DiskCacheService)
    assert service._enable_locking is False


def test_disk_backend_respects_enable_locking_true(disk_config: CacheConfig) -> None:
    service = CacheBackendFactory.create(disk_config, enable_locking=True)

    assert isinstance(service, DiskCacheService)
    assert service._enable_locking is True


def test_redis_fallback_on_import_error_preserves_enable_locking(
    redis_fallback_config: CacheConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force the redis-py import to fail so the factory takes the ImportError
    # fallback branch. We patch ``builtins.__import__`` rather than removing the
    # module so the test works whether or not the [redis] extra is installed.
    # ``monkeypatch.delitem`` ensures the cached module is restored after the
    # test, preventing cross-test pollution.
    real_import = builtins.__import__

    def _fail_redis_import(name, *args, **kwargs):
        if name == "blueprint.agents.services.infrastructure.redis_cache_service":
            raise ImportError("simulated missing extra")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(
        sys.modules,
        "blueprint.agents.services.infrastructure.redis_cache_service",
        raising=False,
    )
    monkeypatch.setattr(builtins, "__import__", _fail_redis_import)

    service = CacheBackendFactory.create(redis_fallback_config, enable_locking=False)

    assert isinstance(service, DiskCacheService)
    assert service._enable_locking is False


def test_redis_fallback_on_connection_error_preserves_enable_locking(
    redis_fallback_config: CacheConfig,
) -> None:
    # Let the import succeed but force the connection probe (_client.ping) to
    # fail so the factory takes the runtime-fallback branch.
    failing_service = MagicMock()
    failing_service._client.ping.side_effect = ConnectionError("simulated outage")
    failing_service.close = MagicMock()

    with patch(
        "blueprint.agents.services.infrastructure.redis_cache_service.RedisCacheService",
        return_value=failing_service,
    ):
        service = CacheBackendFactory.create(redis_fallback_config, enable_locking=False)

    assert isinstance(service, DiskCacheService)
    assert service._enable_locking is False
    failing_service.close.assert_called_once()


def test_redis_fallback_log_does_not_leak_credentials(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    # When the connection probe fails the factory logs a fallback warning with
    # the URL — that line must not include any inline credentials.
    config = CacheConfig(
        backend="redis",
        redis_url="redis://:supersecret@host:6379/0",
        fallback_to_local=True,
        cache_dir=str(tmp_path / "cache"),
    )
    failing_service = MagicMock()
    failing_service._client.ping.side_effect = ConnectionError("simulated outage")
    failing_service.close = MagicMock()

    with patch(
        "blueprint.agents.services.infrastructure.redis_cache_service.RedisCacheService",
        return_value=failing_service,
    ):
        with caplog.at_level(
            "WARNING",
            logger="blueprint.agents.services.infrastructure.cache_backend_factory",
        ):
            CacheBackendFactory.create(config, enable_locking=True)

    assert "supersecret" not in caplog.text
    assert "redis://host:6379/0" in caplog.text


class TestComponentName:
    def test_the_default_cache_keeps_its_derived_name(self) -> None:
        """None means "derive it", which is the name existing lookups and health entries use."""
        assert CacheBackendFactory._component_name(DEFAULT_CACHE_NAME) is None

    def test_a_named_cache_gets_its_own(self) -> None:
        assert CacheBackendFactory._component_name("sessions") == "cache_sessions"

    def test_the_name_does_not_depend_on_the_backend(self, redis_fallback_config: CacheConfig) -> None:
        """fallback_to_local swaps the class, so a class-derived key would move on a Redis outage."""
        failing = MagicMock()
        failing._client.ping.side_effect = ConnectionError("simulated outage")

        with patch(
            "blueprint.agents.services.infrastructure.redis_cache_service.RedisCacheService",
            return_value=failing,
        ):
            service = CacheBackendFactory.create(redis_fallback_config, name="sessions")

        assert isinstance(service, DiskCacheService)
        assert service.name == "cache_sessions"


class TestDiskIsolation:
    def test_the_default_cache_uses_the_configured_directory(self, disk_config: CacheConfig) -> None:
        assert CacheBackendFactory._scoped_cache_dir(disk_config, DEFAULT_CACHE_NAME) == disk_config.cache_dir

    def test_a_name_becomes_a_subdirectory(self) -> None:
        config = CacheConfig(cache_dir=".cache/blueprint")
        assert CacheBackendFactory._scoped_cache_dir(config, "sessions") == ".cache/blueprint/sessions"

    def test_a_windows_separator_does_not_survive_into_the_path(self) -> None:
        config = CacheConfig(cache_dir=".cache\\blueprint")
        assert CacheBackendFactory._scoped_cache_dir(config, "sessions") == ".cache/blueprint/sessions"

    def test_the_created_cache_stores_in_it(self, disk_config: CacheConfig, tmp_path: Path) -> None:
        service = CacheBackendFactory.create(disk_config, name="sessions")
        assert isinstance(service, DiskCacheService)
        assert service.cache_dir == tmp_path / "cache" / "sessions"

    def test_two_names_do_not_share_a_directory(self, disk_config: CacheConfig) -> None:
        first = CacheBackendFactory._scoped_cache_dir(disk_config, "sessions")
        assert first != CacheBackendFactory._scoped_cache_dir(disk_config, "prompts")


class TestRedisIsolation:
    def test_the_default_cache_uses_the_configured_prefix(self) -> None:
        config = CacheConfig(backend="redis", key_prefix="myapp")
        assert CacheBackendFactory._scoped_key_prefix(config, DEFAULT_CACHE_NAME) == "myapp"

    def test_a_name_is_appended_to_the_prefix(self) -> None:
        config = CacheConfig(backend="redis", key_prefix="myapp")
        assert CacheBackendFactory._scoped_key_prefix(config, "sessions") == "myapp:sessions"

    def test_a_name_becomes_the_prefix_when_none_is_configured(self) -> None:
        assert CacheBackendFactory._scoped_key_prefix(CacheConfig(backend="redis"), "sessions") == "sessions"

    def test_two_names_do_not_share_a_keyspace(self) -> None:
        """Without this the name would isolate nothing on Redis: the prefix is all there is."""
        config = CacheConfig(backend="redis", key_prefix="myapp")
        first = CacheBackendFactory._scoped_key_prefix(config, "sessions")
        assert first != CacheBackendFactory._scoped_key_prefix(config, "prompts")

    def test_the_created_service_is_given_the_scoped_prefix(self, tmp_path: Path) -> None:
        config = CacheConfig(backend="redis", redis_url="redis://localhost:6379/0", key_prefix="myapp")
        reachable = MagicMock()

        with patch(
            "blueprint.agents.services.infrastructure.redis_cache_service.RedisCacheService",
            return_value=reachable,
        ) as constructor:
            CacheBackendFactory.create(config, name="sessions")

        assert constructor.call_args.kwargs["key_prefix"] == "myapp:sessions"
        assert constructor.call_args.kwargs["component_name"] == "cache_sessions"


class TestTheFallbackIsolatesAsDiskNotAsRedis:
    def test_the_fallback_uses_the_directory_for_the_name(self, redis_fallback_config: CacheConfig, tmp_path: Path) -> None:
        """The fallback is a different backend, so it needs its own isolation -- a directory."""
        failing = MagicMock()
        failing._client.ping.side_effect = ConnectionError("simulated outage")

        with patch(
            "blueprint.agents.services.infrastructure.redis_cache_service.RedisCacheService",
            return_value=failing,
        ):
            service = CacheBackendFactory.create(redis_fallback_config, name="sessions")

        assert isinstance(service, DiskCacheService)
        assert service.cache_dir == tmp_path / "cache" / "sessions"

    def test_the_import_error_fallback_does_the_same(
        self, redis_fallback_config: CacheConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_import = builtins.__import__

        def _fail_redis_import(name, *args, **kwargs):
            if name == "blueprint.agents.services.infrastructure.redis_cache_service":
                raise ImportError("simulated missing extra")
            return real_import(name, *args, **kwargs)

        monkeypatch.delitem(sys.modules, "blueprint.agents.services.infrastructure.redis_cache_service", raising=False)
        monkeypatch.setattr(builtins, "__import__", _fail_redis_import)

        service = CacheBackendFactory.create(redis_fallback_config, name="sessions")

        assert isinstance(service, DiskCacheService)
        assert service.cache_dir == tmp_path / "cache" / "sessions"


class TestCacheNameValidation:
    @pytest.mark.parametrize(
        "name",
        ["Sessions", "../evil", "a/b", "a\\b", "", " ", "a:b", ".hidden", "_leading", "-leading", "sess ions"],
    )
    def test_a_name_that_cannot_be_a_directory_is_refused(self, disk_config: CacheConfig, name: str) -> None:
        with pytest.raises(ValueError, match="not a legal cache name"):
            CacheBackendFactory.create(disk_config, name=name)

    @pytest.mark.parametrize("name", ["sessions", "default", "llm-responses", "v2.cache", "a", "0", "a_b"])
    def test_a_usable_name_is_accepted(self, disk_config: CacheConfig, name: str) -> None:
        assert isinstance(CacheBackendFactory.create(disk_config, name=name), DiskCacheService)

    def test_the_name_is_checked_before_anything_is_built(self, disk_config: CacheConfig, tmp_path: Path) -> None:
        """Otherwise a rejected name would already have created a directory outside the cache."""
        with pytest.raises(ValueError):
            CacheBackendFactory.create(disk_config, name="../evil")
        assert not (tmp_path / "evil").exists()
