"""Unit tests for CacheBackendFactory.

Focus is on the ``enable_locking`` propagation through the Redis→Disk fallback
paths, which was previously dropped silently.
"""

from __future__ import annotations

import builtins
import sys
from unittest.mock import MagicMock, patch

import pytest

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
