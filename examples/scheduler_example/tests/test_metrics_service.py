"""Unit tests for MetricsService."""


from src.services import MetricsService


class TestMetricsService:
    """Tests for MetricsService."""

    def setup_method(self) -> None:
        self.service = MetricsService()

    def test_record_creates_snapshot(self) -> None:
        snapshot = self.service.record("cpu_percent", 42.5)
        assert snapshot.label == "cpu_percent"
        assert snapshot.value == 42.5
        assert snapshot.timestamp is not None

    def test_list_labels_empty_initially(self) -> None:
        assert self.service.list_labels() == []

    def test_list_labels_after_recording(self) -> None:
        self.service.record("cpu_percent", 10.0)
        self.service.record("memory_percent", 50.0)
        labels = self.service.list_labels()
        assert "cpu_percent" in labels
        assert "memory_percent" in labels

    def test_get_summary_none_when_no_data(self) -> None:
        assert self.service.get_summary("nonexistent") is None

    def test_get_summary_correct_aggregation(self) -> None:
        self.service.record("cpu_percent", 10.0)
        self.service.record("cpu_percent", 20.0)
        self.service.record("cpu_percent", 30.0)

        summary = self.service.get_summary("cpu_percent")
        assert summary is not None
        assert summary.count == 3
        assert summary.average == 20.0
        assert summary.minimum == 10.0
        assert summary.maximum == 30.0

    def test_get_recent_returns_limited_results(self) -> None:
        for i in range(20):
            self.service.record("req_rate", float(i))

        recent = self.service.get_recent("req_rate", limit=5)
        assert len(recent) == 5
        assert recent[-1].value == 19.0

    def test_get_recent_empty_for_unknown_label(self) -> None:
        assert self.service.get_recent("unknown") == []
