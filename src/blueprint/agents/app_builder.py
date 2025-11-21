"""Generic FastAPI application setup and configuration."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic_ai import Agent

from .api import actuators, rest, root
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

    def __init__(
        self,
        config: Config | None = None,
        settings_files: list[str] | None = None,
        root_path: str | None = None,
    ):
        """Initialize the AppBuilder.

        Args:
            config: Pre-configured Config object. If provided, settings_files and root_path are ignored.
            settings_files: List of settings file paths (used only if config is None).
            root_path: Root path for configuration (used only if config is None).
        """
        # Step 1: Initialize logging with default INFO level
        self.logging_manager = LoggingManager()
        self.logging_manager.configure(
            log_level="INFO",
            log_format="text",
            suppress_noisy_loggers=True,
        )

        # Step 2: Initialize or use provided configuration
        if config is not None:
            self.config = config
        else:
            # Backward compatibility: create config from settings_files and root_path
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

        self._rest_api: object | None = None
        self._handlers: list[EventHandler] = []

        # Single unified registry for all components
        self._component_registry = ComponentRegistry(settings=self.config)

    def with_handler(self, handler: type[EventHandler] | EventHandler) -> "AppBuilder":
        """Register a handler class or instance with the startup manager.

        Handler classes are instantiated immediately when registered.
        Handler instances are stored as-is.

        Args:
            handler: Either a handler class (type[EventHandler]) or an instance (EventHandler)

        Returns:
            Self for chaining

        Raises:
            TypeError: If handler is neither a class nor an instance of EventHandler
        """
        if isinstance(handler, type):
            # It's a class - instantiate it immediately
            if not issubclass(handler, EventHandler):
                raise TypeError(f"Handler class must be a subclass of EventHandler, " f"got {handler.__name__}")
            handler_instance = handler()
            self._handlers.append(handler_instance)
        elif isinstance(handler, EventHandler):
            # It's an instance - store as-is
            self._handlers.append(handler)
        else:
            raise TypeError(f"Handler must be either a class or instance of EventHandler, " f"got {type(handler).__name__}")
        return self

    def with_agent(self, agent: Agent) -> "AppBuilder":
        """Register an agent class with the startup manager."""
        self._component_registry.get_agent_registry().register(name=agent.name, agent=agent)
        return self

    def with_rest_api(self, api_instance: object) -> "AppBuilder":
        """Register a custom REST API instance.

        The instance must be a subclass of RestApi. AppBuilder will wire the
        component registry and any registered agents into the instance.

        Args:
            api_instance: An instance of a RestApi subclass

        Raises:
            TypeError: If api_instance is not a RestApi subclass instance
        """
        # Validate that the instance is a RestApi subclass
        if not isinstance(api_instance, rest.RestApi):
            raise TypeError(f"REST API instance must be a subclass of RestApi, got {type(api_instance).__name__}")

        # Wire the component registry into the API instance
        api_instance._component_registry = self._component_registry

        # Wire registered agents into the API instance
        agent_registry = self._component_registry.get_agent_registry()
        agent_names = agent_registry.list_agents()
        if agent_names:
            # If there's a single agent, wire it directly
            if len(agent_names) == 1:
                agent = agent_registry.get(agent_names[0])
                api_instance.with_agent(agent)
            else:
                # If multiple agents, wire them as a dict
                agents_dict = {name: agent_registry.get(name) for name in agent_names}
                api_instance.with_agent(agents_dict)

        # Initialize the router if not already done
        if api_instance.router is None:
            api_instance.router = rest.APIRouter()
            api_instance._register_routes()

        self._rest_api = api_instance
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

        # Configure and register handlers
        try:
            # Configure all handlers with config
            for handler in self._handlers:
                handler.with_config(self.config)

            self._component_registry.register_handlers(self._handlers)
            logger.info(
                "Successfully registered %d handlers",
                len(self._handlers),
            )
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
            title=self.config.get("app_name", "bios-agent"),
            description=self.config.get("app_description", "Generic microservice blueprint for building intelligent agents"),
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

        # Include root endpoints
        root_api = root.RootApi(config=self.config)
        app.include_router(root_api.router, tags=["root"])

        # Include custom REST API
        if self._rest_api:
            app.include_router(self._rest_api.router, prefix="/api", tags=["rest"])

        # Include Dapr endpoints only if handlers are registered
        if dapr is not None and self._handlers:
            dapr_api = dapr.DaprApi(component_registry=self._component_registry)
            app.include_router(dapr_api.router, tags=["dapr"])

        # Instantiate and include actuator routes with dependencies
        agent_registry = self._component_registry.get_agent_registry()
        registered_agents = agent_registry.list_agents()
        event_pub_config = self.config.get_event_publishing_config()

        health_dependencies: dict[str, actuators.HealthCheckProvider] = {}

        if self._handlers or event_pub_config.topic_mapping:
            health_dependencies["rabbitmq"] = DaprPubSubHealthChecker(self.config)

        if registered_agents:
            health_dependencies["ai_provider"] = AIProviderHealthChecker(self.config)

        actuator_api = actuators.ActuatorApi(config=self.config, **health_dependencies)
        app.include_router(actuator_api.router, tags=["actuators"])

        return app
