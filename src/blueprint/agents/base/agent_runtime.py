"""Agent runtime implementation with prompt registry support."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.tools import AgentDepsT

from blueprint.agents.registry.component_registry import ComponentRegistry

from ..config import Config
from ..agent.prompt_loader import PromptLoader

logger: logging.Logger = logging.getLogger(__name__)


class AgentRuntime(Agent[AgentDepsT, Any]):
    """Agent subclass that stores registered prompts and exposes prompt execution.

    Handles all prompt-related operations including loading, registering, and executing
    prompts from files or configuration.

    Implements the ComponentInterface:
    - name: str - Component name
    - get_registry() -> ComponentRegistry - Access component registry
    - on_startup() - Optional initialization
    - on_shutdown() - Optional cleanup
    """

    def __init__(
        self,
        config: Config | None = None,
        runtime_name: str = "default",
        **kwargs: Any,
    ) -> None:
        """Initialize the agent runtime.

        Args:
            config: Application configuration for prompt loading
            runtime_name: Name for runtime-specific config lookup
            **kwargs: Keyword arguments for Agent
        """
        super().__init__(**kwargs)
        self._prompt_cache: Dict[str, str] = {}
        self._config = config
        self._name = runtime_name
        self._component_registry: Any = None

    def get_name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """
        return self._name

    def get_registry(self) -> ComponentRegistry:
        """Get the component registry for accessing other components.

        Returns:
            The ComponentRegistry instance

        Raises:
            RuntimeError: If registry is not wired
        """
        if not hasattr(self, "_component_registry") or self._component_registry is None:
            raise RuntimeError(f"Component registry not linked to service '{self.name}'")
        return self._component_registry

    def link_component_registry(self, registry: "ComponentRegistry") -> None:
        """Link the component registry to the service.

        This allows services to access other components via the registry.

        Args:
            registry: The ComponentRegistry instance
        """
        self._component_registry = registry

    def link_config(self, config: Config) -> None:
        """Link configuration to the service via dependency injection.

        This allows services to access environment variables and configuration
        during runtime.

        Args:
            config: The Config instance
        """
        self.config = config

    async def on_startup(self) -> None:
        """Called when service is registered and wired.

        Override to perform initialization tasks such as:
        - Connecting to external services
        - Loading configuration
        - Initializing resources
        """
        pass

    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks such as:
        - Closing connections
        - Releasing resources
        - Flushing buffers
        """
        pass

    def get_prompt(self, prompt_name: str, runtime_name: str | None = None) -> str:
        """Load instruction prompt by name (lazy loading with caching).

        Prompts are loaded on-demand and cached to avoid repeated file I/O.

        Args:
            prompt_name: Name of the prompt to load (without extension)
            runtime_name: Optional runtime name for config lookup (uses runtime's runtime_name if not provided)

        Returns:
            Prompt content as string

        Raises:
            ValueError: If config is not available
            FileNotFoundError: If prompt file not found
        """
        if self._config is None:
            raise ValueError("Config must be provided to load prompts")

        # Check cache first
        if prompt_name in self._prompt_cache:
            logger.debug("Retrieved cached prompt: %s", prompt_name)
            return self._prompt_cache[prompt_name]

        # Load and cache
        name = runtime_name or self._runtime_name
        prompt_config = self._config.get_prompt_config(name)
        prompt_content = PromptLoader.load_prompt(prompt_name, self.__class__, prompt_config, self._package_root)
        self._prompt_cache[prompt_name] = prompt_content
        logger.info("Loaded and cached prompt: %s", prompt_name)
        return prompt_content

    async def run_with_prompt(self, prompt_name: str, **kwargs: Any) -> AgentRunResult:
        """Execute the agent using the prompt identified by ``prompt_name``.

        Args:
            prompt_name: Name of the prompt to load
            **kwargs: Additional arguments for agent.run()

        Returns:
            The agent run result

        Raises:
            ValueError: If config is not available
            FileNotFoundError: If prompt not found
        """
        prompt = self.get_prompt(prompt_name)
        return await self.run(prompt, **kwargs)

    def run_with_prompt_sync(self, prompt_name: str, **kwargs: Any) -> AgentRunResult:
        """Execute the agent synchronously using the prompt identified by ``prompt_name``.

        Args:
            prompt_name: Name of the prompt to load
            **kwargs: Additional arguments for agent.run_sync()

        Returns:
            The agent run result

        Raises:
            ValueError: If config is not available
            FileNotFoundError: If prompt not found
        """
        prompt = self.get_prompt(prompt_name)
        return self.run_sync(prompt, **kwargs)
