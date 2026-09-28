"""Base classes for all framework components.

This module contains:
- Abstract base class: Component (unified interface for all components)

All components extend Component and inherit:
- name -> str
- registry -> Registry
- config -> Config
- on_startup() and on_shutdown() for lifecycle management
"""

from .component import Component, traced

__all__ = [
    "Component",
    "traced",
]
