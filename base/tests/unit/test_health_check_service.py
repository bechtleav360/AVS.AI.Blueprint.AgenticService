"""Unit tests for health check services."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base.src.config import Config
from base.src.services.health_check_service import (AIProviderHealthChecker,
                                                    DaprPubSubHealthChecker)


class TestAIProviderHealthChecker:
    """Test suite for AIProviderHealthChecker."""

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
        checker = AIProviderHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "disabled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_no_provider_configured(self, mock_config):
        """Test health check when no provider is configured."""
        mock_config.get.return_value = True
        mock_config.get_ai_config.return_value = {"provider": None}
        checker = AIProviderHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "no ai provider configured" in result.message.lower()

    @pytest.mark.asyncio
    async def test_vllm_health_check_success(self, mock_config):
        """Test successful vLLM health check."""
        mock_config.get_ai_config.return_value = {
            "provider": "vllm",
            "base_url": "https://test-vllm.example.com/v1",
            "api_key": "test-key",
        }
        checker = AIProviderHealthChecker(mock_config)

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = AsyncMock()
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get.return_value = (
                mock_response
            )

            result = await checker.health_check()

            assert result.status == "healthy"
            assert "vLLM reachable" in result.message

    @pytest.mark.asyncio
    async def test_vllm_health_check_missing_base_url(self, mock_config):
        """Test vLLM health check with missing base URL."""
        mock_config.get_ai_config.return_value = {
            "provider": "vllm",
            "base_url": None,
            "api_key": "test-key",
        }
        checker = AIProviderHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "unhealthy"
        assert "base_url not configured" in result.message

    @pytest.mark.asyncio
    async def test_vllm_health_check_missing_api_key(self, mock_config):
        """Test vLLM health check with missing API key."""
        mock_config.get_ai_config.return_value = {
            "provider": "vllm",
            "base_url": "https://test-vllm.example.com/v1",
            "api_key": None,
        }
        checker = AIProviderHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "unhealthy"
        assert "api_key not configured" in result.message

    @pytest.mark.asyncio
    async def test_openai_health_check(self, mock_config):
        """Test OpenAI health check (always healthy if configured)."""
        mock_config.get_ai_config.return_value = {
            "provider": "openai",
        }
        checker = AIProviderHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "openai" in result.message.lower()


class TestDaprPubSubHealthChecker:
    """Test suite for DaprPubSubHealthChecker."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = MagicMock(spec=Config)
        config.get.side_effect = lambda key, default=None: {
            "health_check_rabbitmq": True,
            "dapr_pubsub_name": "rabbitmq-pubsub",
            "dapr_http_port": 3500,
            "rabbitmq_host": "localhost:5672",
        }.get(key, default)
        config.get_event_publishing_config.return_value = {
            "default_pubsub_name": "rabbitmq-pubsub",
            "topic_mapping": {"agent.output.test": "test-topic"},
        }
        return config

    @pytest.mark.asyncio
    async def test_health_check_disabled(self, mock_config):
        """Test health check when disabled."""
        mock_config.get.side_effect = lambda key, default=None: {
            "health_check_rabbitmq": False,
            "dapr_pubsub_name": "rabbitmq-pubsub",
            "dapr_http_port": 3500,
            "rabbitmq_host": "localhost:5672",
        }.get(key, default)
        checker = DaprPubSubHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "disabled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_not_configured(self, mock_config):
        """Test health check when RabbitMQ is not configured."""
        mock_config.get.side_effect = lambda key, default=None: {
            "health_check_rabbitmq": True,
            "dapr_pubsub_name": "rabbitmq-pubsub",
            "dapr_http_port": 3500,
            "rabbitmq_host": None,
        }.get(key, default)
        checker = DaprPubSubHealthChecker(mock_config)

        result = await checker.health_check()

        assert result.status == "healthy"
        assert "not configured" in result.message.lower()

    @pytest.mark.asyncio
    async def test_dapr_sidecar_unreachable(self, mock_config):
        """Test health check when Dapr sidecar is unreachable."""
        checker = DaprPubSubHealthChecker(mock_config)

        with patch("httpx.AsyncClient") as mock_client:
            import httpx

            mock_client.return_value.__aenter__.return_value.get.side_effect = (
                httpx.RequestError("Connection refused")
            )

            result = await checker.health_check()

            assert result.status == "unhealthy"
            assert "dapr sidecar unreachable" in result.message.lower()

    @pytest.mark.asyncio
    async def test_pubsub_component_not_loaded(self, mock_config):
        """Test health check when pubsub component is not loaded."""
        checker = DaprPubSubHealthChecker(mock_config)

        with patch("httpx.AsyncClient") as mock_client:
            # Mock Dapr health check success
            mock_health_response = MagicMock()
            mock_health_response.raise_for_status = MagicMock()

            # Mock metadata response with no pubsub component
            mock_metadata_response = MagicMock()
            mock_metadata_response.raise_for_status = MagicMock()
            mock_metadata_response.json = MagicMock(return_value={"components": []})

            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.get = AsyncMock(
                side_effect=[mock_health_response, mock_metadata_response]
            )

            result = await checker.health_check()

            assert result.status == "unhealthy"
            assert "not loaded" in result.message.lower()

    @pytest.mark.asyncio
    async def test_successful_health_check(self, mock_config):
        """Test successful health check with all components working."""
        checker = DaprPubSubHealthChecker(mock_config)

        with patch("httpx.AsyncClient") as mock_client:
            # Mock Dapr health check success
            mock_health_response = MagicMock()
            mock_health_response.raise_for_status = MagicMock()

            # Mock metadata response with pubsub component
            mock_metadata_response = MagicMock()
            mock_metadata_response.raise_for_status = MagicMock()
            mock_metadata_response.json = MagicMock(
                return_value={
                    "components": [
                        {"name": "rabbitmq-pubsub", "type": "pubsub.rabbitmq"}
                    ]
                }
            )

            # Mock publish success
            mock_publish_response = MagicMock()
            mock_publish_response.raise_for_status = MagicMock()

            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.get = AsyncMock(
                side_effect=[mock_health_response, mock_metadata_response]
            )
            mock_client_instance.post = AsyncMock(return_value=mock_publish_response)

            result = await checker.health_check()

            assert result.status == "healthy"
            assert "reachable" in result.message.lower()
            assert "rabbitmq-pubsub" in result.message

    @pytest.mark.asyncio
    async def test_publish_failure(self, mock_config):
        """Test health check when publish fails."""
        checker = DaprPubSubHealthChecker(mock_config)

        with patch("httpx.AsyncClient") as mock_client:
            import httpx

            # Mock Dapr health check success
            mock_health_response = MagicMock()
            mock_health_response.raise_for_status = MagicMock()

            # Mock metadata response with pubsub component
            mock_metadata_response = MagicMock()
            mock_metadata_response.raise_for_status = MagicMock()
            mock_metadata_response.json = MagicMock(
                return_value={
                    "components": [
                        {"name": "rabbitmq-pubsub", "type": "pubsub.rabbitmq"}
                    ]
                }
            )

            mock_client_instance = mock_client.return_value.__aenter__.return_value
            mock_client_instance.get = AsyncMock(
                side_effect=[mock_health_response, mock_metadata_response]
            )
            mock_client_instance.post = AsyncMock(
                side_effect=httpx.RequestError("Publish failed")
            )

            result = await checker.health_check()

            assert result.status == "unhealthy"
            assert "publish failed" in result.message.lower()
