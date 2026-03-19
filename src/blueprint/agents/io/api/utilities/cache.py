"""Cache management API endpoints."""

import logging

from fastapi import HTTPException

from ....models.api import CacheEvictRequest, CacheNamespacesResponse, CacheStatsResponse
from ..rest_api_base import RestApiBase

logger = logging.getLogger(__name__)


class CacheManagementApi(RestApiBase):
    """API for managing cache operations."""

    def __init__(self) -> None:
        super().__init__(should_register=False)

    async def on_startup(self) -> None:
        """No startup actions required; cache service is managed externally."""

    async def on_shutdown(self) -> None:
        """No shutdown actions required; cache service is managed externally."""

    @RestApiBase.get("/cache/stats", response_model=CacheStatsResponse, tags=["cache"], summary="Get cache statistics.")
    async def get_cache_stats(self) -> CacheStatsResponse:
        """Get cache statistics."""
        if not self.registry.has_cache():
            raise HTTPException(status_code=503, detail="Cache service not available")
        stats = self.registry.cache_service.get_stats()
        return CacheStatsResponse(**stats)

    @RestApiBase.get("/cache/namespaces", response_model=CacheNamespacesResponse, tags=["cache"], summary="List all cache namespaces.")
    async def list_cache_namespaces(self) -> CacheNamespacesResponse:
        """List all namespaces currently stored in cache."""
        if not self.registry.has_cache():
            raise HTTPException(status_code=503, detail="Cache service not available")
        namespaces = self.registry.cache_service.list_namespaces()
        logger.debug("Listing cache namespaces: %s", namespaces)
        return CacheNamespacesResponse(namespaces=namespaces, count=len(namespaces))

    @RestApiBase.post("/cache/evict", tags=["cache"], summary="Evict cache contents for an optional namespace.")
    async def evict_cache_entry(self, request: CacheEvictRequest):
        """Evict (clear) cache contents for an optional namespace."""
        if not self.registry.has_cache():
            raise HTTPException(status_code=503, detail="Cache service not available")
        self.registry.cache_service.clear(namespace=request.namespace)
        if request.namespace:
            logger.info("Cleared cache namespace '%s'", request.namespace)
        else:
            logger.info("Cleared entire cache")
        return {
            "status": "ok",
            "namespace": request.namespace or "all",
            "message": f"Cache cleared for namespace '{request.namespace}'" if request.namespace else "Entire cache cleared",
        }
