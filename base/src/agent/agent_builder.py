"""Builder for creating and configuring AI agents without inheritance."""

import logging
from typing import Any, Callable, List, Optional, Type

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.models import Model

from ..config import Config
from .model_provider import ModelProviderFactory
from .prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Builder for creating configured AI agents.

    This builder allows handlers to create agents with custom configuration
    without requiring inheritance or abstract methods.

    Example:
        # Simple agent
        agent = (
            AgentBuilder(config)
            .with_model("gpt-4")
            .with_system_prompt_text("You are an invoice analyzer")
            .build()
        )

        # Fully configured agent
        agent = (
            AgentBuilder(config)
            .with_model_from_config("invoice_analyzer")
            .with_system_prompt_file("invoice_analyzer")
            .with_tools([calculate_tool, validate_tool])
            .with_result_type(InvoiceOutput)
            .build()
        )
    """

    def __init__(self, config: Config, runtime_name: str = "default"):
        """Initialize the agent builder.

        Args:
            config: Application configuration
            runtime_name: Name for runtime-specific config lookup
        """
        self._config = config
        self._runtime_name = runtime_name
        self._model: Optional[Model] = None
        self._system_prompt: Optional[str] = None
        self._tools: List[Tool] = []
        self._result_type: Type[BaseModel] = BaseModel
        self._deps_type: Type[Any] = type(None)

    def with_model(self, model_name: str) -> "AgentBuilder":
        """Configure with a specific model name.

        Args:
            model_name: Name of the model (e.g., "gpt-4", "claude-3")

        Returns:
            Self for chaining
        """
        ai_config = self._config.get_ai_config(self._runtime_name)
        ai_config["model_name"] = model_name
        self._model = ModelProviderFactory.create_model(ai_config)
        logger.debug("Configured agent with model: %s", model_name)
        return self

    def with_model_from_config(
        self, runtime_name: Optional[str] = None
    ) -> "AgentBuilder":
        """Configure model from runtime-specific config.

        Args:
            runtime_name: Runtime name to lookup config, or None to use builder's runtime_name

        Returns:
            Self for chaining
        """
        name = runtime_name or self._runtime_name
        ai_config = self._config.get_ai_config(name)
        self._model = ModelProviderFactory.create_model(ai_config)
        logger.debug(
            "Configured agent with model from config '%s': %s",
            name,
            ai_config.get("model_name"),
        )
        return self

    def with_system_prompt_text(self, prompt: str) -> "AgentBuilder":
        """Configure with a direct system prompt string.

        Args:
            prompt: The system prompt text

        Returns:
            Self for chaining
        """
        self._system_prompt = prompt
        logger.debug("Configured agent with inline system prompt")
        return self

    def with_system_prompt_file(
        self, prompt_name: str, runtime_name: Optional[str] = None
    ) -> "AgentBuilder":
        """Configure with a system prompt from file.

        Args:
            prompt_name: Name of the prompt file (without extension)
            runtime_name: Runtime name for config lookup, or None to use builder's runtime_name

        Returns:
            Self for chaining
        """
        name = runtime_name or self._runtime_name
        prompt_config = self._config.get_prompt_config(name)
        self._system_prompt = PromptLoader.load_prompt(
            prompt_name, self.__class__, prompt_config
        )
        logger.debug("Configured agent with system prompt file: %s", prompt_name)
        return self

    def with_tools(self, tools: List[Tool]) -> "AgentBuilder":
        """Configure with a list of tools.

        Args:
            tools: List of Tool instances

        Returns:
            Self for chaining
        """
        self._tools = tools
        logger.debug("Configured agent with %d tools", len(tools))
        return self

    def with_tool(self, name: str, function: Callable) -> "AgentBuilder":
        """Add a single tool.

        Args:
            name: Name of the tool
            function: The tool function

        Returns:
            Self for chaining
        """
        self._tools.append(Tool(name=name, function=function))
        logger.debug("Added tool: %s", name)
        return self

    def with_result_type(self, result_type: Type[BaseModel]) -> "AgentBuilder":
        """Configure the result type for structured outputs.

        Args:
            result_type: Pydantic model type for agent results

        Returns:
            Self for chaining
        """
        self._result_type = result_type
        logger.debug("Configured agent with result type: %s", result_type.__name__)
        return self

    def with_deps_type(self, deps_type: Type[Any]) -> "AgentBuilder":
        """Configure the dependencies type.

        Args:
            deps_type: Type for agent dependencies/context

        Returns:
            Self for chaining
        """
        self._deps_type = deps_type
        logger.debug("Configured agent with deps type: %s", deps_type.__name__)
        return self

    def build(self) -> Agent:
        """Build the configured agent.

        Returns:
            Configured Agent instance

        Raises:
            ValueError: If required configuration is missing
        """
        if self._model is None:
            raise ValueError("Model must be configured before building agent")

        if self._system_prompt is None:
            raise ValueError("System prompt must be configured before building agent")

        # Create agent with configuration
        agent = Agent(
            model=self._model,
            system_prompt=self._system_prompt,
            tools=self._tools if self._tools else None,
            result_type=self._result_type,
            deps_type=self._deps_type,
        )

        logger.info(
            "Built agent with model=%s, tools=%d, result_type=%s",
            self._model.__class__.__name__,
            len(self._tools),
            self._result_type.__name__,
        )

        return agent
