"""OpenTelemetry configuration and setup."""

import logging
import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from .config import Config

logger = logging.getLogger(__name__)


def setup_telemetry(settings: Config) -> None:
    """
    Set up OpenTelemetry tracing and instrumentation.
    
    Args:
        app_name: Name of the application
    """
    try:
        config = settings.get_observability_config()
        
        # Create resource with service information
        resource = Resource.create({
            "service.name": config["service_name"],
        })
        
        # Parse additional resource attributes
        
        # Set up tracer provider
        tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider)
        
        # Set up span exporters
        exporters = []
        
        # OTLP exporter (if endpoint configured)
        otlp_endpoint = config.get("otel_endpoint")
        if otlp_endpoint:
            try:
                otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
                exporters.append(otlp_exporter)
                logger.info(f"OTLP exporter configured for {otlp_endpoint}")
            except Exception as e:
                logger.warning(f"Failed to configure OTLP exporter: {e}")
        
        # Console exporter (for development)
        if config.get("log_level", "INFO").upper() == "DEBUG":
            console_exporter = ConsoleSpanExporter()
            exporters.append(console_exporter)
            logger.info("Console span exporter enabled for debug mode")
        
        # Add span processors
        for exporter in exporters:
            span_processor = BatchSpanProcessor(exporter)
            tracer_provider.add_span_processor(span_processor)
        
        # Set up automatic instrumentation
        setup_instrumentation()
        
        logger.info("OpenTelemetry telemetry configured successfully")
        
    except Exception as e:
        logger.error(f"Failed to set up telemetry: {e}")
        # Don't fail the application if telemetry setup fails
        pass


def setup_instrumentation() -> None:
    """Set up automatic instrumentation for common libraries."""
    try:
        # Instrument HTTP clients
        HTTPXClientInstrumentor().instrument()
        logger.debug("HTTPX instrumentation enabled")
        
    except Exception as e:
        logger.warning(f"Failed to set up instrumentation: {e}")


def instrument_fastapi(app) -> None:
    """
    Instrument FastAPI application with OpenTelemetry.
    
    Args:
        app: FastAPI application instance
    """
    try:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="actuators/livez,actuators/readyz",  # Exclude health checks
        )
        logger.info("FastAPI instrumentation enabled")
        
    except Exception as e:
        logger.warning(f"Failed to instrument FastAPI: {e}")


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """
    Set up structured logging.
    
    Args:
        log_level: Logging level
        log_format: Logging format (json or text)
    """
    try:
        # Configure root logger
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s" if log_format == "text"
            else "%(message)s",  # JSON formatting would be handled by a JSON formatter
        )
        
        # Set specific logger levels
        logging.getLogger("uvicorn").setLevel(logging.INFO)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("opentelemetry").setLevel(logging.WARNING)
        
        logger.info(f"Logging configured: level={log_level}, format={log_format}")
        
    except Exception as e:
        print(f"Failed to set up logging: {e}")


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
