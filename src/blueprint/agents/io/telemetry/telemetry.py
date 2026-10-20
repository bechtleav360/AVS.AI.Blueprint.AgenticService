"""OpenTelemetry configuration and setup, with one identity per agent (C2).

A grouped process hosts several agents, and a dashboard, an alert or an SLO keyed on
``service.name`` must not notice that. So this module does not configure *the* provider; it
configures **one provider per namespace**, each with its own ``Resource``:

======================== ======================================================================
``service.name``         The agent's name -- ``otel_service_name`` for the root namespace, so a
                         single-agent application's traces are identical to what it produced
                         before any of this existed.
``deployment.group``     Which group this pod runs: the group the process resolved, from
                         ``BLUEPRINT_GROUP`` or a one-group file (S19). Set by the framework and
                         readable through no supported API (C6). Absent without a named group.
``service.instance.id``  Which replica this is. Absent when it cannot be told.
======================== ======================================================================

A key the deployment declares in ``OTEL_RESOURCE_ATTRIBUTES`` or ``OTEL_SERVICE_NAME`` is never
replaced -- see :func:`_framework_attributes` -- with one exception: in a group, an agent keeps its
own ``service.name`` although ``OTEL_SERVICE_NAME`` is set (W1, plan D17). That variable names one
service, and taken for every agent it would make the group's agents indistinguishable.

**The empty namespace is the one that must not regress.** Implemented naively -- one provider,
``service.name`` set to the group -- every existing dashboard would go dark on the day the
framework was upgraded, before anybody grouped anything. So the root is built first, from
``otel_service_name`` exactly as before, and it is the provider that stays global: every
module-level ``trace.get_tracer`` in the framework and in agent code keeps resolving through it.

**One exporter and one span processor for the whole process.** A ``BatchSpanProcessor`` owns a
queue and a background thread, so a processor per agent would multiply both by the group size
for no gain -- the resource is attached to the span at creation, not at export. The same
processor object is therefore added to every provider. Metric readers cannot be shared the same
way: the SDK binds a reader to the provider that registered it, so each provider gets its own
reader over the one shared exporter. Both shared objects count their providers and are shut down
by the last one (S22): a provider's shutdown shuts down what it holds, and the first agent to
stop would otherwise have closed the export for every other one.
"""

import asyncio
import atexit
import logging
import os
import threading
from collections.abc import Sequence
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult, MetricsData, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.context import Context

from ...component.namespace import ROOT_NAMESPACE
from ...deployment import UNGROUPED_LABEL, UNKNOWN_POD_LABEL, deployment_group, pod_identity
from ..io_base import IOBase
from .providers import has_providers, meter_provider, register_providers, shutdown_providers, tracer_provider

logger = logging.getLogger(__name__)

_exit_hook_registered = False
"""Whether :func:`shutdown_providers` is registered with ``atexit`` -- once per process."""


class _Users:
    """How many providers hold a shared export object; the last to let go closes it (S22)."""

    def __init__(self) -> None:
        self._count = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            self._count += 1

    def release(self) -> bool:
        """Let go of it; ``True`` for the last holder, who closes it."""
        with self._lock:
            self._count -= 1
            return self._count == 0


class _SharedSpanProcessor(SpanProcessor):
    """The process's one span processor, added to every provider and shut down by the last."""

    def __init__(self, processor: SpanProcessor) -> None:
        self._processor = processor
        self._users = _Users()

    def acquire(self) -> "_SharedSpanProcessor":
        self._users.acquire()
        return self

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self._processor.on_start(span, parent_context=parent_context)

    def _on_ending(self, span: Span) -> None:
        self._processor._on_ending(span)

    def on_end(self, span: ReadableSpan) -> None:
        self._processor.on_end(span)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._processor.force_flush(timeout_millis)

    def shutdown(self) -> None:
        if self._users.release():
            self._processor.shutdown()


class _SharedMetricExporter(MetricExporter):
    """The process's one metric exporter, behind every provider's reader and shut down by the last."""

    def __init__(self, exporter: MetricExporter) -> None:
        super().__init__(preferred_temporality=exporter._preferred_temporality, preferred_aggregation=exporter._preferred_aggregation)
        self._exporter = exporter
        self._users = _Users()

    def acquire(self) -> "_SharedMetricExporter":
        self._users.acquire()
        return self

    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any) -> MetricExportResult:
        return self._exporter.export(metrics_data, timeout_millis=timeout_millis, **kwargs)

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return self._exporter.force_flush(timeout_millis=timeout_millis)

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        if self._users.release():
            self._exporter.shutdown(timeout_millis=timeout_millis, **kwargs)


def _framework_attributes(service_name: str, group: str, pod: str, own_service_name: bool = False) -> dict[str, str]:
    """The resource attributes the framework sets, minus every key the deployment declared.

    **What the deployment declares is used as it is.** ``OTEL_RESOURCE_ATTRIBUTES`` (and
    ``OTEL_SERVICE_NAME``) are how a platform labels every service's telemetry without touching its
    code, and ``Resource.create`` merges them underneath whatever it is given -- so an attribute
    set here used to replace a declared one silently. Declared keys are left out of what the
    framework sets; ``Resource.create`` then supplies them from the environment, unchanged.

    **Only attributes that exist.** A group that is not set and a pod that cannot be told are not
    written as placeholders: a standalone agent's resource carries no ``deployment.group``, since it
    belongs to no group.

    **The one exception** is ``own_service_name``: an agent of a group keeps its own
    ``service.name`` although ``OTEL_SERVICE_NAME`` is set (W1, plan D17). Every other declared key,
    and all of ``OTEL_RESOURCE_ATTRIBUTES``, is left as it is.
    """
    attributes = {"service.name": service_name}
    if group != UNGROUPED_LABEL:
        attributes["deployment.group"] = group
    if pod != UNKNOWN_POD_LABEL:
        attributes["service.instance.id"] = pod
    declared = OTELResourceDetector().detect().attributes
    return {key: value for key, value in attributes.items() if key not in declared or (own_service_name and key == "service.name")}


class TelemetryManager(IOBase):
    """Object-oriented manager for logging and tracing setup."""

    def __init__(self) -> None:
        # Do not add to component registry
        super().__init__(should_register=False)

    def configure_tracing(self, namespaces: Sequence[str] = ()) -> None:
        """Configure one tracer and meter provider per namespace, sharing one exporter.

        Args:
            namespaces: The agents this process hosts. The root is configured whether or not it
                appears here, because it is where a single-agent application's components live
                and where the framework's own root components go.
        """

        if self.config is None:
            raise ValueError("TelemetryManager.configure_tracing requires a Config instance")

        try:
            observability = self.config.get_observability_config()

            # Check if OpenTelemetry is enabled
            if not observability.otel_enabled:
                logger.info("OpenTelemetry tracing is disabled")
                return

            span_processors = [_SharedSpanProcessor(BatchSpanProcessor(exporter)) for exporter in self._build_exporters(observability)]
            if not span_processors:
                logger.warning("No trace exporters configured")
                return
            metric_exporters = [_SharedMetricExporter(exporter) for exporter in self._build_metric_exporters(observability)]

            group = deployment_group()
            pod = pod_identity()
            # In a group, OTEL_SERVICE_NAME names the root only (W1, plan D17): one name for
            # every agent would make their telemetry impossible to tell apart.
            grouped = any(namespace != ROOT_NAMESPACE for namespace in namespaces)
            declared_service_name = os.environ.get("OTEL_SERVICE_NAME", "").strip()
            if grouped and declared_service_name:
                logger.warning(
                    "OTEL_SERVICE_NAME is set to '%s', which names the root's telemetry only: in a group every agent "
                    "keeps its own name as service.name, so its telemetry stays apart from the other agents'.",
                    declared_service_name,
                )
            # The root first and always: it is the provider that becomes global, and every
            # module-level trace.get_tracer() in the framework resolves through it.
            for namespace in (ROOT_NAMESPACE, *namespaces):
                if has_providers(namespace):
                    continue
                own_service_name = bool(declared_service_name) and namespace != ROOT_NAMESPACE
                self._configure_namespace(
                    namespace, observability.otel_service_name, group, pod, span_processors, metric_exporters, own_service_name
                )
            _register_exit_hook()

            # The root's provider becomes the global one, so every module-level
            # trace.get_tracer() and metrics.get_meter() -- in this framework and in any
            # library -- keeps resolving exactly as it did before agents had identities.
            root_tracers, root_meters = tracer_provider(ROOT_NAMESPACE), meter_provider(ROOT_NAMESPACE)
            if root_tracers is not None and root_meters is not None:
                trace.set_tracer_provider(root_tracers)
                metrics.set_meter_provider(root_meters)

            self._setup_instrumentation()

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Failed to configure telemetry", exc_info=exc)

    @staticmethod
    def _configure_namespace(
        namespace: str,
        root_service_name: str,
        group: str,
        pod: str,
        span_processors: Sequence[_SharedSpanProcessor],
        metric_exporters: Sequence[_SharedMetricExporter],
        own_service_name: bool = False,
    ) -> None:
        """Build and record the two providers for one namespace.

        ``service.name`` is the agent's own name, which is the whole of C2: an agent moved
        between groups keeps it, so a dashboard keyed on it cannot tell that the move happened.
        The root is the exception and takes ``otel_service_name`` from configuration, because it
        is what every single-agent application already reports.

        Args:
            namespace: The agent to configure; ``""`` for the root.
            root_service_name: ``otel_service_name``, used only for the root.
            group: The deployment group, for ``deployment.group``.
            pod: The replica, for ``service.instance.id``.
            span_processors: The process's span processors, shared by every provider.
            metric_exporters: The process's metric exporters, each wrapped in a reader of this
                provider's own.
            own_service_name: Keep ``service.name`` although ``OTEL_SERVICE_NAME`` declares one --
                an agent of a group (D17).
        """
        service_name = root_service_name if namespace == ROOT_NAMESPACE else namespace
        resource = Resource.create(_framework_attributes(service_name, group, pod, own_service_name))

        # No atexit hook per provider: shutdown_providers() closes them in order, the root last.
        provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        for processor in span_processors:
            # The same processor object on every provider: one queue and one export thread,
            # whatever the group size. The resource travels on the span, not on the processor.
            provider.add_span_processor(processor.acquire())

        # A reader cannot be shared -- the SDK binds its collect callback to the provider that
        # registered it, so a shared one would only ever collect from the last provider built --
        # but the exporter behind it can be.
        readers = [PeriodicExportingMetricReader(exporter.acquire()) for exporter in metric_exporters]
        register_providers(namespace, provider, MeterProvider(resource=resource, metric_readers=readers, shutdown_on_exit=False))

        if group == UNGROUPED_LABEL:
            logger.info("OpenTelemetry configured for service '%s'", service_name)
        else:
            logger.info("OpenTelemetry configured for service '%s' in group '%s'", service_name, group)

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

    @staticmethod
    def _build_metric_exporters(observability: Any) -> list[Any]:
        """Return the metric exporters, of which none is a normal state rather than a failure.

        Unlike traces, an absent metric exporter is not a reason to configure nothing. The
        per-namespace gauges C7 requires -- ``blueprint.namespace.up`` and the in-flight gauge --
        are recorded on these providers, and a provider with no reader still accepts them; they
        simply go nowhere, which is the state every process without a metrics pipeline is in.
        """
        otlp_endpoint = observability.otel_endpoint
        if not otlp_endpoint:
            return []
        try:
            return [OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)]
        except Exception as exc:
            logger.warning("Failed to configure OTLP metric exporter: %s", exc)
            return []

    async def on_startup(self) -> None:
        """Startup OpenTelemetry."""

        # OpenTelemetry does not have a startup method
        pass

    async def on_shutdown(self) -> None:
        """Flush and shut down every provider, the root last (S22).

        In a worker thread: each provider exports what it still holds, and against a collector
        that does not answer that waits for the exporter's timeout.
        """
        await asyncio.to_thread(shutdown_providers)


def _register_exit_hook() -> None:
    """Register :func:`shutdown_providers` with ``atexit`` once, for a process that skips the lifespan."""
    global _exit_hook_registered
    if not _exit_hook_registered:
        atexit.register(shutdown_providers)
        _exit_hook_registered = True


class TracingContext:
    """Context manager for creating and managing spans."""

    def __init__(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.name = name
        self.attributes = attributes or {}
        self.span: trace.Span | None = None
        self.tracer = trace.get_tracer(__name__)

    def __enter__(self) -> trace.Span:
        self.span = self.tracer.start_span(self.name)
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
