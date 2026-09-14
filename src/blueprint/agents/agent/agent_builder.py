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

    Like ``AppBuilder``, a ``with_*()`` call **records**: no configuration is read and no
    component is created until ``build()``. That is what lets an unbuilt builder be declared
    where no configuration is in scope, and handed to ``AppBuilder.with_agent`` to be built
    later, inside its agent's namespace and against its agent's configuration view.

    Example:
        # Declared, and built by the application -- the form a grouped agent needs
        AppBuilder().with_agent(
            AgentBuilder(runtime_name="invoice_analyzer")
            .with_model_from_config()
            .with_system_prompt("invoice_analyzer_system")
        )

        # Built here, by the caller
        agent = (
            AgentBuilder(config)
            .with_model_from_config()
            .with_system_prompt("system")
            .build()
        )
    """

    def __init__(
        self,
        config: Config | None = None,
        runtime_name: str = "default",
        meter: Any | None = None,
        package_root: Path | str | None = None,
    ):
        """Initialize the agent builder.

        Args:
            config: Application configuration. **Optional**, and omitting it is what makes this
                builder declarable: ``AgentBuilder.__init__`` used to require one, while
                ``Component._shared_config`` deliberately has no public read path, so in a
                ``main.py`` that only declares -- which is every grouped agent -- there was no
                configuration to pass and this class could not be used at all. Pass it to
                :meth:`build` instead, or let ``AppBuilder`` pass the agent's own view.
            runtime_name: Name for runtime-specific config lookup
            meter: Optional OpenTelemetry Meter for metrics recording
            package_root: Optional root path for the package (e.g., where main.py resides).
                         Used to locate prompts in package_root/prompts directory.
        """
        self._config: Config | None = config
        self._runtime_name = runtime_name
        self._ai_config: AIConfig | None = None
        self._ai_client: AIClientBase | None = None
        self._model_from_config: bool = False
        self._model_name_override: str = ""
        self._system_prompt: str | None = None
        self._tools: list[Tool] = []
        self._result_type: type[BaseModel] = BaseModel
        self._deps_type: type[Any] = type(None)
        self._meter = meter
        self._package_root = Path(package_root) if package_root else ""
        self._metrics_enabled: bool = True
        self._recorder: MetricsRecorder | None = None
        self._built: bool = False

    @property
    def runtime_name(self) -> str:
        """Which runtime's configuration section this agent reads.

        Public because the application names the agent in its logs before it is built: an
        ``AgentBuilder`` handed to ``AppBuilder.with_agent`` is a declaration, and a failure
        while building it has to be able to say which one.
        """
        return self._runtime_name

    def _require_config(self) -> Config:
        """Return the configuration, which exists only once one has been supplied.

        Raises:
            ValueError: if neither ``__init__`` nor ``build()`` was given one. Named rather
                than defaulted: an ``AgentBuilder`` always sits inside an application that has
                a configuration, so a missing one is a wiring mistake and not a case to guess
                a settings file for.
        """
        if self._config is None:
            raise ValueError(
                f"AgentBuilder for runtime '{self._runtime_name}' has no configuration: none was given to "
                "AgentBuilder(config) and none to build(config). Pass one to either -- or hand the unbuilt "
                "builder to AppBuilder.with_agent(), which builds it with its agent's own configuration view."
            )
        return self._config

    def _resolve_config(self, config: Config | None) -> Config:
        """Settle which configuration to build against.

        ``build(config)`` **wins** over ``AgentBuilder(config)``, which is the opposite of
        ``AppBuilder``'s rule and deliberately so. An ``AppBuilder`` is the application, so
        nothing above it knows better and two configurations mean the author is confused. An
        ``AgentBuilder`` sits *inside* an application, and what the application passes is the
        view scoped to this agent's namespace (C5) -- the whole point of D6. A constructor
        argument is a convenience for the standalone ``AgentBuilder(config)...build()`` chain,
        so it yields to the scoped view rather than overriding it.

        At the root ``for_namespace("")`` returns the loader itself, so for a single-agent
        application the two are the same object and there is nothing to choose between.
        """
        if config is None:
            return self._require_config()
        if self._config is not None and self._config is not config:
            logger.debug(
                "AgentBuilder for runtime '%s' was given a configuration in its constructor and another to build(); "
                "building against the one passed to build(), which is the view scoped to this agent",
                self._runtime_name,
            )
        self._config = config
        return config

    def with_model_from_config(self, model_name: str = "", runtime_name: str = "") -> "AgentBuilder":
        """Take the model from application configuration when the agent is built.

        Records the intent; the configuration is read in :meth:`build`. It has to be, because
        there may be no configuration yet -- and in a group the one that matters is the view
        scoped to this agent, which only the application can supply. So the three refusals
        this used to raise here (no model name, no provider, unsupported provider) now raise
        from ``build()``, naming the same runtime.

        Args:
            model_name: Optional model name override. If omitted, uses the value from config.
            runtime_name: Deprecated. Set the runtime in the constructor instead.

        Returns:
            Self for chaining
        """
        if runtime_name:
            logger.warning("Deprecation warning: runtime_name is not necessary anymore. Set the runtime in constructor instead.")

        self._model_from_config = True
        self._model_name_override = model_name
        return self

    def _resolve_ai_config(self) -> AIConfig:
        """Read this runtime's AI configuration and check it can produce a client.

        Raises:
            ValueError: if the model name or provider is missing, or the provider is one this
                framework has no client for.
        """
        ai_config = self._require_config().get_ai_config(self._runtime_name)

        if self._model_name_override:
            ai_config.model_name = self._model_name_override

        if not ai_config.model_name:
            raise ValueError(f"No model name for runtime agent '{self._runtime_name}' configured")

        if not ai_config.provider:
            raise ValueError(f"No provider for runtime agent '{self._runtime_name}' configured")

        if ai_config.provider not in _CLIENT_MAP:
            raise ValueError(f"Unsupported provider: '{ai_config.provider}'. Supported: {list(_CLIENT_MAP.keys())}")

        logger.info("Configured agent with provider=%s, model=%s", ai_config.provider, ai_config.model_name)
        return ai_config

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

        Raises:
            ValueError: if no configuration has been supplied yet. See
                :meth:`_require_config`; ``build()`` adopts the one it is given before calling
                this, so a built agent's settings are always read from the right tree.
        """
        ai_config = self._require_config().get_ai_config(self._runtime_name)
        settings: dict[str, Any] = {}

        if ai_config.max_tokens is not None:
            settings["max_tokens"] = ai_config.max_tokens
            logger.debug("Model settings: max_tokens=%d", ai_config.max_tokens)

        if ai_config.temperature is not None:
            settings["temperature"] = ai_config.temperature
            logger.debug("Model settings: temperature=%.2f", ai_config.temperature)

        return settings

    def build(self, config: Config | None = None, **kwargs: Any) -> AgentRuntime:
        """Build the configured agent.

        Reads the configuration, creates the AI client and resolves the system prompt. Nothing
        before this point touched configuration or created a component, which is what lets the
        application decide *when* and *against which configuration view* an agent is built.

        Args:
            config: The configuration to build against. Wins over the one given to
                ``__init__`` -- see :meth:`_resolve_config` for why the precedence runs this
                way round. ``AppBuilder`` passes the view scoped to this agent's namespace.
            **kwargs: Additional keyword arguments for instantiating the agent

        Returns:
            Configured AgentRuntime instance

        Raises:
            ValueError: If required configuration is missing
            RuntimeError: If this builder has already been built
        """
        if self._built:
            raise RuntimeError("AgentBuilder.build() has already been called. Create a new builder instance.")

        resolved_config = self._resolve_config(config)

        if not self._model_from_config:
            raise ValueError("Model must be configured before building agent. Call with_model_from_config() first.")

        self._ai_config = self._resolve_ai_config()

        # Create AI client Component — registers in registry; model is created in AgentRuntime.on_startup()
        self._ai_client = _CLIENT_MAP[self._ai_config.provider](self._runtime_name)  # type: ignore[index]

        # Resolve system prompt either from explicit configuration or runtime config defaults
        prompt_name = self._system_prompt
        if prompt_name is None:
            try:
                prompt_config = resolved_config.get_prompt_config(self._runtime_name)
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
                resolved_config,
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
            self._recorder = MetricsRecorder(resolved_config, self._meter)
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
