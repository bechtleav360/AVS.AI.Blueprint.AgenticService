"""Generic FastAPI application setup and configuration."""

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

if TYPE_CHECKING:
    from .services.health_check_service import HealthCheckProvider

from .api import actuators, cache, root
from .base import EventHandler, RestApi
from .base.agent_runtime import AgentRuntime
from .base.business_service import BusinessService
from .config import Config, TelemetryManager
from .registry.component_registry import ComponentRegistry
from .services import EventPublishingService
from .services.cache_service import DiskCacheService
from .services.health import DaprPubSubHealthChecker, HealthCheckerRegistry, VLLMProviderHealthChecker
from .services.processing_service import ProcessingService

# Dapr generic endpoints
try:
    from .api import dapr
except ImportError:
    dapr = None

logger = logging.getLogger(__name__)


class AppBuilder:
    """Builds the FastAPI application with a fluent interface."""

    def __init__(
        self,
        config: Config,
    ):
        """Initialize the AppBuilder.

        Args:
            config: Pre-configured Config object.
        """

        self._config = config
        self._telemetry_manager = TelemetryManager(settings=self._config)
        self._component_registry = ComponentRegistry(settings=self._config)
        self._health_checker_registry = HealthCheckerRegistry()

    def build(self) -> FastAPI:
        """Create and configure the FastAPI application.

        This method:
        1. Creates the FastAPI app with lifespan management
        2. Includes all registered routers (root, REST API, Dapr, actuators)
        3. Configures health checks based on registered components
        """
        app = FastAPI(
            title=self._config.get("app_name", "bios-agent"),
            description=self._config.get("app_description", "Generic microservice blueprint for building intelligent agents"),
            version="0.1.0",
            lifespan=self._create_lifespan_manager(),
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        self._build_rest_endpoints(app)

        # Configure health checks based on registered components

        health_dependencies: dict[str, actuators.HealthCheckProvider] = {}

        if self._component_registry.has_handler() or self._config.get_event_publishing_config().topic_mapping:
            logger.info("Health checks for DAPR connection enabled")
            health_dependencies["dapr"] = DaprPubSubHealthChecker(self._config)

        if self._component_registry.has_agent():
            runtime_names = self._component_registry.list_agents()
            logger.info("Health checks for the following Agent runtimes enabled: %s", runtime_names)
            health_dependencies["ai_provider"] = VLLMProviderHealthChecker(
                self._config,
                runtime_names=runtime_names,
            )

        # Add custom health checkers registered via with_health_checker()
        custom_checkers = self._health_checker_registry.get_all()
        if custom_checkers:
            logger.info("Adding %d custom health checkers", len(custom_checkers))
            health_dependencies.update(custom_checkers)

        actuator_api = actuators.ActuatorApi(
            config=self._config,
            health_check_interval_seconds=self._config.get("health_check_interval_seconds", 30),
            **health_dependencies,
        )
        app.include_router(actuator_api.router, tags=["actuators"])

        # Store actuator_api for lifecycle management
        self._actuator_api = actuator_api

        return app

    def _build_rest_endpoints(self, app: FastAPI) -> None:
        """Build REST endpoints for the application."""

        # Include root endpoints
        root_api = root.RootApi(config=self._config)
        app.include_router(root_api.router, tags=["root"])

        # Include custom REST API if registered
        rest_apis = self._component_registry.get_rest_apis()
        for rest_api in rest_apis:
            if rest_api.router is None:
                rest_api.router = APIRouter()
                rest_api._register_routes()
            app.include_router(rest_api.router, prefix="/api", tags=["rest"])

        # Include Dapr endpoints if handlers are registered
        if dapr is not None and self._component_registry.get_handlers():
            dapr_api = dapr.DaprApi(component_registry=self._component_registry)
            app.include_router(dapr_api.router, tags=["dapr"])

        # Include cache management endpoints if cache is registered
        if self._component_registry.has_cache():
            cache_api = cache.CacheManagementApi(component_registry=self._component_registry)
            app.include_router(cache_api.router, prefix="/api", tags=["cache"])

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
            handler = handler()

        self._component_registry.register_handler(handler)
        return self

    def with_service(self, service_instance: BusinessService) -> "AppBuilder":
        """Register a business service class with the startup manager."""

        self._component_registry.register_service(service_instance)
        return self

    def with_agent(self, agent_instance: AgentRuntime) -> "AppBuilder":
        """Register an agent class with the startup manager."""

        self._component_registry.register_agent(agent_instance)
        return self

    def with_rest_api(self, api_instance: RestApi) -> "AppBuilder":
        """Register a custom REST API instance.

        The instance must be a subclass of RestApi. AppBuilder will wire the
        component registry and any registered agents into the instance.

        Args:
            api_instance: An instance of a RestApi subclass

        Raises:
            TypeError: If api_instance is not a RestApi subclass instance
        """

        self._component_registry.register_rest_api(api=api_instance)
        return self

    def with_cache(self, enabled: bool = True, enable_locking: bool = True) -> "AppBuilder":
        """Enable persistent caching using DiskCache.

        Args:
            enabled: Whether to enable caching (default: True)
            enable_locking: Enable file-based locking for multi-deployment safety (default: True).
                           Set to False only in single-deployment scenarios.

        Returns:
            Self for chaining
        """

        if enabled:
            cache_config = self._config.get_cache_config()
            cache_service = DiskCacheService(
                cache_dir=cache_config.cache_dir,
                size_limit=cache_config.size_limit,
                eviction_policy=cache_config.eviction_policy,
                enable_locking=enable_locking,
            )
            self._component_registry.register_cache(cache_service)
            logger.info(
                "Registered DiskCacheService with cache_dir=%s (locking=%s)",
                cache_config.cache_dir,
                enable_locking,
            )
        else:
            logger.info("Caching disabled")
        return self

    def with_health_checker(self, name: str, checker: "HealthCheckProvider") -> "AppBuilder":
        """Register a custom health checker.

        Health checkers are used to determine application readiness. They are executed
        periodically in the background and cached for performance.

        Args:
            name: Unique identifier for the health checker
            checker: Health checker instance implementing HealthCheckProvider

        Returns:
            Self for chaining

        Example:
            ```python
            builder = AppBuilder(config)
            builder.with_health_checker("database", DatabaseHealthChecker())
            builder.with_health_checker("cache", CacheHealthChecker())
            ```
        """
        self._health_checker_registry.register_or_replace(name, checker)
        logger.info("Registered custom health checker: %s", name)
        return self

    def _create_lifespan_manager(self):
        @asynccontextmanager
        async def lifespan(_app: FastAPI):
            """Application lifespan manager for startup and shutdown events."""

            logger.info("Initializing agent components")

            # Start background health check scheduler
            if hasattr(self, "_actuator_api"):
                try:
                    await self._actuator_api.start_health_checks()
                    logger.info("Health check cache scheduler started")
                except Exception as e:
                    logger.warning("Failed to start health check cache: %s", e)

            # Configure OpenTelemetry tracing
            try:
                self._telemetry_manager.configure_tracing()
            except Exception as e:
                logger.warning("Failed to configure OpenTelemetry: %s", e)

            # Initialize and register ProcessingService
            try:
                processing_service = ProcessingService(
                    settings=self._config,
                    component_registry=self._component_registry,
                )
                self._component_registry.register_processing_service(processing_service)
                logger.info("Successfully registered ProcessingService")
            except Exception as e:
                logger.error("Failed to register ProcessingService: %s", e, exc_info=True)
                raise

            # Initialize and register EventPublishingService
            try:
                event_publishing_service = EventPublishingService(config=self._config)
                self._component_registry.register_event_publishing_service(event_publishing_service)
                logger.info("Successfully registered EventPublishingService")
            except Exception as e:
                logger.error("Failed to register EventPublishingService: %s", e, exc_info=True)
                raise

            # Call on_startup on all registered components
            logger.info("Calling on_startup hooks for all components")

            # Handlers
            for handler in self._component_registry.get_handlers():
                try:
                    await handler.on_startup()
                    logger.info("Handler %s startup completed", handler.get_name())
                except Exception as e:
                    logger.error("Handler %s startup failed: %s", handler.get_name(), e, exc_info=True)
                    raise

            # Agents
            for agent_name in self._component_registry.list_agents():
                try:
                    agent = self._component_registry.get_agent(agent_name)
                    await agent.on_startup()
                    logger.info("Agent %s startup completed", agent_name)
                except Exception as e:
                    logger.error("Agent %s startup failed: %s", agent_name, e, exc_info=True)
                    raise

            # Business Services
            for service in self._component_registry.list_services():
                try:
                    await service.on_startup()
                    logger.info("Business service %s startup completed", service.get_name())
                except Exception as e:
                    logger.error("Business service %s startup failed: %s", service.get_name(), e, exc_info=True)
                    raise

            # REST APIs
            for rest_api in self._component_registry.get_rest_apis():
                try:
                    await rest_api.on_startup()
                    logger.info("REST API %s startup completed", rest_api.get_name())
                except Exception as e:
                    logger.error("REST API %s startup failed: %s", rest_api.get_name(), e, exc_info=True)
                    raise

            logger.info("Startup initialization completed")

            logger.info("Service startup completed")

            yield

            logger.info("Shutting down agent service")

            # Stop background health check scheduler
            if hasattr(self, "_actuator_api"):
                try:
                    await self._actuator_api.stop_health_checks()
                    logger.info("Health check cache scheduler stopped")
                except Exception as e:
                    logger.warning("Failed to stop health check cache: %s", e)

            # Call on_shutdown on all registered components (in reverse order)
            logger.info("Calling on_shutdown hooks for all components")

            # REST APIs
            for rest_api in self._component_registry.get_rest_apis():
                try:
                    await rest_api.on_shutdown()
                    logger.info("REST API %s shutdown completed", rest_api.get_name())
                except Exception as e:
                    logger.error("REST API %s shutdown failed: %s", rest_api.get_name(), e, exc_info=True)

            # Business Services
            for service in self._component_registry.list_services():
                try:
                    await service.on_shutdown()
                    logger.info("Business service %s shutdown completed", service.get_name())
                except Exception as e:
                    logger.error("Business service %s shutdown failed: %s", service.get_name(), e, exc_info=True)

            # Agents
            for agent_name in self._component_registry.list_agents():
                try:
                    agent = self._component_registry.get_agent(agent_name)
                    await agent.on_shutdown()
                    logger.info("Agent %s shutdown completed", agent_name)
                except Exception as e:
                    logger.error("Agent %s shutdown failed: %s", agent_name, e, exc_info=True)

            # Handlers
            for handler in self._component_registry.get_handlers():
                try:
                    await handler.on_shutdown()
                    logger.info("Handler %s shutdown completed", handler.get_name())
                except Exception as e:
                    logger.error("Handler %s shutdown failed: %s", handler.get_name(), e, exc_info=True)

            logger.info("Service shutdown completed")

        return lifespan
