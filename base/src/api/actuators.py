"""Actuator endpoints for the agent service (Spring Boot style)."""

import logging
from typing import Any, Dict, Protocol

from ..models.api import LivenessResponse, ReadinessResponse

from fastapi import APIRouter, Depends, HTTPException, status
from opentelemetry import trace

# FIXME: Import your dependencies here.
# from ..dependencies import get_your_agent, get_data_gateway
# from ..agent.runtime import AgentRuntime
# from ..services.data_gateway import DataGatewayClient

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class HealthCheckProvider(Protocol):
    """A protocol for components that can provide a health check."""

    async def health_check(self) -> Dict[str, Any]: ...


class ActuatorApi:
    """Encapsulates all actuator-related endpoints and logic."""

    def __init__(self, **dependencies: HealthCheckProvider):
        self.router = APIRouter()
        self.dependencies = dependencies
        self._register_routes()

    def _register_routes(self):
        self.router.add_api_route(
            "/health/live",
            self.liveness_probe,
            methods=["GET"],
            summary="Performs a liveness probe of the service.",
            tags=["Health"],
            response_model=LivenessResponse,
        )
        self.router.add_api_route(
            "/health/ready",
            self.readiness_probe,
            methods=["GET"],
            summary="Performs a readiness probe of the service.",
            tags=["Health"],
            response_model=ReadinessResponse,
        )

    async def readiness_probe(self) -> ReadinessResponse:
        """Readiness probe to check if the service is ready to accept traffic."""
        with tracer.start_as_current_span("api.readiness_probe") as span:
            try:
                components = {}
                for name, dependency in self.dependencies.items():
                    components[name] = await dependency.health_check()

                if not components:
                    components["placeholder"] = {
                        "status": "healthy",
                        "message": "FIXME: Implement your health checks",
                    }

                all_healthy = all(
                    component.get("status") == "healthy"
                    for component in components.values()
                )

                overall_status = "UP" if all_healthy else "DOWN"

                span.set_attribute("health_status", overall_status)

                return ReadinessResponse(
                    status=overall_status, components=components
                )

            except Exception as e:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                logger.error(f"Health check failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Health check failed",
                )

    async def liveness_probe(self) -> LivenessResponse:
        """Liveness probe to indicate the service is running."""
        return LivenessResponse(status="UP")


# Example of how to instantiate and use the ActuatorApi
# dependencies = {
#     "your_agent": get_your_agent(),
#     "data_gateway": get_data_gateway(),
# }
# actuator_api = ActuatorApi(**dependencies)
# router = actuator_api.router

# For now, we'll keep the original router behavior for compatibility
actuator_api = ActuatorApi()
router = actuator_api.router
