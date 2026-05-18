"""Logging configuration management and correlation ID utilities."""

from __future__ import annotations

import contextvars
import logging
import sys


class HealthCheckFilter(logging.Filter):
    """Filter to suppress successful health check requests from logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out successful health check requests.

        Only logs health checks if they fail (status >= 400).
        """
        message = record.getMessage()

        # Check if this is a uvicorn access log for health endpoints
        if hasattr(record, "name") and record.name == "uvicorn.access":
            # Filter out successful health check requests (status 200)
            if "/health/live" in message or "/health/ready" in message:
                # Only log if it's an error (status >= 400)
                if " 200 " in message or " 204 " in message:
                    return False

        return True


class CorrelationContext:
    """Tracks correlation IDs via context variables."""

    def __init__(self) -> None:
        self._var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="n/a")

    def set(self, value: str | None) -> contextvars.Token[str]:
        """Set the correlation ID for current context and return token."""

        normalized = value or ""
        return self._var.set(normalized)

    def reset(self, token: contextvars.Token[str] | None) -> None:
        """Reset correlation ID to previous value using provided token."""

        if token is None:
            return
        self._var.reset(token)

    def get(self) -> str:
        """Return correlation ID for current context."""

        return self._var.get()

    def build_filter(self) -> logging.Filter:
        """Return a logging filter bound to this context."""

        context = self

        class _CorrelationIdFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
                record.correlation_id = context.get()
                return True

        return _CorrelationIdFilter()


class CorrelationContextProvider:
    """Lazily provides a shared CorrelationContext instance."""

    _instance = CorrelationContext()

    @staticmethod
    def get_correlation_context() -> CorrelationContext:
        return CorrelationContextProvider._instance


class LoggingManager:
    """Manages logging configuration for the application."""

    def __init__(self, correlation: CorrelationContext | None = None) -> None:
        """Initialize the logging manager."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self._configured = False
        self._correlation_context = correlation or CorrelationContextProvider.get_correlation_context()
        self._correlation_filter = self._correlation_context.build_filter()
        self._health_check_filter = HealthCheckFilter()

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

            # Attach correlation-id filter to all root handlers
            self._attach_correlation_filter()

            # Attach health check filter to uvicorn.access logger
            self._attach_health_check_filter()

            # Suppress noisy loggers
            if suppress_noisy_loggers:
                self._suppress_noisy_loggers()

            self._configured = True
            self.logger.info("Logging configured: level=%s, format=%s", log_level, log_format)

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
            return "%(asctime)s - %(name)s - %(levelname)s - %(correlation_id)s - %(message)s"
        elif log_format == "json":
            # For JSON format, emit key-value line that downstream processors can parse
            return (
                '{"timestamp":"%(asctime)s","level":"%(levelname)s","name":"%(name)s",'
                '"correlation_id":"%(correlation_id)s","message":"%(message)s"}'
            )
        else:
            # Default to text format
            return "%(asctime)s - %(name)s - %(levelname)s - %(correlation_id)s - %(message)s"

    def _suppress_noisy_loggers(self) -> None:
        """Suppress noisy third-party loggers."""
        noisy_loggers = {
            "httpx": logging.WARNING,
            "httpcore": logging.WARNING,
            "uvicorn": logging.INFO,
            "uvicorn.access": logging.WARNING,
            "opentelemetry": logging.WARNING,
            "openai": logging.INFO,
            "apscheduler": logging.WARNING,
        }
        # Suppress verbose output from httpcore without touching vendored packages.
        for logger_name, level in noisy_loggers.items():
            logging.getLogger(logger_name).setLevel(level)

        self.logger.debug("Suppressed noisy loggers")

    def _attach_correlation_filter(self) -> None:
        """Attach the correlation-id filter to root logger and handlers."""

        root_logger = logging.getLogger()
        if self._correlation_filter not in root_logger.filters:
            root_logger.addFilter(self._correlation_filter)

        for handler in root_logger.handlers:
            if self._correlation_filter not in handler.filters:
                handler.addFilter(self._correlation_filter)

    def _attach_health_check_filter(self) -> None:
        """Attach the health check filter to uvicorn.access logger."""

        uvicorn_access_logger = logging.getLogger("uvicorn.access")
        if self._health_check_filter not in uvicorn_access_logger.filters:
            uvicorn_access_logger.addFilter(self._health_check_filter)
            self.logger.debug("Attached health check filter to uvicorn.access logger")

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
