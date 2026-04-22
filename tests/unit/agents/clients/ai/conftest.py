"""Shared fixtures for AI client unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blueprint.agents.clients.ai.openai_client import OpenAIClient
from blueprint.agents.clients.ai.vllm_client import VLLMClient
from blueprint.agents.models.config import AIConfig


@pytest.fixture
def mock_ai_config() -> AIConfig:
    """Return a realistic AIConfig used by both OpenAI and VLLM client tests."""
    return AIConfig(
        provider="openai",
        model_name="gpt-4o",
        api_key="test-api-key",
        base_url="https://test.example.com/v1",
        max_tokens=4096,
        temperature=0.7,
        model_settings={},
    )


@pytest.fixture
def openai_client(mock_config: MagicMock, mock_ai_config: AIConfig) -> OpenAIClient:
    """Return an OpenAIClient with mock config pre-configured."""
    mock_config.get_ai_config.return_value = mock_ai_config
    return OpenAIClient("test_runtime")


@pytest.fixture
def vllm_client(mock_config: MagicMock, mock_ai_config: AIConfig) -> VLLMClient:
    """Return a VLLMClient with mock config pre-configured."""
    mock_config.get_ai_config.return_value = mock_ai_config
    return VLLMClient("test_runtime")


@pytest.fixture
def patch_openai_deps():
    """Patch all OpenAI SDK constructors used in OpenAIClient.create_model()."""
    with (
        patch("blueprint.agents.clients.ai.openai_client.AsyncOpenAI") as mock_async_openai,
        patch("blueprint.agents.clients.ai.openai_client.OpenAIProvider") as mock_provider,
        patch("blueprint.agents.clients.ai.openai_client.OpenAIResponsesModel") as mock_model_cls,
        patch("blueprint.agents.clients.ai.openai_client.OpenAIResponsesModelSettings") as mock_settings_cls,
    ):
        mock_async_openai.return_value = MagicMock()
        mock_async_openai.return_value.close = AsyncMock()
        yield {
            "async_openai": mock_async_openai,
            "provider": mock_provider,
            "model_cls": mock_model_cls,
            "settings_cls": mock_settings_cls,
        }


@pytest.fixture
def patch_vllm_deps():
    """Patch all OpenAI SDK constructors used in VLLMClient.create_model()."""
    with (
        patch("blueprint.agents.clients.ai.vllm_client.AsyncOpenAI") as mock_async_openai,
        patch("blueprint.agents.clients.ai.vllm_client.OpenAIProvider") as mock_provider,
        patch("blueprint.agents.clients.ai.vllm_client.OpenAIChatModel") as mock_model_cls,
    ):
        mock_async_openai.return_value = MagicMock()
        mock_async_openai.return_value.close = AsyncMock()
        yield {
            "async_openai": mock_async_openai,
            "provider": mock_provider,
            "model_cls": mock_model_cls,
        }
