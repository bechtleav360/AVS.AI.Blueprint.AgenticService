"""vLLM model provider implementation."""

import logging
from typing import Any, Dict

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from ...model_provider import ModelProviderStrategy

logger = logging.getLogger(__name__)


class VLLMModelProvider(ModelProviderStrategy):
    """Strategy for configuring vLLM models (OpenAI-compatible API)."""

    def get_provider_name(self) -> str:
        return "vllm"

    def create_model(self, ai_config: Dict[str, Any]) -> Model:
        """Create vLLM model configuration.

        Args:
            ai_config: Must contain 'base_url', 'api_key', 'model_name'.
                      Optional: 'timeout' (default: 60 seconds).

        Returns:
            Configured OpenAIChatModel with vLLM-specific profile.
        """
        # Enable debug logging for troubleshooting
        logging.getLogger("openai").setLevel(logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.INFO)
        logging.getLogger("pydantic_ai").setLevel(logging.DEBUG)

        # Set a reasonable timeout to prevent indefinite hangs
        timeout_seconds = ai_config.get("timeout", 60)

        client = AsyncOpenAI(
            max_retries=3,
            base_url=ai_config["base_url"],
            api_key=ai_config["api_key"],
            timeout=timeout_seconds,
        )

        provider = OpenAIProvider(openai_client=client)

        # vLLM uses <think>...</think> tags for reasoning in JSON schema mode
        # These tags must match the actual format returned by the model
        vllm_profile = ModelProfile(
            thinking_tags=("<think>", "</think>"),
            ignore_streamed_leading_whitespace=True,
            supports_json_schema_output=True,
            default_structured_output_mode="native",
        )

        model = OpenAIChatModel(
            provider=provider,
            model_name=ai_config["model_name"],
            profile=vllm_profile,
        )

        logger.info(
            "vLLM model configured: %s at %s (timeout: %ds, JSON schema enabled)",
            ai_config["model_name"],
            ai_config["base_url"],
            timeout_seconds,
        )

        return model
