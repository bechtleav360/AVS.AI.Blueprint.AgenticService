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
        config: Config | None = None,
        runtime_name: str = "default",
        package_root: Path | str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the agent runtime.

        Args:
            *args: Positional arguments for Agent
            config: Application configuration for prompt loading
            runtime_name: Name for runtime-specific config lookup
            package_root: Optional root path for the package (e.g., where main.py resides)
            **kwargs: Keyword arguments for Agent
        """
        super().__init__(*args, **kwargs)
        self._prompt_cache: Dict[str, str] = {}
        self._config = config
        self._runtime_name = runtime_name
        self._package_root = Path(package_root) if package_root else None

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
