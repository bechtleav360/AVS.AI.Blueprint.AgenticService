"""Root endpoints providing service metadata."""

from typing import Any

from fastapi import APIRouter

from ..config import Config


class RootApi:
    """OOP wrapper that exposes the root-related FastAPI router."""

    def __init__(self, config: Config | None = None) -> None:
        """Initialize RootApi with optional config.

        Args:
            config: Configuration object to read service metadata from settings
        """
        self.router = APIRouter()
        self.config = config
        self._register_routes()

    def _register_routes(self) -> None:
        @self.router.get(
            "/",
            tags=["root"],
            summary="Service metadata",
        )
        async def root() -> dict[str, Any]:
            """Return basic information about the service and useful links."""
            # Try to get metadata from config/settings first
            service_name = None
            service_version = None
            service_description = None

            if self.config:
                service_name = self.config.get("app_name")
                service_version = self.config.get("app_version")
                service_description = self.config.get("app_description")

            # Fall back to defaults if not in config
            if not service_name:
                service_name = "agent-service"
            if not service_version:
                service_version = "0.0.0"
            if not service_description:
                service_description = "Generic microservice blueprint for building intelligent agents"

            return {
                "service": service_name,
                "version": service_version,
                "description": service_description,
                "documentation": {
                    "swagger_ui": "/docs",
                    "redoc": "/redoc",
                    "openapi_json": "/openapi.json",
                },
                "probes": {"liveness": "/health/live", "readiness": "/health/ready"},
                "actuators": {
                    "info": "/info",
                    "environment": "/status/env",
                    "llm": "/status/llm",
                    "build": "/status/build",
                },
            }


# For backwards compatibility, keep the router instance
root_api = RootApi()
router = root_api.router
