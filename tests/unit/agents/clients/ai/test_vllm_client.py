"""Unit tests for VLLMClient."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.clients.ai.vllm_client import VLLMClient


class TestVLLMClientConnection:
    def test_is_connected_false_when_client_none(self, vllm_client: VLLMClient) -> None:
        assert vllm_client._is_connected() is False

    def test_is_connected_true_when_client_set(self, vllm_client: VLLMClient) -> None:
        vllm_client._client = MagicMock()
        assert vllm_client._is_connected() is True

    async def test_connect_is_noop(self, vllm_client: VLLMClient) -> None:
        """VLLM uses AsyncOpenAI which connects lazily — connect() must not set _client."""
        await vllm_client.connect()
        assert vllm_client._client is None

    async def test_close_calls_sdk_close_and_clears_client(self, vllm_client: VLLMClient) -> None:
        mock_sdk = MagicMock()
        mock_sdk.close = AsyncMock()
        vllm_client._client = mock_sdk

        await vllm_client.close()

        mock_sdk.close.assert_awaited_once()
        assert vllm_client._client is None

    async def test_close_is_safe_when_client_already_none(self, vllm_client: VLLMClient) -> None:
        await vllm_client.close()  # must not raise


class TestVLLMClientPubSub:
    async def test_subscribe_is_noop(self, vllm_client: VLLMClient) -> None:
        await vllm_client.subscribe({"topic": AsyncMock()})

    async def test_publish_is_noop(self, vllm_client: VLLMClient) -> None:
        await vllm_client.publish("topic", MagicMock())


class TestVLLMClientCreateModel:
    def test_create_model_returns_model_instance(self, vllm_client: VLLMClient, patch_vllm_deps: dict) -> None:
        model = vllm_client.create_model()
        assert model is patch_vllm_deps["model_cls"].return_value

    def test_create_model_passes_base_url_to_async_openai(self, vllm_client: VLLMClient, patch_vllm_deps: dict) -> None:
        vllm_client.create_model()
        _, kwargs = patch_vllm_deps["async_openai"].call_args
        assert kwargs.get("base_url") == "https://test.example.com/v1"

    def test_create_model_passes_api_key_to_async_openai(self, vllm_client: VLLMClient, patch_vllm_deps: dict) -> None:
        vllm_client.create_model()
        _, kwargs = patch_vllm_deps["async_openai"].call_args
        assert kwargs.get("api_key") == "test-api-key"

    def test_create_model_sets_client(self, vllm_client: VLLMClient, patch_vllm_deps: dict) -> None:  # noqa: ARG002
        vllm_client.create_model()
        assert vllm_client._client is not None

    def test_create_model_raises_on_second_call(self, vllm_client: VLLMClient, patch_vllm_deps: dict) -> None:  # noqa: ARG002
        vllm_client.create_model()
        with pytest.raises(RuntimeError, match="Model already created"):
            vllm_client.create_model()

    def test_create_model_uses_model_name_from_ai_config(self, vllm_client: VLLMClient, patch_vllm_deps: dict) -> None:
        vllm_client.create_model()
        _, kwargs = patch_vllm_deps["model_cls"].call_args
        assert kwargs.get("model_name") == "gpt-4o"


class TestVLLMClientHealthCheck:
    async def test_unhealthy_when_client_not_initialised(self, vllm_client: VLLMClient) -> None:
        result = await vllm_client.health_check()
        assert result.status == "unhealthy"

    async def test_healthy_when_models_list_returns_data(self, vllm_client: VLLMClient) -> None:
        mock_sdk = MagicMock()
        mock_sdk.models.list = AsyncMock(return_value=MagicMock(data=[MagicMock()]))
        vllm_client._client = mock_sdk

        result = await vllm_client.health_check()

        assert result.status == "healthy"

    async def test_unhealthy_when_models_list_empty(self, vllm_client: VLLMClient) -> None:
        mock_sdk = MagicMock()
        mock_sdk.models.list = AsyncMock(return_value=MagicMock(data=[]))
        vllm_client._client = mock_sdk

        result = await vllm_client.health_check()

        assert result.status == "unhealthy"

    async def test_unhealthy_on_connection_error(self, vllm_client: VLLMClient) -> None:
        mock_sdk = MagicMock()
        mock_sdk.models.list = AsyncMock(side_effect=Exception("timeout"))
        vllm_client._client = mock_sdk

        result = await vllm_client.health_check()

        assert result.status == "unhealthy"
        assert "timeout" in result.message
