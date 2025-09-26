"""Generic FastAPI application setup and configuration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import actuators, events, root

# Telemetry utilities
from .telemetry import setup_logging

from typing import List, Type

from .agent.base.decisions.event_handler import EventHandler
from .agent.base.runtime.base_agent import BaseAgent
from .config import Config
from .startup import StartupManager, startup_manager

# Dapr generic endpoints
try:
    from .api import dapr
except Exception:
    dapr = None
# from .config import get_observability_config, get_security_config, settings
# from .telemetry import instrument_fastapi, setup_logging, setup_telemetry

logger = logging.getLogger(__name__)


def create_lifespan_manager(
    config: Config,
    startup_manager_instance: "StartupManager",
):
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """
        Application lifespan manager for startup and shutdown events.
        """
        # Startup
        root_logger = logging.getLogger()
        if not root_logger.handlers:
            setup_logging(log_level="INFO", log_format="text")
        logger.info("Starting agent service")

        # Initialize components by injecting dependencies
        startup_manager_instance.initialize_components()

        logger.info("Service startup completed")

        yield

        # Shutdown
        logger.info("Shutting down agent service")
        logger.info("Service shutdown completed")

    return lifespan


class AppBuilder:
    """Builds the FastAPI application with a fluent interface."""

    def __init__(self, settings_files: list[str] = None, root_path: str = None):
        self.config = Config(settings_files=settings_files, root_path=root_path)
        self.startup_manager = StartupManager(self.config)
        self._custom_routers = []
        self._rest_api_class = None

    def with_handler(self, handler_class: Type[EventHandler]) -> "AppBuilder":
        """Register a handler class with the startup manager."""
        self.startup_manager.register_handler(handler_class)
        return self

    def with_agent_runtime(
        self, runtime_class: Type[BaseAgent], is_default: bool = False
    ) -> "AppBuilder":
        """Register an agent runtime class with the startup manager."""
        self.startup_manager.register_runtime(runtime_class, is_default)
        return self

    def with_rest_api(self, api_class: Type) -> "AppBuilder":
        """Register a custom REST API class."""
        self._rest_api_class = api_class
        return self

    def with_router(
        self, router, prefix: str = "", tags: list[str] = None
    ) -> "AppBuilder":
        """Add a custom router to the application."""
        self._custom_routers.append(
            {"router": router, "prefix": prefix, "tags": tags or []}
        )
        return self

    def build(self) -> FastAPI:
        """Create and configure the FastAPI application."""
        app = FastAPI(
            title=self.config.get("app_name"),
            description="Generic microservice blueprint for building intelligent agents",
            version="0.1.0",
            lifespan=create_lifespan_manager(
                config=self.config,
                startup_manager_instance=self.startup_manager,
            ),
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        # Add CORS middleware
        # FIXME: Replace with your security configuration
        # security_config = get_security_config()
        # app.add_middleware(
        #     CORSMiddleware,
        #     allow_origins=security_config["cors_origins"],
        #     allow_credentials=True,
        #     allow_methods=["GET", "POST", "PUT", "DELETE"],
        #     allow_headers=["*"],
        # )

        # Include base routers
        app.include_router(actuators.router, tags=["actuators"])
        app.include_router(events.router, prefix="/events", tags=["events"])
        app.include_router(root.router, tags=["root"])
        if dapr is not None:
            app.include_router(dapr.router, tags=["dapr"])

        # Include custom routers
        for custom_router in self._custom_routers:
            app.include_router(
                custom_router["router"],
                prefix=custom_router["prefix"],
                tags=custom_router["tags"],
            )

        # Include custom REST API
        if self._rest_api_class:
            rest_api = self._rest_api_class()
            app.include_router(
                rest_api.router, prefix="/api", tags=["rest"]
            )

        return app


def create_app(
    settings_files: list[str] = None,
    root_path: str = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    FIXME: Customize with your domain-specific configuration
    FIXME: Add your custom middleware, routers, and endpoints

    Returns:
        Configured FastAPI application
    """
    return AppBuilder(settings_files=settings_files, root_path=root_path).build()


# Create the application instance for default execution (e.g., uvicorn base.src.app:app)
app = create_app()
