from abc import ABC

from ..component.component import Component
from ..component.namespace import ROOT_NAMESPACE


class ServiceBase(Component, ABC):
    """Base class for business services.

    Extends Component to provide consistent lifecycle and registry access
    for business logic services. All lifecycle and dependency injection methods
    are inherited from Component.
    """

    def __init__(self, name: str | None = None, namespace: str = ROOT_NAMESPACE, *, should_register: bool = True) -> None:
        """Initialize the business service.

        Args:
            name: Registry name to use instead of the derived one. Forwarded to
                ``Component``, which registers under it.
            namespace: The agent this service belongs to; ``""`` for the root namespace.
                Forwarded to ``Component``, which validates it and qualifies the name.
            should_register: Whether to add this instance to the registry. Keyword-only and
                default ``True``, so no existing subclass changes. ``False`` is for a
                service-shaped object that is not a collaborator anyone looks up --
                ``AgentScopedCache``, which is one agent's lens on a registered cache and
                would otherwise register a second entry per agent. ``RestApiBase`` has taken
                the same parameter since before namespaces.
        """
        super().__init__(should_register=should_register, name=name, namespace=namespace)
