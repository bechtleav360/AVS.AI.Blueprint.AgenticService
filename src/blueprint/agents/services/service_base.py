from abc import ABC

from ..component.component import Component


class ServiceBase(Component, ABC):
    """Base class for business services.

    Extends Component to provide consistent lifecycle and registry access
    for business logic services. All lifecycle and dependency injection methods
    are inherited from Component.
    """

    def __init__(self) -> None:
        """Initialize the business service."""
        super().__init__()
