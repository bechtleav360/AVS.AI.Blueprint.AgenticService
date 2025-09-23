"""Generic FastAPI application setup and configuration."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import actuators, rest, events
# Dapr generic endpoints
try:
    from .api import dapr
except Exception:
    dapr = None
# from .config import get_observability_config, get_security_config, settings
# from .telemetry import instrument_fastapi, setup_logging, setup_telemetry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown events.

    FIXME: Customize with your domain-specific startup/shutdown logic
    FIXME: Add initialization of your custom components and services

    Args:
        app: FastAPI application instance
    """
    # Startup
    # FIXME: Replace with your service name
    logger.info("Starting agent service")

    # FIXME: Add your custom startup logic here
    # - Initialize database connections
    # - Setup external service clients
    # - Load configuration
    # - Start background tasks
    # - Initialize caches

    # Setup telemetry and logging (if using observability)
    # FIXME: Replace with your observability setup
    # obs_config = get_observability_config()
    # setup_logging(obs_config["log_level"], obs_config["log_format"])
    # setup_telemetry(obs_config["service_name"])

    # Instrument FastAPI (if using observability)
    # FIXME: Replace with your instrumentation setup
    # instrument_fastapi(app)

    logger.info("Service startup completed")

    yield

    # Shutdown
    # FIXME: Replace with your service name
    logger.info("Shutting down agent service")

    # FIXME: Add your custom cleanup logic here
    # - Close database connections
    # - Cleanup external service clients
    # - Stop background tasks
    # - Flush caches
    # - Save state if needed

    # Cleanup dependencies (if using dependency injection)
    # FIXME: Replace with your cleanup logic
    # await cleanup_dependencies()

    logger.info("Service shutdown completed")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    FIXME: Customize with your domain-specific configuration
    FIXME: Add your custom middleware, routers, and endpoints

    Returns:
        Configured FastAPI application
    """
    # Create FastAPI app
    # FIXME: Replace with your service information
    app = FastAPI(
        title="Agent Service",
        description="Generic microservice blueprint for building intelligent agents",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # FIXME: Add your custom middleware here
    # Security middleware
    # app.add_middleware(HTTPSRedirectMiddleware)

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

    # FIXME: Add your custom authentication middleware
    # app.add_middleware(AuthenticationMiddleware)

    # Include only base routers here. Custom routers can be added by the agent app if needed.
    app.include_router(actuators.router, tags=["actuators"])
    app.include_router(rest.router, prefix="/api", tags=["rest"])
    app.include_router(events.router, prefix="/events", tags=["events"])
    if dapr is not None:
        app.include_router(dapr.router, tags=["dapr"]) 

    # FIXME: Add your custom root endpoint
    @app.get("/")
    async def root():
        """
        Root endpoint with service information.

        FIXME: Customize with your service-specific information
        FIXME: Add links to your domain-specific endpoints
        """
        return {
            "service": "agent-service",
            "version": "0.1.0",
            "description": "Generic microservice blueprint for building intelligent agents",
            "docs": "/docs",
            "health": "/actuators/health",
            # FIXME: Add your custom endpoints
            # "your-custom-endpoint": "/your-endpoint",
        }

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    # FIXME: Replace with your configuration imports
    # import uvicorn
    # from .config import settings

    # FIXME: Add your custom startup logic
    # - Import your custom modules
    # - Setup your dependencies
    # - Configure your services

    # Run the application
    # FIXME: Replace with your configuration
    # uvicorn.run(
    #     "src.app:app",
    #     host="0.0.0.0",
    #     port=settings.app_port,
    #     reload=True,
    #     log_level=settings.log_level.lower(),
    # )

    print("FIXME: Add your custom startup logic for running the application")
    print("Example:")
    print("  import uvicorn")
    print("  from .config import settings")
    print("  uvicorn.run('src.app:app', host='0.0.0.0', port=settings.app_port, reload=True)")
