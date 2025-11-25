"""Deprecated response handler abstractions.

.. deprecated::
    These abstractions are no longer part of the primary agent pipeline.
    They are retained for compatibility with legacy provider implementations
    (for example, the optional OpenAI and vLLM response handlers) but will be
    removed in a future release once downstream dependencies are updated.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar


T = TypeVar("T")


class ResponseHandlerStrategy(Generic[T], ABC):
    """Legacy strategy base class for extracting structured results."""

    @abstractmethod
    def extract_result(self, agent_response: Any, result_type: type[T]) -> T:
        """Extract the provider result and cast it into ``result_type``."""
