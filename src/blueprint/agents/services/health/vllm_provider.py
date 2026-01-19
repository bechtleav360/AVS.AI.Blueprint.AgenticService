"""Health check provider for AI models."""

from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx

from ...config import Config
from ...models.api import ComponentHealth
from ...models.config import AIConfig

logger = logging.getLogger(__name__)


class VLLMProviderHealthChecker:
    """Health check provider for the configured AI model."""

    def __init__(self, config: Config, runtime_names: Iterable[str] | None = None) -> None:
        self.config: Config = config
        self.enabled: bool = config.get("health_check_ai_provider", True)
        self._runtime_names = self._normalize_runtime_names(runtime_names)

    @staticmethod
    def _normalize_runtime_names(runtime_names: Iterable[str] | None) -> list[str]:
        names: list[str] = []
        if runtime_names:
            for name in runtime_names:
                normalized = (name or "default").strip() or "default"
                if normalized not in names:
                    names.append(normalized)
        if not names:
            return ["default"]
        return names

    async def health_check(self) -> ComponentHealth:
        """Check AI provider health if enabled."""
        if not self.enabled:
            logger.debug("AI provider health check is disabled")
            return ComponentHealth(
                status="healthy",
                message="AI provider health check disabled",
            )

        unhealthy_messages: list[str] = []
        healthy_runtimes: list[str] = []

        for runtime_name in self._runtime_names:
            ai_config: AIConfig = self.config.get_ai_config(runtime_name)
            provider: str | None = ai_config.provider

            if not provider:
                logger.warning("AI provider health check failed for runtime '%s': No provider configured", runtime_name)
                continue

            if provider == "vllm":
                runtime_result = await self._check_vllm_runtime(runtime_name, ai_config)
                if runtime_result.status == "healthy":
                    healthy_runtimes.append(runtime_result.message or f"[{runtime_name}] vLLM healthy")
                else:
                    unhealthy_messages.append(runtime_result.message or f"[{runtime_name}] vLLM check failed")
                    logger.warning(
                        "AI provider health check failed for runtime '%s': %s",
                        runtime_name,
                        runtime_result.message,
                    )
            elif provider == "openai":
                healthy_runtimes.append(f"[{runtime_name}] OpenAI configured")
            else:
                message = f"[{runtime_name}] Unsupported provider: {provider}"
                unhealthy_messages.append(message)
                logger.warning(message)

        if unhealthy_messages:
            return ComponentHealth(
                status="unhealthy",
                message="; ".join(unhealthy_messages),
            )

        return ComponentHealth(
            status="healthy",
            message="AI runtimes healthy: " + ", ".join(healthy_runtimes),
        )

    async def _check_vllm_runtime(self, runtime_name: str, ai_config: AIConfig) -> ComponentHealth:
        base_url: str | None = ai_config.base_url
        if not base_url:
            return ComponentHealth(
                status="unhealthy",
                message=f"[{runtime_name}] vLLM base_url not configured",
            )

        api_key: str | None = ai_config.api_key
        if not api_key:
            return ComponentHealth(
                status="unhealthy",
                message=f"[{runtime_name}] vLLM api_key not configured",
            )

        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient() as client:
                # vLLM servers have a /health endpoint at the root, not under /v1
                # Remove /v1 suffix if present
                health_url = base_url.rstrip("/").removesuffix("/v1") + "/health"
                response = await client.get(health_url, headers=headers)
                response.raise_for_status()
                # Only log successful health checks at debug level
                logger.debug("vLLM health check passed for runtime '%s': %s", runtime_name, base_url)
                return ComponentHealth(
                    status="healthy",
                    message=f"[{runtime_name}] vLLM reachable at {base_url}",
                )
        except httpx.RequestError as e:
            # Log failures at warning level
            logger.warning("vLLM health check failed for runtime '%s': %s", runtime_name, e)
            return ComponentHealth(
                status="unhealthy",
                message=f"[{runtime_name}] vLLM check failed: {e}",
            )
