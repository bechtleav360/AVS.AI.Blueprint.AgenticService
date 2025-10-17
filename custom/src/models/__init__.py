"""Custom models package.

Place your domain-specific model extensions here. These models should extend the
base framework models from `base.src.models.*` so you inherit validation and
serialisation behaviour.

Example usage:

from base.src.models.result import AgentOutput

class MyOutput(AgentOutput):
    pass
"""

from .payloads import CustomPayload
from .processing import ProcessingContext
from .resource import InvoiceInput, InvoiceLineItem
from .results import HandlerResult, InvoiceAnalysisOutput

__all__ = [
    "CustomPayload",
    "ProcessingContext",
    "InvoiceAnalysisOutput",
    "HandlerResult",
    "InvoiceInput",
    "InvoiceLineItem",
]
