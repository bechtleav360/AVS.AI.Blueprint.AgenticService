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
    Asset,
    AssetStatus,
    AssetType,
    HardwareExtension,
    Reference,
    SoftwareExtension,
)
from .payloads import CustomPayload
from .processing import ProcessingContext
from .resource import InvoiceInput, InvoiceLineItem
from .results import AssetTaggingOutput, HandlerResult, HarmonizingOutput

__all__ = [
    "Asset",
    "AssetStatus",
    "AssetTaggingOutput",
    "AssetType",
    "CustomPayload",
    "HandlerResult",
    "HardwareExtension",
    "HarmonizingOutput",
    "InvoiceInput",
    "InvoiceLineItem",
    "ProcessingContext",
    "Reference",
    "SoftwareExtension",
]
