"""Unit tests for MetricsRecorder."""

import types
from unittest.mock import MagicMock

import pytest

from blueprint.agents.agent.metrics import MetricsRecorder
from blueprint.agents.config import Config


def _usage(
    input_tokens: int = 10,
    output_tokens: int = 20,
    total_tokens: int = 30,
    requests: int = 1,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        requests=requests,
    )


def _result(usage: types.SimpleNamespace | None = None) -> types.SimpleNamespace:
    captured = usage
    return types.SimpleNamespace(usage=lambda: captured)


@pytest.fixture
def otel_off_config() -> MagicMock:
    config = MagicMock(spec=Config)
    config.get_observability_config.return_value = MagicMock(otel_enabled=False, token_metrics_enabled=False)
    return config


@pytest.fixture
def otel_on_config() -> MagicMock:
    config = MagicMock(spec=Config)
    config.get_observability_config.return_value = MagicMock(otel_enabled=True, token_metrics_enabled=True)
    return config


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------


class TestRecord:
    def test_logs_usage_when_present(self, otel_off_config: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        recorder = MetricsRecorder(otel_off_config)

        with caplog.at_level("INFO"):
            recorder.record(_result(_usage()), 123.4, "gpt-4o")

        assert "gpt-4o" in caplog.text

    def test_logs_warning_when_no_usage(self, otel_off_config: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        recorder = MetricsRecorder(otel_off_config)

        with caplog.at_level("WARNING"):
            recorder.record(_result(None), 50.0, "gpt-4o")

        assert "No usage information" in caplog.text

    def test_no_otel_when_disabled(self, otel_off_config: MagicMock) -> None:
        meter = MagicMock()
        recorder = MetricsRecorder(otel_off_config, meter=meter)

        recorder.record(_result(_usage()), 100.0, "gpt-4o")

        meter.create_counter.assert_not_called()
        meter.create_histogram.assert_not_called()

    def test_otel_recorded_when_enabled_and_meter_provided(self, otel_on_config: MagicMock) -> None:
        meter = MagicMock()
        recorder = MetricsRecorder(otel_on_config, meter=meter)

        recorder.record(_result(_usage()), 100.0, "gpt-4o")

        meter.create_counter.assert_called()
        meter.create_histogram.assert_called()

    def test_no_otel_when_meter_is_none(self, otel_on_config: MagicMock) -> None:
        recorder = MetricsRecorder(otel_on_config, meter=None)
        recorder.record(_result(_usage()), 100.0, "gpt-4o")  # must not raise

    def test_config_exception_suppressed(self) -> None:
        config = MagicMock(spec=Config)
        config.get_observability_config.side_effect = RuntimeError("config unavailable")
        recorder = MetricsRecorder(config)
        recorder.record(_result(_usage()), 100.0, "gpt-4o")  # must not raise
