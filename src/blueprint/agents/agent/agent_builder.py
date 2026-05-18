"""Builder for creating and configuring AI agents without inheritance."""

import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.run import AgentRunResult

from .agent_runtime import AgentRuntime
from ..clients.ai.ai_client_base import AIClientBase
from ..clients.ai.openai_client import OpenAIClient
from ..clients.ai.vllm_client import VLLMClient
from ..config import Config
from ..models.config import AIConfig
from .metrics import MetricsExtractor, MetricsRecorder
from .prompt_loader import PromptLoader

logger: logging.Logger = logging.getLogger(__name__)

_CLIENT_MAP: dict[str, type[AIClientBase]] = {
    "vllm": VLLMClient,
    "openai": OpenAIClient,
}

_AGENT_SIGNATURE = inspect.signature(Agent)
_BUILDER_ARGS = frozenset(["model", "system_prompt", "tools"])


class AgentBuilder:
    """Builder for creating configured AI agents.

    This builder allows handlers to create agents with custom configuration
    without requiring inheritance or abstract methods.

    Example:
        # Simple agent
        agent = await (
            AgentBuilder(config)
            .with_model_from_config()
            .with_system_prompt("system")
            .build()
        )

        # Fully configured agent
        agent = await (
            AgentBuilder(config, runtime_name="invoice_analyzer")
            .with_model_from_config()
            .with_system_prompt("invoice_analyzer_system")
            .with_tools([calculate_tool, validate_tool])
            .with_result_type(InvoiceOutput)
            .build()
        )
    """

    def __init__(
        self,
        config: Config,
        runtime_name: str = "default",
        meter: Any | None = None,
        package_root: Path | str | None = None,
    ):
        """Initialize the agent builder.

        Args:
            config: Application configuration
            runtime_name: Name for runtime-specific config lookup
            meter: Optional OpenTelemetry Meter for metrics recording
            package_root: Optional root path for the package (e.g., where main.py resides).
                         Used to locate prompts in package_root/prompts directory.
        """
        self._config = config
        self._runtime_name = runtime_name
        self._ai_config: AIConfig | None = None
        self._ai_client: AIClientBase | None = None
        self._system_prompt: str | None = None
        self._tools: list[Tool] = []
        self._result_type: type[BaseModel] = BaseModel
        self._deps_type: type[Any] = type(None)
        self._meter = meter
        self._package_root = Path(package_root) if package_root else ""
        self._metrics_enabled: bool = True
        self._recorder: MetricsRecorder | None = None
        self._built: bool = False

    def with_model_from_config(self, model_name: str = "", runtime_name: str = "") -> "AgentBuilder":
        """Configure the model from application config.

        Args:
            model_name: Optional model name override. If omitted, uses the value from config.
            runtime_name: Deprecated. Set the runtime in the constructor instead.

        Returns:
            Self for chaining
        """
        if runtime_name:
            logger.warning("Deprecation warning: runtime_name is not necessary anymore. Set the runtime in constructor instead.")

        ai_config = self._config.get_ai_config(self._runtime_name)

        if model_name:
            ai_config.model_name = model_name

        if not ai_config.model_name:
            raise ValueError(f"No model name for runtime agent '{self._runtime_name}' configured")

        if not ai_config.provider:
            raise ValueError(f"No provider for runtime agent '{self._runtime_name}' configured")

        if ai_config.provider not in _CLIENT_MAP:
            raise ValueError(f"Unsupported provider: '{ai_config.provider}'. Supported: {list(_CLIENT_MAP.keys())}")

        self._ai_config = ai_config
        logger.info("Configured agent with provider=%s, model=%s", ai_config.provider, ai_config.model_name)
        return self

    def with_system_prompt(self, name: str | None = None) -> "AgentBuilder":
        """Configure the system prompt by name.

        Args:
            name: Name of the system prompt file, or None to use default 'system'

        Returns:
            Self for chaining
        """
        if name is None:
            logger.warning("System prompt name is None, using default 'system'")
            name = "system"

        self._system_prompt = name
        logger.info("Configured agent with system prompt: '%s'", name)
        return self

    def with_tools(self, tools: list[Tool]) -> "AgentBuilder":
        """Configure with a list of tools.

        Args:
            tools: List of Tool instances

        Returns:
            Self for chaining
        """
        self._tools = tools
        logger.info("Configured agent with %d tools", len(tools))
        return self

    def with_tool(self, name: str, function: Callable[..., Any]) -> "AgentBuilder":
        """Add a single tool.

        Args:
            name: Name of the tool
            function: The tool function

        Returns:
            Self for chaining
        """
        self._tools.append(Tool(name=name, function=function))
        logger.info("Added tool: %s", name)
        return self

    def with_result_type(self, result_type: type[BaseModel]) -> "AgentBuilder":
        """Configure the result type for structured outputs.

        Args:
            result_type: Pydantic model type for agent results

        Returns:
            Self for chaining
        """
        self._result_type = result_type
        logger.info("Configured agent with result type: %s", result_type.__name__)
        return self

    def with_deps_type(self, deps_type: type[Any]) -> "AgentBuilder":
        """Configure the dependencies type.

        Args:
            deps_type: Type for agent dependencies/context

        Returns:
            Self for chaining
        """
        self._deps_type = deps_type
        logger.info("Configured agent with deps type: %s", deps_type.__name__)
        return self

    def with_metrics(self, enabled: bool = True) -> "AgentBuilder":
        """Configure whether metrics logging is enabled.

        Args:
            enabled: Whether to enable metrics logging (default: True)

        Returns:
            Self for chaining
        """
        self._metrics_enabled = enabled
        logger.info("Metrics logging %s", "enabled" if enabled else "disabled")
        return self

    def get_model_settings(self) -> dict[str, Any]:
        """Get model settings for use in agent.run() calls.

        Returns:
            ModelSettings object with configuration from runtime settings
        """
        ai_config = self._config.get_ai_config(self._runtime_name)
        settings: dict[str, Any] = {}

        if ai_config.max_tokens is not None:
            settings["max_tokens"] = ai_config.max_tokens
            logger.debug("Model settings: max_tokens=%d", ai_config.max_tokens)

        if ai_config.temperature is not None:
            settings["temperature"] = ai_config.temperature
            logger.debug("Model settings: temperature=%.2f", ai_config.temperature)

        return settings

    def build(self, **kwargs: Any) -> AgentRuntime:
        """Build the configured agent.

        Creates the model and resolves the system prompt.

        Args:
            **kwargs: Additional keyword arguments for instantiating the agent

        Returns:
            Configured AgentRuntime instance

        Raises:
            ValueError: If required configuration is missing
        """
        if self._ai_config is None:
            raise ValueError("Model must be configured before building agent. Call with_model_from_config() first.")

        if self._built:
            raise RuntimeError("AgentBuilder.build() has already been called. Create a new builder instance.")

        # Create AI client Component — registers in registry; model is created in AgentRuntime.on_startup()
        self._ai_client = _CLIENT_MAP[self._ai_config.provider](self._runtime_name)  # type: ignore[index]

        # Resolve system prompt either from explicit configuration or runtime config defaults
        prompt_name = self._system_prompt
        if prompt_name is None:
            try:
                prompt_config = self._config.get_prompt_config(self._runtime_name)
                prompt_name = prompt_config.system_prompt_name
            except Exception as exc:
                raise ValueError(
                    "System prompt must be configured before building agent. "
                    "Either call with_system_prompt() or configure system_prompt_name in settings."
                ) from exc

        if not prompt_name:
            raise ValueError(
                "System prompt must be configured before building agent. "
                "Either call with_system_prompt() or configure system_prompt_name in settings."
            )

        try:
            self._system_prompt = PromptLoader.load_prompt(
                prompt_name,
                self._config,
                path=self._package_root,
                provider=self._ai_config.provider,  # type: ignore[arg-type]
            )
        except Exception as e:
            raise ValueError(
                f"Failed to load system prompt '{prompt_name}' – ensure the prompt file exists or call with_system_prompt()."
            ) from e

        # Check for unexpected kwargs
        if kwargs:
            for kwarg in kwargs:
                if kwarg in _BUILDER_ARGS:
                    raise ValueError(f"The Agent argument '{kwarg}' is set by the builder and cannot be given for instantiation")

            allowed = {name for name in _AGENT_SIGNATURE.parameters if name not in _BUILDER_ARGS}
            for kwarg in kwargs:
                if kwarg not in allowed:
                    raise ValueError(f"Unexpected keyword argument for Agent: {kwarg}")

        runtime = AgentRuntime(
            system_prompt=self._system_prompt,
            tools=self._tools if self._tools else [],
            **kwargs,
        )
        runtime._ai_client = self._ai_client

        self._built = True
        if self._metrics_enabled:
            self._recorder = MetricsRecorder(self._config, self._meter)
            runtime._recorder = self._recorder

        runtime._model_settings = self.get_model_settings()  # type: ignore[assignment]

        logger.info(
            "Built agent with provider=%s, model=%s, tools=%d, result_type=%s",
            self._ai_config.provider,
            self._ai_config.model_name,
            len(self._tools),
            self._result_type.__name__,
        )

        return runtime

    @staticmethod
    def extract_response_text(result: AgentRunResult) -> str:
        """Extract response text from an agent result.

        Args:
            result: The agent result object

        Returns:
            The response text as a string
        """
        return MetricsExtractor.extract_response_text(result)

    @staticmethod
    def extract_usage_info(result: AgentRunResult) -> dict[str, Any]:
        """Extract usage information from an agent result.

        Args:
            result: The AgentRunResult object from agent.run()

        Returns:
            Dictionary with usage information
        """
        return MetricsExtractor.extract_usage_info(result)
