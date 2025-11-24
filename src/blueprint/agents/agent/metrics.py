"""Metrics recording and extraction for agent executions."""

import logging
from typing import Any

from pydantic_ai.run import AgentRunResult

from ..config import Config

logger: logging.Logger = logging.getLogger(__name__)


class MetricsRecorder:
    """Records and manages LLM metrics for agent executions.

    Handles both logging and OpenTelemetry recording of token usage and latency metrics.
    """

    def __init__(self, config: Config, meter: Any | None = None, model: Any | None = None):
        """Initialize the metrics recorder.

        Args:
            config: Application configuration
            meter: Optional OpenTelemetry Meter for metrics recording
            model: Optional model instance for extracting model name
        """
        self._config = config
        self._meter = meter
        self._model = model

    def record(
        self,
        result: AgentRunResult,
        duration_ms: float,
        model_name: str,
    ) -> None:
        """Record LLM metrics to logs and OpenTelemetry.

        Always logs token usage and response latency metrics. Records to OpenTelemetry
        only if both otel_enabled and token_metrics_enabled are True in config.

        Args:
            result: The AgentRunResult object from agent.run()
            duration_ms: Response time in milliseconds
            model_name: Name of the LLM model (e.g., "gpt-4o-mini")

        Behavior:
            - Usage information is ALWAYS logged to application logs
            - OpenTelemetry recording only happens if:
              - otel_enabled=True AND token_metrics_enabled=True in config
              - AND meter is provided to MetricsRecorder

        Example:
            import time

            start = time.time()
            result = await agent.run(prompt)
            duration_ms = (time.time() - start) * 1000
            recorder.record(result, duration_ms, "gpt-4o-mini")
        """
        # Extract usage information
        usage = MetricsExtractor.extract_usage_info(result)

        # ALWAYS log usage information
        if usage:
            logger.info(
                "LLM Metrics - Model: %s, Input tokens: %s, Output tokens: %s, Total tokens: %s, Response time: %.2fms (%.2fs)",
                model_name,
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                usage.get("total_tokens"),
                duration_ms,
                duration_ms / 1000.0,
            )
        else:
            logger.warning(
                "No usage information available for model: %s, Response time: %.2fms (%.2fs)",
                model_name,
                duration_ms,
                duration_ms / 1000.0,
            )

        # Check if OpenTelemetry metrics should be recorded
        otel_metrics_enabled = False
        try:
            observability = self._config.get_observability_config()
            # OpenTelemetry metrics only recorded if both settings are enabled
            otel_metrics_enabled = observability.otel_enabled and observability.token_metrics_enabled
        except Exception as e:
            logger.warning("Error checking observability config: %s", str(e))

        # Record to OpenTelemetry if enabled and meter is provided
        if otel_metrics_enabled and self._meter is not None and usage:
            try:
                # Record token usage as counter
                token_counter = self._meter.create_counter(
                    name="llm.tokens.count",
                    description="Number of tokens processed by the LLM",
                    unit="tokens",
                )
                token_counter.add(
                    usage.get("total_tokens", 0),
                    {"model": model_name, "type": "total"},
                )

                # Record input tokens
                if usage.get("input_tokens"):
                    token_counter.add(
                        usage.get("input_tokens", 0),
                        {"model": model_name, "type": "prompt"},
                    )

                # Record output tokens
                if usage.get("output_tokens"):
                    token_counter.add(
                        usage.get("output_tokens", 0),
                        {"model": model_name, "type": "completion"},
                    )

                # Record response latency as histogram
                latency_histogram = self._meter.create_histogram(
                    name="llm.response.latency",
                    description="Distribution of LLM response times",
                    unit="ms",
                )
                latency_histogram.record(duration_ms, {"model": model_name})

                logger.debug("OpenTelemetry metrics recorded successfully")
            except Exception as e:
                logger.error("Error recording OpenTelemetry metrics: %s", str(e))
        elif not otel_metrics_enabled:
            logger.debug("OpenTelemetry metrics recording disabled (otel_enabled or token_metrics_enabled is False)")


class MetricsExtractor:
    """Extracts metrics and information from agent results."""

    @staticmethod
    def extract_response_text(result: AgentRunResult) -> str:
        """Extract response text from an agent result.

        Handles different response types from Pydantic AI agents:
        - Structured responses with .data attribute
        - String responses wrapped in AgentRunResult with .output attribute
        - Plain string responses
        - Fallback to string representation

        Args:
            result: The agent result object

        Returns:
            The response text as a string

        Example:
            result = await agent.run(prompt)
            response_text = MetricsExtractor.extract_response_text(result)
            data = json.loads(response_text)
        """
        # Try different attributes in order of preference
        if hasattr(result, "data"):
            return result.data
        elif hasattr(result, "output"):
            return result.output
        else:
            return str(result)

    @staticmethod
    def extract_usage_info(result: AgentRunResult) -> dict[str, Any]:
        """Extract usage information from an agent result.

        Extracts token counts and other usage metrics from the Pydantic AI agent result.
        The result object has a `usage` attribute (RunUsage) containing token information.

        Args:
            result: The AgentRunResult object from agent.run()

        Returns:
            Dictionary with usage information:
            - input_tokens: Tokens sent to the language model
            - output_tokens: Tokens generated by the model
            - total_tokens: Total tokens consumed (input + output)
            - requests: Number of model API calls

        Example:
            result = await agent.run(prompt)
            usage = MetricsExtractor.extract_usage_info(result)
            logger.info("Tokens - Input: %d, Output: %d, Total: %d",
                       usage.get("input_tokens"),
                       usage.get("output_tokens"),
                       usage.get("total_tokens"))
        """
        usage_info: dict[str, Any] = {}

        # Extract from usage() method (RunUsage object from Pydantic AI)
        # Note: usage is a method, not an attribute
        if hasattr(result, "usage") and callable(result.usage):
            try:
                usage = result.usage()
                if usage is not None:
                    # RunUsage object has these attributes
                    if hasattr(usage, "input_tokens"):
                        usage_info["input_tokens"] = usage.input_tokens
                    if hasattr(usage, "output_tokens"):
                        usage_info["output_tokens"] = usage.output_tokens
                    if hasattr(usage, "total_tokens"):
                        usage_info["total_tokens"] = usage.total_tokens
                    if hasattr(usage, "requests"):
                        usage_info["requests"] = usage.requests
                else:
                    logger.info("Result.usage() returned None")
            except Exception as e:
                logger.info("Error calling result.usage(): %s", str(e))
        else:
            logger.info("Result object has no callable usage method")

        return usage_info
