"""Shared fixtures for sessions service unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from cachetools import TTLCache

from blueprint.agents.services.sessions.api_client import SessionsApiClient
from blueprint.agents.services.sessions.key_provider import SessionKeyProvider


@pytest.fixture
def sessions_config() -> dict:
    """Minimal valid sessions_service configuration dict."""
    return {
        "base_url": "http://sessions.local:8000",
        "api_key": "test-api-key",
    }


@pytest.fixture
def api_client(mock_registry: MagicMock, mock_config: MagicMock) -> SessionsApiClient:
    """Fresh SessionsApiClient — not yet started."""
    return SessionsApiClient()


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Async mock of httpx.AsyncClient with common HTTP methods pre-set."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"result": "ok"}

    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_response)
    client.post = AsyncMock(return_value=mock_response)
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def started_api_client(api_client: SessionsApiClient, mock_http_client: AsyncMock) -> SessionsApiClient:
    """SessionsApiClient with _base_url, _api_key, and _client pre-set (bypasses on_startup)."""
    api_client._base_url = "http://sessions.local:8000"
    api_client._api_key = "test-api-key"
    api_client._client = mock_http_client
    return api_client


@pytest.fixture
def key_provider(mock_registry: MagicMock, mock_config: MagicMock) -> SessionKeyProvider:
    """Fresh SessionKeyProvider — not yet started."""
    return SessionKeyProvider()


@pytest.fixture
def started_key_provider(key_provider: SessionKeyProvider) -> SessionKeyProvider:
    """SessionKeyProvider with cache and config pre-set (bypasses on_startup)."""
    key_provider._cache = TTLCache(maxsize=100, ttl=3600)
    key_provider._source = "env"
    key_provider._env_var = "SESSION_KEY"
    key_provider._cache_ttl = 3600
    return key_provider
