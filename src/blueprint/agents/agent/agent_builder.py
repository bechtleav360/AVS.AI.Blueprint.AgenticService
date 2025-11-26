"""Builder for creating and configuring AI agents without inheritance."""

import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.models import Model
from pydantic_ai.run import AgentRunResult

from ..config import Config
from ..base import AgentRuntime
from .metrics import MetricsExtractor, MetricsRecorder
from .model_provider import ModelProviderFactory
from .prompt_loader import PromptLoader

logger: logging.Logger = logging.getLogger(__name__)


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
        self._model: Model | None = None
        self._system_prompt: str | None = None
        self._tools: list[Tool] = []
        self._result_type: type[BaseModel] = BaseModel
        self._deps_type: type[Any] = type(None)
        self._meter = meter
        self._package_root = Path(package_root) if package_root else None
        self._metrics_enabled: bool = True

    def with_model(self, model_name: str) -> "AgentBuilder":
        """Configure with a specific model name.

        Args:
            model_name: Name of the model (e.g., "gpt-4", "claude-3")

        Returns:
            Self for chaining
        """
        ai_config = self._config.get_ai_config(self._runtime_name)
        # Create a modified copy with the new model_name
        ai_config_dict = ai_config.model_dump()
        ai_config_dict["model_name"] = model_name
        self._model = ModelProviderFactory.create_model(ai_config_dict)
        logger.info("Configured agent with model: %s", model_name)
        return self

    def with_model_from_config(self, runtime_name: str | None = None) -> "AgentBuilder":
        """Configure model from runtime-specific config.

        Args:
            runtime_name: Runtime name to lookup config, or None to use builder's runtime_name

        Returns:
            Self for chaining
        """
        name = runtime_name or self._runtime_name
        ai_config = self._config.get_ai_config(name)
        self._model = ModelProviderFactory.create_model(ai_config)
        logger.info(
            "Configured agent with model from config '%s': %s",
            name,
            ai_config.model_name,
        )
        return self

    def with_system_prompt(self, name: str | None = None) -> "AgentBuilder":
        """Configure the system prompt.

        Can be used in two ways:
        1. With text: .with_system_prompt("You are an assistant")
        2. Load from config: .with_system_prompt() or .with_system_prompt(None)

        Args:
            name: Name of the system prompt, or None to load from config

        Returns:
            Self for chaining
        """
        if name is None:
            # Load from config
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

    def with_tool(self, name: str, function: Callable) -> "AgentBuilder":
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

        Controls whether token usage and response latency metrics are logged
        and recorded to OpenTelemetry.

        Args:
            enabled: Whether to enable metrics logging (default: True)

        Returns:
            Self for chaining
        """
        self._metrics_enabled = enabled
        logger.info("Metrics logging %s", "enabled" if enabled else "disabled")
        return self

    def build(self, **kwargs) -> AgentRuntime:
        """Build the configured agent.

        If no system prompt is configured, automatically loads it from config.

        Args:
            **kwargs: Additional keyword arguments for instantiating the agent

        Returns:
            Configured AgentRuntime instance with prompt handling capabilities

        Raises:
            ValueError: If required configuration is missing
        """
        if self._model is None:
            raise ValueError("Model must be configured before building agent")

        # Auto-load system prompt from config if not already set
        if self._system_prompt is not None:
            try:
                self._system_prompt = PromptLoader.load_prompt(
                    self._system_prompt,
                    self._config,
                    self._package_root,
                )
            except Exception as e:
                raise ValueError(
                    f"System prompt must be configured before building agent. "
                    f"Either call with_system_prompt() or ensure system_prompt_name is configured. Error: {e}"
                ) from e

        # Check for unexpected kwargs
        if kwargs:
            # Get parameters from Agent constructor
            sig = inspect.signature(Agent)

            # List of arguments set by builder
            builder_args = ["model", "system_prompt", "tools"]

            # Check for not allowed kwargs
            for kwarg in kwargs:
                if kwarg in builder_args:
                    raise ValueError(f"The Agent argument '{kwarg}' is set by the builder and cannot be given for instantiation")

            # Remove arguments set by builder
            filtered_parameters = {name: param for name, param in sig.parameters.items() if name not in builder_args}
            for kwarg in kwargs:
                if kwarg not in filtered_parameters:
                    raise ValueError(f"Unexpected keyword argument for Agent: {kwarg}")

        # Create agent runtime with configuration
        runtime = AgentRuntime[self._deps_type](  # type: ignore[misc]
            model=self._model,
            system_prompt=self._system_prompt,
            tools=self._tools if self._tools else [],
            config=self._config,
            runtime_name=self._runtime_name,
            **kwargs,
        )

        # Attach metrics recording method to the agent runtime
        runtime.record_metrics = self._create_metrics_recorder()  # type: ignore[attr-defined]

        logger.info(
            "Built agent with model=%s, tools=%d, result_type=%s",
            self._model.__class__.__name__,
            len(self._tools),
            self._result_type.__name__,
        )

        return runtime

    def _create_metrics_recorder(self) -> Any:
        """Create a metrics recorder function bound to this builder instance.

        Returns a callable that records metrics when called with agent result and duration.
        This is attached to the agent instance for easy access.

        Returns:
            A callable that records metrics: record_metrics(result, duration_ms, model_name)
            or a no-op function if metrics are disabled.
        """
        if not self._metrics_enabled:
            # Return a no-op function if metrics are disabled
            def noop_recorder(result: AgentRunResult, duration_ms: float, model_name: str | None = None) -> None:
                pass

            return noop_recorder

        recorder = MetricsRecorder(self._config, self._meter, self._model)

        def record_metrics_impl(result: AgentRunResult, duration_ms: float, model_name: str | None = None) -> None:
            """Record metrics for an agent execution.

            Args:
                result: The AgentRunResult from agent.run()
                duration_ms: Response time in milliseconds
                model_name: Model name (optional, uses configured model if not provided)
            """
            model = model_name or (self._model.model_name if hasattr(self._model, "model_name") else "unknown")
            recorder.record(result, duration_ms, model)

        return record_metrics_impl

    def record_metrics(
        self,
        result: AgentRunResult,
        duration_ms: float,
        model_name: str,
    ) -> None:
        """Record LLM metrics to logs and OpenTelemetry.

        Delegates to MetricsRecorder for actual recording if metrics are enabled.
        Does nothing if metrics are disabled via with_metrics(False).

        Args:
            result: The AgentRunResult object from agent.run()
            duration_ms: Response time in milliseconds
            model_name: Name of the LLM model (e.g., "gpt-4o-mini")
        """
        if not self._metrics_enabled:
            return

        recorder = MetricsRecorder(self._config, self._meter, self._model)
        recorder.record(result, duration_ms, model_name)

    @staticmethod
    def extract_response_text(result: AgentRunResult) -> str:
        """Extract response text from an agent result.

        Delegates to MetricsExtractor.

        Args:
            result: The agent result object

        Returns:
            The response text as a string
        """
        return MetricsExtractor.extract_response_text(result)

    @staticmethod
    def extract_usage_info(result: AgentRunResult) -> dict[str, Any]:
        """Extract usage information from an agent result.

        Delegates to MetricsExtractor.

        Args:
            result: The AgentRunResult object from agent.run()

        Returns:
            Dictionary with usage information
        """
        return MetricsExtractor.extract_usage_info(result)
