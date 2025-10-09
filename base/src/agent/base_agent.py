"""Base class for the Pydantic AI agent runtime."""

import asyncio
import inspect
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from openai import AsyncOpenAI
from opentelemetry import trace
from pydantic_ai import Agent, NativeOutput, Tool
from pydantic_ai.models import Model
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from ..config import Config
from ..models import (
    AgentHealthDependencies,
    AgentHealthResponse,
    AgentOutput,
    AIModelHealth,
    CustomCheckHealth,
)
from ..registry.service_registry import ServiceRegistry

T = TypeVar("T")
DepsT = TypeVar("DepsT")  # Type variable for dependencies/context

# Initialize the tracer
tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for the agent runtime."""

    def __init__(self, settings: Config):
        self.settings = settings
        self._agent: Optional[Agent] = None
        ai_config = self.settings.get_ai_config()
        limit = ai_config.get("concurrency_limit")
        if isinstance(limit, int) and limit > 0:
            self._concurrency_semaphore: Optional[asyncio.Semaphore] = (
                asyncio.Semaphore(limit)
            )
            logger.info("Agent concurrency limit set to %s", limit)
        else:
            self._concurrency_semaphore = None

    def link_service_registry(self, service_registry: ServiceRegistry) -> None:
        """Link the service registry to the agent."""
        self._service_registry = service_registry

    def _get_model_configuration(self) -> Model:
        """Return the AI model configuration string (e.g., 'openai:gpt-4')."""
        ai_config = self.settings.get_ai_config()

        if ai_config["provider"] == "openai":
            client = AsyncOpenAI(
                max_retries=3,
                api_key=ai_config["api_key"],
            )
            provider = OpenAIProvider(openai_client=client)
            return OpenAIChatModel(
                provider=provider,
                model_name=ai_config["model_name"],
            )
        elif ai_config["provider"] == "vllm":
            # Enable debug logging for OpenAI client
            logging.getLogger("openai").setLevel(logging.DEBUG)
            logging.getLogger("httpx").setLevel(logging.INFO)
            logging.getLogger("pydantic_ai").setLevel(logging.DEBUG)

            # Set a reasonable timeout to prevent indefinite hangs
            # Default is 10 minutes which is too long for most use cases
            timeout_seconds = ai_config.get("timeout", 60)  # 2 minutes default

            client = AsyncOpenAI(
                max_retries=3,
                base_url=ai_config["base_url"],
                api_key=ai_config["api_key"],
                timeout=timeout_seconds,
            )

            provider = OpenAIProvider(
                openai_client=client,
            )

            # vLLM uses <think>...</think> tags for reasoning in JSON schema mode
            # These tags must match the actual format returned by the model
            # to prevent response parsing hangs
            # Note: Some models use _<think>, others use <think> - adjust based on your model
            vllm_profile = ModelProfile(
                thinking_tags=("<think>", "</think>"),  # Match vLLM's actual format
                ignore_streamed_leading_whitespace=True,
                supports_json_schema_output=True,  # Enable JSON schema output for vLLM
                default_structured_output_mode="native",  # Use native mode instead of tool mode
            )

            model = OpenAIChatModel(
                provider=provider,
                model_name=ai_config["model_name"],
                profile=vllm_profile,
            )

            logger.info(
                "vLLM client configured with timeout: %d seconds and JSON schema output enabled",
                timeout_seconds,
            )
            return model

    @abstractmethod
    def _get_prompt_name(self) -> str:
        """Return the system prompt string for the agent
        (implemented by custom)."""
        pass

    def _get_system_prompt(self) -> str:
        """
        Load the system prompt based on the implementing class location.

        By default, this resolves the prompt directory relative to the concrete
        subclass file path, expecting a sibling prompts directory, e.g.:
        `<module_dir>/../prompts/<prompt_name>.prompt`.

        Implementations can override `_get_prompt_dir()` if they want a
        different layout.
        """
        prompt_name = self._get_prompt_name()
        prompt_dir = self._get_prompt_dir()
        prompt_path = prompt_dir / f"{prompt_name}.prompt"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text().strip()

    def _get_prompt_dir(self) -> Path:
        """
        Determine the directory containing prompt files for the concrete agent.

        Default behaviour:
        - For a subclass defined in `.../custom/agent/<file>.py`, this returns
          `.../custom/prompts` by walking up one directory from the subclass
          module directory and appending `prompts`.
        """
        subclass_file = Path(inspect.getfile(self.__class__)).resolve()
        module_dir = subclass_file.parent  # e.g., .../custom/agent
        return module_dir.parent / "prompts"  # e.g., .../custom/prompts

    @abstractmethod
    def _get_tools(self) -> List[Tool]:
        """Return a list of tools for the AI agent."""
        pass

    @abstractmethod
    async def custom_health_check(self) -> bool:
        """Perform a custom, domain-specific health check."""
        pass

    async def process_request(self, context: Optional[Any] = None, **kwargs) -> Any:
        """Prepare prompt and context, then run the agent.

        Args:
            context: Processing context instance (type defined by _get_processing_context_type())
                     or None if no context is needed.
            **kwargs: Additional keyword arguments. Subclasses may accept domain-specific
                     parameters. The base implementation ignores these.

        Returns:
            The result from the agent processing.
        """
        start_time = time.time()
        with tracer.start_as_current_span("agent.process_request") as span:
            prompt = self._get_system_prompt()

            try:
                result = await self._process_request(prompt, context)
            except Exception:
                logger.exception("Agent process_request failed")
                span.set_status(trace.Status(trace.StatusCode.ERROR, "agent_failure"))
                raise

            duration_ms = int((time.time() - start_time) * 1000)
            span.set_attribute("agent.model", self._get_model_configuration())
            span.set_attribute("processing.time_ms", duration_ms)
            logger.info("Agent process_request completed in %.2fms", duration_ms)
            return result

    def _build_context(self, **kwargs) -> Any:
        """Build a processing context instance from kwargs, if a type is defined.

        This is a helper method for backward compatibility and convenience.
        Prefer passing context objects directly to process_request().

        Args:
            **kwargs: Keyword arguments to construct the context.

        Returns:
            Context instance or None.
        """
        deps_type = self._get_processing_context_type()
        try:
            if deps_type is type(None):
                return None
            # Try to instantiate with kwargs; if fails, return kwargs as-is
            return deps_type(**kwargs)  # type: ignore[call-arg]
        except Exception:
            return kwargs or None

    async def _process_request(self, prompt: str, context: Any) -> Any:
        """Run the agent with the prepared prompt and context."""

        response = await self.run_with_agent(prompt, deps=context)
        return self._handle_agent_response(response)

    def _handle_agent_response(self, agent_response: Any) -> Any:
        """Adapt the agent response to the desired return type."""

        return agent_response

    def _get_processing_context_type(self) -> Type[T]:
        """Return the type for the processing context dependencies."""
        # By default, there is no processing context.
        return type(None)

    def _get_result_type(self) -> Type[T]:
        """Return the type for the agent's result."""
        # By default, the result type is the generic AgentOutput.
        return AgentOutput

    def _ensure_agent(self) -> Agent:

        if self._agent is None:
            ai_config = self.settings.get_ai_config()
            is_vllm = ai_config.get("provider") == "vllm"

            # For vLLM with tools, don't use output_type
            # Let tools return the result naturally without forcing a schema
            # NativeOutput/ToolOutput modes can cause issues with vLLM's response format
            if is_vllm:
                logger.info(
                    "Configuring vLLM agent with tools (no output_type constraint)",
                )
                self._agent = Agent(
                    model=self._get_model_configuration(),
                    tools=self._get_tools(),
                    deps_type=self._get_processing_context_type(),
                    system_prompt=self._get_system_prompt(),
                )
            else:
                # For OpenAI and other providers, use default ToolOutput mode
                self._agent = Agent(
                    model=self._get_model_configuration(),
                    tools=self._get_tools(),
                    model_settings=OpenAIChatModelSettings(
                        extra_body={"tool_choice": "auto"},
                    ),
                    deps_type=self._get_processing_context_type(),
                    output_type=self._get_result_type(),
                    system_prompt=self._get_system_prompt(),
                )

        return self._agent

    @property
    def agent(self) -> Agent:
        return self._ensure_agent()

    def get_agent(self) -> Agent:
        """Accessor for the underlying Pydantic AI Agent instance."""
        return self.agent

    async def run_with_agent(self, instruction: str, deps: Any = None) -> Any:
        """Execute the underlying agent with the given instruction and context."""
        # Build usage limits from config
        usage_limits = self._build_usage_limits()

        # For vLLM, no special model settings needed
        # The ModelProfile with correct thinking_tags handles response parsing
        ai_config = self.settings.get_ai_config()
        settings = None
        if ai_config.get("provider") == "vllm":
            # vLLM with NativeOutput mode works with default settings
            # The thinking tags (_<think>...</think>) are automatically stripped
            # by Pydantic AI when configured correctly in the ModelProfile
            settings = None

        logger.info(
            "Starting agent.run() with instruction length: %d", len(instruction)
        )
        logger.debug(
            "Agent configuration - output_type: %s, tools: %s",
            self._get_result_type().__name__,
            [t.name for t in self._get_tools()],
        )

        try:
            result = await self.agent.run(
                instruction,
                deps=deps,
                usage_limits=usage_limits,
                model_settings=settings,
            )
            logger.info(
                "Agent.run() completed successfully, result type: %s",
                type(result).__name__,
            )
            logger.debug(
                "Agent result output: %s",
                result.output if hasattr(result, "output") else str(result)[:200],
            )
            return result
        except asyncio.TimeoutError:
            logger.error(
                "Agent.run() timed out after waiting for response", exc_info=True
            )
            raise
        except Exception:
            logger.error("Agent.run() failed", exc_info=True)
            raise

    def _build_usage_limits(self) -> Optional[UsageLimits]:
        """Build UsageLimits from AI config."""
        ai_config = self.settings.get_ai_config()
        limits = ai_config.get("usage_limits", {})

        # Only create UsageLimits if at least one limit is set
        if not any(limits.values()):
            return None

        return UsageLimits(
            request_limit=limits.get("request_limit"),
            input_tokens_limit=limits.get("input_tokens_limit"),
            output_tokens_limit=limits.get("output_tokens_limit"),
            total_tokens_limit=limits.get("total_tokens_limit"),
        )

    @staticmethod
    def _serialize_context(context: Any) -> Optional[Dict[str, Any]]:
        if context is None:
            return None

        if isinstance(context, dict):
            return context

        if hasattr(context, "dict") and callable(context.dict):
            return context.dict()

        try:
            return dict(context)
        except TypeError:
            logger.debug("Unable to serialize context %s; using None", context)
            return None

    async def close(self):
        """Perform any cleanup required by the agent."""
        pass

    async def health_check(self) -> AgentHealthResponse:
        """
        Perform a health check of the agent.

        This check performs a simple, non-tool-using request to the underlying
        AI model to ensure it is reachable and functioning.
        """
        with tracer.start_as_current_span("agent.health_check") as span:
            start_time = time.time()
            try:
                # A simple, low-token instruction to test model connectivity.
                await self.agent.run("Respond with only the word 'OK'.")
                processing_time = time.time() - start_time

                model_check_passed = True
                model_check_duration_ms = int(processing_time * 1000)
            except Exception as e:
                logger.error("AI model health check failed: %s", e, exc_info=True)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                model_check_passed = False
                model_check_duration_ms = int((time.time() - start_time) * 1000)

            # Perform custom health check
            custom_check_passed = await self.custom_health_check()

            # Determine overall status
            is_healthy = model_check_passed and custom_check_passed
            overall_status = "healthy" if is_healthy else "unhealthy"

            span.set_attribute("health_check.status", overall_status)

            # Get model identifier as string
            model_config = self._get_model_configuration()
            model_str = str(model_config)

            return AgentHealthResponse(
                status=overall_status,
                dependencies=AgentHealthDependencies(
                    ai_model=AIModelHealth(
                        status="healthy" if model_check_passed else "unhealthy",
                        model=model_str,
                        response_time_ms=model_check_duration_ms,
                    ),
                    custom_check=CustomCheckHealth(
                        status="healthy" if custom_check_passed else "unhealthy",
                    ),
                ),
            )
