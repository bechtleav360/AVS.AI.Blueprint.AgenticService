"""Base class for the Pydantic AI agent runtime."""

from abc import ABC, abstractmethod
import logging
import time
from typing import Any, Dict, List, Optional, Type, TypeVar

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

T = TypeVar("T")

from pydantic_ai import Agent

from opentelemetry import trace

import inspect
from pathlib import Path

from base.src.config import Config
from base.src.models.result import AgentOutput

# Initialize the tracer
tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for the agent runtime."""

    def __init__(self, settings: Config):
        self.settings = settings
        self.agent = Agent(
            model=self._get_model(),
            deps_type=self._get_processing_context_type(),
            result_type=self._get_result_type(),
            system_prompt=self._get_system_prompt(),
        )
        self._register_tools()

    def _get_model(self) -> Model:
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
            client = AsyncOpenAI(
                max_retries=3,
                base_url=ai_config["base_url"],
                api_key=ai_config["api_key"],
            )

            provider = OpenAIProvider(
                openai_client=client,
            )

            model = OpenAIChatModel(
                provider=provider,
                model_name=ai_config["model_name"],
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
    def _get_tools(self) -> List[Any]:
        """Return a list of tools for the AI agent."""
        pass

    @abstractmethod
    async def custom_health_check(self) -> bool:
        """Perform a custom, domain-specific health check."""
        pass

    async def process_request(self, **context_kwargs) -> Any:
        """
        Generic request processing wrapper with tracing and timing.

        This method prepares the system prompt and a processing context built
        from keyword arguments, then delegates the actual processing to the
        implementation hook `_process_request`.

        Subclasses should implement `_process_request(prompt, context)` and
        return their domain-specific result model as specified by
        `_get_result_type()`.
        """
        start_time = time.time()
        with tracer.start_as_current_span("agent.process_request") as span:
            try:
                # Normalize context to a plain dict for the agent deps
                prompt = self._get_system_prompt()
                context = self._build_context(**context_kwargs)

                if context is None:
                    context: Optional[Dict[str, Any]] = None
                else:
                    context = (
                        context.dict() if hasattr(context, "dict") else dict(context)
                    )  # type: ignore[arg-type]

                result = await self._process_request(prompt, context)
                span.set_attribute("agent.model", self._get_model())
                span.set_attribute(
                    "processing.time_ms", int((time.time() - start_time) * 1000)
                )
                logger.info(
                    f"Agent process_request completed in "
                    f"{time.time() - start_time:.2f}s"
                )
                return result
            except Exception:
                logger.exception("Agent process_request failed")
                raise

    def _build_context(self, **kwargs):
        """Build a processing context instance from kwargs, if a type is defined."""
        deps_type = self._get_processing_context_type()
        try:
            if deps_type is type(None):
                return None
            # Try to instantiate with kwargs; if fails, return kwargs as-is
            return deps_type(**kwargs)  # type: ignore[call-arg]
        except Exception:
            return kwargs or None

    @abstractmethod
    async def _process_request(
        self, prompt: str, context: Optional[Dict[str, Any]] | Any
    ) -> Any:
        """
        Implementation hook that performs the actual processing.

        Typically this should call `await self.process(prompt, context_dict)`
        and adapt the result to the custom model specified by `_get_result_type()`.
        """
        pass

    def _get_processing_context_type(self) -> Type[T]:
        """Return the type for the processing context dependencies."""
        # By default, there is no processing context.
        return type(None)

    def _get_result_type(self) -> Type[T]:
        """Return the type for the agent's result."""
        # By default, the result type is the generic AgentOutput.
        return AgentOutput

    def _register_tools(self):
        """Register the tools with the Pydantic AI agent."""
        # TODO: Implement tool registration when pydantic_ai API is clarified
        # for tool in self._get_tools():
        #     self.agent.register(tool)
        pass

    def get_agent(self) -> Agent:
        """Accessor for the underlying Pydantic AI Agent instance."""
        return self.agent

    async def run_with_agent(
        self, instruction: str, deps: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Convenience wrapper to run the underlying Pydantic AI Agent.

        Implementations can use this to invoke the model without the base
        layering any opinionated logic. Tracing for the overall request is
        handled in `process_request`; individual handler logic should add
        spans as needed.
        """
        return await self.get_agent().run(instruction, deps=deps)

    async def close(self):
        """Perform any cleanup required by the agent."""
        pass

    async def health_check(self) -> Dict[str, Any]:
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
                logger.error(f"AI model health check failed: {e}", exc_info=True)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                model_check_passed = False
                model_check_duration_ms = int((time.time() - start_time) * 1000)

            # Perform custom health check
            custom_check_passed = await self.custom_health_check()

            # Determine overall status
            is_healthy = model_check_passed and custom_check_passed
            overall_status = "healthy" if is_healthy else "unhealthy"

            span.set_attribute("health_check.status", overall_status)

            return {
                "status": overall_status,
                "dependencies": {
                    "ai_model": {
                        "status": "healthy" if model_check_passed else "unhealthy",
                        "model": self._get_model(),
                        "response_time_ms": model_check_duration_ms,
                    },
                    "custom_check": {
                        "status": "healthy" if custom_check_passed else "unhealthy",
                    },
                },
            }
