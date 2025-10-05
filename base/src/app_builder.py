"""Generic FastAPI application setup and configuration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from typing import Type

from .registry.handler_registry import HandlerRegistry
from .registry.runtime_registry import RuntimeRegistry
from .registry.service_registry import ServiceRegistry

from .api import actuators, root
from .api.events import EventApi

# Telemetry utilities
from .telemetry import TelemetryManager


from .agent import EventHandler, BaseAgent
from .config import Config

# Dapr generic endpoints
try:
    from .api import dapr
except Exception:
    dapr = None
# from .config import get_observability_config, get_security_config, settings
# from .telemetry import instrument_fastapi, setup_logging, setup_telemetry

logger = logging.getLogger(__name__)


class AppBuilder:
    """Builds the FastAPI application with a fluent interface."""

    def __init__(self, settings_files: list[str] = None, root_path: str = None):
        # Setup basic logging before config initialization
        root_logger = logging.getLogger()
        if not root_logger.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            )

        self.config = Config(settings_files=settings_files, root_path=root_path)
        self._custom_routers = []
        self._rest_api_class = None
        self._handler_classes: list[Type[EventHandler]] = []
        self._runtime_classes: list[dict] = []

        self._service_registry = ServiceRegistry(settings=self.config)
        self._handler_registry = HandlerRegistry(
            settings=self.config, service_registry=self._service_registry
        )
        self._runtime_registry = RuntimeRegistry(
            settings=self.config, service_registry=self._service_registry
        )
        self._service_registry.configure(
            handler_registry=self._handler_registry,
            runtime_registry=self._runtime_registry,
        )

    def with_handler(self, handler_class: Type[EventHandler]) -> "AppBuilder":
        """Register a handler class with the startup manager."""
        self._handler_classes.append(handler_class)
        return self

    def with_agent_runtime(
        self, runtime_class: Type[BaseAgent], is_default: bool = False
    ) -> "AppBuilder":
        """Register an agent runtime class with the startup manager."""
        self._runtime_classes.append(
            {"runtime_class": runtime_class, "is_default": is_default}
        )
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

    def _create_lifespan_manager(self):
        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            """Application lifespan manager for startup and shutdown events."""

            logger.info("Starting agent service")

            self._initialize_components()

            logger.info("Service startup completed")

            yield

            logger.info("Shutting down agent service")
            logger.info("Service shutdown completed")

        return lifespan

    def _initialize_components(self) -> None:
        """Initialize and register all agent components."""
        logger.info("Initializing agent components")

        # Initialize and register handlers
        try:
            handlers = [handler_class() for handler_class in self._handler_classes]
            self._handler_registry.register_handlers(handlers)
            logger.info("Successfully registered %d handlers", len(handlers))
        except Exception as e:
            logger.error("Failed to register handlers: %s", e, exc_info=True)

        # Initialize and register runtimes
        try:
            for runtime_info in self._runtime_classes:
                runtime_class = runtime_info["runtime_class"]
                is_default = runtime_info["is_default"]
                runtime_instance = runtime_class(self.config)
                self._runtime_registry.register_runtime(
                    runtime_class.__name__, runtime_instance, is_default=is_default
                )
            logger.info(
                "Successfully registered %d runtimes", len(self._runtime_classes)
            )
        except Exception as e:
            logger.error("Failed to register runtimes: %s", e, exc_info=True)

        logger.info("Startup initialization completed")

    def build(self) -> FastAPI:
        """Create and configure the FastAPI application."""

        app = FastAPI(
            title=self.config.get("app_name"),
            description="Generic microservice blueprint for building intelligent agents",
            version="0.1.0",
            lifespan=self._create_lifespan_manager(),
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

        # Instantiate and include actuator routes with dependencies
        health_dependencies = {
            "ai_provider": actuators.AIProviderHealthChecker(self.config)
        }
        actuator_api = actuators.ActuatorApi(config=self.config, **health_dependencies)
        app.include_router(actuator_api.router, tags=["actuators"])

        # Include other base routers
        event_api = EventApi(service_registry=self._service_registry)
        app.include_router(event_api.router, prefix="/events", tags=["events"])
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
            rest_api = self._rest_api_class(registry=self._service_registry)
            app.include_router(rest_api.router, prefix="/api", tags=["rest"])

        return app
