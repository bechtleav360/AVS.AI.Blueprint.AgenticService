"""Base classes for all framework components.

This module contains:
- Abstract base class: Component (unified interface for all components)
- Concrete implementations: EventHandler, AgentRuntime, RestApi, BusinessService, Scheduler

All components extend Component and inherit:
- get_name() -> str
- get_registry() -> ComponentRegistry
- get_config() -> Config
- link_component_registry() and link_config() for dependency injection
- on_startup() and on_shutdown() for lifecycle management
"""

from .agent_runtime import AgentRuntime
from .business_service import BusinessService
from .component import Component
from .event_handler import EventHandler
from .rest_api import RestApi
from .scheduler import Scheduler

__all__ = [
    "Component",
    "AgentRuntime",
    "BusinessService",
    "EventHandler",
    "RestApi",
    "Scheduler",
]
