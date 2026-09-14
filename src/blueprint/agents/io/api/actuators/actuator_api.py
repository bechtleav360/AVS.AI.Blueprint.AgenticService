"""Actuator endpoints for the agent service (Spring Boot style)."""

import logging
import os
import platform
from importlib import metadata
from importlib.metadata import PackageNotFoundError
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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

SECRET_KEY_MARKERS = ("key", "secret", "token", "password", "passwd", "pwd", "credential", "auth", "private", "salt")
"""Substrings that make a configuration key too dangerous to return over HTTP.

Matched as substrings, not whole keys, because the keys that actually carry secrets in this
framework are compound: ``openai_api_key``, ``nats_password``, ``azure_client_secret``. A
whole-key match sees none of them.

Deliberately over-broad. A key such as ``api_key_header`` or ``cache_key_prefix`` is masked
although it holds nothing sensitive, which costs a line of diagnostics; the opposite error
publishes a credential to anything that can reach the actuator.
"""

CONFIG_MASK = "***"
"""What a masked value is replaced with. Presence stays visible; the value does not."""


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
        """Expose the current configuration state (with secrets masked).

        In a grouped process the settings tree holds every co-hosted agent's configuration, and
        flattened into one dictionary it says nothing about which agent a key belongs to. So the
        response separates them: ``settings`` is what the root namespace resolves, and
        ``namespaces`` carries one entry per agent -- each one flattened the way that agent reads
        it, root keys included, so a value inherited from the root is visible where it is used
        rather than only where it is declared.

        ``envvar_prefix`` is reported because an override that is ignored and an override that is
        misspelled look identical from outside the process.
        """

        config = self._ensure_config()

        # One read of the raw tree per request, not one per field. Config.settings is audited
        # (it logs every raw-tree access), so re-reading it for current_env and again for the
        # log line turned a single operator request into three records.
        settings = config.settings
        environment = getattr(settings, "current_env", "unknown")

        namespaces: dict[str, dict[str, Any]] = {}
        if config.is_view:
            # An agent-scoped actuator reports its own scope and nothing else: resolving for
            # another namespace is refused on a view (C6), and listing neighbours is the thing
            # C6 exists to prevent.
            raw_config = self._as_dict(settings)
        else:
            raw_config = config.resolved_settings()
            namespaces = {name: self._sanitize_config(config.resolved_settings(name)) for name in config.namespaces}

        logger.info(
            "Returning environment status for env %s (%d namespace(s), overrides read from %s)",
            environment,
            len(namespaces),
            f"{config.envvar_prefix}_*" if config.envvar_prefix else "the whole process environment, unprefixed",
        )

        return EnvironmentStatus(
            environment=environment,
            envvar_prefix=config.envvar_prefix if isinstance(config.envvar_prefix, str) else None,
            settings=self._sanitize_config(raw_config),
            namespaces=namespaces,
        )

    @staticmethod
    def _as_dict(settings: Any) -> dict[str, Any]:
        """Return the settings tree as a plain dictionary, or ``{}`` if it cannot be read."""
        try:
            return dict(settings.as_dict())
        except AttributeError:  # pragma: no cover - defensive
            return {}

    @RestApiBase.get("/status/llm", response_model=LLMStatus, tags=["Status"], summary="Returns AI provider configuration and diagnostics.")
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

    @RestApiBase.get("/status/build", response_model=BuildStatus, tags=["Status"], summary="Returns build and runtime information.")
    async def build_status(self) -> BuildStatus:
        """Expose build and runtime metadata."""

        config = self._ensure_config()

        logger.info("Returning build status for service %s", config.get("app_name"))

        # One read of the audited raw tree, as in env_status: current_env and settings_files
        # are two fields of the same object, not two reasons to reach past the scoped getters.
        settings = config.settings

        return BuildStatus(
            app_name=config.get("app_name"),
            app_version=config.get("app_version", "unknown"),
            environment=getattr(settings, "current_env", "unknown"),
            python_version=platform.python_version(),
            platform=platform.platform(),
            settings_files=list(getattr(settings, "settings_files", None) or []),
            build_commit=os.getenv("BUILD_COMMIT", "unknown"),
            build_timestamp=os.getenv("BUILD_TIMESTAMP", "unknown"),
        )

    def _sanitize_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return ``data`` with everything that could be a credential masked.

        This endpoint publishes configuration over HTTP, so the bias is towards masking: a
        false positive loses a line of diagnostics, a false negative publishes a secret.

        Three rules, in order:

        1. A key containing any of :data:`SECRET_KEY_MARKERS` is masked, whatever its value.
        2. A string value that parses as a URL carrying userinfo has that userinfo stripped,
           whatever its key -- ``redis://user:pass@host`` under a key called ``nats_url``
           names nothing sensitive but carries a password.
        3. Booleans pass through even under a matching key. A flag cannot carry a credential,
           and ``auth_enabled`` is exactly the kind of value someone reads this endpoint for.

        Dictionaries and lists are walked, because a masked key is worthless if the same
        secret sits one level down in a list of provider entries.
        """
        return {key: self._sanitize_value(key, value) for key, value in data.items()}

    def _sanitize_value(self, key: str, value: Any) -> Any:
        """Apply the rules in :meth:`_sanitize_config` to one key/value pair."""
        if isinstance(value, dict):
            return self._sanitize_config(value)
        if isinstance(value, (list, tuple)):
            return [self._sanitize_value(key, item) for item in value]
        if isinstance(value, bool):
            return value
        if self._is_secret_key(key):
            return CONFIG_MASK
        if isinstance(value, str):
            return self._strip_url_userinfo(value)
        return value

    @staticmethod
    def _is_secret_key(key: str) -> bool:
        """Return whether a configuration key may carry a credential."""
        lowered = key.lower()
        return any(marker in lowered for marker in SECRET_KEY_MARKERS)

    @staticmethod
    def _strip_url_userinfo(value: str) -> str:
        """Return ``value`` with ``user:password@`` removed if it is a URL that carries it.

        Unlike ``_sanitize_redis_url``, which is handed a value already known to be a Redis
        URL and returns a placeholder when it cannot parse it, this is handed *every* string
        in the configuration. So anything that does not parse as a URL with userinfo is
        returned unchanged -- most configuration values are not URLs, and replacing them with
        a placeholder would empty the endpoint.
        """
        if "@" not in value or "//" not in value:
            return value
        try:
            parts = urlsplit(value)
        except ValueError:
            return CONFIG_MASK
        if not parts.username and not parts.password:
            return value
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        netloc = f"{host}:{parts.port}" if parts.port is not None else host
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    def _ensure_config(self) -> Config:
        if not self.config:
            logger.error("Configuration not available for status endpoint")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Configuration not available",
            )
        return self.config
