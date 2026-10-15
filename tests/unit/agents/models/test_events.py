"""Unit tests for CloudEvent validators."""

import pytest
from pydantic import ValidationError

from blueprint.agents.models.events import CloudEvent

# ---------------------------------------------------------------------------
# validate_time_format
# ---------------------------------------------------------------------------


class TestValidateTimeFormat:
    def test_iso8601_with_z_suffix_is_valid(self) -> None:
        event = CloudEvent(id="1", type="t", time="2024-01-15T10:30:00Z")
        assert event.time == "2024-01-15T10:30:00Z"

    def test_iso8601_with_offset_is_valid(self) -> None:
        event = CloudEvent(id="1", type="t", time="2024-01-15T10:30:00+00:00")
        assert event.time == "2024-01-15T10:30:00+00:00"

    def test_iso8601_without_timezone_raises(self) -> None:
        with pytest.raises(ValidationError, match="timezone"):
            CloudEvent(id="1", type="t", time="2024-01-15T10:30:00")

    def test_non_string_time_raises(self) -> None:
        with pytest.raises(ValidationError):
            CloudEvent(id="1", type="t", time=None)  # type: ignore[arg-type]

    def test_default_time_is_valid(self) -> None:
        """Default factory must produce a validator-passing timestamp."""
        event = CloudEvent(id="1", type="t")
        assert event.time is not None
        assert "Z" in event.time or "+" in event.time


# ---------------------------------------------------------------------------
# validate_data_exclusivity
# ---------------------------------------------------------------------------


class TestValidateDataExclusivity:
    def test_only_data_is_valid(self) -> None:
        event = CloudEvent(id="1", type="t", data={"key": "val"})
        assert event.data == {"key": "val"}

    def test_only_data_base64_is_valid(self) -> None:
        event = CloudEvent(id="1", type="t", data_base64="aGVsbG8=")
        assert event.data_base64 == "aGVsbG8="

    def test_neither_data_nor_data_base64_is_valid(self) -> None:
        event = CloudEvent(id="1", type="t")
        assert event.data is None

    def test_both_data_and_data_base64_raises(self) -> None:
        with pytest.raises(ValidationError):
            CloudEvent(id="1", type="t", data={"x": 1}, data_base64="aGVsbG8=")


# ---------------------------------------------------------------------------
# HandlerResult.skipped
# ---------------------------------------------------------------------------


class TestHandlerResultSkipped:
    """``HandlerResult.skipped``: the responsible handler's "this event needs nothing"."""

    def test_skipped_carries_its_reason_and_reports_itself(self) -> None:
        from blueprint.agents.models.events import HandlerResult

        result = HandlerResult.skipped("status unchanged", metadata={"field": "status"})
        assert result.is_skipped
        assert result.skip_reason == "status unchanged"
        assert result.metadata == {"field": "status"}
        assert result.event_type is None and result.data is None

    def test_an_ordinary_result_is_not_skipped(self) -> None:
        from blueprint.agents.models.events import HandlerResult

        assert not HandlerResult(event_type="x").is_skipped

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_an_empty_reason_is_refused(self, reason: str) -> None:
        """A skip without a reason leaves the INFO line saying nothing about why the event was dropped."""
        from blueprint.agents.models.events import HandlerResult

        with pytest.raises(ValidationError, match="must name why"):
            HandlerResult.skipped(reason)

    @pytest.mark.parametrize("extra", [{"event_type": "x"}, {"subject": "s"}, {"data": {"a": 1}}])
    def test_a_skip_that_would_also_publish_or_return_data_is_refused(self, extra: dict) -> None:
        """Both published and skipped would leave nobody able to tell which one the author meant."""
        from blueprint.agents.models.events import HandlerResult

        with pytest.raises(ValidationError, match="carries only its reason"):
            HandlerResult(skip_reason="r", **extra)
