"""Agent runtime implementation with prompt registry support."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import AgentDepsT

from .metrics import MetricsRecorder
from .prompt_loader import PromptLoader
from ..component.component import Component

if TYPE_CHECKING:
    pass

logger: logging.Logger = logging.getLogger(__name__)


class AgentRuntime(Agent[AgentDepsT, Any], Component):
    """Agent subclass that stores registered prompts and exposes prompt execution.

    Handles all prompt-related operations including loading, registering, and executing
    prompts from files or configuration.

    Extends Component to provide consistent lifecycle and registry access.
    """

    @property
    def name(self) -> str | None:
        """Agent name — delegates to Agent.name to preserve _override_name context-var logic."""
        return Agent.name.fget(self)

    @name.setter
    def name(self, value: str | None) -> None:
        """Update name in both the pydantic_ai Agent and the Component registry."""
        Agent.name.fset(self, value)       # pydantic_ai side-effects (future-proof)
        Component.name.fset(self, value)   # registry update + self._name

    def __init__(
        self,
        name: str,
        **kwargs: Any,
    ) -> None:
        """Initialize the agent runtime.

        Args:
            name: Name used for registry lookup and logging
            **kwargs: Keyword arguments forwarded to pydantic_ai.Agent
        """
        Agent.__init__(self, name=name, **kwargs)
        Component.__init__(self, should_register=False)
        self._name = name
        self.registry.add_component(name, self)

        self._prompt_cache: dict[str, str] = {}
        self._model_settings: ModelSettings = {}  # type: ignore[assignment]
        self._recorder: MetricsRecorder | None = None

    def get_pydantic_name(self) -> str:
        """This method only exists for compatibility with old agent access using the pydantic name.

        Returns:
            The pydantic agent name
        """

        return self._name

    def get_model_settings(self) -> ModelSettings:
        """Get model settings for use in agent.run() calls.

        Returns model configuration settings (max_tokens, temperature, etc.)
        that should be passed to agent.run() via the model_settings parameter.

        Returns:
            ModelSettings object with configuration from runtime settings
        """
        if not self._model_settings:
            try:
                ai_config = self.config.get_ai_config(self.name)
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
        if model_settings is None:
            model_settings = self.get_model_settings()

        return await super().run(user_prompt, model_settings=model_settings, **kwargs)

    async def on_startup(self) -> None:
        """No startup actions required; lifecycle is managed by AgentBuilder."""

    async def on_shutdown(self) -> None:
        """No shutdown actions required; lifecycle is managed by AgentBuilder."""

    def record_metrics(self, result: AgentRunResult, duration_ms: float, model_name: str | None = None) -> None:
        """Record LLM metrics to logs and OpenTelemetry.

        Args:
            result: The AgentRunResult object from agent.run()
            duration_ms: Response time in milliseconds
            model_name: Name of the LLM model; resolved from the agent's model if omitted
        """
        if self._recorder is None:
            return

        resolved = model_name or getattr(getattr(self, "model", None), "model_name", "unknown")
        self._recorder.record(result, duration_ms, resolved)

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
        if prompt_name in self._prompt_cache:
            logger.debug("Retrieved cached prompt: %s", prompt_name)
            return self._prompt_cache[prompt_name]

        prompt_content = PromptLoader.load_prompt(prompt_name, self.config, path)
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
