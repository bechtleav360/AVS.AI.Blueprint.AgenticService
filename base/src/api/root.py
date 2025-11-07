"""Root endpoints providing service metadata."""

from importlib import metadata as importlib_metadata
from typing import Any, Dict

from fastapi import APIRouter


class RootApi:
    """OOP wrapper that exposes the root-related FastAPI router."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self._project_metadata = self._load_project_metadata()
        self._register_routes()

    def _register_routes(self) -> None:
        @self.router.get(
            "/",
            tags=["root"],
            summary="Service metadata",
        )
        async def root() -> dict[str, Any]:
            """Return basic information about the service and useful links."""
            return {
                "service": self._project_metadata["name"],
                "version": self._project_metadata["version"],
                "description": self._project_metadata["description"],
                "docs": "/docs",
                "probes": {"liveness": "/health/live", "readiness": "/health/ready"},
                # FIXME: Add your custom endpoints
                # "your-custom-endpoint": "/your-endpoint",
            }

    def _load_project_metadata(self) -> Dict[str, str]:
        """Load distribution metadata exposed from pyproject configuration."""
        distribution_name = "avs-blueprint-agents"
        defaults: Dict[str, str] = {
            "name": "agent-service",
            "version": "0.0.0",
            "description": "Generic microservice blueprint for building intelligent agents",
        }

        try:
            metadata = importlib_metadata.metadata(distribution_name)
        except importlib_metadata.PackageNotFoundError:
            return defaults

        return {
            "name": metadata.get("Name", defaults["name"]),
            "version": metadata.get("Version", defaults["version"]),
            "description": metadata.get("Summary", defaults["description"]),
        }


# For backwards compatibility, keep the router instance
root_api = RootApi()
router = root_api.router
