from abc import ABC

from ..component.component import Component
from ..component.namespace import ROOT_NAMESPACE


class ServiceBase(Component, ABC):
    """Base class for business services.

    Extends Component to provide consistent lifecycle and registry access
    for business logic services. All lifecycle and dependency injection methods
    are inherited from Component.
    """

    def __init__(self, name: str | None = None, namespace: str = ROOT_NAMESPACE) -> None:
        """Initialize the business service.

        Args:
            name: Registry name to use instead of the derived one. Forwarded to
                ``Component``, which registers under it.
            namespace: The agent this service belongs to; ``""`` for the root namespace.
                Forwarded to ``Component``, which validates it and qualifies the name.
        """
        super().__init__(name=name, namespace=namespace)
