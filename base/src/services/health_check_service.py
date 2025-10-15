"""Health-related service helpers for the agent application."""

import logging

import httpx

from ..config import Config
from ..models.api import ComponentHealth

logger = logging.getLogger(__name__)


class AIProviderHealthChecker:
    """Health check provider for the configured AI model."""

    def __init__(self, config: Config):
        self.config = config

    async def health_check(self) -> ComponentHealth:
        ai_config = self.config.get_ai_config()
        provider = ai_config.get("provider")

        if provider == "vllm":
            base_url = ai_config.get("base_url")
            if not base_url:
                return ComponentHealth(
                    status="unhealthy",
                    message="vLLM base_url not configured",
                )

            api_key = ai_config.get("api_key")
            if not api_key:
                return ComponentHealth(
                    status="unhealthy",
                    message="vLLM api_key not configured",
                )

            try:
                headers = {"Authorization": f"Bearer {api_key}"}
                async with httpx.AsyncClient() as client:
                    # vLLM servers have a /health endpoint at the root, not under /v1
                    # Remove /v1 suffix if present
                    health_url = base_url.rstrip('/').removesuffix('/v1') + '/health'
                    response = await client.get(health_url, headers=headers)
                    response.raise_for_status()
                    return ComponentHealth(
                        status="healthy",
                        message=f"vLLM reachable at {base_url}",
                    )
            except httpx.RequestError as e:
                logger.warning("vLLM health check failed: %s", e)
                return ComponentHealth(
                    status="unhealthy",
                    message=f"vLLM check failed: {e}",
                )

        elif provider == "openai":
            # No external dependency to check, assume healthy if configured
            logger.info("AI provider is 'openai', skipping health check.")
            return ComponentHealth(
                status="healthy",
                message="openai provider selected; health assumed",
            )

        return ComponentHealth(
            status="unknown",
            message=f"Unsupported provider: {provider}",
        )
