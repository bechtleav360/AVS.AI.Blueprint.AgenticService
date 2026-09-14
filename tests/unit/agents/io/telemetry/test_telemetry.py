"""Unit tests for TelemetryManager and TracingContext."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.io.telemetry.providers import agent_meter, agent_tracer, configured_namespaces, reset_providers, tracer_provider
from blueprint.agents.io.telemetry.telemetry import TelemetryManager, TracingContext
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
