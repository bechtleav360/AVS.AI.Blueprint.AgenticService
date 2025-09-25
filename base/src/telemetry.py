"""OpenTelemetry configuration and setup."""

import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from .config import Config


class TelemetryManager:
    """Object-oriented manager for logging and tracing setup."""

    def __init__(self, settings: Optional[Config] = None, *, logger: Optional[logging.Logger] = None) -> None:
        self.settings = settings
        self.logger = logger or logging.getLogger(self.__class__.__name__)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def configure_tracing(self) -> None:
        """Configure OpenTelemetry tracing using the provided settings."""

        if self.settings is None:
            raise ValueError("TelemetryManager.configure_tracing requires a Config instance")

        try:
            observability = self.settings.get_observability_config()
            service_name = observability.get("service_name", "agent-service")

            resource = Resource.create({"service.name": service_name})
            tracer_provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(tracer_provider)

            exporters = self._build_exporters(observability)
            for exporter in exporters:
                tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

            self.setup_instrumentation()
            self.logger.info("OpenTelemetry configured for service '%s'", service_name)

        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error("Failed to configure telemetry", exc_info=exc)

    def setup_instrumentation(self) -> None:
        """Enable automatic instrumentation for supported libraries."""

        try:
            HTTPXClientInstrumentor().instrument()
            self.logger.debug("HTTPX instrumentation enabled")
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.warning("Failed to setup HTTPX instrumentation: %s", exc)

    def instrument_fastapi(self, app) -> None:
        """Instrument the FastAPI application."""

        try:
            FastAPIInstrumentor.instrument_app(
                app,
                excluded_urls="actuators/livez,actuators/readyz",
            )
            self.logger.info("FastAPI instrumentation enabled")
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.warning("Failed to instrument FastAPI: %s", exc)

    def setup_logging(self, log_level: str = "INFO", log_format: str = "json") -> None:
        """Configure structured logging for the application."""

        try:
            logging.basicConfig(
                level=getattr(logging, log_level.upper()),
                format=(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                    if log_format == "text"
                    else "%(message)s"
                ),
            )

            logging.getLogger("uvicorn").setLevel(logging.INFO)
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("opentelemetry").setLevel(logging.WARNING)

            self.logger.info("Logging configured: level=%s, format=%s", log_level, log_format)

        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"Failed to set up logging: {exc}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_exporters(self, observability: dict) -> list:
        exporters = []

        otlp_endpoint = observability.get("otel_endpoint")
        if otlp_endpoint:
            try:
                exporters.append(OTLPSpanExporter(endpoint=otlp_endpoint))
                self.logger.info("OTLP exporter configured for %s", otlp_endpoint)
            except Exception as exc:
                self.logger.warning("Failed to configure OTLP exporter: %s", exc)

        if observability.get("log_level", "INFO").upper() == "DEBUG":
            exporters.append(ConsoleSpanExporter())
            self.logger.info("Console span exporter enabled for debug log level")

        return exporters


# ----------------------------------------------------------------------
# Backwards-compatible functional wrappers
# ----------------------------------------------------------------------


def setup_telemetry(settings: Config) -> None:
    """Legacy wrapper to configure telemetry using the default manager."""

    TelemetryManager(settings=settings).configure_tracing()


def setup_instrumentation() -> None:
    """Legacy wrapper for instrumentation setup."""

    TelemetryManager().setup_instrumentation()


def instrument_fastapi(app) -> None:
    """Legacy wrapper to instrument FastAPI applications."""

    TelemetryManager().instrument_fastapi(app)


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Legacy wrapper for logging configuration."""

    TelemetryManager().setup_logging(log_level=log_level, log_format=log_format)


def get_tracer(name: str) -> trace.Tracer:
    """
    Get a tracer instance.
    
    Args:
        name: Tracer name (usually module name)
        
    Returns:
        Tracer instance
    """
    return trace.get_tracer(name)


def add_span_attributes(span: trace.Span, attributes: dict) -> None:
    """
    Add multiple attributes to a span.
    
    Args:
        span: OpenTelemetry span
        attributes: Dictionary of attributes to add
    """
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, str(value))


def create_child_span(name: str, parent_span: Optional[trace.Span] = None) -> trace.Span:
    """
    Create a child span.
    
    Args:
        name: Span name
        parent_span: Parent span (if None, uses current span)
        
    Returns:
        New child span
    """
    tracer = trace.get_tracer(__name__)
    
    if parent_span:
        with trace.use_span(parent_span):
            return tracer.start_span(name)
    else:
        return tracer.start_span(name)


class TracingContext:
    """Context manager for creating and managing spans."""
    
    def __init__(self, name: str, attributes: Optional[dict] = None):
        self.name = name
        self.attributes = attributes or {}
        self.span = None
        self.tracer = trace.get_tracer(__name__)
    
    def __enter__(self) -> trace.Span:
        self.span = self.tracer.start_span(self.name)
        add_span_attributes(self.span, self.attributes)
        return self.span
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            if exc_type is not None:
                self.span.set_status(
                    trace.Status(trace.StatusCode.ERROR, str(exc_val))
                )
            self.span.end()


# Convenience function for creating traced functions
def traced(name: Optional[str] = None, attributes: Optional[dict] = None):
    """
    Decorator for automatically tracing function calls.
    
    Args:
        name: Span name (defaults to function name)
        attributes: Additional span attributes
        
    Returns:
        Decorated function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            span_name = name or f"{func.__module__}.{func.__name__}"
            
            with TracingContext(span_name, attributes) as span:
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.message", str(e))
                    raise
        
        return wrapper
    return decorator
