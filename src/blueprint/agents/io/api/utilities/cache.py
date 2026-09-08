"""Cache management API endpoints."""

import logging

from fastapi import HTTPException

from ....component.registry import DEFAULT_CACHE_NAME
from ....models.api import CacheEvictRequest, CacheNamespacesResponse, CacheStatsResponse
from ....services.infrastructure.cache_service import CacheService
from ..rest_api_base import RestApiBase

logger = logging.getLogger(__name__)


class CacheManagementApi(RestApiBase):
    """API for managing cache operations.

    One router for the process, and every endpoint takes an optional ``?name=`` naming which
    cache to act on. It defaults to :data:`DEFAULT_CACHE_NAME`, so a request that names nothing
    reaches the cache a single-cache application has always had.

    A router per cache was the alternative and is wrong: caches can be registered after startup
    (``registry.add_cache``), and routes cannot, so anything keyed on the set of caches at build
    time would serve a stale list. Resolving the name per request has no such window.
    """

    def __init__(self) -> None:
        super().__init__(should_register=False)

    async def on_startup(self) -> None:
        """No startup actions required; cache service is managed externally."""

    async def on_shutdown(self) -> None:
        """No shutdown actions required; cache service is managed externally."""

    def _cache(self, name: str) -> CacheService:
        """Return the cache called ``name``, or answer the request with an HTTP error.

        Two distinct failures, answered differently. **503** when no cache is registered at all:
        the application was built without one, the condition is not the caller's doing, and it
        may resolve without a redeploy -- which is what 503 says. **404** when caches exist but
        none has this name: that is a bad request for a resource that is not there, and
        answering 503 would invite a retry that can never succeed.

        The registered names go in the 404 body. A caller who mistypes a cache name otherwise
        has no way to discover the right one, and there is no endpoint that lists them.

        Raises:
            HTTPException: 503 with no cache registered, 404 for an unknown name.
        """
        if not self.registry.get_all_caches():
            raise HTTPException(status_code=503, detail="Cache service not available")
        try:
            return self.registry.get_cache(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @RestApiBase.get("/cache/stats", response_model=CacheStatsResponse, tags=["cache"], summary="Get cache statistics.")
    async def get_cache_stats(self, name: str = DEFAULT_CACHE_NAME) -> CacheStatsResponse:
        """Get statistics for one cache."""
        stats = self._cache(name).get_stats()
        return CacheStatsResponse(**stats)

    @RestApiBase.get("/cache/namespaces", response_model=CacheNamespacesResponse, tags=["cache"], summary="List all cache namespaces.")
    async def list_cache_namespaces(self, name: str = DEFAULT_CACHE_NAME) -> CacheNamespacesResponse:
        """List all namespaces currently stored in one cache."""
        namespaces = self._cache(name).list_namespaces()
        logger.debug("Listing namespaces in cache '%s': %s", name, namespaces)
        return CacheNamespacesResponse(namespaces=namespaces, count=len(namespaces))

    @RestApiBase.post("/cache/evict", tags=["cache"], summary="Evict cache contents for an optional namespace.")
    async def evict_cache_entry(self, request: CacheEvictRequest, name: str = DEFAULT_CACHE_NAME) -> dict[str, str]:
        """Evict (clear) contents of one cache, for an optional namespace within it."""
        self._cache(name).clear(namespace=request.namespace)
        if request.namespace:
            logger.info("Cleared namespace '%s' in cache '%s'", request.namespace, name)
        else:
            logger.info("Cleared the whole of cache '%s'", name)
        return {
            "status": "ok",
            "cache": name,
            "namespace": request.namespace or "all",
            "message": f"Cache cleared for namespace '{request.namespace}'" if request.namespace else "Entire cache cleared",
        }
