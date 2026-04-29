"""Generic FastAPI application setup and configuration."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, TypeVar

from fastapi import FastAPI

if TYPE_CHECKING:
    from .io.api.actuators.health import HealthCheckerBase

from .component.component import Component
from .component.registry import Registry
from .agent.agent_runtime import AgentRuntime
from .handler.event_handler_base import EventHandlerBase
from .io.api.rest_api_base import RestApiBase
from .io.api.scheduling.scheduler import SchedulerBase
from .io.api.actuators.actuator_api import ActuatorApi
from .io.api.actuators.health import ClientHealthChecker
from .io.api.eventing.dapr import DaprEventing
from .io.api.eventing.nats import NatsEventing
from .io.api.utilities.root import RootApi
from .io.api.utilities.cache import CacheManagementApi
from .clients.io.dapr_client import DaprClient
from .clients.io.nats_client import NATSClient
from .services.service_base import ServiceBase
from .services.eventing.event_processing_service import EventProcessingService
from .services.eventing.event_publishing_service import EventPublishingService
from .services.infrastructure.cache_service import DiskCacheService
from .config import Config, TelemetryManager

HandlerT = TypeVar("HandlerT", bound=EventHandlerBase)
ServiceT = TypeVar("ServiceT", bound=ServiceBase)
AgentT = TypeVar("AgentT", bound=AgentRuntime)
SchedulerT = TypeVar("SchedulerT", bound=SchedulerBase)
RestApiT = TypeVar("RestApiT", bound=RestApiBase)

logger = logging.getLogger(__name__)


class AppBuilder:
    """Builds the FastAPI application with a fluent interface.

    Usage::

        app = (
            AppBuilder(config)
            .with_handler(MyHandler)
            .with_agent(my_agent)
            .with_cache()
            .build()
        )

    Components are instantiated via with_*() calls (accepting either a class or
    an instance) and auto-register themselves in the shared registry. AppBuilder
    injects the Config in build() before the lifespan starts.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._telemetry_manager = TelemetryManager()
        self._eventing_component: DaprEventing | NatsEventing | None = None
        self._actuator_api: ActuatorApi | None = None

    # ------------------------------------------------------------------
    # Fluent registration API
    # ------------------------------------------------------------------

    def with_handler(self, handler: type[HandlerT] | HandlerT, *, name: str | None = None, **kwargs: Any) -> "AppBuilder":
        """Register an event handler class or instance."""
        if isinstance(handler, type):
            if not issubclass(handler, EventHandlerBase):
                raise TypeError(f"Expected EventHandlerBase subclass, got {handler.__name__}")
            instance = handler(**kwargs)
        else:
            instance = handler
        if name is not None:
            instance.name = name
        return self

    def with_service(self, service: type[ServiceT] | ServiceT, *, name: str | None = None, **kwargs: Any) -> "AppBuilder":
        """Register a business service class or instance."""
        instance = service(**kwargs) if isinstance(service, type) else service
        if name is not None:
            instance.name = name
        return self

    def with_agent(self, agent: type[AgentT] | AgentT, *, name: str | None = None, **kwargs: Any) -> "AppBuilder":
        """Register an agent runtime class or instance."""
        instance = agent(**kwargs) if isinstance(agent, type) else agent
        if name is not None:
            instance.name = name
        return self

    def with_scheduler(self, scheduler: type[SchedulerT] | SchedulerT, *, name: str | None = None, **kwargs: Any) -> "AppBuilder":
        """Register a scheduler class or instance."""
        instance = scheduler(**kwargs) if isinstance(scheduler, type) else scheduler
        if name is not None:
            instance.name = name
        return self

    def with_rest_api(self, api: type[RestApiT] | RestApiT, *, name: str | None = None, **kwargs: Any) -> "AppBuilder":
        """Register a custom REST API class or instance."""
        instance = api(**kwargs) if isinstance(api, type) else api
        if name is not None:
            instance.name = name
        return self

    def with_cache(self, enabled: bool = True, enable_locking: bool = True) -> "AppBuilder":
        """Enable persistent caching using DiskCache.

        Args:
            enabled: Whether to enable caching (default: True)
            enable_locking: Enable file-based locking for multi-deployment safety (default: True).
        """
        if enabled:
            cache_config = self._config.get_cache_config()
            cache_service = DiskCacheService(
                cache_dir=cache_config.cache_dir,
                size_limit=cache_config.size_limit,
                eviction_policy=cache_config.eviction_policy,
                enable_locking=enable_locking,
            )
            Component.shared_registry.cache_service = cache_service  # type: ignore[union-attr]
            logger.info(
                "Registered DiskCacheService with cache_dir=%s (locking=%s)",
                cache_config.cache_dir,
                enable_locking,
            )
        else:
            logger.info("Caching disabled")
        return self

    def with_health_checker(self, name: str, checker: "HealthCheckerBase") -> "AppBuilder":
        """Register a custom health checker on the ActuatorApi.

        Must be called after build() has created the ActuatorApi, or the checker
        will be added during build() automatically. Prefer calling before build().
        """
        if self._actuator_api is not None:
            self._actuator_api.add_health_providers({name: checker})
        else:
            # Stored temporarily; flushed into ActuatorApi during build()
            if not hasattr(self, "_custom_health_checkers"):
                self._custom_health_checkers: dict[str, HealthCheckerBase] = {}
            self._custom_health_checkers[name] = checker
        return self

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> FastAPI:
        """Create and configure the FastAPI application.

        This method:
        1. Injects Config into the Component class hierarchy
        2. Creates IO clients and internal services based on configuration
        3. Wires health checkers from all registered clients
        4. Returns a FastAPI app with lifespan management
        """
        # 1. Inject config — enforced once-only by metaclass guard
        Component.configure(self._config)

        registry: Registry = Component.shared_registry  # type: ignore[assignment]

        # 2. Create IO transport client and eventing endpoint if handlers registered
        if registry.get_event_handler():
            event_bus_type = self._config.get("event_bus", "").lower()
            if event_bus_type == "dapr":
                DaprClient()  # auto-registers
                self._eventing_component = DaprEventing()
            elif event_bus_type == "nats":
                NATSClient()  # auto-registers
                self._eventing_component = NatsEventing()
            else:
                logger.warning(
                    "Event handlers are registered but no valid event_bus configured ('dapr' or 'nats'). Event handling will be disabled."
                )

        # 3. Create internal services (auto-register)
        EventProcessingService()
        if registry.get_io_clients():
            EventPublishingService()

        # 4. Create ActuatorApi and wire health checkers from all registered clients
        self._actuator_api = ActuatorApi()
        health_providers: dict[str, HealthCheckerBase] = {client.name: ClientHealthChecker([client]) for client in registry.get_clients()}
        if hasattr(self, "_custom_health_checkers"):
            health_providers.update(self._custom_health_checkers)
        if health_providers:
            self._actuator_api.add_health_providers(health_providers)

        # 5. Build FastAPI app
        app = FastAPI(
            title=self._config.get("app_name", "bios-agent"),
            description=self._config.get(
                "app_description",
                "Generic microservice blueprint for building intelligent agents",
            ),
            version="0.1.0",
            lifespan=self._create_lifespan_manager(),
            docs_url="/docs",
            redoc_url="/redoc",
            openapi_url="/openapi.json",
        )

        self._build_rest_endpoints(app, registry)
        return app

    def _build_rest_endpoints(self, app: FastAPI, registry: Registry) -> None:
        """Include all routers into the FastAPI app."""
        app.include_router(RootApi(app=app).router, tags=["root"])

        for rest_api in registry.get_rest_apis():
            app.include_router(rest_api.router, prefix="/api", tags=["rest"])

        if self._eventing_component is not None:
            app.include_router(self._eventing_component.router)

        if registry.has_cache():
            app.include_router(CacheManagementApi().router, prefix="/api", tags=["cache"])

        if self._actuator_api is not None:
            app.include_router(self._actuator_api.router, tags=["actuators"])

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    def _create_lifespan_manager(self) -> Any:
        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
            """Application lifespan manager for startup and shutdown events."""
            registry: Registry = Component.shared_registry  # type: ignore[assignment]
            logger.info("Starting up application components")

            # Configure OpenTelemetry tracing
            try:
                self._telemetry_manager.configure_tracing()
            except Exception as e:
                logger.warning("Failed to configure OpenTelemetry: %s", e)

            # ActuatorApi
            if self._actuator_api is not None:
                await self._actuator_api.on_startup()

            # Clients (IO + AI) — config reading and lazy-connect preparation
            for client in registry.get_clients():
                try:
                    await client.on_startup()
                    logger.info("Client %s startup completed", client.name)
                except Exception as e:
                    logger.error("Client %s startup failed: %s", client.name, e, exc_info=True)
                    raise

            # Services (includes EventProcessingService, EventPublishingService, user services)
            for service in registry.get_services():
                try:
                    await service.on_startup()
                    logger.info("Service %s startup completed", service.name)
                except Exception as e:
                    logger.error("Service %s startup failed: %s", service.name, e, exc_info=True)
                    raise

            # Handlers
            for handler in registry.get_event_handler():
                try:
                    await handler.on_startup()
                    logger.info("Handler %s startup completed", handler.name)
                except Exception as e:
                    logger.error("Handler %s startup failed: %s", handler.name, e, exc_info=True)
                    raise

            # Agents
            for agent_name in registry.get_agents():
                try:
                    agent = registry.get_component(agent_name)
                    await agent.on_startup()
                    logger.info("Agent %s startup completed", agent_name)
                except Exception as e:
                    logger.error("Agent %s startup failed: %s", agent_name, e, exc_info=True)
                    raise

            # User REST APIs
            for rest_api in registry.get_rest_apis():
                try:
                    await rest_api.on_startup()
                    logger.info("REST API %s startup completed", rest_api.name)
                except Exception as e:
                    logger.error("REST API %s startup failed: %s", rest_api.name, e, exc_info=True)
                    raise

            # Schedulers
            for scheduler in registry.get_schedulers():
                try:
                    await scheduler.on_startup()
                    logger.info("Scheduler %s startup completed", scheduler.name)
                except Exception as e:
                    logger.error("Scheduler %s startup failed: %s", scheduler.name, e, exc_info=True)
                    raise

            # Eventing component (Dapr / NATS endpoint)
            if self._eventing_component is not None:
                try:
                    await self._eventing_component.on_startup()
                    logger.info("Eventing component startup completed")
                except Exception as e:
                    logger.error("Eventing component startup failed: %s", e, exc_info=True)
                    raise

            logger.info("Application startup completed")
            yield

            # ----------------------------------------------------------
            # Shutdown — reverse order
            # ----------------------------------------------------------
            logger.info("Shutting down application components")

            if self._eventing_component is not None:
                try:
                    await self._eventing_component.on_shutdown()
                except Exception as e:
                    logger.error("Eventing component shutdown failed: %s", e, exc_info=True)

            for scheduler in registry.get_schedulers():
                try:
                    await scheduler.on_shutdown()
                except Exception as e:
                    logger.error("Scheduler %s shutdown failed: %s", scheduler.name, e, exc_info=True)

            for rest_api in registry.get_rest_apis():
                try:
                    await rest_api.on_shutdown()
                except Exception as e:
                    logger.error("REST API %s shutdown failed: %s", rest_api.name, e, exc_info=True)

            for agent_name in registry.get_agents():
                try:
                    agent = registry.get_component(agent_name)
                    await agent.on_shutdown()
                except Exception as e:
                    logger.error("Agent %s shutdown failed: %s", agent_name, e, exc_info=True)

            for handler in registry.get_event_handler():
                try:
                    await handler.on_shutdown()
                except Exception as e:
                    logger.error("Handler %s shutdown failed: %s", handler.name, e, exc_info=True)

            for service in registry.get_services():
                try:
                    await service.on_shutdown()
                except Exception as e:
                    logger.error("Service %s shutdown failed: %s", service.name, e, exc_info=True)

            for client in registry.get_clients():
                try:
                    await client.on_shutdown()
                except Exception as e:
                    logger.error("Client %s shutdown failed: %s", client.name, e, exc_info=True)

            if self._actuator_api is not None:
                await self._actuator_api.on_shutdown()
            logger.info("Application shutdown completed")

        return lifespan
