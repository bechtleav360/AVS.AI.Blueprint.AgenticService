"""Handler exceptions, and the delivery disposition each one implies."""

from collections.abc import Iterable
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


def combined_disposition(dispositions: Iterable[DeliveryDisposition]) -> DeliveryDisposition:
    """Return the one disposition that answers for several dispatches of one delivery.

    Needed where a single delivery is fanned out to several agents and the transport reads
    exactly one answer -- which is the Dapr path in a grouped process: the sidecar delivers a
    topic once and reads one status from the response.

    The order is ``NAK`` > ``ACK`` > ``TERM``, and each step is a decision:

    - **Any ``NAK`` wins.** One agent asked for the delivery again, and the only way to give it
      one is to ask for a redelivery of the whole message. The cost is that the agents which
      already succeeded see it again, so a grouped Dapr deployment wants
      ``idempotency_enabled`` -- there is no per-agent acknowledgement to be had on this path,
      because there is no per-agent delivery.
    - **Otherwise any ``ACK`` wins over ``TERM``.** A ``TERM`` from one agent means *that* agent
      found the message undeliverable, which is a finished outcome rather than a failure of the
      delivery; if another agent handled it, the message was handled. Answering ``TERM`` there
      would report a successful delivery as dropped.
    - **All ``TERM`` is ``TERM``.** Every agent judged it undeliverable, and no redelivery
      changes that.

    An empty argument is ``ACK``: nothing was dispatched, so nothing failed, and the delivery is
    complete. That is the same answer the single-agent path gives for an event no handler wanted.

    Args:
        dispositions: What each dispatch of this delivery earned.

    Returns:
        The disposition to report to the transport.
    """
    outcomes = set(dispositions)
    if DeliveryDisposition.NAK in outcomes:
        return DeliveryDisposition.NAK
    if DeliveryDisposition.ACK in outcomes or not outcomes:
        return DeliveryDisposition.ACK
    return DeliveryDisposition.TERM
