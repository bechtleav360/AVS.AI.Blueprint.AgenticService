"""Actuator endpoints for the agent service (Spring Boot style)."""

import logging
import os
import platform
from typing import Any, Dict, Optional, Protocol

import httpx
from fastapi import APIRouter, HTTPException, status
from importlib import metadata
from importlib.metadata import PackageNotFoundError
from opentelemetry import trace

from ..config import Config
from ..models.api import ComponentHealth, LivenessResponse, ReadinessResponse

# FIXME: Import your dependencies here.
# from ..dependencies import get_your_agent, get_data_gateway
# from ..agent.runtime import AgentRuntime
# from ..services.data_gateway import DataGatewayClient

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class HealthCheckProvider(Protocol):
    """A protocol for components that can provide a health check."""

    async def health_check(self) -> ComponentHealth: ...


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
                    # vLLM servers have a /health endpoint
                    response = await client.get(
                        f"{base_url.rstrip('/')}/health", headers=headers
                    )
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


class ActuatorApi:
    """Encapsulates all actuator-related endpoints and logic."""

    def __init__(
        self, config: Optional[Config] = None, **dependencies: HealthCheckProvider
    ):
        self.router = APIRouter()
        self.config = config
        self.dependencies = dependencies
        self._register_routes()

    def _register_routes(self):
        self.router.add_api_route(
            "/health/live",
            self.liveness_probe,
            methods=["GET"],
            summary="Performs a liveness probe of the service.",
            tags=["Health"],
            response_model=LivenessResponse,
        )
        self.router.add_api_route(
            "/health/ready",
            self.readiness_probe,
            methods=["GET"],
            summary="Performs a readiness probe of the service.",
            tags=["Health"],
            response_model=ReadinessResponse,
        )
        self.router.add_api_route(
            "/status/env",
            self.env_status,
            methods=["GET"],
            summary="Returns a snapshot of the current configuration.",
            tags=["Status"],
        )
        self.router.add_api_route(
            "/status/llm",
            self.llm_status,
            methods=["GET"],
            summary="Returns AI provider configuration and diagnostics.",
            tags=["Status"],
        )
        self.router.add_api_route(
            "/status/build",
            self.build_status,
            methods=["GET"],
            summary="Returns build and runtime information.",
            tags=["Status"],
        )

    async def readiness_probe(self) -> ReadinessResponse:
        """Readiness probe to check if the service is ready to accept traffic."""
        with tracer.start_as_current_span("api.readiness_probe") as span:
            try:
                components: Dict[str, ComponentHealth] = {}
                for name, dependency in self.dependencies.items():
                    components[name] = await dependency.health_check()

                all_healthy = all(
                    component.status == "healthy" for component in components.values()
                )

                overall_status = "UP" if all_healthy else "DOWN"

                span.set_attribute("health_status", overall_status)

                return ReadinessResponse(status=overall_status, components=components)

            except Exception as exc:  # pragma: no cover - defensive logging
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                logger.error("Health check failed: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Health check failed",
                )

    async def liveness_probe(self) -> LivenessResponse:
        """Liveness probe to indicate the service is running."""
        if self.config and self.config.has_validation_errors():
            logger.error(
                "Configuration validation errors detected: %s",
                self.config.get_validation_errors(),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "status": "DOWN",
                    "errors": self.config.get_validation_errors(),
                },
            )

        return LivenessResponse(status="UP")

    async def env_status(self) -> Dict[str, Any]:
        """Expose the current configuration state (with secrets masked)."""

        config = self._ensure_config()
        try:
            raw_config = config.settings.as_dict()
        except AttributeError:  # pragma: no cover - defensive
            raw_config = {}

        logger.info(
            "Returning environment status for env %s", config.settings.current_env
        )

        return {
            "environment": config.settings.current_env,
            "settings": self._sanitize_config(raw_config),
        }

    async def llm_status(self) -> Dict[str, Any]:
        """Expose AI configuration and provider diagnostics."""

        config = self._ensure_config()
        ai_config = self._sanitize_config(config.get_ai_config())
        status_payload: Dict[str, Any] = {"config": ai_config}

        provider = ai_config.get("provider")

        if provider == "vllm":
            vllm_info: Dict[str, Any] = {}
            try:
                vllm_info["version"] = metadata.version("vllm")
            except PackageNotFoundError:
                vllm_info["version"] = "unknown"

            base_url = config.get_ai_config().get("base_url")
            api_key = config.get_ai_config().get("api_key")

            if base_url:
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.get(
                            f"{base_url.rstrip('/')}/models",
                            headers=headers or None,
                        )
                        response.raise_for_status()
                        payload = response.json()
                        vllm_info["models"] = [
                            item.get("id") for item in payload.get("data", [])
                        ]
                except httpx.RequestError as exc:
                    logger.warning("Failed to query vLLM models: %s", exc)
                    vllm_info["models_error"] = str(exc)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Unexpected vLLM models error: %s", exc)
                    vllm_info["models_error"] = str(exc)

            status_payload["vllm"] = vllm_info

        return status_payload

    async def build_status(self) -> Dict[str, Any]:
        """Expose build and runtime metadata."""

        config = self._ensure_config()

        logger.info("Returning build status for service %s", config.get("app_name"))

        return {
            "app_name": config.get("app_name"),
            "app_version": config.get("app_version", "unknown"),
            "environment": config.settings.current_env,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "settings_files": list(config.settings.settings_files or []),
            "build_commit": os.getenv("BUILD_COMMIT", "unknown"),
            "build_timestamp": os.getenv("BUILD_TIMESTAMP", "unknown"),
        }

    def _sanitize_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive keys in configuration dictionaries."""

        sensitive = {"api_key", "secret", "token", "password"}
        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            if key.lower() in sensitive:
                sanitized[key] = "***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_config(value)
            else:
                sanitized[key] = value
        return sanitized

    def _ensure_config(self) -> Config:
        if not self.config:
            logger.error("Configuration not available for status endpoint")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Configuration not available",
            )
        return self.config


# Example of how to instantiate and use the ActuatorApi
# dependencies = {
#     "your_agent": get_your_agent(),
#     "data_gateway": get_data_gateway(),
# }
# actuator_api = ActuatorApi(**dependencies)
# router = actuator_api.router

# The router is now created and configured within the AppBuilder
router = APIRouter()
