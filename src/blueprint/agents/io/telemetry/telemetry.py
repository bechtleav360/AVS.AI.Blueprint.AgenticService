"""OpenTelemetry configuration and setup."""

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ..io_base import IOBase

logger = logging.getLogger(__name__)


class TelemetryManager(IOBase):
    """Object-oriented manager for logging and tracing setup."""

    def __init__(self):
        # Do not add to component registry
        super().__init__(should_register=False)

    def configure_tracing(self) -> None:
        """Configure OpenTelemetry tracing using the provided settings."""

        if self.config is None:
            raise ValueError("TelemetryManager.configure_tracing requires a Config instance")

        try:
            observability = self.config.get_observability_config()

            # Check if OpenTelemetry is enabled
            if not observability.otel_enabled:
                logger.info("OpenTelemetry tracing is disabled")
                return

            service_name = observability.otel_service_name

            resource = Resource.create({"service.name": service_name})
            tracer_provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(tracer_provider)

            exporters = self._build_exporters(observability)
            if not exporters:
                logger.warning("No trace exporters configured")
                return

            for exporter in exporters:
                tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

            self._setup_instrumentation()
            logger.info("OpenTelemetry configured for service '%s'", service_name)

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to configure telemetry", exc_info=exc)

    def _setup_instrumentation(self) -> None:
        """Enable automatic instrumentation for supported libraries."""

        try:
            HTTPXClientInstrumentor().instrument()
            logger.debug("HTTPX instrumentation enabled")
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to setup HTTPX instrumentation: %s", exc)

    def _build_exporters(self, observability: Any) -> list[Any]:
        exporters = []

        otlp_endpoint = observability.otel_endpoint
        if otlp_endpoint:
            try:
                # Use gRPC exporter for better performance
                # gRPC doesn't need /v1/traces path, just host:port
                exporters.append(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
                logger.info("OTLP gRPC exporter configured for %s", otlp_endpoint)
            except Exception as exc:
                logger.warning("Failed to configure OTLP exporter: %s", exc)

        # ConsoleSpanExporter disabled - traces are sent to OTLP collector only
        # Uncomment below to enable console output for debugging:
        # if observability.get("log_level", "INFO").upper() == "DEBUG":
        #     exporters.append(ConsoleSpanExporter())
        #     self.logger.info("Console span exporter enabled for debug log level")

        return exporters

    def on_startup(self) -> None:
        """Startup OpenTelemetry.
        """

        # OpenTelemetry does not have a startup method
        pass

    def on_shutdown(self) -> None:
        """Shutdown OpenTelemetry.
        """

        # OpenTelemetry does not have a shutdown method
        pass


class TracingContext:
    """Context manager for creating and managing spans."""

    def __init__(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.name = name
        self.attributes = attributes or {}
        self.span: trace.Span | None = None
        self.tracer = trace.get_tracer(__name__)

    def __enter__(self) -> trace.Span:
        self.span = self.tracer.start_span(self.name)
        assert self.span is not None
        self._add_span_attributes(self.span, self.attributes)
        return self.span

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        if self.span:
            if exc_type is not None:
                self.span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc_val)))
            self.span.end()

    @staticmethod
    def _add_span_attributes(span: trace.Span, attributes: dict[str, Any]) -> None:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, str(value))
