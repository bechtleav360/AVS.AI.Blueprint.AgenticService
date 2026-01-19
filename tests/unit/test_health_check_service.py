"""Unit tests for health check services."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blueprint.agents.config import Config
from blueprint.agents.models.config import AIConfig
from blueprint.agents.services.health_check_service import DaprPubSubHealthChecker, VLLMProviderHealthChecker


class TestVLLMProviderHealthChecker:
    """Test suite for VLLMProviderHealthChecker."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock(spec=Config)
        config.get.return_value = True  # health_check_ai_provider enabled by default
        return config

    @pytest.mark.asyncio
    async def test_health_check_disabled(self, mock_config):
        """Test health check when disabled."""
        mock_config.get.return_value = False
        checker = VLLMProviderHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "disabled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_no_provider_configured(self, mock_config):
        """Test health check when no provider is configured."""
        mock_config.get.return_value = True
        mock_config.get_ai_config.return_value = AIConfig()
        checker = VLLMProviderHealthChecker(mock_config, runtime_names=["default"])

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "healthy" in result.message.lower()

    @pytest.mark.asyncio
    async def test_vllm_health_check_success(self, mock_config):
        """Test successful vLLM health check."""
        mock_config.get_ai_config.return_value = AIConfig(
            provider="vllm",
            base_url="https://test-vllm.example.com/v1",
            api_key="test-key",
        )
        checker = VLLMProviderHealthChecker(mock_config, runtime_names=["default"])

        with patch("blueprint.agents.services.health.vllm_provider.httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            result = await checker.health_check()

            assert result.status == "healthy"
            assert "vLLM reachable" in result.message

    @pytest.mark.asyncio
    async def test_vllm_health_check_missing_base_url(self, mock_config):
        """Test vLLM health check with missing base URL."""
        mock_config.get_ai_config.return_value = AIConfig(
            provider="vllm",
            base_url=None,
            api_key="test-key",
        )
        checker = VLLMProviderHealthChecker(mock_config, runtime_names=["default"])

        result = await checker.health_check()

        assert result.status == "unhealthy"
        assert "base_url not configured" in result.message

    @pytest.mark.asyncio
    async def test_vllm_health_check_missing_api_key(self, mock_config):
        """Test vLLM health check with missing API key."""
        mock_config.get_ai_config.return_value = AIConfig(
            provider="vllm",
            base_url="https://test-vllm.example.com/v1",
            api_key=None,
        )
        checker = VLLMProviderHealthChecker(mock_config, runtime_names=["default"])

        result = await checker.health_check()

        assert result.status == "unhealthy"
        assert "api_key not configured" in result.message

    @pytest.mark.asyncio
    async def test_openai_health_check(self, mock_config):
        """Test OpenAI health check (always healthy if configured)."""
        mock_config.get_ai_config.return_value = AIConfig(provider="openai")
        checker = VLLMProviderHealthChecker(mock_config, runtime_names=["default"])

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "openai" in result.message.lower()

    @pytest.mark.asyncio
    async def test_runtime_specific_configuration_used(self, mock_config):
        """Ensure health checker uses provided runtime names when fetching config."""
        mock_config.get_ai_config.side_effect = lambda runtime_name="default": AIConfig(
            provider="openai" if runtime_name == "analysis" else None
        )
        checker = VLLMProviderHealthChecker(mock_config, runtime_names=["analysis", "default"])

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "analysis" in (result.message or "")


class TestDaprPubSubHealthChecker:
    """Test suite for DaprPubSubHealthChecker."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock(spec=Config)
        config.get.side_effect = lambda key, default=None: {
            "health_check_dapr": True,
            "dapr_http_port": 3500,
        }.get(key, default)
        return config

    @pytest.mark.asyncio
    async def test_health_check_disabled(self, mock_config):
        """Test health check when disabled."""
        mock_config.get.side_effect = lambda key, default=None: {
            "health_check_dapr": False,
            "dapr_http_port": 3500,
        }.get(key, default)
        checker = DaprPubSubHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "disabled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_dapr_sidecar_reachable(self, mock_config):
        """Test health check when Dapr sidecar is reachable."""
        checker = DaprPubSubHealthChecker(mock_config)

        with patch("blueprint.agents.services.health.dapr_pubsub.httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

            result = await checker.health_check()

            assert result.status == "healthy"
            assert "reachable" in result.message.lower()

    @pytest.mark.asyncio
    async def test_dapr_sidecar_unreachable(self, mock_config):
        """Test health check when Dapr sidecar is unreachable."""
        checker = DaprPubSubHealthChecker(mock_config)

        with patch("blueprint.agents.services.health.dapr_pubsub.httpx.AsyncClient") as mock_client:
            import httpx

            mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.RequestError("Connection refused")

            result = await checker.health_check()

            assert result.status == "unhealthy"
            assert "dapr sidecar unreachable" in result.message.lower()

    @pytest.mark.asyncio
    async def test_dapr_health_check_exception(self, mock_config):
        """Test health check when an unexpected exception occurs."""
        checker = DaprPubSubHealthChecker(mock_config)

        with patch("blueprint.agents.services.health.dapr_pubsub.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.side_effect = Exception("Unexpected error")

            result = await checker.health_check()

            assert result.status == "unhealthy"
            assert "error" in result.message.lower()
