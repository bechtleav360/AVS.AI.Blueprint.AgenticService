"""Custom models package.

Place your domain-specific model extensions here. These models should extend the
base framework models from `base.src.models.*` so you inherit validation and
serialisation behaviour.

Example usage:

from base.src.models.result import AgentOutput

class MyOutput(AgentOutput):
    pass
"""

from .asset import (
    AssetHarmonizingOutput,
    AssetStatus,
    AssetType,
    HardwareExtension,
    Reference,
    SoftwareExtension,
)
from .payloads import AssetData, HarmonizingInputPayload
from .processing import ProcessingContext
from .resource import InvoiceInput, InvoiceLineItem
from .results import AssetTaggingOutput, HandlerResult, HarmonizingOutput

__all__ = [
    "AssetHarmonizingOutput",
    "AssetData",
    "AssetStatus",
    "AssetTaggingOutput",
    "AssetType",
    "HandlerResult",
    "HardwareExtension",
    "HarmonizingInputPayload",
    "HarmonizingOutput",
    "InvoiceInput",
    "InvoiceLineItem",
    "ProcessingContext",
    "Reference",
    "SoftwareExtension",
]
