from .component import Component


class BusinessService(Component):
    """Base class for business services.

    Extends Component to provide consistent lifecycle and registry access
    for business logic services. All lifecycle and dependency injection methods
    are inherited from Component.
    """

    def __init__(self, name: str = "BusinessService") -> None:
        """Initialize the business service.

        Args:
            name: Human-readable name for the service
        """
        super().__init__(name)
