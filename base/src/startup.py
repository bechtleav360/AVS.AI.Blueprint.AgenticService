"""Startup initialization for the agent application."""

import logging
from typing import List, Type, TypedDict

from .agent.base.decisions.event_handler import EventHandler
from .agent.base.runtime.base_agent import BaseAgent
from .config import Config
from .registry import handler_registry, runtime_registry

logger = logging.getLogger(__name__)


class _RuntimeInfo(TypedDict):
    """Type hint for runtime class and its default status."""

    runtime_class: Type[BaseAgent]
    is_default: bool


class StartupManager:
    """Manages the startup and registration of handlers and runtimes."""

    def __init__(self, config: Config):
        self.config = config
        self._initialized = False
        self._handler_classes: List[Type[EventHandler]] = []
        self._runtime_classes: List[_RuntimeInfo] = []

    def register_handler(self, handler_class: Type[EventHandler]) -> None:
        """Register a handler class to be initialized at startup."""
        self._handler_classes.append(handler_class)

    def register_runtime(
        self, runtime_class: Type[BaseAgent], is_default: bool = False
    ) -> None:
        """Register an agent runtime class to be initialized at startup."""
        self._runtime_classes.append(
            {"runtime_class": runtime_class, "is_default": is_default}
        )

    def initialize_components(self) -> None:
        """
        Initialize and register all agent components.
        """
        if self._initialized:
            logger.warning("Startup manager already initialized, skipping")
            return

        logger.info("Initializing agent components")

        # Initialize and register handlers
        try:
            handlers = [handler_class() for handler_class in self._handler_classes]
            handler_registry.register_handlers(handlers)
            logger.info("Successfully registered %d handlers", len(handlers))
        except Exception as e:
            logger.error("Failed to register handlers: %s", str(e), exc_info=True)

        # Initialize and register runtimes
        try:
            for runtime_info in self._runtime_classes:
                runtime_class = runtime_info["runtime_class"]
                is_default = runtime_info["is_default"]
                runtime_instance = runtime_class(self.config)
                runtime_registry.register_runtime(
                    runtime_class.__name__, runtime_instance, is_default=is_default
                )
            logger.info(
                "Successfully registered %d runtimes", len(self._runtime_classes)
            )
        except Exception as e:
            logger.error("Failed to register runtimes: %s", str(e), exc_info=True)

        self._initialized = True
        logger.info("Startup initialization completed")

    def is_initialized(self) -> bool:
        """Check if the startup manager has been initialized."""
        return self._initialized

    def reset(self) -> None:
        """Reset the startup manager (useful for testing)."""
        logger.info("Resetting startup manager")
        handler_registry.clear_handlers()
        runtime_registry.clear_runtimes()
        self._initialized = False
