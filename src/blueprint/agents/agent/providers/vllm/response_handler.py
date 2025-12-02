"""vLLM response handler implementation.

.. deprecated::
    This module is not integrated into the agent creation flow.
    Kept for potential future use but not exported from public API.
"""

import json
import logging
from typing import Any

from ...response_handler import (  # type: ignore[import-not-found]
    ResponseHandlerStrategy, T)

logger = logging.getLogger(__name__)


class VLLMResponseHandler(ResponseHandlerStrategy):
    """Response handler for vLLM models without output_type.

    vLLM responses typically have tool results in the message history
    rather than in a structured output field.
    """

    def extract_result(self, agent_response: Any, result_type: type[T]) -> T:
        """Extract result from vLLM response by inspecting message history.

        vLLM with tools (no output_type) stores results in ToolReturnPart
        within the message history.
        """
        # First, try to get result from new_messages
        new_messages_func = getattr(agent_response, "new_messages", None)

        if new_messages_func and callable(new_messages_func):
            try:
                messages = new_messages_func()
                logger.debug(
                    "Retrieved %d new messages from agent response",
                    len(messages) if messages else 0,
                )

                # Look for tool return messages (iterate in reverse to get latest)
                for idx, msg in enumerate(reversed(messages)):
                    msg_type = type(msg).__name__
                    logger.debug(
                        "Message %d: type=%s, kind=%s, role=%s",
                        idx,
                        msg_type,
                        getattr(msg, "kind", None),
                        getattr(msg, "role", None),
                    )

                    # Try to extract from message content
                    content = getattr(msg, "content", None)
                    if content and isinstance(content, str):
                        result = self._try_parse_json(content, result_type)
                        if result:
                            return result

                    # Check if message has parts (ToolReturnPart contains results)
                    if hasattr(msg, "parts"):
                        for part_idx, part in enumerate(msg.parts):
                            part_type = type(part).__name__
                            logger.debug("Part %d type: %s", part_idx, part_type)

                            if part_type == "ToolReturnPart":
                                # Try return_value first
                                return_value = getattr(part, "return_value", None)
                                if return_value is not None:
                                    if isinstance(return_value, result_type):
                                        logger.debug("Found result in ToolReturnPart.return_value")
                                        return return_value

                                    if isinstance(return_value, str):
                                        result = self._try_parse_json(return_value, result_type)
                                        if result:
                                            return result

                                # Try content attribute
                                content = getattr(part, "content", None)
                                if content is not None:
                                    if isinstance(content, result_type):
                                        logger.debug("Found result in ToolReturnPart.content")
                                        return content

                                    if isinstance(content, str):
                                        result = self._try_parse_json(content, result_type)
                                        if result:
                                            return result

                            # Check other part types
                            elif hasattr(part, "content"):
                                part_content = part.content
                                if isinstance(part_content, str):
                                    result = self._try_parse_json(part_content, result_type)
                                    if result:
                                        return result

            except Exception as e:
                logger.warning("Failed to retrieve new messages: %s", str(e), exc_info=True)

        # Fallback: try standard attributes
        data = getattr(agent_response, "data", None)
        if isinstance(data, result_type):
            logger.debug("Found result in agent_response.data")
            return data

        output = getattr(agent_response, "output", None)
        if isinstance(output, result_type):
            logger.debug("Found result in agent_response.output")
            return output

        if isinstance(output, str):
            result = self._try_parse_json(output, result_type)
            if result:
                return result

        # Log diagnostic information
        logger.error(
            "Failed to extract %s from vLLM response. " "data type: %s, output type: %s, response type: %s",
            result_type.__name__,
            type(data).__name__ if data is not None else "None",
            type(output).__name__ if output is not None else "None",
            type(agent_response).__name__,
        )
        logger.debug("Output content: %s", str(output)[:500] if output else "None")

        raise ValueError(
            f"Could not extract {result_type.__name__} from vLLM response. " "Ensure the agent called a tool that returns the correct type."
        )

    def _try_parse_json(self, content: str, result_type: type[T]) -> T | None:
        """Try to parse JSON content into result_type.

        Returns:
            Parsed result or None if parsing fails.
        """
        try:
            result_json = json.loads(content)
            result = result_type(**result_json)
            logger.debug("Successfully parsed %s from JSON", result_type.__name__)
            return result
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug("Content is not valid JSON for %s: %s", result_type.__name__, str(e))
            return None
