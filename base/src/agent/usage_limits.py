"""Utility for building usage limits from configuration."""

import logging
from typing import Any, Dict, Optional

from pydantic_ai.usage import UsageLimits

logger = logging.getLogger(__name__)


class UsageLimitsBuilder:
    """Builder for creating UsageLimits from configuration."""

    @staticmethod
    def build_from_config(ai_config: Dict[str, Any]) -> Optional[UsageLimits]:
        """Build UsageLimits from AI configuration.

        Args:
            ai_config: Configuration dictionary that may contain 'usage_limits'.

        Returns:
            UsageLimits instance if any limits are configured, None otherwise.
        """
        limits = ai_config.get("usage_limits", {})

        # Only create UsageLimits if at least one limit is set
        if not any(limits.values()):
            logger.debug("No usage limits configured")
            return None

        usage_limits = UsageLimits(
            request_limit=limits.get("request_limit"),
            input_tokens_limit=limits.get("input_tokens_limit"),
            output_tokens_limit=limits.get("output_tokens_limit"),
            total_tokens_limit=limits.get("total_tokens_limit"),
        )

        logger.info(
            "Usage limits configured: requests=%s, input_tokens=%s, output_tokens=%s, total_tokens=%s",
            usage_limits.request_limit,
            usage_limits.input_tokens_limit,
            usage_limits.output_tokens_limit,
            usage_limits.total_tokens_limit,
        )

        return usage_limits
