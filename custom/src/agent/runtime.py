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
        """Extract the typed output from the agent response.

        When tools are used without output_type, the tool result is in the message
        history. The model may generate a final text response after calling tools,
        which is in agent_response.output, but we need the actual tool result.
        """
        import json

        # First, check the new_messages for tool results
        # AgentRunResult has new_messages() that returns messages from this run
        new_messages_func = getattr(agent_response, "new_messages", None)
        
        if new_messages_func and callable(new_messages_func):
            try:
                messages = new_messages_func()
                logger.info("Retrieved %d new messages from agent response", len(messages) if messages else 0)
                
                # Look for tool return messages (iterate in reverse to get latest)
                for idx, msg in enumerate(reversed(messages)):
                    # Log message structure for debugging
                    msg_type = type(msg).__name__
                    msg_kind = getattr(msg, "kind", None)
                    msg_role = getattr(msg, "role", None)
                    logger.info("Message %d: type=%s, kind=%s, role=%s", idx, msg_type, msg_kind, msg_role)
                    
                    # Check all attributes to find the content
                    msg_attrs = dir(msg)
                    logger.debug("Message attributes: %s", [a for a in msg_attrs if not a.startswith('_')])
                    
                    # Try different ways to get content
                    content = getattr(msg, "content", None)
                    if content and isinstance(content, str):
                        logger.info("Found content in message (first 200 chars): %s", content[:200])
                        try:
                            result_json = json.loads(content)
                            logger.info("Successfully parsed tool result from message.content")
                            return InvoiceAnalysisOutput(**result_json)
                        except (json.JSONDecodeError, TypeError, ValueError) as e:
                            logger.debug("Content is not valid JSON: %s", str(e))
                    
                    # Also check if message has parts (some message types use parts)
                    if hasattr(msg, "parts"):
                        logger.info("Message has %d parts", len(msg.parts))
                        for part_idx, part in enumerate(msg.parts):
                            part_type = type(part).__name__
                            logger.info("Part %d type: %s", part_idx, part_type)
                            
                            # ToolReturnPart contains the tool result
                            if part_type == "ToolReturnPart":
                                # Log all attributes to see what's available
                                part_attrs = [a for a in dir(part) if not a.startswith('_')]
                                logger.info("ToolReturnPart attributes: %s", part_attrs)
                                
                                # First check return_value - this is the actual tool return
                                return_value = getattr(part, "return_value", None)
                                logger.info("ToolReturnPart.return_value exists: %s, type: %s", 
                                           return_value is not None,
                                           type(return_value).__name__ if return_value is not None else "None")
                                
                                if return_value is not None:
                                    # If it's already an InvoiceAnalysisOutput, return it
                                    if isinstance(return_value, InvoiceAnalysisOutput):
                                        logger.info("return_value is already InvoiceAnalysisOutput")
                                        return return_value
                                    
                                    # If it's a string, try to parse as JSON
                                    if isinstance(return_value, str):
                                        logger.info("return_value is string (first 200 chars): %s", return_value[:200])
                                        try:
                                            result_json = json.loads(return_value)
                                            logger.info("Successfully parsed JSON from ToolReturnPart.return_value")
                                            return InvoiceAnalysisOutput(**result_json)
                                        except (json.JSONDecodeError, TypeError, ValueError) as e:
                                            logger.warning("return_value is not valid JSON: %s", str(e))
                                
                                # Also check content attribute (might be the Pydantic model or JSON string)
                                content = getattr(part, "content", None)
                                logger.info("ToolReturnPart.content exists: %s, type: %s",
                                           content is not None,
                                           type(content).__name__ if content is not None else "None")
                                
                                if content is not None:
                                    # If it's already an InvoiceAnalysisOutput, return it
                                    if isinstance(content, InvoiceAnalysisOutput):
                                        logger.info("ToolReturnPart.content is already InvoiceAnalysisOutput!")
                                        return content
                                    
                                    # If it's a string, try to parse as JSON
                                    if isinstance(content, str):
                                        logger.info("Found content in ToolReturnPart (first 200 chars): %s", content[:200])
                                        try:
                                            result_json = json.loads(content)
                                            logger.info("Successfully parsed JSON from ToolReturnPart.content")
                                            return InvoiceAnalysisOutput(**result_json)
                                        except (json.JSONDecodeError, TypeError, ValueError) as e:
                                            logger.warning("ToolReturnPart.content is not valid JSON: %s", str(e))
                                            continue
                            
                            # Check other part types for content
                            elif hasattr(part, "content"):
                                part_content = part.content
                                if isinstance(part_content, str):
                                    logger.info("Found content in part (first 200 chars): %s", part_content[:200])
                                    try:
                                        result_json = json.loads(part_content)
                                        logger.info("Successfully parsed tool result from message part")
                                        return InvoiceAnalysisOutput(**result_json)
                                    except (json.JSONDecodeError, TypeError, ValueError):
                                        logger.debug("Part content is not valid JSON")
                                        continue
            except Exception as e:
                logger.warning("Failed to retrieve new messages: %s", str(e), exc_info=True)

        # Fallback: Try to get the data attribute (contains final message content)
        data = getattr(agent_response, "data", None)
        if isinstance(data, InvoiceAnalysisOutput):
            return data

        # Fallback: Try output attribute
        output = getattr(agent_response, "output", None)
        if isinstance(output, InvoiceAnalysisOutput):
            return output

        # Fallback: If output is a JSON string, try to parse it
        if isinstance(output, str):
            try:
                output_json = json.loads(output)
                return InvoiceAnalysisOutput(**output_json)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass  # Expected - output is human-readable text, not JSON

        # Log what we got for debugging
        logger.error(
            "Agent response structure - data type: %s, output type: %s, response type: %s",
            type(data).__name__ if data is not None else "None",
            type(output).__name__ if output is not None else "None",
            type(agent_response).__name__,
        )
        logger.debug("Output content: %s", str(output)[:500] if output else "None")

        raise ValueError(
            "Model response did not return an InvoiceAnalysisOutput. "
            "Ensure the agent called the calculate_invoice tool and it returned the correct type."
        )

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

        # Create instruction with the unstructured invoice text
        instruction = f"Analyze this invoice and extract the information:\n\n{invoice_text}"

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
