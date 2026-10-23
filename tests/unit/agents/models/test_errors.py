"""Unit tests for the delivery disposition mapping (spec sec. 7.2)."""

import pytest
from pydantic import ValidationError

from blueprint.agents.models.errors import (
    CriticalHandlerError,
    DeliveryDisposition,
    InvalidEventError,
    RetryableHandlerError,
    describe_validation_errors,
    disposition_for,
)
from blueprint.agents.models.events import CloudEvent

SECRET = "PLACEHOLDER-SECRET-VALUE"


def _validation_error(**payload: object) -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        CloudEvent(**payload)
    return caught.value


class TestDescribeValidationErrors:
    """Only where and what kind of error, never the value: payloads carry customer data and secrets."""

    def test_names_the_field_and_the_error_type(self) -> None:
        error = _validation_error(id={"token": SECRET}, source="s", type="t")
        assert describe_validation_errors(error.errors()) == "id: string_type"

    def test_never_contains_the_input_value(self) -> None:
        error = _validation_error(id={"token": SECRET}, source=[SECRET], type="t")
        assert SECRET in str(error)  # what pydantic itself renders, and why this exists
        assert SECRET not in describe_validation_errors(error.errors())

    def test_nested_locations_are_dotted(self) -> None:
        assert describe_validation_errors([{"loc": ("body", "data", 0), "type": "missing"}]) == "body.data.0: missing"

    def test_a_long_list_is_cut_with_a_count(self) -> None:
        errors = [{"loc": (f"f{index}",), "type": "missing"} for index in range(13)]
        described = describe_validation_errors(errors)
        assert described.endswith("(+3 more)")
        assert "f9: missing" in described
        assert "f10" not in described


class TestDispositionFor:
    def test_retryable_error_naks(self) -> None:
        assert disposition_for(RetryableHandlerError(status="e", reason="r")) is DeliveryDisposition.NAK

    def test_invalid_event_error_terms(self) -> None:
        assert disposition_for(InvalidEventError(status="e", reason="r")) is DeliveryDisposition.TERM

    def test_critical_error_terms(self) -> None:
        assert disposition_for(CriticalHandlerError(status="e", reason="r")) is DeliveryDisposition.TERM

    def test_unrecognised_exception_naks(self) -> None:
        assert disposition_for(RuntimeError("boom")) is DeliveryDisposition.NAK

    def test_subclass_inherits_its_parents_disposition(self) -> None:
        class ProjectSpecificError(InvalidEventError):
            pass

        assert disposition_for(ProjectSpecificError(status="e", reason="r")) is DeliveryDisposition.TERM

    def test_never_returns_ack(self) -> None:
        """Acknowledgement is what a normal return means; this function only sees failures."""
        failures = [
            RetryableHandlerError(status="e", reason="r"),
            InvalidEventError(status="e", reason="r"),
            CriticalHandlerError(status="e", reason="r"),
            RuntimeError("boom"),
            ValueError("nope"),
        ]
        assert all(disposition_for(exc) is not DeliveryDisposition.ACK for exc in failures)
