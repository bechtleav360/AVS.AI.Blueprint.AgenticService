"""OpenAI model provider implementation."""

import logging
from typing import TYPE_CHECKING, Any, Dict, Union

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ...model_provider import ModelProviderStrategy

if TYPE_CHECKING:
    from ...models.config import AIConfig

logger = logging.getLogger(__name__)


class OpenAIModelProvider(ModelProviderStrategy):
    """Strategy for configuring OpenAI models."""

    def get_provider_name(self) -> str:
        return "openai"

    def create_model(self, ai_config: Union[Dict[str, Any], "AIConfig"]) -> Model:
        """Create OpenAI model configuration.

        Args:
            ai_config: Configuration object (dict or AIConfig) with 'api_key' and 'model_name'.

        Returns:
            Configured OpenAIChatModel.
        """
        # Handle both dict and Pydantic model
        if isinstance(ai_config, dict):
            api_key = ai_config["api_key"]
            model_name = ai_config["model_name"]
        else:
            api_key = ai_config.api_key
            model_name = ai_config.model_name

        client = AsyncOpenAI(
            max_retries=3,
            api_key=api_key,
        )
        provider = OpenAIProvider(openai_client=client)

        logger.info("OpenAI model configured: %s", model_name)

        return OpenAIChatModel(
            provider=provider,
            model_name=model_name,
        )
