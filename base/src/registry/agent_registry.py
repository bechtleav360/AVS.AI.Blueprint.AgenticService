"""Registry for managing pre-configured AI agents."""

import logging
from typing import Dict, Optional

from pydantic_ai import Agent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry for storing and retrieving pre-configured agents.

    This registry allows agents to be configured once and reused across
    multiple handlers, avoiding duplication and ensuring consistency.

    Example:
        # Register agents
        registry = AgentRegistry()
        registry.register("invoice_analyzer", invoice_agent)
        registry.register("document_classifier", classifier_agent)

        # Get agent in handler
        agent = registry.get("invoice_analyzer")
        result = await agent.run(...)
    """

    def __init__(self):
        """Initialize the agent registry."""
        self._agents: Dict[str, Agent] = {}
        logger.info("AgentRegistry initialized")

    def register(self, name: str, agent: Agent) -> None:
        """Register an agent with a name.

        Args:
            name: Unique name for the agent
            agent: Configured Agent instance

        Raises:
            ValueError: If agent with this name already exists
        """
        if name in self._agents:
            raise ValueError(f"Agent '{name}' is already registered")

        self._agents[name] = agent
        logger.info("Registered agent: %s", name)

    def get(self, name: str) -> Agent:
        """Get a registered agent by name.

        Args:
            name: Name of the agent to retrieve

        Returns:
            The registered Agent instance

        Raises:
            ValueError: If agent not found
        """
        if name not in self._agents:
            available = ", ".join(self._agents.keys()) if self._agents else "none"
            raise ValueError(f"Agent '{name}' not found. Available agents: {available}")

        return self._agents[name]

    def has(self, name: str) -> bool:
        """Check if an agent is registered.

        Args:
            name: Name of the agent

        Returns:
            True if agent is registered, False otherwise
        """
        return name in self._agents

    def list_agents(self) -> list[str]:
        """Get list of all registered agent names.

        Returns:
            List of agent names
        """
        return list(self._agents.keys())

    def clear(self) -> None:
        """Clear all registered agents (useful for testing)."""
        logger.info("Clearing all registered agents")
        self._agents.clear()
