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
from .agent_runtime import AgentRuntime
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
        self._prompts: dict[str, str] = {}
        self._meter = meter
        self._package_root = Path(package_root) if package_root else None

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
        logger.debug("Configured agent with model: %s", model_name)
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
        logger.debug(
            "Configured agent with model from config '%s': %s",
            name,
            ai_config.model_name,
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

    def with_system_prompt_file(self, prompt_name: str, runtime_name: str | None = None) -> "AgentBuilder":
        """Configure with a system prompt from file.

        Args:
            prompt_name: Name of the prompt file (without extension)
            runtime_name: Runtime name for config lookup, or None to use builder's runtime_name

        Returns:
            Self for chaining
        """
        name = runtime_name or self._runtime_name
        prompt_config = self._config.get_prompt_config(name)
        self._system_prompt = PromptLoader.load_prompt(prompt_name, self.__class__, prompt_config, self._package_root)
        logger.debug("Configured agent with system prompt file: %s", prompt_name)
        return self

    def with_system_prompt_from_config(self, runtime_name: str | None = None) -> "AgentBuilder":
        """Configure with system prompt from config-specified file.

        Uses the system_prompt_name from PromptConfig to load the prompt file.

        Args:
            runtime_name: Runtime name for config lookup, or None to use builder's runtime_name

        Returns:
            Self for chaining
        """
        name = runtime_name or self._runtime_name
        prompt_config = self._config.get_prompt_config(name)
        self._system_prompt = PromptLoader.load_prompt(prompt_config.system_prompt_name, self.__class__, prompt_config, self._package_root)
        logger.debug(
            "Configured agent with system prompt from config: %s",
            prompt_config.system_prompt_name,
        )
        return self

    def with_prompt(self, prompt_name: str, runtime_name: str | None = None) -> "AgentBuilder":
        """Register a named prompt from file.

        Loads a prompt file and stores it by name for later retrieval.
        The prompt will be available on the runtime via runtime.prompts[prompt_name].

        Args:
            prompt_name: Name of the prompt file (without extension)
            runtime_name: Runtime name for config lookup, or None to use builder's runtime_name

        Returns:
            Self for chaining
        """
        name = runtime_name or self._runtime_name
        prompt_config = self._config.get_prompt_config(name)
        prompt_content = PromptLoader.load_prompt(prompt_name, self.__class__, prompt_config, self._package_root)
        self._prompts[prompt_name] = prompt_content
        logger.debug("Registered prompt: %s", prompt_name)
        return self

    def with_tools(self, tools: list[Tool]) -> "AgentBuilder":
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

    def with_result_type(self, result_type: type[BaseModel]) -> "AgentBuilder":
        """Configure the result type for structured outputs.

        Args:
            result_type: Pydantic model type for agent results

        Returns:
            Self for chaining
        """
        self._result_type = result_type
        logger.debug("Configured agent with result type: %s", result_type.__name__)
        return self

    def with_deps_type(self, deps_type: type[Any]) -> "AgentBuilder":
        """Configure the dependencies type.

        Args:
            deps_type: Type for agent dependencies/context

        Returns:
            Self for chaining
        """
        self._deps_type = deps_type
        logger.debug("Configured agent with deps type: %s", deps_type.__name__)
        return self

    def build(self, **kwargs) -> AgentRuntime:
        """Build the configured agent.

        Args:
            **kwargs: Additional keyword arguments for instantiating the agent

        Returns:
            Configured AgentRuntime instance with prompt handling capabilities

        Raises:
            ValueError: If required configuration is missing
        """
        if self._model is None:
            raise ValueError("Model must be configured before building agent")

        if self._system_prompt is None:
            raise ValueError("System prompt must be configured before building agent")

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

        # Create agent runtime with configuration and registered prompts
        runtime = AgentRuntime[self._deps_type](  # type: ignore[misc]
            model=self._model,
            system_prompt=self._system_prompt,
            tools=self._tools if self._tools else [],
            prompts=self._prompts.copy(),
            config=self._config,
            runtime_name=self._runtime_name,
            package_root=self._package_root,
            **kwargs,
        )

        # Attach metrics recording method to the agent runtime
        runtime.record_metrics = self._create_metrics_recorder()  # type: ignore[attr-defined]

        logger.info(
            "Built agent with model=%s, tools=%d, result_type=%s, prompts=%d",
            self._model.__class__.__name__,
            len(self._tools),
            self._result_type.__name__,
            len(self._prompts),
        )

        return runtime

    def _create_metrics_recorder(self) -> Any:
        """Create a metrics recorder function bound to this builder instance.

        Returns a callable that records metrics when called with agent result and duration.
        This is attached to the agent instance for easy access.

        Returns:
            A callable that records metrics: record_metrics(result, duration_ms, model_name)
        """

        def record_metrics_impl(result: AgentRunResult, duration_ms: float, model_name: str | None = None) -> None:
            """Record metrics for an agent execution.

            Args:
                result: The AgentRunResult from agent.run()
                duration_ms: Response time in milliseconds
                model_name: Model name (optional, uses configured model if not provided)
            """
            model = model_name or (self._model.model_name if hasattr(self._model, "model_name") else "unknown")
            self.record_metrics(result, duration_ms, model)

        return record_metrics_impl

    def record_metrics(
        self,
        result: AgentRunResult,
        duration_ms: float,
        model_name: str,
    ) -> None:
        """Record LLM metrics to logs and OpenTelemetry.

        Always logs token usage and response latency metrics. Records to OpenTelemetry
        only if both otel_enabled and token_metrics_enabled are True in config.

        Args:
            result: The AgentRunResult object from agent.run()
            duration_ms: Response time in milliseconds
            model_name: Name of the LLM model (e.g., "gpt-4o-mini")

        Behavior:
            - Usage information is ALWAYS logged to application logs
            - OpenTelemetry recording only happens if:
              - otel_enabled=True AND token_metrics_enabled=True in config
              - AND meter is provided to AgentBuilder

        Example:
            import time

            start = time.time()
            result = await agent.run(prompt)
            duration_ms = (time.time() - start) * 1000
            agent.record_metrics(result, duration_ms, "gpt-4o-mini")
        """
        # Extract usage information
        usage = self.extract_usage_info(result)

        # ALWAYS log usage information
        if usage:
            logger.info(
                "LLM Metrics - Model: %s, Input tokens: %s, Output tokens: %s, Total tokens: %s, Response time: %.2fms (%.2fs)",
                model_name,
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                usage.get("total_tokens"),
                duration_ms,
                duration_ms / 1000.0,
            )
        else:
            logger.warning(
                "No usage information available for model: %s, Response time: %.2fms (%.2fs)", model_name, duration_ms, duration_ms / 1000.0
            )

        # Check if OpenTelemetry metrics should be recorded
        otel_metrics_enabled = False
        try:
            observability = self._config.get_observability_config()
            # OpenTelemetry metrics only recorded if both settings are enabled
            otel_metrics_enabled = observability.otel_enabled and observability.token_metrics_enabled
        except Exception as e:
            logger.warning("Error checking observability config: %s", str(e))

        # Record to OpenTelemetry if enabled and meter is provided
        if otel_metrics_enabled and self._meter is not None and usage:
            try:
                # Record token usage as counter
                token_counter = self._meter.create_counter(
                    name="llm.tokens.count",
                    description="Number of tokens processed by the LLM",
                    unit="tokens",
                )
                token_counter.add(
                    usage.get("total_tokens", 0),
                    {"model": model_name, "type": "total"},
                )

                # Record input tokens
                if usage.get("input_tokens"):
                    token_counter.add(
                        usage.get("input_tokens", 0),
                        {"model": model_name, "type": "prompt"},
                    )

                # Record output tokens
                if usage.get("output_tokens"):
                    token_counter.add(
                        usage.get("output_tokens", 0),
                        {"model": model_name, "type": "completion"},
                    )

                # Record response latency as histogram
                latency_histogram = self._meter.create_histogram(
                    name="llm.response.latency",
                    description="Distribution of LLM response times",
                    unit="ms",
                )
                latency_histogram.record(duration_ms, {"model": model_name})

                logger.debug("OpenTelemetry metrics recorded successfully")
            except Exception as e:
                logger.error("Error recording OpenTelemetry metrics: %s", str(e))
        elif not otel_metrics_enabled:
            logger.debug("OpenTelemetry metrics recording disabled (otel_enabled or token_metrics_enabled is False)")

    @staticmethod
    def extract_response_text(result: AgentRunResult) -> str:
        """Extract response text from an agent result.

        Handles different response types from Pydantic AI agents:
        - Structured responses with .data attribute
        - String responses wrapped in AgentRunResult with .output attribute
        - Plain string responses
        - Fallback to string representation

        Args:
            result: The agent result object

        Returns:
            The response text as a string

        Example:
            result = await agent.run(prompt)
            response_text = AgentBuilder.extract_response_text(result)
            data = json.loads(response_text)
        """
        # Try different attributes in order of preference
        if hasattr(result, "data"):
            return result.data
        elif hasattr(result, "output"):
            return result.output
        else:
            return str(result)

    @staticmethod
    def extract_usage_info(result: AgentRunResult) -> dict[str, Any]:
        """Extract usage information from an agent result.

        Extracts token counts and other usage metrics from the Pydantic AI agent result.
        The result object has a `usage` attribute (RunUsage) containing token information.

        Args:
            result: The AgentRunResult object from agent.run()

        Returns:
            Dictionary with usage information:
            - input_tokens: Tokens sent to the language model
            - output_tokens: Tokens generated by the model
            - total_tokens: Total tokens consumed (input + output)
            - requests: Number of model API calls

        Example:
            result = await agent.run(prompt)
            usage = AgentBuilder.extract_usage_info(result)
            logger.info("Tokens - Input: %d, Output: %d, Total: %d",
                       usage.get("input_tokens"),
                       usage.get("output_tokens"),
                       usage.get("total_tokens"))
        """
        usage_info: dict[str, Any] = {}

        # Extract from usage() method (RunUsage object from Pydantic AI)
        # Note: usage is a method, not an attribute
        if hasattr(result, "usage") and callable(result.usage):
            try:
                usage = result.usage()
                if usage is not None:
                    # RunUsage object has these attributes
                    if hasattr(usage, "input_tokens"):
                        usage_info["input_tokens"] = usage.input_tokens
                    if hasattr(usage, "output_tokens"):
                        usage_info["output_tokens"] = usage.output_tokens
                    if hasattr(usage, "total_tokens"):
                        usage_info["total_tokens"] = usage.total_tokens
                    if hasattr(usage, "requests"):
                        usage_info["requests"] = usage.requests
                else:
                    logger.info("Result.usage() returned None")
            except Exception as e:
                logger.info("Error calling result.usage(): %s", str(e))
        else:
            logger.info("Result object has no callable usage method")

        return usage_info
