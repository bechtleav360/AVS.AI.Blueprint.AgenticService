"""Unit tests for the delivery disposition mapping (spec sec. 7.2)."""

from blueprint.agents.models.errors import (
    CriticalHandlerError,
    DeliveryDisposition,
    InvalidEventError,
    RetryableHandlerError,
    disposition_for,
)


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
