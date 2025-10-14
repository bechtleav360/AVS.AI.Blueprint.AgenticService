"""Customizable implementation of the Pydantic AI agent runtime."""

import logging

from pydantic_ai import Tool

from base.src.agent import BaseAgent
from base.src.config import Config

from ..models.processing import ProcessingContext
from ..models.results import InvoiceAnalysisOutput
from ..services import HealthCheckService
from .tools import Tools

logger = logging.getLogger(__name__)


class AgentRuntime(BaseAgent):
    """
    Customizable implementation of the agent runtime.

    This class provides concrete implementations for the abstract methods in
    BaseAgent. You should customize this class for your domain-specific
    requirements.

    Supports multiple runtime instances with different configurations by
    specifying a runtime_name that maps to [runtime.{name}] sections in settings.toml.
    """

    def __init__(self, settings: Config, runtime_name: str = "default"):
        """Initialize the agent runtime with configuration.

        Args:
            settings: Application configuration.
            runtime_name: Name of this runtime instance for runtime-specific config.
                         Maps to [runtime.{runtime_name}] section in settings.toml.
        """
        super().__init__(settings, runtime_name)
        self._health_check_service = HealthCheckService()

        logger.info(
            "AgentRuntime '%s' initialized with prompt: %s, model: %s",
            runtime_name,
            settings.get_prompt_config(runtime_name).get("system_prompt_name"),
            settings.get_ai_config(runtime_name).get("model_name")
        )

    def _get_tools(self) -> list[Tool]:
        """Return a list of tools for the AI agent.
        
        The agent will extract data from OCR text, then use this tool to calculate.
        
        Returns:
            List of Tool instances available to the agent.
        """
        tools = Tools()
        return [Tool(name="calculate_invoice", function=tools.calculate_invoice)]

    def _get_processing_context_type(self) -> type[ProcessingContext]:
        """Return the type for the processing context dependencies.
        
        Returns:
            ProcessingContext type for dependency injection.
        """
        return ProcessingContext

    def _get_result_type(self) -> type[InvoiceAnalysisOutput]:
        """Return the custom result model type for typed outputs.
        
        Returns:
            InvoiceAnalysisOutput type for structured agent responses.
        """
        return InvoiceAnalysisOutput

    async def process_request(
        self,
        context: ProcessingContext | None = None,
        invoice_text: str | None = None,
        **kwargs,
    ) -> InvoiceAnalysisOutput:
        """Process unstructured invoice text through the agent.

        Args:
            context: Processing context with correlation_id and event_id.
            invoice_text: The unstructured invoice text to analyze.
            **kwargs: Additional parameters (e.g., event, handler_result) that may be
                     passed by the processing service but are not used directly.

        Returns:
            InvoiceAnalysisOutput with extracted invoice data.

        Raises:
            ValueError: If invoice_text is not provided.
        """
        if not invoice_text:
            raise ValueError("No invoice_text provided")

        # Log any additional kwargs for debugging
        if kwargs:
            logger.debug(
                "Received additional kwargs in process_request: %s",
                list(kwargs.keys()),
            )

        # Load and format instruction prompt with fallback
        instruction = self._load_and_format_instruction(
            fallback_template="Analyze this invoice and extract the information:\n\n{invoice_text}",
            invoice_text=invoice_text
        )

        # Run agent with instruction
        response = await self.run_with_agent(instruction, deps=context)
        return self._handle_agent_response(response)

    async def custom_health_check(self) -> bool:
        """Perform a custom, domain-specific health check.

        Delegates to the HealthCheckService for domain-specific checks.

        Returns:
            True if all health checks pass, False otherwise.
        """
        return await self._health_check_service.check_health()
