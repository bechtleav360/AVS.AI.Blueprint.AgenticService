"""OpenTelemetry configuration and setup."""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import \
    OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .config import Config


class TelemetryManager:
    """Object-oriented manager for logging and tracing setup."""

    def __init__(
        self,
        settings: Config | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
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

            # Check if OpenTelemetry is enabled
            if not observability.otel_enabled:
                self.logger.info("OpenTelemetry tracing is disabled")
                return

            service_name = observability.otel_service_name

            resource = Resource.create({"service.name": service_name})
            tracer_provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(tracer_provider)

            exporters = self._build_exporters(observability)
            if not exporters:
                self.logger.warning("No trace exporters configured")
                return

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
                format=("%(asctime)s - %(name)s - %(levelname)s - %(message)s" if log_format == "text" else "%(message)s"),
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
    def _build_exporters(self, observability) -> list:
        exporters = []

        otlp_endpoint = observability.otel_endpoint
        if otlp_endpoint:
            try:
                # Use gRPC exporter for better performance
                # gRPC doesn't need /v1/traces path, just host:port
                exporters.append(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
                self.logger.info("OTLP gRPC exporter configured for %s", otlp_endpoint)
            except Exception as exc:
                self.logger.warning("Failed to configure OTLP exporter: %s", exc)

        # ConsoleSpanExporter disabled - traces are sent to OTLP collector only
        # Uncomment below to enable console output for debugging:
        # if observability.get("log_level", "INFO").upper() == "DEBUG":
        #     exporters.append(ConsoleSpanExporter())
        #     self.logger.info("Console span exporter enabled for debug log level")

        return exporters


class TracingContext:
    """Context manager for creating and managing spans."""

    def __init__(self, name: str, attributes: dict | None = None):
        self.name = name
        self.attributes = attributes or {}
        self.span = None
        self.tracer = trace.get_tracer(__name__)

    def __enter__(self) -> trace.Span:
        self.span = self.tracer.start_span(self.name)
        self._add_span_attributes(self.span, self.attributes)
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.span:
            if exc_type is not None:
                self.span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc_val)))
            self.span.end()

    @staticmethod
    def _add_span_attributes(span: trace.Span, attributes: dict) -> None:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, str(value))
