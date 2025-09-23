"""Custom models package.

Place your domain-specific model extensions here. These models should extend the
base framework models from `base.src.models.*` so you inherit validation and
serialisation behaviour.

Example usage:

from base.src.models.domain import AgentOutput

class MyOutput(AgentOutput):
    pass
"""

from processing import ProcessingContext
from results import CustomAgentOutput
from resource import ResourceInput

__all__ = [
    "ProcessingContext",
    "CustomAgentOutput",
    "ResourceInput",
]
