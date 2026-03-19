"""
Abstract base class for all IO components.

This module provides the common interface that all IO components
implement.
"""

from abc import ABC

from ..component import Component


class IOBase(Component, ABC):
    pass
