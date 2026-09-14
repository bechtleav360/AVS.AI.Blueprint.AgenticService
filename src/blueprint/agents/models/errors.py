"""Handler exceptions, and the delivery disposition each one implies."""

from enum import Enum


class HandlerError(Exception):
    """Domain-specific exception raised by handlers."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.code = code or "handler_error"


class RetryableHandlerError(HandlerError):
    """Domain-specific exception raised by handlers that should trigger a retry."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(status=status, reason=reason, code=code)


class CriticalHandlerError(HandlerError):
    """Domain-specific exception raised by handlers that force a restart."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(status=status, reason=reason, code=code)


class InvalidEventError(HandlerError):
    """Domain-specific exception raised by handlers that force a drop of the event."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(status=status, reason=reason, code=code)


class DeliveryDisposition(Enum):
    """What a transport does with a delivery once dispatch has finished.

    Spec sec. 7.2 fixes one outcome table for every transport, so the mapping lives
    beside the exceptions it classifies rather than inside any one transport: NATS
    renders these as ``ack``/``nak``/``term`` and Dapr as ``SUCCESS``/``RETRY``/``DROP``,
    but they must never disagree about which one an outcome deserves.
    """

    ACK = "ack"
    NAK = "nak"
    TERM = "term"


_DISPOSITION_BY_ERROR: tuple[tuple[type[BaseException], DeliveryDisposition], ...] = (
    (RetryableHandlerError, DeliveryDisposition.NAK),
    (InvalidEventError, DeliveryDisposition.TERM),
    (CriticalHandlerError, DeliveryDisposition.TERM),
)


def disposition_for(exc: BaseException) -> DeliveryDisposition:
    """Return the delivery disposition a failed dispatch earns (spec sec. 7.2).

    Never returns ``ACK``: acknowledgement is what a *normal return* means, and the
    transport edge decides that without consulting this function. An unrecognised
    exception is treated as retryable, on the grounds that an unexpected failure is
    more often transient than permanent -- which is why ``max_deliver`` and a
    dead-letter destination are required alongside it.

    Matching is by ``isinstance``, so a project's own subclass of one of these errors
    inherits its disposition.
    """
    for error_type, disposition in _DISPOSITION_BY_ERROR:
        if isinstance(exc, error_type):
            return disposition
    return DeliveryDisposition.NAK
