"""Unit tests for SessionKeyProvider."""

import os
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from cachetools import TTLCache

from blueprint.agents.services.sessions.key_provider import SessionKeyProvider

_SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")


# ---------------------------------------------------------------------------
# on_startup
# ---------------------------------------------------------------------------


class TestOnStartup:
    async def test_initializes_cache(self, key_provider: SessionKeyProvider, mock_config: MagicMock) -> None:
        mock_config.get.return_value = {
            "session_key_source": "env",
            "session_key_env_var": "SESSION_KEY",
            "session_key_cache_ttl_seconds": 3600,
        }
        await key_provider.on_startup()
        assert key_provider._cache is not None

    async def test_reads_source_from_config(self, key_provider: SessionKeyProvider, mock_config: MagicMock) -> None:
        mock_config.get.return_value = {
            "session_key_source": "config",
        }
        await key_provider.on_startup()
        assert key_provider._source == "config"

    async def test_reads_env_var_name_from_config(self, key_provider: SessionKeyProvider, mock_config: MagicMock) -> None:
        mock_config.get.return_value = {
            "session_key_env_var": "MY_SESSION_KEY",
        }
        await key_provider.on_startup()
        assert key_provider._env_var == "MY_SESSION_KEY"

    async def test_raises_when_sessions_service_config_missing(self, key_provider: SessionKeyProvider, mock_config: MagicMock) -> None:
        mock_config.get.return_value = None
        with pytest.raises(ValueError, match="sessions_service configuration not found"):
            await key_provider.on_startup()


# ---------------------------------------------------------------------------
# on_shutdown
# ---------------------------------------------------------------------------


class TestOnShutdown:
    async def test_clears_cache(self, started_key_provider: SessionKeyProvider) -> None:
        started_key_provider._cache["key"] = "val"
        await started_key_provider.on_shutdown()
        assert len(started_key_provider._cache) == 0

    async def test_noop_when_cache_not_initialized(self, key_provider: SessionKeyProvider) -> None:
        await key_provider.on_shutdown()  # Should not raise


# ---------------------------------------------------------------------------
# get_session_key — env source
# ---------------------------------------------------------------------------


class TestGetSessionKeyEnv:
    async def test_reads_from_env_var(self, started_key_provider: SessionKeyProvider) -> None:
        with patch.dict(os.environ, {"SESSION_KEY": "my-secret-key"}):
            result = await started_key_provider.get_session_key()
        assert result == "my-secret-key"

    async def test_raises_when_env_var_not_set(self, started_key_provider: SessionKeyProvider) -> None:
        env_without_key = {k: v for k, v in os.environ.items() if k != "SESSION_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            with pytest.raises(ValueError, match="SESSION_KEY"):
                await started_key_provider.get_session_key()

    async def test_result_cached_after_first_fetch(self, started_key_provider: SessionKeyProvider) -> None:
        with patch.dict(os.environ, {"SESSION_KEY": "cached-key"}):
            await started_key_provider.get_session_key()
        assert "default" in started_key_provider._cache

    async def test_cache_hit_returned_without_env_lookup(self, started_key_provider: SessionKeyProvider) -> None:
        started_key_provider._cache["default"] = "cached-value"
        # Remove env var to prove cache is used, not env
        env_without_key = {k: v for k, v in os.environ.items() if k != "SESSION_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            result = await started_key_provider.get_session_key()
        assert result == "cached-value"


# ---------------------------------------------------------------------------
# get_session_key — config source
# ---------------------------------------------------------------------------


class TestGetSessionKeyConfig:
    async def test_reads_from_config(
        self,
        started_key_provider: SessionKeyProvider,
        mock_config: MagicMock,
    ) -> None:
        started_key_provider._source = "config"
        mock_config.get.return_value = {"session_key": "config-secret"}
        result = await started_key_provider.get_session_key()
        assert result == "config-secret"

    async def test_raises_when_key_not_in_config(
        self,
        started_key_provider: SessionKeyProvider,
        mock_config: MagicMock,
    ) -> None:
        started_key_provider._source = "config"
        mock_config.get.return_value = {}
        with pytest.raises(ValueError, match="session_key not found"):
            await started_key_provider.get_session_key()


# ---------------------------------------------------------------------------
# get_session_key — vault source
# ---------------------------------------------------------------------------


class TestGetSessionKeyVault:
    async def test_raises_not_implemented_for_vault(self, started_key_provider: SessionKeyProvider) -> None:
        started_key_provider._source = "vault"
        with pytest.raises(NotImplementedError):
            await started_key_provider.get_session_key()


# ---------------------------------------------------------------------------
# get_session_key — unknown source
# ---------------------------------------------------------------------------


class TestGetSessionKeyUnknownSource:
    async def test_raises_for_unknown_source(self, started_key_provider: SessionKeyProvider) -> None:
        started_key_provider._source = "unsupported"
        with pytest.raises(ValueError, match="Unknown session key source"):
            await started_key_provider.get_session_key()


# ---------------------------------------------------------------------------
# invalidate_cache
# ---------------------------------------------------------------------------


class TestInvalidateCache:
    def test_removes_default_key_when_no_session_id(self, started_key_provider: SessionKeyProvider) -> None:
        started_key_provider._cache["default"] = "secret"
        started_key_provider.invalidate_cache()
        assert "default" not in started_key_provider._cache

    def test_removes_session_specific_key(self, started_key_provider: SessionKeyProvider) -> None:
        started_key_provider._cache[str(_SESSION_ID)] = "per-session-key"
        started_key_provider.invalidate_cache(_SESSION_ID)
        assert str(_SESSION_ID) not in started_key_provider._cache

    def test_noop_when_key_not_in_cache(self, started_key_provider: SessionKeyProvider) -> None:
        started_key_provider.invalidate_cache()  # cache is empty — should not raise

    def test_noop_when_cache_not_initialized(self, key_provider: SessionKeyProvider) -> None:
        key_provider.invalidate_cache()  # _cache is None — should not raise


# ---------------------------------------------------------------------------
# get_session_key — remote source
# ---------------------------------------------------------------------------

_REMOTE_URL = "http://sessions.local:8001/v1/sessions"


def _make_remote_provider(remote_url: str = _REMOTE_URL, api_key: str = "test-key") -> SessionKeyProvider:
    provider = SessionKeyProvider()
    provider._source = "remote"
    provider._remote_url = remote_url
    provider._api_key = api_key
    provider._cache = TTLCache(maxsize=100, ttl=60)
    return provider


class TestGetSessionKeyRemote:
    @respx.mock
    async def test_returns_key_from_remote(self) -> None:
        session_id = uuid4()
        respx.get(f"{_REMOTE_URL}/{session_id}/key").mock(return_value=httpx.Response(200, json={"session_key": "remote-secret"}))
        provider = _make_remote_provider()
        result = await provider.get_session_key(session_id)
        assert result == "remote-secret"

    @respx.mock
    async def test_caches_key_after_first_fetch(self) -> None:
        session_id = uuid4()
        route = respx.get(f"{_REMOTE_URL}/{session_id}/key").mock(return_value=httpx.Response(200, json={"session_key": "cached-remote"}))
        provider = _make_remote_provider()
        await provider.get_session_key(session_id)
        await provider.get_session_key(session_id)
        assert route.call_count == 1

    @respx.mock
    async def test_raises_on_non_2xx_response(self) -> None:
        session_id = uuid4()
        respx.get(f"{_REMOTE_URL}/{session_id}/key").mock(return_value=httpx.Response(404))
        provider = _make_remote_provider()
        with pytest.raises(httpx.HTTPStatusError):
            await provider.get_session_key(session_id)

    async def test_raises_when_session_id_missing(self) -> None:
        provider = _make_remote_provider()
        with pytest.raises(ValueError, match="session_id required"):
            await provider.get_session_key(None)

    async def test_raises_when_remote_url_not_configured(self) -> None:
        provider = _make_remote_provider(remote_url="")
        with pytest.raises(ValueError, match="session_key_remote_url not configured"):
            await provider.get_session_key(uuid4())
