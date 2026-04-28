"""Unit tests for TelemetryManager and TracingContext."""

from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.io.telemetry.telemetry import TelemetryManager, TracingContext
from blueprint.agents.models.config import ObservabilityConfig


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

        Component.shared_config = None
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
            patch.object(telemetry_manager, "_setup_instrumentation"),
        ):
            mock_provider = MagicMock()
            mock_provider_cls.return_value = mock_provider
            telemetry_manager.configure_tracing()
        mock_provider_cls.assert_called_once()


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
