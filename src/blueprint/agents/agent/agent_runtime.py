"""Agent runtime implementation with prompt registry support."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.tools import AgentDepsT

from ..config import Config
from .prompt_loader import PromptLoader

logger: logging.Logger = logging.getLogger(__name__)


class AgentRuntime(Agent[AgentDepsT, Any]):
    """Agent subclass that stores registered prompts and exposes prompt execution.

    Handles all prompt-related operations including loading, registering, and executing
    prompts from files or configuration.
    """

    def __init__(
        self,
        *args: Any,
        prompts: Dict[str, str] | None = None,
        config: Config | None = None,
        runtime_name: str = "default",
        package_root: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the agent runtime.

        Args:
            *args: Positional arguments for Agent
            prompts: Dictionary of registered prompts
            config: Application configuration for prompt loading
            runtime_name: Name for runtime-specific config lookup
            package_root: Optional root path for the package (e.g., where main.py resides)
            **kwargs: Keyword arguments for Agent
        """
        super().__init__(*args, **kwargs)
        self._prompts: Dict[str, str] = prompts.copy() if prompts else {}
        self._config = config
        self._runtime_name = runtime_name
        self._package_root = Path(package_root) if package_root else None

    @property
    def prompts(self) -> Dict[str, str]:
        """Return registered prompts."""
        return self._prompts

    def register_prompt(self, name: str, prompt: str) -> None:
        """Register or update a prompt in the runtime.

        Args:
            name: Name of the prompt
            prompt: Prompt content
        """
        self._prompts[name] = prompt
        logger.debug("Registered prompt: %s", name)

    def load_prompt_from_file(
        self,
        prompt_name: str,
        runtime_name: str | None = None,
    ) -> str:
        """Load a prompt from file using configuration.

        Args:
            prompt_name: Name of the prompt file (without extension)
            runtime_name: Runtime name for config lookup, or None to use runtime's runtime_name

        Returns:
            The loaded prompt content

        Raises:
            ValueError: If config is not available or prompt cannot be loaded
        """
        if self._config is None:
            raise ValueError("Config must be provided to load prompts from file")

        name = runtime_name or self._runtime_name
        prompt_config = self._config.get_prompt_config(name)
        prompt_content = PromptLoader.load_prompt(prompt_name, self.__class__, prompt_config, self._package_root)
        logger.debug("Loaded prompt from file: %s", prompt_name)
        return prompt_content

    def load_system_prompt_from_file(
        self,
        prompt_name: str,
        runtime_name: str | None = None,
    ) -> str:
        """Load a system prompt from file using configuration.

        Args:
            prompt_name: Name of the prompt file (without extension)
            runtime_name: Runtime name for config lookup, or None to use runtime's runtime_name

        Returns:
            The loaded system prompt content

        Raises:
            ValueError: If config is not available or prompt cannot be loaded
        """
        if self._config is None:
            raise ValueError("Config must be provided to load prompts from file")

        name = runtime_name or self._runtime_name
        prompt_config = self._config.get_prompt_config(name)
        prompt_content = PromptLoader.load_prompt(prompt_name, self.__class__, prompt_config, self._package_root)
        logger.debug("Loaded system prompt from file: %s", prompt_name)
        return prompt_content

    def load_system_prompt_from_config(
        self,
        runtime_name: str | None = None,
    ) -> str:
        """Load system prompt from config-specified file.

        Uses the system_prompt_name from PromptConfig to load the prompt file.

        Args:
            runtime_name: Runtime name for config lookup, or None to use runtime's runtime_name

        Returns:
            The loaded system prompt content

        Raises:
            ValueError: If config is not available or prompt cannot be loaded
        """
        if self._config is None:
            raise ValueError("Config must be provided to load prompts from file")

        name = runtime_name or self._runtime_name
        prompt_config = self._config.get_prompt_config(name)
        prompt_content = PromptLoader.load_prompt(prompt_config.system_prompt_name, self.__class__, prompt_config, self._package_root)
        logger.debug("Loaded system prompt from config: %s", prompt_config.system_prompt_name)
        return prompt_content

    async def run_with_prompt(self, prompt_name: str, **kwargs: Any) -> AgentRunResult:
        """Execute the agent using the prompt identified by ``prompt_name``.

        Args:
            prompt_name: Name of the registered prompt
            **kwargs: Additional arguments for agent.run()

        Returns:
            The agent run result

        Raises:
            KeyError: If prompt_name is not registered
        """
        return await self.run(self._prompts[prompt_name], **kwargs)

    def run_with_prompt_sync(self, prompt_name: str, **kwargs: Any) -> AgentRunResult:
        """Execute the agent synchronously using the prompt identified by ``prompt_name``.

        Args:
            prompt_name: Name of the registered prompt
            **kwargs: Additional arguments for agent.run_sync()

        Returns:
            The agent run result

        Raises:
            KeyError: If prompt_name is not registered
        """
        return self.run_sync(self._prompts[prompt_name], **kwargs)
