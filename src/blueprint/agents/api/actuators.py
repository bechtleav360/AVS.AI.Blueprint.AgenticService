"""Actuator endpoints for the agent service (Spring Boot style)."""

import logging
import os
import platform
from importlib import metadata
from importlib.metadata import PackageNotFoundError
from typing import Any, Protocol

import httpx
from fastapi import APIRouter, HTTPException, status
from opentelemetry import trace

from ..config import Config
from ..models.api import ComponentHealth, LivenessResponse, ReadinessResponse
from ..models.status import BuildStatus, EnvironmentStatus, LLMStatus, ServiceInfo, VLLMInfo
from ..services.health.cache import HealthCheckCache

# FIXME: Import your dependencies here.
# from ..dependencies import get_your_agent, get_data_gateway
# from ..agent.runtime import AgentRuntime
# from ..services.data_gateway import DataGatewayClient

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class HealthCheckProvider(Protocol):
    """A protocol for components that can provide a health check."""

    async def health_check(self) -> ComponentHealth: ...


class ActuatorApi:
    """Encapsulates all actuator-related endpoints and logic."""

    def __init__(
        self,
        config: Config | None = None,
        health_check_interval_seconds: int = 30,
        **dependencies: HealthCheckProvider,
    ):
        self.router = APIRouter()
        self.config = config
        self.dependencies = dependencies
        self._health_cache = HealthCheckCache(check_interval_seconds=health_check_interval_seconds)
        self._health_cache.set_health_check_provider(dependencies)
        self._register_routes()

    def _register_routes(self) -> None:
        self.router.add_api_route(
            "/info",
            self.info,
            methods=["GET"],
            summary="Returns service information and dependencies.",
            tags=["Status"],
            response_model=ServiceInfo,
        )
        self.router.add_api_route(
            "/health/live",
            self.liveness_probe,
            methods=["GET"],
            summary="Performs a liveness probe of the service.",
            tags=["Health"],
            response_model=LivenessResponse,
            include_in_schema=False,
        )
        self.router.add_api_route(
            "/health/ready",
            self.readiness_probe,
            methods=["GET"],
            summary="Performs a readiness probe of the service.",
            tags=["Health"],
            response_model=ReadinessResponse,
            include_in_schema=False,
        )
        self.router.add_api_route(
            "/status/env",
            self.env_status,
            methods=["GET"],
            summary="Returns a snapshot of the current configuration.",
            tags=["Status"],
            response_model=EnvironmentStatus,
            include_in_schema=False,
        )
        self.router.add_api_route(
            "/status/llm",
            self.llm_status,
            methods=["GET"],
            summary="Returns AI provider configuration and diagnostics.",
            tags=["Status"],
            response_model=LLMStatus,
            include_in_schema=False,
        )
        self.router.add_api_route(
            "/status/build",
            self.build_status,
            methods=["GET"],
            summary="Returns build and runtime information.",
            tags=["Status"],
            response_model=BuildStatus,
            include_in_schema=False,
        )

    async def info(self) -> ServiceInfo:
        """Expose service information and dependencies."""
        config = self._ensure_config()

        dependencies = {dist.metadata["Name"]: dist.version for dist in metadata.distributions()}

        return ServiceInfo(
            name=config.get("app_name", "unknown"),
            version=config.get("app_version", "unknown"),
            dependencies=dependencies,
        )

    async def readiness_probe(self) -> ReadinessResponse:
        """Readiness probe to check if the service is ready to accept traffic.

        Returns cached health status from background checks to minimize resource consumption.
        """

        with tracer.start_as_current_span("api.readiness_probe") as span:
            try:
                if self.config and self.config.has_validation_errors():
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={
                            "status": "DOWN",
                            "errors": self.config.get_validation_errors(),
                        },
                    )

                # Return cached health status (updated periodically in background)
                response = await self._health_cache.get_health_status()

                span.set_attribute("health_status", response.status)
                span.set_attribute("cache_age_seconds", self._health_cache.get_cache_age_seconds())

                # Only log if health check fails
                if response.status != "UP":
                    logger.warning("Readiness probe failed: %s", response.components)

                return response

            except Exception as exc:  # pragma: no cover - defensive logging
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                logger.error("Readiness probe failed: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Readiness probe failed",
                ) from exc

    async def liveness_probe(self) -> LivenessResponse:
        """Liveness probe to indicate the service is running.

        Returns 200 OK even if configuration has validation errors, as restarting
        the pod won't fix configuration issues. Configuration errors should be
        caught by the readiness probe instead.
        """
        if self.config and self.config.has_validation_errors():
            logger.warning(
                "Liveness probe: configuration validation errors present: %s",
                self.config.get_validation_errors(),
            )
            # Still return UP - configuration errors don't require pod restart
            # The readiness probe will handle marking the service as not ready
            return LivenessResponse(status="UP")

        # Only log failures - successful liveness checks are not logged
        return LivenessResponse(status="UP")

    async def env_status(self) -> EnvironmentStatus:
        """Expose the current configuration state (with secrets masked)."""

        config = self._ensure_config()
        try:
            raw_config = config.settings.as_dict()
        except AttributeError:  # pragma: no cover - defensive
            raw_config = {}

        logger.info("Returning environment status for env %s", config.settings.current_env)

        return EnvironmentStatus(
            environment=config.settings.current_env,
            settings=self._sanitize_config(raw_config),
        )

    async def llm_status(self) -> LLMStatus:
        """Expose AI configuration and provider diagnostics."""

        config = self._ensure_config()
        ai_config_model = config.get_ai_config()
        ai_config_dict = (
            ai_config_model.model_dump()
            if hasattr(ai_config_model, "model_dump")
            else ai_config_model.dict() if hasattr(ai_config_model, "dict") else {}
        )
        ai_config = self._sanitize_config(ai_config_dict)

        provider = ai_config.get("provider")
        vllm_info_data: VLLMInfo | None = None

        if provider == "vllm":
            version = "unknown"
            try:
                version = metadata.version("vllm")
            except PackageNotFoundError:
                pass

            models: list[str] | None = None
            models_error: str | None = None

            base_url = ai_config_model.base_url
            api_key = ai_config_model.api_key

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
                        models = [item.get("id") for item in payload.get("data", [])]
                except httpx.RequestError as exc:
                    logger.warning("Failed to query vLLM models: %s", exc)
                    models_error = str(exc)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Unexpected vLLM models error: %s", exc)
                    models_error = str(exc)

            vllm_info_data = VLLMInfo(
                version=version,
                models=models,
                models_error=models_error,
            )

        return LLMStatus(config=ai_config, vllm=vllm_info_data)

    async def build_status(self) -> BuildStatus:
        """Expose build and runtime metadata."""

        config = self._ensure_config()

        logger.info("Returning build status for service %s", config.get("app_name"))

        return BuildStatus(
            app_name=config.get("app_name"),
            app_version=config.get("app_version", "unknown"),
            environment=config.settings.current_env,
            python_version=platform.python_version(),
            platform=platform.platform(),
            settings_files=list(config.settings.settings_files or []),
            build_commit=os.getenv("BUILD_COMMIT", "unknown"),
            build_timestamp=os.getenv("BUILD_TIMESTAMP", "unknown"),
        )

    def _sanitize_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Mask sensitive keys in configuration dictionaries."""

        sensitive = {"api_key", "secret", "token", "password"}
        sanitized: dict[str, Any] = {}
        for key, value in data.items():
            if key.lower() in sensitive:
                sanitized[key] = "***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_config(value)
            else:
                sanitized[key] = value
        return sanitized

    async def start_health_checks(self) -> None:
        """Start the background health check scheduler.

        This should be called during application startup.
        """
        await self._health_cache.start()

    async def stop_health_checks(self) -> None:
        """Stop the background health check scheduler.

        This should be called during application shutdown.
        """
        await self._health_cache.stop()

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

# The router is created and configured within the AppBuilder
