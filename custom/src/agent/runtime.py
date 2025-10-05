"""Customizable implementation of the Pydantic AI agent runtime."""

import logging
from typing import Any

from pydantic_ai import Tool

from base.src.agent import BaseAgent
from base.src.config import Config

from ..models.processing import ProcessingContext
from ..models.results import InvoiceAnalysisOutput
from .tools import Tools

logger = logging.getLogger(__name__)


class AgentRuntime(BaseAgent):
    """
    Customizable implementation of the agent runtime.

    This class provides concrete implementations for the abstract methods in
    BaseAgent. You should customize this class for your domain-specific
    requirements.
    """

    def __init__(self, settings: Config):
        """Initialize the generic agent."""
        super().__init__(settings)

    def _get_prompt_name(self) -> str:
        """Return the name of the prompt file to use."""
        return "system"

    def _get_tools(self) -> list[Tool]:
        """
        Return a list of tools for the AI agent.
        The agent will extract data from OCR text, then use this tool to calculate.
        """
        tools = Tools()
        return [Tool(name="calculate_invoice", function=tools.calculate_invoice)]

    def _get_processing_context_type(self) -> type[ProcessingContext]:
        """Return the type for the processing context dependencies."""
        return ProcessingContext

    def _get_result_type(self) -> type[InvoiceAnalysisOutput]:
        """Return the custom result model type for typed outputs."""
        return InvoiceAnalysisOutput

    def _handle_agent_response(self, agent_response: Any) -> InvoiceAnalysisOutput:
        """Extract the typed output from the agent response."""
        output = getattr(agent_response, "output", None)
        if not isinstance(output, InvoiceAnalysisOutput):
            raise ValueError(
                "Model response did not return an InvoiceAnalysisOutput. " "Ensure the agent called the calculate_invoice tool."
            )
        return output

    async def process_request(self, **context_kwargs) -> InvoiceAnalysisOutput:
        """Process unstructured invoice text through the agent."""
        # Extract invoice text from context
        invoice_text = context_kwargs.get("invoice_text")
        if not invoice_text:
            raise ValueError("No invoice_text provided in context")

        # Create instruction with the unstructured invoice text
        instruction = f"Analyze this invoice and extract the information:\n\n{invoice_text}"

        # Build context for deps
        context_model = self._build_context(**context_kwargs)
        context = self._serialize_context(context_model)

        # Run agent with instruction
        response = await self.run_with_agent(instruction, deps=context)
        return self._handle_agent_response(response)

    async def custom_health_check(self) -> bool:
        """
        Perform a custom, domain-specific health check.

        FIXME: Implement your custom health check logic here. This could include
        checking database connections, external API availability, or other
        dependencies.
        """
        # For this example, we'll just return True.
        return True
