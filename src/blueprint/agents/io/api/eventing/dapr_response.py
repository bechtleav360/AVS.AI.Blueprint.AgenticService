"""Rendering of a delivery disposition into Dapr's response vocabulary.

Dapr acknowledges by response body rather than by a call on the message, so the dict a
route returns *is* the acknowledgement. Spec sec. 7.2 fixes one outcome table for every
transport: what an outcome deserves is decided once, by
:func:`blueprint.agents.models.errors.disposition_for`, and each transport only renders
that decision in its own words. Keeping the words here rather than in ``models`` stops
Dapr's vocabulary from leaking into the shared layer, and keeping them out of ``dapr.py``
lets ``EventHandlingBase.handle_event`` render identically without importing a subclass.
"""

from ....models.errors import DeliveryDisposition

_STATUS_BY_DISPOSITION: dict[DeliveryDisposition, str] = {
    DeliveryDisposition.ACK: "SUCCESS",
    DeliveryDisposition.NAK: "RETRY",
    DeliveryDisposition.TERM: "DROP",
}


def dapr_status(disposition: DeliveryDisposition) -> str:
    """Return the Dapr status word for a delivery disposition."""

    return _STATUS_BY_DISPOSITION[disposition]
