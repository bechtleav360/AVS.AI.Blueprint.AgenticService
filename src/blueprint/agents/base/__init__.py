"""Base classes and interfaces for all framework components.

This module contains:
- Abstract base classes: EventHandler, AgentRuntime, RestApi, BusinessService
- Interface definitions: ComponentInterface

All components must implement:
- get_registry() -> ComponentRegistry
- name: str (attribute)
- link_component_registry() and link_config() for dependency injection
- Optionally: on_startup() and on_shutdown() for lifecycle management
"""

from .agent_runtime import AgentRuntime
from .business_service import BusinessService
from .event_handler import EventHandler
from .rest_api import RestApi
from .interfaces import ComponentInterface

__all__ = [
    "AgentRuntime",
    "BusinessService",
    "EventHandler",
    "RestApi",
    "ComponentInterface",
]
