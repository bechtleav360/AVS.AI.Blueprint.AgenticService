"""OpenAI response handler implementation."""

import json
import logging
from typing import Any, Type

from ...response_handler import ResponseHandlerStrategy, T

logger = logging.getLogger(__name__)


class OpenAIResponseHandler(ResponseHandlerStrategy[T]):
    """Response handler for OpenAI models with output_type."""

    def extract_result(self, agent_response: Any, result_type: Type[T]) -> T:
        """Extract result from OpenAI response.
        
        OpenAI responses with output_type have the result in the .data attribute.
        """
        # Check data attribute first (standard location for output_type results)
        data = getattr(agent_response, "data", None)
        if isinstance(data, result_type):
            logger.debug("Extracted result from agent_response.data")
            return data

        # Fallback: check output attribute
        output = getattr(agent_response, "output", None)
        if isinstance(output, result_type):
            logger.debug("Extracted result from agent_response.output")
            return output

        # Fallback: try to parse output as JSON if it's a string
        if isinstance(output, str):
            try:
                output_json = json.loads(output)
                result = result_type(**output_json)
                logger.debug("Parsed result from JSON string in output")
                return result
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug("Output is not valid JSON: %s", str(e))

        # Log diagnostic information
        logger.error(
            "Failed to extract %s from OpenAI response. "
            "data type: %s, output type: %s, response type: %s",
            result_type.__name__,
            type(data).__name__ if data is not None else "None",
            type(output).__name__ if output is not None else "None",
            type(agent_response).__name__,
        )

        raise ValueError(
            f"Could not extract {result_type.__name__} from OpenAI response. "
            "Ensure the agent is configured with output_type."
        )
