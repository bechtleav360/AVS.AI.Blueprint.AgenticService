"""Decorator class for Pydantic AI Agent with enhanced functionality.

This module provides a decorator pattern implementation that wraps a Pydantic AI Agent
with additional features like prompt name resolution and prompt directory management.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Sequence

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.run import AgentRunResult
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import AgentDepsT

if TYPE_CHECKING:
    from pydantic_ai.agent.abstract import EventStreamHandler, Instructions
    from pydantic_ai.messages import ModelMessage, UserContent
    from pydantic_ai.run import AgentRun
    from pydantic_ai.tools import DeferredToolResults
    from pydantic_ai.usage import RunUsage, UsageLimits

logger: logging.Logger = logging.getLogger(__name__)


class AgentDecorator(Agent[AgentDepsT, Any]):
    """Decorator class that wraps a Pydantic AI Agent with enhanced functionality.

    This class implements the decorator pattern to wrap an Agent instance while
    maintaining full compatibility with the Agent interface. It adds:
    - Prompt name resolution (prompt_name parameter in run methods)
    - Prompt directory management
    - Registered prompts dictionary

    The decorator delegates all Agent methods to the wrapped instance while
    providing enhanced functionality for prompt handling.

    Example:
        ```python
        from blueprint.agents import AgentBuilder, AgentDecorator
        from blueprint.agents.config import Config

        config = Config("settings.toml")
        agent = (
            AgentBuilder(config)
            .with_model("gpt-4")
            .with_system_prompt_text("You are helpful")
            .with_prompt("analyze", "default")
            .build()
        )

        # Wrap with decorator for enhanced functionality
        decorated_agent = AgentDecorator(agent, prompt_directory="src/prompts")

        # Use with prompt_name
        result = await decorated_agent.run(prompt_name="analyze")
        ```
    """

    def __init__(
        self,
        agent: Agent[AgentDepsT, Any],
        prompt_directory: str | Path | None = None,
    ) -> None:
        """Initialize the agent decorator.

        Args:
            agent: The Pydantic AI Agent instance to wrap
            prompt_directory: Optional directory path for prompt files
        """
        self._wrapped_agent = agent
        self._prompt_directory = Path(prompt_directory) if prompt_directory else None

        # Copy attributes from wrapped agent for compatibility
        self._model = agent._model
        self._name = agent._name
        self.end_strategy = agent.end_strategy
        self.model_settings = agent.model_settings
        self._output_type = agent._output_type
        self.instrument = agent.instrument
        self._deps_type = agent._deps_type
        self._output_schema = agent._output_schema
        self._output_validators = agent._output_validators
        self._instructions = agent._instructions
        self._system_prompts = agent._system_prompts
        self._system_prompt_functions = agent._system_prompt_functions
        self._system_prompt_dynamic_functions = agent._system_prompt_dynamic_functions
        self._max_result_retries = agent._max_result_retries
        self._max_tool_retries = agent._max_tool_retries
        self._builtin_tools = agent._builtin_tools
        self._prepare_tools = agent._prepare_tools
        self._prepare_output_tools = agent._prepare_output_tools
        self._output_toolset = agent._output_toolset
        self._function_toolset = agent._function_toolset
        self._dynamic_toolsets = agent._dynamic_toolsets
        self._user_toolsets = agent._user_toolsets
        self.history_processors = agent.history_processors
        self._event_stream_handler = agent._event_stream_handler
        self._override_name = agent._override_name
        self._override_deps = agent._override_deps
        self._override_model = agent._override_model
        self._override_toolsets = agent._override_toolsets
        self._override_tools = agent._override_tools
        self._override_instructions = agent._override_instructions
        self._enter_lock = agent._enter_lock
        self._entered_count = agent._entered_count
        self._exit_stack = agent._exit_stack

        # Copy custom attributes if present
        if hasattr(agent, "prompts"):
            self.prompts = agent.prompts  # type: ignore[attr-defined]
        else:
            self.prompts = {}  # type: ignore[attr-defined]

        if hasattr(agent, "record_metrics"):
            self.record_metrics = agent.record_metrics  # type: ignore[attr-defined]

        logger.debug(
            "Created AgentDecorator wrapping agent with prompt_directory=%s",
            self._prompt_directory,
        )

    @property
    def wrapped_agent(self) -> Agent[AgentDepsT, Any]:
        """Get the wrapped agent instance."""
        return self._wrapped_agent

    @property
    def prompt_directory(self) -> Path | None:
        """Get the prompt directory path."""
        return self._prompt_directory

    @property
    def model(self) -> Model | str | None:
        """The default model configured for this agent."""
        return self._wrapped_agent.model

    @model.setter
    def model(self, value: Model | str | None) -> None:
        """Set the default model configured for this agent."""
        self._wrapped_agent.model = value
        self._model = value

    @property
    def name(self) -> str | None:
        """The name of the agent, used for logging."""
        return self._wrapped_agent.name

    @name.setter
    def name(self, value: str | None) -> None:
        """Set the name of the agent, used for logging."""
        self._wrapped_agent.name = value
        self._name = value

    @property
    def deps_type(self) -> type:
        """The type of dependencies used by the agent."""
        return self._wrapped_agent.deps_type

    @property
    def output_type(self) -> Any:
        """The type of data output by agent runs."""
        return self._wrapped_agent.output_type

    @property
    def event_stream_handler(self) -> EventStreamHandler[AgentDepsT] | None:
        """Optional handler for events from the model's streaming response."""
        return self._wrapped_agent.event_stream_handler

    def __repr__(self) -> str:
        """Return string representation of the decorator."""
        return f"{type(self).__name__}(" f"wrapped_agent={self._wrapped_agent!r}, " f"prompt_directory={self._prompt_directory!r})"

    # Delegation methods for Agent interface

    def override(self, **kwargs: Any) -> Any:
        """Context manager to temporarily override agent settings.

        Delegates to wrapped agent's override method.
        """
        return self._wrapped_agent.override(**kwargs)

    def instructions(self, func: Any = None, /) -> Any:
        """Decorator to register an instructions function.

        Delegates to wrapped agent's instructions method.
        """
        return self._wrapped_agent.instructions(func)

    def system_prompt(self, func: Any = None, /, **kwargs: Any) -> Any:
        """Decorator to register a system prompt function.

        Delegates to wrapped agent's system_prompt method.
        """
        return self._wrapped_agent.system_prompt(func, **kwargs)

    def output_validator(self, func: Any, /) -> Any:
        """Decorator to register an output validator function.

        Delegates to wrapped agent's output_validator method.
        """
        return self._wrapped_agent.output_validator(func)

    def tool(self, func: Any = None, /, **kwargs: Any) -> Any:
        """Decorator to register a tool function.

        Delegates to wrapped agent's tool method.
        """
        return self._wrapped_agent.tool(func, **kwargs)

    def tool_plain(self, func: Any = None, /, **kwargs: Any) -> Any:
        """Decorator to register a plain tool function.

        Delegates to wrapped agent's tool_plain method.
        """
        return self._wrapped_agent.tool_plain(func, **kwargs)

    def toolset(self, func: Any = None, /, **kwargs: Any) -> Any:
        """Decorator to register a toolset function.

        Delegates to wrapped agent's toolset method.
        """
        return self._wrapped_agent.toolset(func, **kwargs)

    async def run(
        self,
        user_prompt: str | Sequence[UserContent] | None = None,
        *,
        prompt_name: str | None = None,
        message_history: Sequence[ModelMessage] | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
        model: Model | str | None = None,
        instructions: Instructions[AgentDepsT] | None = None,
        deps: AgentDepsT | None = None,
        model_settings: ModelSettings | None = None,
        usage_limits: UsageLimits | None = None,
        usage: RunUsage | None = None,
        infer_name: bool = True,
        toolsets: Sequence[Any] | None = None,
        builtin_tools: Sequence[Any] | None = None,
    ) -> AgentRunResult:
        """Run the agent with support for prompt_name parameter.

        Args:
            user_prompt: User input to start/continue the conversation
            prompt_name: Name of a registered prompt to load from agent.prompts
            message_history: History of the conversation so far
            deferred_tool_results: Optional results for deferred tool calls
            model: Optional model to use for this run
            instructions: Optional additional instructions
            deps: Optional dependencies to use
            model_settings: Optional settings for model request
            usage_limits: Optional limits on token usage
            usage: Optional usage to start with
            infer_name: Whether to infer agent name from call frame
            toolsets: Optional additional toolsets
            builtin_tools: Optional additional builtin tools

        Returns:
            AgentRunResult from the agent execution

        Raises:
            ValueError: If prompt_name not found or neither prompt nor prompt_name provided
        """
        # Resolve prompt_name to actual prompt text
        final_prompt = user_prompt

        if prompt_name is not None:
            if not hasattr(self, "prompts") or prompt_name not in self.prompts:  # type: ignore[attr-defined]
                available = list(self.prompts.keys()) if hasattr(self, "prompts") else []  # type: ignore[attr-defined]
                raise ValueError(f"Prompt '{prompt_name}' not found in agent.prompts. " f"Available prompts: {available}")
            final_prompt = self.prompts[prompt_name]  # type: ignore[attr-defined]

        if final_prompt is None:
            raise ValueError("Either 'user_prompt' or 'prompt_name' must be provided")

        # Call wrapped agent's run method
        return await self._wrapped_agent.run(
            final_prompt,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            model=model,
            instructions=instructions,
            deps=deps,
            model_settings=model_settings,
            usage_limits=usage_limits,
            usage=usage,
            infer_name=infer_name,
            toolsets=toolsets,
            builtin_tools=builtin_tools,
        )

    def run_sync(
        self,
        user_prompt: str | Sequence[UserContent] | None = None,
        *,
        prompt_name: str | None = None,
        message_history: Sequence[ModelMessage] | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
        model: Model | str | None = None,
        instructions: Instructions[AgentDepsT] | None = None,
        deps: AgentDepsT | None = None,
        model_settings: ModelSettings | None = None,
        usage_limits: UsageLimits | None = None,
        usage: RunUsage | None = None,
        infer_name: bool = True,
        toolsets: Sequence[Any] | None = None,
        builtin_tools: Sequence[Any] | None = None,
    ) -> AgentRunResult:
        """Run the agent synchronously with support for prompt_name parameter.

        Args:
            user_prompt: User input to start/continue the conversation
            prompt_name: Name of a registered prompt to load from agent.prompts
            message_history: History of the conversation so far
            deferred_tool_results: Optional results for deferred tool calls
            model: Optional model to use for this run
            instructions: Optional additional instructions
            deps: Optional dependencies to use
            model_settings: Optional settings for model request
            usage_limits: Optional limits on token usage
            usage: Optional usage to start with
            infer_name: Whether to infer agent name from call frame
            toolsets: Optional additional toolsets
            builtin_tools: Optional additional builtin tools

        Returns:
            AgentRunResult from the agent execution

        Raises:
            ValueError: If prompt_name not found or neither prompt nor prompt_name provided
        """
        # Resolve prompt_name to actual prompt text
        final_prompt = user_prompt

        if prompt_name is not None:
            if not hasattr(self, "prompts") or prompt_name not in self.prompts:  # type: ignore[attr-defined]
                available = list(self.prompts.keys()) if hasattr(self, "prompts") else []  # type: ignore[attr-defined]
                raise ValueError(f"Prompt '{prompt_name}' not found in agent.prompts. " f"Available prompts: {available}")
            final_prompt = self.prompts[prompt_name]  # type: ignore[attr-defined]

        if final_prompt is None:
            raise ValueError("Either 'user_prompt' or 'prompt_name' must be provided")

        # Call wrapped agent's run_sync method
        return self._wrapped_agent.run_sync(
            final_prompt,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            model=model,
            instructions=instructions,
            deps=deps,
            model_settings=model_settings,
            usage_limits=usage_limits,
            usage=usage,
            infer_name=infer_name,
            toolsets=toolsets,
            builtin_tools=builtin_tools,
        )

    async def iter(
        self,
        user_prompt: str | Sequence[UserContent] | None = None,
        *,
        prompt_name: str | None = None,
        output_type: Any | None = None,
        message_history: Sequence[ModelMessage] | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
        model: Model | str | None = None,
        instructions: Instructions[AgentDepsT] | None = None,
        deps: AgentDepsT | None = None,
        model_settings: ModelSettings | None = None,
        usage_limits: UsageLimits | None = None,
        usage: RunUsage | None = None,
        infer_name: bool = True,
        toolsets: Sequence[Any] | None = None,
        builtin_tools: Sequence[Any] | None = None,
    ) -> AsyncIterator[AgentRun[AgentDepsT, Any]]:
        """Iterate over agent graph nodes with support for prompt_name parameter.

        Args:
            user_prompt: User input to start/continue the conversation
            prompt_name: Name of a registered prompt to load from agent.prompts
            output_type: Custom output type for this run
            message_history: History of the conversation so far
            deferred_tool_results: Optional results for deferred tool calls
            model: Optional model to use for this run
            instructions: Optional additional instructions
            deps: Optional dependencies to use
            model_settings: Optional settings for model request
            usage_limits: Optional limits on token usage
            usage: Optional usage to start with
            infer_name: Whether to infer agent name from call frame
            toolsets: Optional additional toolsets
            builtin_tools: Optional additional builtin tools

        Yields:
            AgentRun nodes as they are executed

        Raises:
            ValueError: If prompt_name not found or neither prompt nor prompt_name provided
        """
        # Resolve prompt_name to actual prompt text
        final_prompt = user_prompt

        if prompt_name is not None:
            if not hasattr(self, "prompts") or prompt_name not in self.prompts:  # type: ignore[attr-defined]
                available = list(self.prompts.keys()) if hasattr(self, "prompts") else []  # type: ignore[attr-defined]
                raise ValueError(f"Prompt '{prompt_name}' not found in agent.prompts. " f"Available prompts: {available}")
            final_prompt = self.prompts[prompt_name]  # type: ignore[attr-defined]

        if final_prompt is None:
            raise ValueError("Either 'user_prompt' or 'prompt_name' must be provided")

        # Call wrapped agent's iter method
        async for node in self._wrapped_agent.iter(
            final_prompt,
            output_type=output_type,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            model=model,
            instructions=instructions,
            deps=deps,
            model_settings=model_settings,
            usage_limits=usage_limits,
            usage=usage,
            infer_name=infer_name,
            toolsets=toolsets,
            builtin_tools=builtin_tools,
        ):
            yield node

    def iter_sync(
        self,
        user_prompt: str | Sequence[UserContent] | None = None,
        *,
        prompt_name: str | None = None,
        output_type: Any | None = None,
        message_history: Sequence[ModelMessage] | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
        model: Model | str | None = None,
        instructions: Instructions[AgentDepsT] | None = None,
        deps: AgentDepsT | None = None,
        model_settings: ModelSettings | None = None,
        usage_limits: UsageLimits | None = None,
        usage: RunUsage | None = None,
        infer_name: bool = True,
        toolsets: Sequence[Any] | None = None,
        builtin_tools: Sequence[Any] | None = None,
    ) -> Any:
        """Iterate over agent graph nodes synchronously with support for prompt_name parameter.

        Args:
            user_prompt: User input to start/continue the conversation
            prompt_name: Name of a registered prompt to load from agent.prompts
            output_type: Custom output type for this run
            message_history: History of the conversation so far
            deferred_tool_results: Optional results for deferred tool calls
            model: Optional model to use for this run
            instructions: Optional additional instructions
            deps: Optional dependencies to use
            model_settings: Optional settings for model request
            usage_limits: Optional limits on token usage
            usage: Optional usage to start with
            infer_name: Whether to infer agent name from call frame
            toolsets: Optional additional toolsets
            builtin_tools: Optional additional builtin tools

        Returns:
            Context manager for iterating over agent run nodes

        Raises:
            ValueError: If prompt_name not found or neither prompt nor prompt_name provided
        """
        # Resolve prompt_name to actual prompt text
        final_prompt = user_prompt

        if prompt_name is not None:
            if not hasattr(self, "prompts") or prompt_name not in self.prompts:  # type: ignore[attr-defined]
                available = list(self.prompts.keys()) if hasattr(self, "prompts") else []  # type: ignore[attr-defined]
                raise ValueError(f"Prompt '{prompt_name}' not found in agent.prompts. " f"Available prompts: {available}")
            final_prompt = self.prompts[prompt_name]  # type: ignore[attr-defined]

        if final_prompt is None:
            raise ValueError("Either 'user_prompt' or 'prompt_name' must be provided")

        # Call wrapped agent's iter_sync method
        return self._wrapped_agent.iter_sync(
            final_prompt,
            output_type=output_type,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            model=model,
            instructions=instructions,
            deps=deps,
            model_settings=model_settings,
            usage_limits=usage_limits,
            usage=usage,
            infer_name=infer_name,
            toolsets=toolsets,
            builtin_tools=builtin_tools,
        )

    def __enter__(self) -> Any:
        """Enter context manager."""
        return self._wrapped_agent.__enter__()

    def __exit__(self, *args: Any) -> Any:
        """Exit context manager."""
        return self._wrapped_agent.__exit__(*args)

    async def __aenter__(self) -> Any:
        """Enter async context manager."""
        return await self._wrapped_agent.__aenter__()

    async def __aexit__(self, *args: Any) -> Any:
        """Exit async context manager."""
        return await self._wrapped_agent.__aexit__(*args)
