from .agent_invoker import AgentInvokerHandler
from .simple_processor import SimpleProcessorHandler

# Backwards-compatible alias for legacy imports/tests referencing ProcessingHandler
ProcessingHandler = SimpleProcessorHandler

__all__ = [
    "AgentInvokerHandler",
    "SimpleProcessorHandler",
    "ProcessingHandler",
]
