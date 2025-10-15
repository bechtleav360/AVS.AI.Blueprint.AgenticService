"""OpenAI model provider implementation."""

import logging
from typing import Any, Dict

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ...model_provider import ModelProviderStrategy

logger = logging.getLogger(__name__)


class OpenAIModelProvider(ModelProviderStrategy):
    """Strategy for configuring OpenAI models."""

    def get_provider_name(self) -> str:
        return "openai"

    def create_model(self, ai_config: Dict[str, Any]) -> Model:
        """Create OpenAI model configuration.

        Args:
            ai_config: Must contain 'api_key' and 'model_name'.

        Returns:
            Configured OpenAIChatModel.
        """
        client = AsyncOpenAI(
            max_retries=3,
            api_key=ai_config["api_key"],
        )
        provider = OpenAIProvider(openai_client=client)

        logger.info(
            "OpenAI model configured: %s",
            ai_config["model_name"]
        )

        return OpenAIChatModel(
            provider=provider,
            model_name=ai_config["model_name"],
        )
