"""Unit tests for CacheHealthChecker.

Bypasses real cache __init__ (registry side-effects + real Redis client) using
__new__ + manual attribute injection, matching the pattern in
test_redis_cache_service.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from blueprint.agents.io.api.actuators.health.cache_health import CacheHealthChecker
from blueprint.agents.services.infrastructure.cache_service import DiskCacheService
from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService


# ---------------------------------------------------------------------------
# Fixture-style helpers
# ---------------------------------------------------------------------------


def _make_redis_cache(*, ping_works: bool) -> RedisCacheService:
    """Build a RedisCacheService bypassing __init__ (no real connection)."""
    cache = RedisCacheService.__new__(RedisCacheService)
    cache._client = MagicMock()
    if ping_works:
        cache._client.ping.return_value = True
    else:
        cache._client.ping.side_effect = ConnectionError("simulated outage")
    cache._redis_url = "redis://test:6379/0"
    cache._key_prefix = ""
    return cache


def _make_disk_cache() -> DiskCacheService:
    """Build a DiskCacheService bypassing __init__."""
    return DiskCacheService.__new__(DiskCacheService)


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


class TestRedisBackend:
    async def test_reachable_redis_reports_healthy(self) -> None:
        cache = _make_redis_cache(ping_works=True)
        checker = CacheHealthChecker(cache)
        result = await checker.health_check()
        assert result.status == "healthy"
        assert "redis://test:6379/0" in (result.message or "")

    async def test_unreachable_redis_reports_unhealthy(self) -> None:
        cache = _make_redis_cache(ping_works=False)
        checker = CacheHealthChecker(cache)
        result = await checker.health_check()
        assert result.status == "unhealthy"
        assert "simulated outage" in (result.message or "")

    async def test_recovers_to_healthy_when_redis_returns(self) -> None:
        # Same instance: first call fails, second succeeds. Mirrors the
        # production case where Redis comes back after an outage.
        cache = _make_redis_cache(ping_works=False)

        first = await CacheHealthChecker(cache).health_check()
        assert first.status == "unhealthy"

        # Redis is back: clear the side effect, return success
        cache._client.ping.side_effect = None
        cache._client.ping.return_value = True

        second = await CacheHealthChecker(cache).health_check()
        assert second.status == "healthy"

    async def test_redis_check_offloads_blocking_ping_to_thread(self) -> None:
        # The sync redis-py client must not block the event loop. We assert
        # this by using a ping() that captures whether it ran on a non-main
        # thread (asyncio.to_thread runs in a worker thread).
        import threading

        cache = _make_redis_cache(ping_works=True)
        main_thread = threading.get_ident()
        observed: dict[str, Any] = {}

        def _capture_ping() -> bool:
            observed["thread_id"] = threading.get_ident()
            return True

        cache._client.ping.side_effect = _capture_ping

        result = await CacheHealthChecker(cache).health_check()

        assert result.status == "healthy"
        assert observed["thread_id"] != main_thread, (
            "ping() should run on a worker thread to avoid blocking the event loop"
        )


# ---------------------------------------------------------------------------
# Disk backend
# ---------------------------------------------------------------------------


class TestDiskBackend:
    async def test_disk_cache_reports_healthy(self) -> None:
        cache = _make_disk_cache()
        result = await CacheHealthChecker(cache).health_check()
        assert result.status == "healthy"
        assert "DiskCacheService" in (result.message or "")

    async def test_disk_check_does_not_touch_disk(self) -> None:
        # The disk check is intentionally trivial — it must not call any
        # methods on the cache. This guards against accidental probe writes.
        cache = MagicMock(spec=DiskCacheService)
        await CacheHealthChecker(cache).health_check()

        cache.get.assert_not_called()
        cache.set.assert_not_called()
        cache.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown / custom backend
# ---------------------------------------------------------------------------


class TestCustomBackend:
    async def test_custom_backend_reports_healthy_with_neutral_message(self) -> None:
        # A user implementing their own CacheService should still pass the
        # readiness probe by default — they can register their own checker
        # via with_health_checker() if they want a stricter probe.
        custom = MagicMock()
        custom.__class__.__name__ = "CustomCache"
        result = await CacheHealthChecker(custom).health_check()
        assert result.status == "healthy"
        assert "no backend-specific probe" in (result.message or "")
