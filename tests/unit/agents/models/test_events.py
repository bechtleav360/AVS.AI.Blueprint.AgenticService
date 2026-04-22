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
