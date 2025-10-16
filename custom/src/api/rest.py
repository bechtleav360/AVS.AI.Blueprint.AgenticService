"""Custom REST API definition for the agent service."""

from base.src.api.rest import RestApi
from base.src.registry.component_registry import ComponentRegistry

from ..models import CustomPayload


class CustomRestApi(RestApi[CustomPayload]):
    """Custom REST API definition."""

    def __init__(self, registry: ComponentRegistry):
        super().__init__(payload_type=CustomPayload, registry=registry)
