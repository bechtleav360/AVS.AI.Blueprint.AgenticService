"""Unit tests for parse_bool."""

import pytest

from blueprint.agents.utils import parse_bool


class TestParseBool:
    @pytest.mark.parametrize("value", [True, False])
    def test_a_real_bool_passes_through(self, value: bool) -> None:
        assert parse_bool(value, "some_key") is value

    @pytest.mark.parametrize("value", ["true", "TRUE", " True ", "1", "yes"])
    def test_truthy_strings(self, value: str) -> None:
        """An environment override arrives as text, so "true" must mean True."""
        assert parse_bool(value, "some_key") is True

    @pytest.mark.parametrize("value", ["false", "FALSE", " False ", "0", "no"])
    def test_falsy_strings(self, value: str) -> None:
        assert parse_bool(value, "some_key") is False

    @pytest.mark.parametrize("value", ["maybe", "", "  ", None, 2, 1.5, [], {}])
    def test_anything_else_raises(self, value: object) -> None:
        """A typo must not be read as false and silently disable a feature."""
        with pytest.raises(ValueError, match="must be a boolean"):
            parse_bool(value, "some_key")

    def test_the_error_names_the_key(self) -> None:
        with pytest.raises(ValueError, match="idempotency_enabled"):
            parse_bool("nope", "idempotency_enabled")
