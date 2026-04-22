"""Unit tests for CacheManagementApi."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from blueprint.agents.io.api.utilities.cache import CacheManagementApi
from blueprint.agents.models.api import CacheEvictRequest


@pytest.fixture
def cache_api(mock_config: MagicMock, mock_registry: MagicMock) -> CacheManagementApi:
    """Return a CacheManagementApi with a mocked registry."""
    return CacheManagementApi()


@pytest.fixture
def cache_api_with_cache(cache_api: CacheManagementApi, mock_registry: MagicMock) -> CacheManagementApi:
    """CacheManagementApi with registry.has_cache() returning True."""
    mock_registry.has_cache.return_value = True
    mock_registry.cache_service.get_stats.return_value = {
        "size": 10,
        "cache_dir": "/tmp/cache",
        "ttl_tracked_keys": 5,
        "size_limit": 1_000_000_000,
        "eviction_policy": "least-recently-used",
    }
    mock_registry.cache_service.list_namespaces.return_value = ["ns1", "ns2"]
    mock_registry.cache_service.clear = MagicMock()
    return cache_api


class TestGetCacheStats:
    async def test_raises_503_when_no_cache(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        mock_registry.has_cache.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await cache_api.get_cache_stats()
        assert exc_info.value.status_code == 503

    async def test_returns_stats_when_cache_available(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.get_cache_stats()
        assert result.size == 10
        assert result.cache_dir == "/tmp/cache"

    async def test_calls_cache_service_get_stats(self, cache_api_with_cache: CacheManagementApi, mock_registry: MagicMock) -> None:
        await cache_api_with_cache.get_cache_stats()
        mock_registry.cache_service.get_stats.assert_called_once()


class TestListCacheNamespaces:
    async def test_raises_503_when_no_cache(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        mock_registry.has_cache.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await cache_api.list_cache_namespaces()
        assert exc_info.value.status_code == 503

    async def test_returns_namespaces(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.list_cache_namespaces()
        assert result.namespaces == ["ns1", "ns2"]
        assert result.count == 2


class TestEvictCacheEntry:
    async def test_raises_503_when_no_cache(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        mock_registry.has_cache.return_value = False
        with pytest.raises(HTTPException) as exc_info:
            await cache_api.evict_cache_entry(CacheEvictRequest())
        assert exc_info.value.status_code == 503

    async def test_clears_specific_namespace(self, cache_api_with_cache: CacheManagementApi, mock_registry: MagicMock) -> None:
        await cache_api_with_cache.evict_cache_entry(CacheEvictRequest(namespace="ns1"))
        mock_registry.cache_service.clear.assert_called_once_with(namespace="ns1")

    async def test_clears_all_when_no_namespace(self, cache_api_with_cache: CacheManagementApi, mock_registry: MagicMock) -> None:
        await cache_api_with_cache.evict_cache_entry(CacheEvictRequest())
        mock_registry.cache_service.clear.assert_called_once_with(namespace=None)

    async def test_returns_ok_status(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.evict_cache_entry(CacheEvictRequest(namespace="ns1"))
        assert result["status"] == "ok"

    async def test_response_includes_namespace(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.evict_cache_entry(CacheEvictRequest(namespace="ns1"))
        assert result["namespace"] == "ns1"

    async def test_response_reports_all_when_no_namespace(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.evict_cache_entry(CacheEvictRequest())
        assert result["namespace"] == "all"
