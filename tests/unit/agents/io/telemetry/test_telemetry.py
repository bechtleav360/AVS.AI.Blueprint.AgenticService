"""Unit tests for TelemetryManager and TracingContext."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.io.telemetry.providers import agent_meter, agent_tracer, configured_namespaces, reset_providers, tracer_provider
from blueprint.agents.io.telemetry.telemetry import TelemetryConfigError, TelemetryManager, TracingContext
from blueprint.agents.models.config import ObservabilityConfig


@pytest.fixture(autouse=True)
def _forget_providers() -> Iterator[None]:
    """Clear the per-namespace providers around every case.

    They live in a module-level register, which is what lets a component reach its own without
    holding the manager (C6). That makes them process state, so one case's providers would
    otherwise satisfy the next case's assertions -- and ``configure_tracing`` skips a namespace
    that already has one, so the second case would configure nothing at all.
    """
    reset_providers()
    yield
    reset_providers()


@pytest.fixture(autouse=True)
def _agent_views(mock_config: MagicMock) -> None:
    """An agent's view reports the agent's name, as ``Config`` does for an agent that sets none (C2)."""
    mock_config.for_namespace.side_effect = lambda namespace: MagicMock(
        get_observability_config=MagicMock(return_value=ObservabilityConfig(otel_service_name=namespace))
    )


@pytest.fixture
def telemetry_manager(mock_config: MagicMock, mock_registry: MagicMock) -> TelemetryManager:
    """Return a TelemetryManager with mocked config."""
    return TelemetryManager()


@pytest.fixture
def disabled_observability() -> ObservabilityConfig:
    return ObservabilityConfig(otel_enabled=False)


@pytest.fixture
def enabled_observability() -> ObservabilityConfig:
    return ObservabilityConfig(
        otel_enabled=True,
        otel_service_name="test-service",
        otel_endpoint="localhost:4317",
    )


@pytest.fixture
def enabled_no_endpoint_observability() -> ObservabilityConfig:
    return ObservabilityConfig(
        otel_enabled=True,
        otel_service_name="test-service",
        otel_endpoint=None,
    )


class TestConfigureTracing:
    def test_raises_when_config_is_none(self, telemetry_manager: TelemetryManager) -> None:
        from blueprint.agents.component.component import Component

        Component.reset_shared_state()
        with pytest.raises((ValueError, RuntimeError)):
            telemetry_manager.configure_tracing()

    def test_no_op_when_otel_disabled(
        self,
        telemetry_manager: TelemetryManager,
        mock_config: MagicMock,
        disabled_observability: ObservabilityConfig,
    ) -> None:
        mock_config.get_observability_config.return_value = disabled_observability
        with patch("blueprint.agents.io.telemetry.telemetry.TracerProvider") as mock_provider:
            telemetry_manager.configure_tracing()
        mock_provider.assert_not_called()

    def test_creates_tracer_provider_when_enabled(
        self,
        telemetry_manager: TelemetryManager,
        mock_config: MagicMock,
        enabled_observability: ObservabilityConfig,
    ) -> None:
        mock_config.get_observability_config.return_value = enabled_observability
        with (
            patch("blueprint.agents.io.telemetry.telemetry.TracerProvider") as mock_provider_cls,
            patch("blueprint.agents.io.telemetry.telemetry.Resource"),
            patch("blueprint.agents.io.telemetry.telemetry.trace"),
            patch.object(telemetry_manager, "_build_exporters", return_value=[MagicMock()]),
            patch.object(telemetry_manager, "_build_metric_exporters", return_value=[]),
            patch.object(telemetry_manager, "_setup_instrumentation"),
        ):
            mock_provider = MagicMock()
            mock_provider_cls.return_value = mock_provider
            telemetry_manager.configure_tracing()
        mock_provider_cls.assert_called_once()


class TestOneIdentityPerAgent:
    """C2: each agent gets its own providers, and the root keeps the one it always had."""

    @pytest.fixture
    def configure(self, telemetry_manager: TelemetryManager, mock_config: MagicMock, enabled_observability: ObservabilityConfig):
        """Return a callable that configures telemetry for the given agents, exporting nothing."""

        def _configure(*namespaces: str) -> None:
            mock_config.get_observability_config.return_value = enabled_observability
            with (
                patch.object(telemetry_manager, "_build_exporters", return_value=[MagicMock()]),
                patch.object(telemetry_manager, "_build_metric_exporters", return_value=[]),
                patch.object(telemetry_manager, "_setup_instrumentation"),
            ):
                telemetry_manager.configure_tracing(namespaces)

        return _configure

    @staticmethod
    def _attributes(namespace: str) -> dict[str, object]:
        provider = tracer_provider(namespace)
        assert provider is not None
        return dict(provider.resource.attributes)

    def test_the_root_is_configured_even_when_no_agent_is(self, configure) -> None:
        configure()
        assert configured_namespaces() == ("",)

    def test_the_root_keeps_the_configured_service_name(self, configure) -> None:
        configure("orders")
        assert self._attributes("")["service.name"] == "test-service"

    def test_an_agent_is_its_own_service(self, configure) -> None:
        configure("orders", "billing")
        assert self._attributes("orders")["service.name"] == "orders"
        assert self._attributes("billing")["service.name"] == "billing"

    def test_every_resource_carries_the_deployment(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BLUEPRINT_GROUP", "finance")
        monkeypatch.setenv("POD_NAME", "pod-7")
        configure("orders")
        for namespace in ("", "orders"):
            assert self._attributes(namespace)["deployment.group"] == "finance"
            assert self._attributes(namespace)["service.instance.id"] == "pod-7"

    def test_one_span_processor_serves_every_provider(self, configure) -> None:
        """A processor per agent would be a queue and an export thread per agent."""
        configure("orders", "billing")
        processors = {id(tracer_provider(namespace)._active_span_processor) for namespace in ("", "orders", "billing")}
        assert len(processors) == 3, "each provider has its own multi-processor wrapper"
        underlying = {
            id(processor)
            for namespace in ("", "orders", "billing")
            for processor in tracer_provider(namespace)._active_span_processor._span_processors
        }
        assert len(underlying) == 1

    def test_a_tracer_comes_from_its_own_agents_provider(self, configure) -> None:
        configure("orders")
        assert agent_tracer("orders", "X") is not agent_tracer("", "X")

    def test_an_unconfigured_agent_falls_back_rather_than_failing(self, configure) -> None:
        configure("orders")
        assert agent_tracer("nobody", "X") is not None
        assert agent_meter("nobody", "X") is not None

    def test_configuring_twice_does_not_replace_a_provider(self, configure) -> None:
        configure("orders")
        first = tracer_provider("orders")
        configure("orders")
        assert tracer_provider("orders") is first


class TestBuildExporters:
    def test_returns_otlp_exporter_when_endpoint_configured(
        self,
        telemetry_manager: TelemetryManager,
        enabled_observability: ObservabilityConfig,
    ) -> None:
        with patch("blueprint.agents.io.telemetry.telemetry.OTLPSpanExporter") as mock_exporter_cls:
            exporters = telemetry_manager._build_exporters(enabled_observability)
        assert len(exporters) == 1
        mock_exporter_cls.assert_called_once_with(endpoint="localhost:4317", insecure=True)

    def test_returns_empty_list_when_no_endpoint(
        self,
        telemetry_manager: TelemetryManager,
        enabled_no_endpoint_observability: ObservabilityConfig,
    ) -> None:
        exporters = telemetry_manager._build_exporters(enabled_no_endpoint_observability)
        assert exporters == []


# ---------------------------------------------------------------------------
# TracingContext
# ---------------------------------------------------------------------------


class TestTracingContext:
    def test_enter_returns_span(self) -> None:
        with TracingContext("test-operation") as span:
            assert span is not None

    def test_span_is_ended_on_exit(self) -> None:
        ctx = TracingContext("test-op")
        with patch.object(ctx, "tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            with ctx:
                pass
        mock_span.end.assert_called_once()

    def test_span_status_set_to_error_on_exception(self) -> None:
        ctx = TracingContext("test-op")
        with patch.object(ctx, "tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            with pytest.raises(ValueError):
                with ctx:
                    raise ValueError("test error")
        mock_span.set_status.assert_called_once()

    def test_attributes_are_added_to_span(self) -> None:
        ctx = TracingContext("test-op", attributes={"key": "value"})
        with patch.object(ctx, "tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            with ctx:
                pass
        mock_span.set_attribute.assert_called_with("key", "value")

    def test_none_attribute_values_are_skipped(self) -> None:
        ctx = TracingContext("test-op", attributes={"key": None, "other": "val"})
        with patch.object(ctx, "tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_tracer.start_span.return_value = mock_span
            with ctx:
                pass
        called_keys = [call[0][0] for call in mock_span.set_attribute.call_args_list]
        assert "key" not in called_keys
        assert "other" in called_keys


class TestTheDeploymentDeclaresTheResource:
    """OTEL_RESOURCE_ATTRIBUTES is the deployment's word: declared values are used as they are."""

    @pytest.fixture
    def configure(self, telemetry_manager: TelemetryManager, mock_config: MagicMock, enabled_observability: ObservabilityConfig):
        def _configure(*namespaces: str) -> None:
            mock_config.get_observability_config.return_value = enabled_observability
            with (
                patch.object(telemetry_manager, "_build_exporters", return_value=[MagicMock()]),
                patch.object(telemetry_manager, "_build_metric_exporters", return_value=[]),
                patch.object(telemetry_manager, "_setup_instrumentation"),
            ):
                telemetry_manager.configure_tracing(namespaces)

        return _configure

    @staticmethod
    def _attributes(namespace: str) -> dict[str, object]:
        provider = tracer_provider(namespace)
        assert provider is not None
        return dict(provider.resource.attributes)

    def test_a_declared_value_is_not_replaced(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.instance.id=declared-7,service.name=declared-service")
        monkeypatch.setenv("POD_NAME", "pod-7")
        configure()
        attributes = self._attributes("")
        assert attributes["service.instance.id"] == "declared-7"
        assert attributes["service.name"] == "declared-service"

    def test_an_undeclared_key_is_still_filled(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=prod")
        monkeypatch.setenv("POD_NAME", "pod-7")
        configure()
        attributes = self._attributes("")
        assert attributes["deployment.environment"] == "prod"
        assert attributes["service.instance.id"] == "pod-7"
        assert attributes["service.name"] == "test-service"

    def test_a_standalone_agent_has_no_deployment_group(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        """No group exists for it, so no placeholder group is written."""
        monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
        monkeypatch.delenv("BLUEPRINT_GROUP", raising=False)
        configure()
        assert "deployment.group" not in self._attributes("")

    def test_an_unknown_pod_writes_no_placeholder(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        """The framework writes nothing; the SDK's own default instance id stands, as without the framework."""
        monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
        monkeypatch.delenv("POD_NAME", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)

        def _raise() -> str:
            raise OSError("no host name")

        monkeypatch.setattr("blueprint.agents.deployment.socket.gethostname", _raise)
        configure()
        assert self._attributes("").get("service.instance.id") != "<unknown-pod>"


class _RecordingMetricExporter:
    """A metric exporter that remembers what it exported, and what arrived after its shutdown."""

    def __init__(self) -> None:
        from opentelemetry.sdk.metrics.export import MetricExporter

        class _Exporter(MetricExporter):
            def __init__(inner) -> None:
                super().__init__()
                inner.exported = 0
                inner.after_shutdown = 0
                inner.shutdowns = 0

            def export(inner, metrics_data, timeout_millis: float = 10_000, **kwargs):  # type: ignore[no-untyped-def]
                from opentelemetry.sdk.metrics.export import MetricExportResult

                if inner.shutdowns:
                    inner.after_shutdown += 1
                    return MetricExportResult.FAILURE
                inner.exported += 1
                return MetricExportResult.SUCCESS

            def force_flush(inner, timeout_millis: float = 10_000) -> bool:
                return True

            def shutdown(inner, timeout_millis: float = 30_000, **kwargs) -> None:  # type: ignore[no-untyped-def]
                inner.shutdowns += 1

        self.exporter = _Exporter()


class TestTheSharedExportOutlivesOneProvider:
    """S22 -- the shared exporter and span processor were closed by the first provider that shut down."""

    @pytest.fixture
    def configure(self, telemetry_manager: TelemetryManager, mock_config: MagicMock, enabled_observability: ObservabilityConfig):
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        spans = InMemorySpanExporter()
        metrics = _RecordingMetricExporter().exporter

        def _configure(*namespaces: str):  # type: ignore[no-untyped-def]
            mock_config.get_observability_config.return_value = enabled_observability
            with (
                patch.object(telemetry_manager, "_build_exporters", return_value=[spans]),
                patch.object(telemetry_manager, "_build_metric_exporters", return_value=[metrics]),
                patch.object(telemetry_manager, "_setup_instrumentation"),
            ):
                telemetry_manager.configure_tracing(namespaces)
            return spans, metrics

        return _configure

    def test_a_span_ended_after_one_agent_shut_down_is_still_exported(self, configure) -> None:
        spans, _ = configure("orders", "billing")
        tracer_provider("orders").shutdown()

        tracer_provider("billing").get_tracer("probe").start_span("after-orders-stopped").end()
        tracer_provider("billing").force_flush()

        assert [span.name for span in spans.get_finished_spans()] == ["after-orders-stopped"]

    def test_the_metric_exporter_survives_until_the_last_provider(self, configure) -> None:
        from blueprint.agents.io.telemetry.providers import meter_provider

        _, metrics = configure("orders", "billing")
        meter_provider("orders").shutdown()
        assert metrics.shutdowns == 0

        meter_provider("billing").get_meter("probe").create_counter("probe.count").add(1)
        meter_provider("billing").force_flush()
        assert metrics.after_shutdown == 0

        meter_provider("billing").shutdown()
        meter_provider("").shutdown()
        assert metrics.shutdowns == 1

    def test_no_provider_shuts_itself_down_at_exit(self, configure) -> None:
        """The framework shuts them down in order (agents, then the root); an atexit hook each would not."""
        from blueprint.agents.io.telemetry.providers import meter_provider

        configure("orders")
        for namespace in ("", "orders"):
            assert tracer_provider(namespace)._atexit_handler is None
            assert meter_provider(namespace)._atexit_handler is None


class TestShutdownProviders:
    """S22 -- every provider is flushed and shut down by the framework, the root last."""

    @staticmethod
    def _register(*namespaces: str) -> list[str]:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.trace import TracerProvider

        from blueprint.agents.io.telemetry.providers import register_providers

        order: list[str] = []
        for namespace in namespaces:
            tracers, meters = TracerProvider(shutdown_on_exit=False), MeterProvider(shutdown_on_exit=False)
            tracers.shutdown = lambda ns=namespace: order.append(f"traces:{ns}")  # type: ignore[method-assign]
            meters.shutdown = lambda ns=namespace, **_: order.append(f"metrics:{ns}")  # type: ignore[method-assign]
            register_providers(namespace, tracers, meters)
        return order

    def test_the_root_is_shut_down_last(self) -> None:
        from blueprint.agents.io.telemetry.providers import shutdown_providers

        order = self._register("", "orders", "billing")
        shutdown_providers()
        assert order[-2:] == ["traces:", "metrics:"]
        assert sorted(order[:-2]) == ["metrics:billing", "metrics:orders", "traces:billing", "traces:orders"]

    def test_it_runs_once(self) -> None:
        from blueprint.agents.io.telemetry.providers import shutdown_providers

        order = self._register("", "orders")
        shutdown_providers()
        shutdown_providers()
        assert len(order) == 4
        assert configured_namespaces() == ()

    def test_one_failing_provider_does_not_stop_the_rest(self, caplog: pytest.LogCaptureFixture) -> None:
        from blueprint.agents.io.telemetry.providers import shutdown_providers, tracer_provider as provider_of

        order = self._register("", "orders")

        def _fail() -> None:
            raise RuntimeError("collector gone")

        provider_of("orders").shutdown = _fail  # type: ignore[method-assign]
        with caplog.at_level("WARNING"):
            shutdown_providers()
        assert order == ["metrics:orders", "traces:", "metrics:"]
        assert "collector gone" in caplog.text

    async def test_the_manager_shuts_them_down_off_the_event_loop(self, telemetry_manager: TelemetryManager) -> None:
        import threading

        threads: list[int] = []
        with patch("blueprint.agents.io.telemetry.telemetry.shutdown_providers", lambda: threads.append(threading.get_ident())):
            await telemetry_manager.on_shutdown()
        assert len(threads) == 1
        assert threads[0] != threading.get_ident()


class TestOtelServiceNameInAGroup:
    """W1, plan D17 -- OTEL_SERVICE_NAME named every agent of a group alike; the agents keep their own names."""

    @pytest.fixture
    def configure(self, telemetry_manager: TelemetryManager, mock_config: MagicMock, enabled_observability: ObservabilityConfig):
        def _configure(*namespaces: str) -> None:
            mock_config.get_observability_config.return_value = enabled_observability
            with (
                patch.object(telemetry_manager, "_build_exporters", return_value=[MagicMock()]),
                patch.object(telemetry_manager, "_build_metric_exporters", return_value=[]),
                patch.object(telemetry_manager, "_setup_instrumentation"),
            ):
                telemetry_manager.configure_tracing(namespaces)

        return _configure

    @staticmethod
    def _name(namespace: str) -> object:
        provider = tracer_provider(namespace)
        assert provider is not None
        return provider.resource.attributes["service.name"]

    def test_the_agents_keep_their_names_and_the_root_takes_it(
        self, configure, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("OTEL_SERVICE_NAME", "platform-wide")
        with caplog.at_level("WARNING"):
            configure("orders", "billing")
        assert [self._name(ns) for ns in ("", "orders", "billing")] == ["platform-wide", "orders", "billing"]
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING" and r.name.startswith("blueprint")]
        assert len(warnings) == 1
        assert "'platform-wide'" in warnings[0]

    def test_other_declared_attributes_still_reach_the_agents(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OTEL_SERVICE_NAME", "platform-wide")
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=prod")
        configure("orders")
        provider = tracer_provider("orders")
        assert provider is not None
        assert provider.resource.attributes["deployment.environment"] == "prod"

    def test_standalone_is_unchanged(self, configure, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setenv("OTEL_SERVICE_NAME", "platform-wide")
        with caplog.at_level("WARNING"):
            configure()
        assert self._name("") == "platform-wide"
        assert [r for r in caplog.records if r.levelname == "WARNING" and r.name.startswith("blueprint")] == []

    def test_a_service_name_only_in_resource_attributes_fails_a_group(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        """D17 (D23 c) -- taken as declared it would name every agent alike."""
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=platform-wide,deployment.environment=prod")
        with pytest.raises(TelemetryConfigError, match="orders, billing"):
            configure("orders", "billing")

    def test_with_otel_service_name_too_it_does_not(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        """OTEL_SERVICE_NAME names the root only, and the agents keep their names, as before."""
        monkeypatch.setenv("OTEL_SERVICE_NAME", "platform-wide")
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=platform-wide")
        configure("orders")
        assert [self._name(ns) for ns in ("", "orders")] == ["platform-wide", "orders"]

    def test_standalone_it_is_used_as_declared(self, configure, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.name=platform-wide")
        configure()
        assert self._name("") == "platform-wide"

    def test_an_agents_own_otel_service_name_reaches_its_resource(
        self, configure, mock_config: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N16 -- ``<agent>.otel_service_name`` was resolved by the view and never used."""
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
        monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)
        names = {"orders": "orders", "billing": "billing-override"}
        mock_config.for_namespace.side_effect = lambda namespace: MagicMock(
            get_observability_config=MagicMock(return_value=ObservabilityConfig(otel_service_name=names[namespace]))
        )
        configure("orders", "billing")
        assert [self._name(ns) for ns in ("", "orders", "billing")] == ["test-service", "orders", "billing-override"]
