"""Cache management API endpoints."""

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from ..models.api import CacheEvictRequest, CacheNamespacesResponse, CacheStatsResponse

if TYPE_CHECKING:
    from ..registry.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)


class CacheManagementApi:
    """API for managing cache operations."""

    def __init__(self, component_registry: "ComponentRegistry") -> None:
        """Initialize cache management API.

        Args:
            component_registry: Component registry with cache service
        """
        self.router = APIRouter(prefix="/cache", tags=["cache"])
        self._component_registry = component_registry
        self._register_routes()

    def _register_routes(self) -> None:
        """Register cache management routes."""

        @self.router.get("/stats", response_model=CacheStatsResponse)
        async def get_cache_stats():
            """Get cache statistics."""
            if not self._component_registry.has_cache():
                raise HTTPException(status_code=503, detail="Cache service not available")

            cache = self._component_registry.get_cache()
            stats = cache.get_stats()
            return CacheStatsResponse(**stats)

        @self.router.get("/namespaces", response_model=CacheNamespacesResponse)
        async def list_cache_namespaces():
            """List all namespaces currently stored in cache."""
            if not self._component_registry.has_cache():
                raise HTTPException(status_code=503, detail="Cache service not available")

            cache = self._component_registry.get_cache()
            namespaces = cache.list_namespaces()
            logger.debug("Listing cache namespaces: %s", namespaces)
            return CacheNamespacesResponse(namespaces=namespaces, count=len(namespaces))

        @self.router.post("/evict")
        async def evict_cache_entry(request: CacheEvictRequest):
            """Evict (clear) cache contents for an optional namespace.

            Args:
                request: Cache eviction request containing optional namespace
            """
            if not self._component_registry.has_cache():
                raise HTTPException(status_code=503, detail="Cache service not available")

            cache = self._component_registry.get_cache()
            cache.clear(namespace=request.namespace)
            if request.namespace:
                logger.info("Cleared cache namespace '%s'", request.namespace)
            else:
                logger.info("Cleared entire cache")
            return {
                "status": "ok",
                "namespace": request.namespace or "all",
                "message": f"Cache cleared for namespace '{request.namespace}'" if request.namespace else "Entire cache cleared",
            }
