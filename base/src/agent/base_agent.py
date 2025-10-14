"""Refactored base class for the Pydantic AI agent runtime."""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Type, TypeVar

from opentelemetry import trace
from pydantic import BaseModel
from pydantic_ai import Agent, Tool
from pydantic_ai.models import Model

from ..config import Config
from ..models import (
    AgentHealthDependencies,
    AgentHealthResponse,
    AgentOutput,
    AIModelHealth,
    CustomCheckHealth,
)
from ..registry.service_registry import ServiceRegistry
from .agent_factory import AgentFactory
from .model_provider import ModelProviderFactory
from .prompt_loader import PromptLoader
from .response_handler import ResponseHandlerFactory
from .usage_limits import UsageLimitsBuilder

T = TypeVar("T", bound=BaseModel)

# Initialize the tracer
tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for the agent runtime.

    This class provides the core orchestration for AI agents while delegating
    provider-specific logic to strategy classes. Subclasses only need to
    implement abstract methods for domain-specific configuration.
    """

    def __init__(self, settings: Config, runtime_name: str = "default"):
        """Initialize the agent with configuration.

        Args:
            settings: Application configuration containing AI provider settings.
            runtime_name: Name of this runtime instance for runtime-specific config.
        """
        self.settings = settings
        self.runtime_name = runtime_name
        self._agent: Optional[Agent] = None
        self._model: Optional[Model] = None
        self._service_registry: Optional[ServiceRegistry] = None

        # Setup concurrency control using runtime-specific config
        ai_config = self.settings.get_ai_config(self.runtime_name)
        limit = ai_config.get("concurrency_limit")
        if isinstance(limit, int) and limit > 0:
            self._concurrency_semaphore: Optional[asyncio.Semaphore] = (
                asyncio.Semaphore(limit)
            )
            logger.info(
                "Agent runtime '%s' concurrency limit set to %s",
                self.runtime_name,
                limit
            )
        else:
            self._concurrency_semaphore = None

        logger.info(
            "Initialized BaseAgent with runtime '%s', model: %s",
            self.runtime_name,
            ai_config.get("model_name")
        )

    def link_service_registry(self, service_registry: ServiceRegistry) -> None:
        """Link the service registry to the agent.

        Args:
            service_registry: Registry for accessing shared services.
        """
        self._service_registry = service_registry

    # =========================================================================
    # Abstract methods - must be implemented by subclasses
    # =========================================================================

    @abstractmethod
    def _get_tools(self) -> List[Tool]:
        """Return a list of tools available to the AI agent.

        Returns:
            List of Tool instances that the agent can invoke.
        """
        pass

    @abstractmethod
    async def custom_health_check(self) -> bool:
        """Perform a custom, domain-specific health check.

        Returns:
            True if healthy, False otherwise.
        """
        pass

    # =========================================================================
    # Optional override methods - provide defaults but can be customized
    # =========================================================================

    def _get_processing_context_type(self) -> Type[Any]:
        """Return the type for the processing context dependencies.

        Returns:
            Type to use for agent dependencies, or type(None) for no context.
        """
        return type(None)

    def _get_result_type(self) -> Type[T]:
        """Return the type for the agent's structured result.

        Returns:
            Pydantic model type for the agent's output.
        """
        return AgentOutput  # type: ignore

    # =========================================================================
    # Core orchestration methods - use strategies, not provider-specific code
    # =========================================================================

    def _get_model_configuration(self) -> Model:
        """Get the configured AI model using runtime-specific config.

        Returns:
            Configured Model instance.
        """
        if self._model is None:
            ai_config = self.settings.get_ai_config(self.runtime_name)
            self._model = ModelProviderFactory.create_model(ai_config)
        return self._model

    def _get_system_prompt(self) -> str:
        """Load the system prompt using runtime-specific config.

        Returns:
            System prompt text.
        """
        prompt_config = self.settings.get_prompt_config(self.runtime_name)
        prompt_name = prompt_config.get("system_prompt_name", "system")
        return PromptLoader.load_prompt(prompt_name, self.__class__, prompt_config)

    def _get_instruction_prompt(self, prompt_name: str | None = None) -> str:
        """Load an instruction prompt template using runtime-specific config.

        Args:
            prompt_name: Name of the instruction prompt file. If None, uses the
                        configured instruction_prompt_name (default: "instruction").

        Returns:
            Instruction prompt template text.

        Raises:
            FileNotFoundError: If the prompt file doesn't exist.
        """
        prompt_config = self.settings.get_prompt_config(self.runtime_name)
        if prompt_name is None:
            prompt_name = prompt_config.get("instruction_prompt_name", "instruction")
        return PromptLoader.load_prompt(prompt_name, self.__class__, prompt_config)

    def _load_and_format_instruction(
        self,
        fallback_template: str,
        **format_kwargs: Any
    ) -> str:
        """Load instruction prompt and format it with provided variables.

        This is a convenience method that handles loading the instruction prompt
        with fallback to a default template if the file doesn't exist.

        Args:
            fallback_template: Default template to use if prompt file not found.
            **format_kwargs: Variables to format the template with.

        Returns:
            Formatted instruction string.
        """
        try:
            instruction_template = self._get_instruction_prompt()
        except FileNotFoundError:
            logger.warning(
                "Instruction prompt not found, using fallback template. "
                "Configure 'instruction_prompt_name' in settings.toml or create the prompt file."
            )
            instruction_template = fallback_template

        return instruction_template.format(**format_kwargs)

    def _ensure_agent(self) -> Agent:
        """Ensure the agent is initialized, creating it if necessary.

        Returns:
            Configured Agent instance.
        """
        if self._agent is None:
            ai_config = self.settings.get_ai_config(self.runtime_name)
            provider_name = ai_config.get("provider", "openai")

            self._agent = AgentFactory.create_agent(
                model=self._get_model_configuration(),
                provider_name=provider_name,
                tools=self._get_tools(),
                system_prompt=self._get_system_prompt(),
                deps_type=self._get_processing_context_type(),
                result_type=self._get_result_type(),
            )

        return self._agent

    @property
    def agent(self) -> Agent:
        """Get the configured agent instance.

        Returns:
            Agent instance.
        """
        return self._ensure_agent()

    def get_agent(self) -> Agent:
        """Accessor for the underlying Pydantic AI Agent instance.

        Returns:
            Agent instance.
        """
        return self.agent

    def _handle_agent_response(self, agent_response: Any) -> Any:
        """Extract the result from the agent response using the appropriate handler.

        Args:
            agent_response: Raw response from agent.run().

        Returns:
            Extracted result in the expected type.
        """
        ai_config = self.settings.get_ai_config(self.runtime_name)
        provider_name = ai_config.get("provider", "openai")
        result_type = self._get_result_type()

        handler = ResponseHandlerFactory.get_handler(provider_name)
        return handler.extract_result(agent_response, result_type)

    async def run_with_agent(self, instruction: str, deps: Any = None) -> Any:
        """Execute the agent with the given instruction and context.

        Args:
            instruction: The instruction/prompt for the agent.
            deps: Optional dependencies/context for the agent.

        Returns:
            Agent response (raw, before extraction).
        """
        usage_limits = UsageLimitsBuilder.build_from_config(
            self.settings.get_ai_config(self.runtime_name)
        )

        logger.info(
            "Starting agent.run() with instruction length: %d", len(instruction)
        )
        logger.debug(
            "Agent configuration - result_type: %s, tools: %s",
            self._get_result_type().__name__,
            [t.name for t in self._get_tools()],
        )

        try:
            result = await self.agent.run(
                instruction,
                deps=deps,
                usage_limits=usage_limits,
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

    async def process_request(self, context: Optional[Any] = None, **kwargs) -> Any:
        """Process a request through the agent.

        Args:
            context: Processing context instance (type defined by
                    _get_processing_context_type()) or None.
            **kwargs: Additional keyword arguments for subclass use.

        Returns:
            The result from the agent processing.
        """
        start_time = time.time()
        with tracer.start_as_current_span("agent.process_request") as span:
            prompt = self._get_system_prompt()

            try:
                result = await self._process_request(prompt, context, **kwargs)
            except Exception:
                logger.exception("Agent process_request failed")
                span.set_status(trace.Status(trace.StatusCode.ERROR, "agent_failure"))
                raise

            duration_ms = int((time.time() - start_time) * 1000)
            span.set_attribute("agent.model", str(self._get_model_configuration()))
            span.set_attribute("processing.time_ms", duration_ms)
            logger.info("Agent process_request completed in %.2fms", duration_ms)
            return result

    async def _process_request(self, prompt: str, context: Any, **kwargs) -> Any:
        """Run the agent with the prepared prompt and context.

        Args:
            prompt: System prompt text.
            context: Processing context.
            **kwargs: Additional arguments (subclass-specific).

        Returns:
            Processed result.
        """
        response = await self.run_with_agent(prompt, deps=context)
        return self._handle_agent_response(response)

    async def close(self):
        """Perform any cleanup required by the agent."""
        pass

    async def health_check(self) -> AgentHealthResponse:
        """Perform a health check of the agent.

        This check performs a simple request to the AI model to ensure
        it is reachable and functioning.

        Returns:
            AgentHealthResponse with status and diagnostics.
        """
        with tracer.start_as_current_span("agent.health_check") as span:
            start_time = time.time()
            try:
                # Simple, low-token instruction to test model connectivity
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
