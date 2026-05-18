"""Health checker for the cache backend (DiskCache or Redis)."""

from __future__ import annotations

import logging
from typing import Any

from .....models.api import ComponentHealth
from .....services.infrastructure.cache_service import CacheService, DiskCacheService
from .health_base import HealthCheckerBase

# Redis is an optional extra; the import may legitimately fail.
try:
    from .....services.infrastructure.redis_cache_service import RedisCacheService

    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover — only triggered when [redis] is missing
    RedisCacheService = None  # type: ignore[assignment,misc]
    _REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class CacheHealthChecker(HealthCheckerBase):
    """Reports the cache backend as part of the readiness probe.

    For ``DiskCacheService``: always reports healthy. The local disk cannot
    "fail" the way a network service can; disk-side issues surface through
    other code paths.

    For ``RedisCacheService``: pings Redis on every check. A failed ping flips
    the readiness probe to ``unhealthy``, taking the pod out of K8s service
    rotation until Redis recovers. Liveness is unaffected — the pod stays
    alive and re-enters rotation automatically once Redis is back.
    """

    def __init__(self, cache: CacheService) -> None:
        self._cache = cache

    async def health_check(self) -> ComponentHealth:
        if _REDIS_AVAILABLE and isinstance(self._cache, RedisCacheService):
            return await self._check_redis(self._cache)
        if isinstance(self._cache, DiskCacheService):
            return ComponentHealth(status="healthy", message="DiskCacheService (local)")
        # Custom CacheService implementation — no backend-specific probe available
        return ComponentHealth(
            status="healthy",
            message=f"{type(self._cache).__name__} (no backend-specific probe)",
        )

    @staticmethod
    async def _check_redis(cache: Any) -> ComponentHealth:
        # Use the pre-sanitized URL: ComponentHealth.message is exposed via the
        # /readiness probe and warning logs go to central aggregators — the raw
        # URL may carry inline credentials.
        safe_url = cache._safe_redis_url
        try:
            await cache.ping()
            return ComponentHealth(
                status="healthy",
                message=f"Redis reachable at {safe_url}",
            )
        except Exception as exc:
            logger.warning("Cache health check failed: Redis unreachable at %s: %s", safe_url, exc)
            return ComponentHealth(
                status="unhealthy",
                message=f"Redis unreachable at {safe_url}: {exc}",
            )
