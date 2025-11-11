"""Generic FastAPI application setup and configuration."""

import logging
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic_ai import Agent

from .api import actuators, root
from .config import Config, ConfigError, LoggingManager, TelemetryManager
from .handler import EventHandler
from .registry.component_registry import ComponentRegistry
from .services import AIProviderHealthChecker, DaprPubSubHealthChecker, EventPublishingService
from .services.processing_service import ProcessingService

# Dapr generic endpoints
try:
    from .api import dapr
except Exception:
    dapr = None

logger = logging.getLogger(__name__)


class AppBuilder:
    """Builds the FastAPI application with a fluent interface."""

    def __init__(self, settings_files: list[str] | None = None, root_path: str | None = None):
        # Step 1: Initialize logging with default INFO level
        self.logging_manager = LoggingManager()
        self.logging_manager.configure(
            log_level="INFO",
            log_format="text",
            suppress_noisy_loggers=True,
        )

        # Step 2: Initialize configuration (may log warnings/errors if required params missing)
        try:
            self.config = Config(settings_files=settings_files, root_path=root_path)
        except ConfigError as exc:
            logger.error("Configuration error: %s", exc)
            sys.exit(1)

        # Step 3: Set logging level from configuration
        config_log_level = self.config.get("log_level", "INFO")
        self.logging_manager.set_level(config_log_level)

        # Step 4: Initialize telemetry (will be configured during startup)
        self.telemetry_manager = TelemetryManager(settings=self.config)

        self._custom_routers: list[dict[str, Any]] = []
        self._rest_api_class: type | None = None
        self._handler_classes: list[type[EventHandler]] = []

        # Single unified registry for all components
        self._component_registry = ComponentRegistry(settings=self.config)

    def with_handler(self, handler_class: type[EventHandler]) -> "AppBuilder":
        """Register a handler class with the startup manager."""
        self._handler_classes.append(handler_class)
        return self

    def with_agent(self, agent: Agent) -> "AppBuilder":
        """Register an agent class with the startup manager."""
        self._component_registry.get_agent_registry().register(name=agent.name, agent=agent)
        return self

    def with_rest_api(self, api_class: type) -> "AppBuilder":
        """Register a custom REST API class."""
        self._rest_api_class = api_class
        return self

    def with_router(self, router: Any, prefix: str = "", tags: list[str] | None = None) -> "AppBuilder":
        """Add a custom router to the application."""
        self._custom_routers.append({"router": router, "prefix": prefix, "tags": tags or []})
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

        # Configure OpenTelemetry tracing (telemetry manager already initialized in __init__)
        try:
            self.telemetry_manager.configure_tracing()
        except Exception as e:
            logger.warning("Failed to configure OpenTelemetry: %s", e)

        # Initialize and register handlers
        try:
            handlers: list[EventHandler] = [handler_class().with_config(self.config) for handler_class in self._handler_classes]
            self._component_registry.register_handlers(handlers)
            logger.info("Successfully registered %d handlers", len(handlers))
        except Exception as e:
            logger.error("Failed to register handlers: %s", e, exc_info=True)

        # Initialize and register ProcessingService
        try:
            processing_service = ProcessingService(
                settings=self.config,
                component_registry=self._component_registry,
            )
            self._component_registry.register_processing_service(processing_service)
            logger.info("Successfully registered ProcessingService")
        except Exception as e:
            logger.error("Failed to register ProcessingService: %s", e, exc_info=True)

        # Initialize and register EventPublishingService
        try:
            event_publishing_service = EventPublishingService(config=self.config)
            self._component_registry.register_event_publishing_service(event_publishing_service)
            logger.info("Successfully registered EventPublishingService")
        except Exception as e:
            logger.error("Failed to register EventPublishingService: %s", e, exc_info=True)

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
            "ai_provider": AIProviderHealthChecker(self.config),
            "rabbitmq": DaprPubSubHealthChecker(self.config),
        }
        actuator_api = actuators.ActuatorApi(config=self.config, **health_dependencies)
        app.include_router(actuator_api.router, tags=["actuators"])

        # Include other base routers
        app.include_router(root.router, tags=["root"])
        if dapr is not None:
            dapr_api = dapr.DaprApi(component_registry=self._component_registry)
            app.include_router(dapr_api.router, tags=["dapr"])

        # Include custom routers
        for custom_router in self._custom_routers:
            app.include_router(
                custom_router["router"],
                prefix=custom_router["prefix"],
                tags=custom_router["tags"],
            )

        # Include custom REST API
        if self._rest_api_class:
            rest_api = self._rest_api_class(registry=self._component_registry)
            app.include_router(rest_api.router, prefix="/api", tags=["rest"])

        return app
