"""Unit tests for CacheManagementApi.

Every endpoint takes an optional ``?name=`` naming which cache to act on, defaulting to the
one a single-cache application has always had. The two failure answers are deliberately
different -- 503 when no cache is registered at all, 404 for a name that is not among the ones
that are -- and both are asserted, because answering 503 for a mistyped name would invite a
retry that can never succeed.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from blueprint.agents.io.api.utilities.cache import CacheManagementApi
from blueprint.agents.models.api import CacheEvictRequest

STATS = {
    "size": 10,
    "cache_dir": "/tmp/cache",
    "ttl_tracked_keys": 5,
    "size_limit": 1_000_000_000,
    "eviction_policy": "least-recently-used",
}


@pytest.fixture
def cache_api(mock_config: MagicMock, mock_registry: MagicMock) -> CacheManagementApi:
    """Return a CacheManagementApi with a mocked registry holding no cache."""
    mock_registry.get_all_caches.return_value = {}
    return CacheManagementApi()


def register(mock_registry: MagicMock, **caches: MagicMock) -> None:
    """Make the mocked registry answer for exactly the given cache names."""
    mock_registry.get_all_caches.return_value = dict(caches)
    mock_registry.get_cache.side_effect = lambda name="default": (
        caches[name] if name in caches else _raise(ValueError(f"No cache registered as '{name}' (registered: {', '.join(sorted(caches))})"))
    )


def _raise(error: Exception) -> None:
    raise error


def cache_double() -> MagicMock:
    cache = MagicMock()
    cache.get_stats.return_value = STATS
    cache.list_namespaces.return_value = ["ns1", "ns2"]
    cache.clear = MagicMock()
    return cache


@pytest.fixture
def cache_api_with_cache(cache_api: CacheManagementApi, mock_registry: MagicMock) -> CacheManagementApi:
    """CacheManagementApi with one cache registered under the default name."""
    register(mock_registry, default=cache_double())
    return cache_api


class TestGetCacheStats:
    async def test_raises_503_when_no_cache(self, cache_api: CacheManagementApi) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await cache_api.get_cache_stats()
        assert exc_info.value.status_code == 503

    async def test_returns_stats_when_cache_available(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.get_cache_stats()
        assert result.size == 10
        assert result.cache_dir == "/tmp/cache"

    async def test_calls_cache_service_get_stats(self, cache_api_with_cache: CacheManagementApi, mock_registry: MagicMock) -> None:
        await cache_api_with_cache.get_cache_stats()
        mock_registry.get_all_caches.return_value["default"].get_stats.assert_called_once()


class TestListCacheNamespaces:
    async def test_raises_503_when_no_cache(self, cache_api: CacheManagementApi) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await cache_api.list_cache_namespaces()
        assert exc_info.value.status_code == 503

    async def test_returns_namespaces(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.list_cache_namespaces()
        assert result.namespaces == ["ns1", "ns2"]
        assert result.count == 2


class TestEvictCacheEntry:
    async def test_raises_503_when_no_cache(self, cache_api: CacheManagementApi) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await cache_api.evict_cache_entry(CacheEvictRequest())
        assert exc_info.value.status_code == 503

    async def test_clears_specific_namespace(self, cache_api_with_cache: CacheManagementApi, mock_registry: MagicMock) -> None:
        await cache_api_with_cache.evict_cache_entry(CacheEvictRequest(namespace="ns1"))
        mock_registry.get_all_caches.return_value["default"].clear.assert_called_once_with(namespace="ns1")

    async def test_clears_all_when_no_namespace(self, cache_api_with_cache: CacheManagementApi, mock_registry: MagicMock) -> None:
        await cache_api_with_cache.evict_cache_entry(CacheEvictRequest())
        mock_registry.get_all_caches.return_value["default"].clear.assert_called_once_with(namespace=None)

    async def test_returns_ok_status(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.evict_cache_entry(CacheEvictRequest(namespace="ns1"))
        assert result["status"] == "ok"

    async def test_response_includes_namespace(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.evict_cache_entry(CacheEvictRequest(namespace="ns1"))
        assert result["namespace"] == "ns1"

    async def test_response_reports_all_when_no_namespace(self, cache_api_with_cache: CacheManagementApi) -> None:
        result = await cache_api_with_cache.evict_cache_entry(CacheEvictRequest())
        assert result["namespace"] == "all"


class TestNamedCaches:
    async def test_stats_read_the_named_cache(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        default, sessions = cache_double(), cache_double()
        sessions.get_stats.return_value = {**STATS, "size": 99}
        register(mock_registry, default=default, sessions=sessions)

        result = await cache_api.get_cache_stats(name="sessions")

        assert result.size == 99
        default.get_stats.assert_not_called()

    async def test_the_default_is_used_when_no_name_is_given(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        default, sessions = cache_double(), cache_double()
        register(mock_registry, default=default, sessions=sessions)

        await cache_api.get_cache_stats()

        default.get_stats.assert_called_once()
        sessions.get_stats.assert_not_called()

    async def test_evict_clears_only_the_named_cache(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        default, sessions = cache_double(), cache_double()
        register(mock_registry, default=default, sessions=sessions)

        await cache_api.evict_cache_entry(CacheEvictRequest(), name="sessions")

        sessions.clear.assert_called_once_with(namespace=None)
        default.clear.assert_not_called()

    async def test_the_response_names_the_cache_it_cleared(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        register(mock_registry, default=cache_double(), sessions=cache_double())

        result = await cache_api.evict_cache_entry(CacheEvictRequest(), name="sessions")

        assert result["cache"] == "sessions"

    async def test_namespaces_read_the_named_cache(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        sessions = cache_double()
        sessions.list_namespaces.return_value = ["jobs"]
        register(mock_registry, default=cache_double(), sessions=sessions)

        result = await cache_api.list_cache_namespaces(name="sessions")

        assert result.namespaces == ["jobs"]


class TestUnknownName:
    @pytest.mark.parametrize("call", ["get_cache_stats", "list_cache_namespaces"])
    async def test_an_unknown_name_answers_404(self, cache_api: CacheManagementApi, mock_registry: MagicMock, call: str) -> None:
        """404 rather than 503: a mistyped name is a bad request, and a retry cannot fix it."""
        register(mock_registry, default=cache_double())

        with pytest.raises(HTTPException) as exc_info:
            await getattr(cache_api, call)(name="nope")

        assert exc_info.value.status_code == 404

    async def test_evict_answers_404_too(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        register(mock_registry, default=cache_double())

        with pytest.raises(HTTPException) as exc_info:
            await cache_api.evict_cache_entry(CacheEvictRequest(), name="nope")

        assert exc_info.value.status_code == 404

    async def test_the_404_lists_the_registered_names(self, cache_api: CacheManagementApi, mock_registry: MagicMock) -> None:
        """There is no endpoint that lists them, so a mistyped name has to be recoverable here."""
        register(mock_registry, default=cache_double(), sessions=cache_double())

        with pytest.raises(HTTPException) as exc_info:
            await cache_api.get_cache_stats(name="nope")

        assert "default" in str(exc_info.value.detail) and "sessions" in str(exc_info.value.detail)
