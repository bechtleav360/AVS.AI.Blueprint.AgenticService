"""Root endpoints providing service metadata."""

from fastapi import APIRouter


class RootApi:
    """OOP wrapper that exposes the root-related FastAPI router."""

    def __init__(self) -> None:
        self.router = APIRouter()
        self._register_routes()

    def _register_routes(self) -> None:
        @self.router.get(
            "/",
            tags=["root"],
            summary="Service metadata",
        )
        async def root() -> dict[str, str]:
            """Return basic information about the service and useful links."""
            return {
                "service": "agent-service",
                "version": "0.1.0",
                "description": "Generic microservice blueprint for building intelligent agents",
                "docs": "/docs",
                "health": "/actuators/health",
                # FIXME: Add your custom endpoints
                # "your-custom-endpoint": "/your-endpoint",
            }


# For backwards compatibility, keep the router instance
root_api = RootApi()
router = root_api.router
