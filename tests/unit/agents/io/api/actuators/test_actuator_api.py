"""Unit tests for ActuatorApi."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blueprint.agents.io.api.actuators.actuator_api import ActuatorApi


@pytest.fixture
def actuator_api(mock_config: MagicMock, mock_registry: MagicMock) -> ActuatorApi:
    """Return an ActuatorApi instance with mocked config and registry."""
    mock_config.get.side_effect = lambda key, default=None: {
        "health_check_interval_seconds": 30,
    }.get(key, default)
    return ActuatorApi()


# ---------------------------------------------------------------------------
# _sanitize_config
# ---------------------------------------------------------------------------


class TestSanitizeConfig:
    def test_non_sensitive_values_are_unchanged(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"app_name": "agent", "port": 8080})
        assert result == {"app_name": "agent", "port": 8080}

    def test_api_key_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"api_key": "secret-value"})
        assert result["api_key"] == "***"

    def test_password_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"password": "hunter2"})
        assert result["password"] == "***"

    def test_secret_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"secret": "shh"})
        assert result["secret"] == "***"

    def test_token_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"token": "bearer-abc"})
        assert result["token"] == "***"

    def test_nested_sensitive_key_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"database": {"host": "localhost", "password": "db-pass"}})
        assert result["database"]["host"] == "localhost"
        assert result["database"]["password"] == "***"

    def test_deeply_nested_api_key_is_masked(self, actuator_api: ActuatorApi) -> None:
        result = actuator_api._sanitize_config({"ai": {"provider": {"api_key": "sk-1234", "model": "gpt-4"}}})
        assert result["ai"]["provider"]["api_key"] == "***"
        assert result["ai"]["provider"]["model"] == "gpt-4"

    def test_empty_dict_returns_empty_dict(self, actuator_api: ActuatorApi) -> None:
        assert actuator_api._sanitize_config({}) == {}


# ---------------------------------------------------------------------------
# liveness_probe
# ---------------------------------------------------------------------------


class TestLivenessProbe:
    async def test_returns_up_when_no_config_errors(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        mock_config.has_validation_errors.return_value = False
        result = await actuator_api.liveness_probe()
        assert result.status == "UP"

    async def test_returns_up_even_when_config_has_validation_errors(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        mock_config.has_validation_errors.return_value = True
        mock_config.get_validation_errors.return_value = ["missing field"]
        result = await actuator_api.liveness_probe()
        assert result.status == "UP"


# ---------------------------------------------------------------------------
# on_startup / on_shutdown
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_creates_health_cache(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as mock_cache_cls:
            mock_cache_cls.return_value.start = AsyncMock()
            await actuator_api.on_startup()
        mock_cache_cls.assert_called_once()
        assert actuator_api._health_cache is mock_cache_cls.return_value

    async def test_on_startup_uses_configured_interval(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: 60 if key == "health_check_interval_seconds" else default
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as mock_cache_cls:
            mock_cache_cls.return_value.start = AsyncMock()
            await actuator_api.on_startup()
        mock_cache_cls.assert_called_once_with(check_interval_seconds=60)

    async def test_on_startup_registers_pending_providers(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        provider = MagicMock()
        actuator_api._pending_providers = {"db": provider}
        with patch("blueprint.agents.io.api.actuators.actuator_api.HealthCheckCache") as mock_cache_cls:
            mock_cache_cls.return_value.start = AsyncMock()
            mock_cache_cls.return_value.set_health_check_provider = MagicMock()
            await actuator_api.on_startup()
        mock_cache_cls.return_value.set_health_check_provider.assert_called_once_with({"db": provider})

    async def test_on_shutdown_stops_health_cache(self, actuator_api: ActuatorApi, mock_config: MagicMock) -> None:
        mock_cache = MagicMock()
        mock_cache.stop = AsyncMock()
        actuator_api._health_cache = mock_cache
        await actuator_api.on_shutdown()
        mock_cache.stop.assert_awaited_once()

    async def test_on_shutdown_is_safe_when_cache_none(self, actuator_api: ActuatorApi) -> None:
        actuator_api._health_cache = None
        await actuator_api.on_shutdown()  # must not raise
