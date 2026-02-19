"""Custom REST API definition for the agent service."""

from blueprint.agents.base import RestApi


class CustomRestApi(RestApi):
    """Custom REST API definition.

    The component registry and agent will be wired in by AppBuilder.
    Routes are registered via @RestApi.get / @RestApi.post decorators on methods.
    """

    def __init__(self) -> None:
        super().__init__(name="CustomRestApi")
