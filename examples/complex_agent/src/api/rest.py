"""Custom REST API definition for the agent service."""

from typing import Any

from blueprint.agents.api.rest import RestApi

from ..models import CustomPayload


class CustomRestApi(RestApi[CustomPayload]):
    """Custom REST API definition.

    The component registry and agent will be wired in by AppBuilder.
    """

    def __init__(self) -> None:
        """Initialize the custom REST API.

        The component registry and agent will be wired in by AppBuilder.
        """
        self._component_registry: Any = None
        self._agent: Any = None
        self.router: Any = None
        self.payload_type = CustomPayload
