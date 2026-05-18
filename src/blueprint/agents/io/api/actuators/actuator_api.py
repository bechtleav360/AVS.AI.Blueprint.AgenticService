"""Actuator endpoints for the agent service (Spring Boot style)."""

import logging
import os
import platform
from importlib import metadata
from importlib.metadata import PackageNotFoundError
from typing import Any

import httpx
from fastapi import HTTPException, status
from opentelemetry import trace

from ....component.component import traced
from ....config import Config
from ....models.api import LivenessResponse, ReadinessResponse
from ....models.status import BuildStatus, EnvironmentStatus, LLMStatus, ServiceInfo, VLLMInfo
from .health.health_cache import HealthCheckCache
from ..rest_api_base import RestApiBase
from .health.health_base import HealthCheckerBase

logger = logging.getLogger(__name__)


class ActuatorApi(RestApiBase):
    """Encapsulates all actuator-related endpoints and logic."""

    def __init__(self) -> None:
        super().__init__(should_register=False)
        self._health_cache: HealthCheckCache | None = None
        self._pending_providers: dict[str, HealthCheckerBase] = {}

    def add_health_providers(self, providers: dict[str, HealthCheckerBase]) -> None:
        """Register health check providers.

        Args:
            providers: Mapping of component name to HealthCheckerBase instance
        """
        if self._health_cache is not None:
            self._health_cache.set_health_check_provider(providers)
        else:
            self._pending_providers = providers

    async def on_startup(self) -> None:
        """Start the health check cache."""
        self._health_cache = HealthCheckCache(check_interval_seconds=self.config.get("health_check_interval_seconds", 30))
        if hasattr(self, "_pending_providers") and self._pending_providers:
            self._health_cache.set_health_check_provider(self._pending_providers)
        await self._health_cache.start()

    async def on_shutdown(self) -> None:
        """Stop the health check cache."""
        if self._health_cache is not None:
            await self._health_cache.stop()

    @RestApiBase.get("/info", response_model=ServiceInfo, tags=["Status"], summary="Returns service information and dependencies.")
    async def info(self) -> ServiceInfo:
        """Expose service information and dependencies."""
        config = self._ensure_config()

        dependencies = {dist.metadata["Name"]: dist.version for dist in metadata.distributions()}

        return ServiceInfo(
            name=config.get("app_name", "unknown"),
            version=config.get("app_version", "unknown"),
            dependencies=dependencies,
        )

    @RestApiBase.get(
        "/health/ready", response_model=ReadinessResponse, tags=["Health"], summary="Performs a readiness probe of the service."
    )
    @traced()
    async def readiness_probe(self) -> ReadinessResponse:
        """Readiness probe to check if the service is ready to accept traffic.

        Returns cached health status from background checks to minimize resource consumption.
        """
        try:
            if self.config and self.config.has_validation_errors():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "status": "DOWN",
                        "errors": self.config.get_validation_errors(),
                    },
                )

            if self._health_cache is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Health check cache not initialized",
                )

            # Return cached health status (updated periodically in background)
            response = await self._health_cache.get_health_status()

            span = trace.get_current_span()
            span.set_attribute("health_status", response.status)
            span.set_attribute("cache_age_seconds", self._health_cache.get_cache_age_seconds())

            # Translate aggregated DOWN status into HTTP 503 so a default K8s
            # httpGet readiness probe (which only inspects the status code) sees
            # the failure and removes the pod from service rotation.
            if response.status != "UP":
                logger.warning("Readiness probe failed: %s", response.components)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=response.model_dump(),
                )

            return response

        except HTTPException:
            # Propagate explicit 503s (validation errors, aggregated DOWN) with
            # their detailed payload — don't let the generic catch below
            # overwrite them with a generic message.
            raise
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Readiness probe failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Readiness probe failed",
            ) from exc

    @RestApiBase.get("/health/live", response_model=LivenessResponse, tags=["Health"], summary="Performs a liveness probe of the service.")
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

    @RestApiBase.get(
        "/status/env", response_model=EnvironmentStatus, tags=["Status"], summary="Returns a snapshot of the current configuration."
    )
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

    @RestApiBase.get("/status/llm", response_model=LLMStatus, tags=["Status"], summary="Returns AI provider configuration and diagnostics.")
    async def llm_status(self) -> LLMStatus:
        """Expose AI configuration and provider diagnostics."""

        config = self._ensure_config()
        ai_config_model = config.get_ai_config()
        ai_config_dict = (
            ai_config_model.model_dump()
            if hasattr(ai_config_model, "model_dump")
            else ai_config_model.dict()
            if hasattr(ai_config_model, "dict")
            else {}
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

    @RestApiBase.get("/status/build", response_model=BuildStatus, tags=["Status"], summary="Returns build and runtime information.")
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

    def _ensure_config(self) -> Config:
        if not self.config:
            logger.error("Configuration not available for status endpoint")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Configuration not available",
            )
        return self.config
