"""Logging configuration management."""

import logging
import sys


class LoggingManager:
    """Manages logging configuration for the application."""

    def __init__(self) -> None:
        """Initialize the logging manager."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self._configured = False

    def configure(self, log_level: str = "INFO", log_format: str = "text", suppress_noisy_loggers: bool = True) -> None:
        """Configure logging for the application.

        Args:
            log_level: The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            log_format: The log format ('text' or 'json').
            suppress_noisy_loggers: Whether to suppress noisy third-party loggers.
        """
        if self._configured:
            self.logger.debug("Logging already configured, skipping")
            return

        try:
            # Get root logger and configure it
            root_logger = logging.getLogger()

            # Only configure if no handlers exist
            if not root_logger.handlers:
                self._setup_basic_config(log_level, log_format)

            # Suppress noisy loggers
            if suppress_noisy_loggers:
                self._suppress_noisy_loggers()

            self._configured = True
            self.logger.info(
                "Logging configured: level=%s, format=%s", log_level, log_format
            )

        except Exception as exc:
            # Fallback to print if logging setup fails
            print(f"Failed to configure logging: {exc}", file=sys.stderr)
            raise

    def _setup_basic_config(self, log_level: str, log_format: str) -> None:
        """Set up basic logging configuration.

        Args:
            log_level: The logging level.
            log_format: The log format ('text' or 'json').
        """
        format_string = self._get_format_string(log_format)

        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format=format_string,
            stream=sys.stdout,
        )

    def _get_format_string(self, log_format: str) -> str:
        """Get the format string based on the log format type.

        Args:
            log_format: The log format type ('text' or 'json').

        Returns:
            The format string for logging.
        """
        if log_format == "text":
            return "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        elif log_format == "json":
            # For JSON format, we use a simple format and rely on
            # structured logging libraries or log processors
            return "%(message)s"
        else:
            # Default to text format
            return "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def _suppress_noisy_loggers(self) -> None:
        """Suppress noisy third-party loggers."""
        noisy_loggers = {
            "httpx": logging.WARNING,
            "uvicorn": logging.INFO,
            "uvicorn.access": logging.WARNING,
            "opentelemetry": logging.WARNING,
        }

        for logger_name, level in noisy_loggers.items():
            logging.getLogger(logger_name).setLevel(level)

        self.logger.debug("Suppressed noisy loggers")

    def set_level(self, log_level: str) -> None:
        """Change the logging level dynamically.

        Args:
            log_level: The new logging level.
        """
        try:
            level = getattr(logging, log_level.upper(), logging.INFO)
            logging.getLogger().setLevel(level)
            self.logger.info("Logging level changed to %s", log_level)
        except Exception as exc:
            self.logger.error("Failed to set logging level: %s", exc)

    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger instance with the specified name.

        Args:
            name: The name for the logger.

        Returns:
            A logger instance.
        """
        return logging.getLogger(name)
