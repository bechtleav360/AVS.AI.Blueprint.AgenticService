"""Abstract base class for health check providers, and what a registered check is."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .....component.namespace import ROOT_LABEL, qualified_entry_name
from .....models.api import ComponentHealth


class HealthCheckerBase(ABC):
    """Abstract base class for all health check providers.

    All health check implementations must inherit from this class and implement
    the health_check() method to provide component-specific health status.

    Example:
        ```python
        class CustomHealthChecker(HealthCheckerBase):
            async def health_check(self) -> ComponentHealth:
                # Perform health check logic
                return ComponentHealth(status="UP", message="Service OK")
        ```
    """

    @abstractmethod
    async def health_check(self) -> ComponentHealth:
        """Perform health check and return component status.

        Returns:
            ComponentHealth: Status object with status ("UP" or "DOWN") and message.

        Raises:
            Exception: Any exceptions are caught by the caller and logged.
        """
        raise NotImplementedError()


@dataclass(frozen=True)
class HealthCheckEntry:
    """One registered check: what it is called, **which agent it belongs to**, and the checker.

    A dict of ``name -> checker`` was what this replaces, and it lost the attribution twice
    over. Two agents calling ``with_health_checker("db", ...)`` collided on one key and one
    disappeared with nothing logged; and even where the keys differed, nothing recorded whose
    check a failing entry was -- ``readiness_policy = "critical"`` (phase 9) has to answer
    exactly that.

    So the agent is carried **as data**, and :attr:`key` is only its rendering. Recovering the
    namespace by splitting the key would break on the first name containing the separator, and
    ``cache:v2.sessions`` is one.

    Attributes:
        name: What this check is called within its agent.
        namespace: The agent it belongs to; ``""`` for the root.
        checker: The checker to poll.
    """

    name: str
    namespace: str
    checker: HealthCheckerBase

    @property
    def key(self) -> str:
        """The entry name this check appears under in the readiness payload.

        The root keeps the bare name, so an existing single-agent payload is unchanged.
        """
        return qualified_entry_name(self.namespace, self.name)

    @property
    def agent(self) -> str:
        """The owning agent, as it is written where a value is required (``<root>`` at the root)."""
        return self.namespace or ROOT_LABEL
