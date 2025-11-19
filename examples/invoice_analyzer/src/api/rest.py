"""Custom REST API definition for the agent service."""

from blueprint.agents.api.rest import RestApi
from blueprint.agents.registry.component_registry import ComponentRegistry

from ..models import CustomPayload


class CustomRestApi(RestApi[CustomPayload]):
    """Custom REST API definition."""

    def __init__(self, registry: ComponentRegistry):
        super().__init__(payload_type=CustomPayload, registry=registry)
