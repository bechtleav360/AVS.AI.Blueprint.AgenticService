"""Agent runtime implementation with prompt registry support."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import AgentDepsT

from ..agent.prompt_loader import PromptLoader
from ..config import Config
from .component import Component

if TYPE_CHECKING:
    from ..registry.component_registry import ComponentRegistry

logger: logging.Logger = logging.getLogger(__name__)


class AgentRuntime(Agent[AgentDepsT, Any], Component):
    """Agent subclass that stores registered prompts and exposes prompt execution.

    Handles all prompt-related operations including loading, registering, and executing
    prompts from files or configuration.

    Extends Component to provide consistent lifecycle and registry access.
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
        if "name" in kwargs:
            Agent.__init__(self, **kwargs)
        else:
            Agent.__init__(self, name=runtime_name, **kwargs)

        Component.__init__(self, runtime_name)

        self._prompt_cache: dict[str, str] = {}
        self._config = config
        self._runtime_name: str = runtime_name
        self._model_settings: ModelSettings = {}  # type: ignore[assignment]

    def get_name(self) -> str:
        """Get the component name.

        Returns:
            The component name set during initialization
        """

        return self._runtime_name

    def get_pydantic_name(self) -> str:
        """This method only exists for compatibility with old agent access using the pydantic name.

        Returns:
            The pydantic agent name
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
            raise RuntimeError(f"Component registry not linked to service '{self.get_name()}'")
        return self._component_registry

    def get_config(self) -> Config:
        """Get the configuration linked to this agent runtime.

        Returns:
            The Config instance linked via dependency injection or constructor

        Raises:
            RuntimeError: If config is not wired
        """

        if not hasattr(self, "_config") or self._config is None:
            raise RuntimeError(f"Config not linked to agent runtime '{self.get_name()}'")
        return self._config

    def link_component_registry(self, registry: ComponentRegistry) -> None:
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
        self._config = config

    async def on_startup(self) -> None:
        """Called when service is registered and wired.

        Override to perform initialization tasks such as:
        - Connecting to external services
        - Loading configuration
        - Initializing resources
        """

    async def on_shutdown(self) -> None:
        """Called when application is shutting down.

        Override to perform cleanup tasks such as:
        - Closing connections
        - Releasing resources
        - Flushing buffers
        """

    def get_model_settings(self) -> ModelSettings:
        """Get model settings for use in agent.run() calls.

        Returns model configuration settings (max_tokens, temperature, etc.)
        that should be passed to agent.run() via the model_settings parameter.

        Returns:
            ModelSettings object with configuration from runtime settings
        """
        if not self._model_settings and self._config:
            try:
                ai_config = self._config.get_ai_config(self._runtime_name)
                settings: ModelSettings = {}  # type: ignore[assignment]

                if ai_config.max_tokens is not None:
                    settings["max_tokens"] = ai_config.max_tokens

                if ai_config.temperature is not None:
                    settings["temperature"] = ai_config.temperature

                self._model_settings = settings
            except Exception as e:
                logger.warning("Failed to load model settings from config: %s", e)
                self._model_settings = {}  # type: ignore[assignment]

        return self._model_settings

    async def run(
        self,
        user_prompt: str | None = None,
        *,
        model_settings: ModelSettings | None = None,
        **kwargs: Any,
    ) -> AgentRunResult:
        """Execute the agent with automatic model settings from configuration.

        Overrides the parent Agent.run() method to automatically apply model settings
        from configuration if not explicitly provided.

        Args:
            user_prompt: The user prompt to send to the agent
            model_settings: Optional model settings. If not provided, uses settings from configuration.
            **kwargs: Additional keyword arguments passed to parent Agent.run()

        Returns:
            Agent run result
        """
        # Use provided model_settings, or fall back to configuration settings
        if model_settings is None:
            model_settings = self.get_model_settings()

        # Call parent run() with all parameters
        return await super().run(user_prompt, model_settings=model_settings, **kwargs)

    def get_prompt(self, prompt_name: str, path: str = "") -> str:
        """Load instruction prompt by name (lazy loading with caching).

        Prompts are loaded on-demand and cached to avoid repeated file I/O.

        Args:
            prompt_name: Name of the prompt to load (without extension)
            path: Optional path to load the prompt from

        Returns:
            Prompt content as string

        Raises:
            ValueError: If config is not available
            FileNotFoundError: If prompt file not found
        """

        # Check cache first
        if prompt_name in self._prompt_cache:
            logger.debug("Retrieved cached prompt: %s", prompt_name)
            return self._prompt_cache[prompt_name]

        # Load and cache
        prompt_content = PromptLoader.load_prompt(prompt_name, self.get_config(), path)
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
        logger.warning("run_with_prompt has been deprecated, since we need to typically resolve variables anyway.")
        raise NotImplementedError

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
        logger.warning("run_with_prompt_sync has been deprecated, since we need to typically resolve variables anyway.")
        raise NotImplementedError
