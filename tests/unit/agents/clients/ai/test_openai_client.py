"""Unit tests for OpenAIClient."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.clients.ai.openai_client import OpenAIClient


class TestOpenAIClientConnection:
    def test_is_connected_false_when_client_none(self, openai_client: OpenAIClient) -> None:
        assert openai_client._is_connected() is False

    def test_is_connected_true_when_client_set(self, openai_client: OpenAIClient) -> None:
        openai_client._client = MagicMock()
        assert openai_client._is_connected() is True

    async def test_connect_is_noop(self, openai_client: OpenAIClient) -> None:
        """OpenAI connects lazily on first API call — connect() must not set _client."""
        await openai_client.connect()
        assert openai_client._client is None

    async def test_close_calls_sdk_close_and_clears_client(self, openai_client: OpenAIClient) -> None:
        mock_sdk = MagicMock()
        mock_sdk.close = AsyncMock()
        openai_client._client = mock_sdk

        await openai_client.close()

        mock_sdk.close.assert_awaited_once()
        assert openai_client._client is None

    async def test_close_is_safe_when_client_already_none(self, openai_client: OpenAIClient) -> None:
        await openai_client.close()  # must not raise


class TestOpenAIClientPubSub:
    async def test_subscribe_is_noop(self, openai_client: OpenAIClient) -> None:
        await openai_client.subscribe("topic", AsyncMock())  # must not raise

    async def test_publish_is_noop(self, openai_client: OpenAIClient) -> None:
        await openai_client.publish("topic", MagicMock())  # must not raise


class TestOpenAIClientCreateModel:
    def test_create_model_returns_model_instance(self, openai_client: OpenAIClient, patch_openai_deps: dict) -> None:
        model = openai_client.create_model()
        assert model is patch_openai_deps["model_cls"].return_value

    def test_create_model_builds_async_openai_with_api_key(self, openai_client: OpenAIClient, patch_openai_deps: dict) -> None:
        openai_client.create_model()
        patch_openai_deps["async_openai"].assert_called_once_with(max_retries=3, api_key="test-api-key")

    def test_create_model_sets_client(self, openai_client: OpenAIClient, patch_openai_deps: dict) -> None:  # noqa: ARG002
        openai_client.create_model()
        assert openai_client._client is not None

    def test_create_model_sets_model(self, openai_client: OpenAIClient, patch_openai_deps: dict) -> None:  # noqa: ARG002
        openai_client.create_model()
        assert openai_client._model is not None

    def test_create_model_raises_on_second_call(self, openai_client: OpenAIClient, patch_openai_deps: dict) -> None:  # noqa: ARG002
        openai_client.create_model()
        with pytest.raises(RuntimeError, match="Model already created"):
            openai_client.create_model()

    def test_create_model_uses_model_name_from_ai_config(self, openai_client: OpenAIClient, patch_openai_deps: dict) -> None:
        openai_client.create_model()
        _, kwargs = patch_openai_deps["model_cls"].call_args
        assert kwargs.get("model_name") == "gpt-4o"


class TestOpenAIClientHealthCheck:
    async def test_unhealthy_when_client_not_initialised(self, openai_client: OpenAIClient) -> None:
        result = await openai_client.health_check()
        assert result.status == "unhealthy"

    async def test_healthy_when_models_list_returns_data(self, openai_client: OpenAIClient) -> None:
        mock_sdk = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(), MagicMock()]
        mock_sdk.models.list = AsyncMock(return_value=mock_response)
        openai_client._client = mock_sdk

        result = await openai_client.health_check()

        assert result.status == "healthy"

    async def test_unhealthy_when_models_list_empty(self, openai_client: OpenAIClient) -> None:
        mock_sdk = MagicMock()
        mock_sdk.models.list = AsyncMock(return_value=MagicMock(data=[]))
        openai_client._client = mock_sdk

        result = await openai_client.health_check()

        assert result.status == "unhealthy"

    async def test_unhealthy_on_connection_error(self, openai_client: OpenAIClient) -> None:
        mock_sdk = MagicMock()
        mock_sdk.models.list = AsyncMock(side_effect=Exception("connection refused"))
        openai_client._client = mock_sdk

        result = await openai_client.health_check()

        assert result.status == "unhealthy"
        assert "connection refused" in result.message
