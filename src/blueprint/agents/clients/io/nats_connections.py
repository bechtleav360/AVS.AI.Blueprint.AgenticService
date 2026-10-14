"""What a deployment tells the framework about a connection it supplies (named-connections plan).

The framework does not know what a named connection stands for. It receives, per agent and
connection, a :class:`JetStreamBinding`: which of the agent's declared subjects the connection
serves, the prefix that turns a declared subject into the subject on the wire, and the durable
consumer that carries them -- every wire value verbatim, never derived (N4).
"""

from dataclasses import dataclass, field

from nats.js import api as js_api

from .io_client_base import subject_is_covered_by


@dataclass(frozen=True)
class JetStreamBinding:
    """One agent's durable push consumer on one connection, as the deployment defines it.

    ``ack_wait`` and ``max_deliver`` are the consumer's contract values. They are carried here
    rather than read from the broker because a binding with ``manage_consumer = False`` sends no
    JetStream API request at all -- its account may not be allowed to -- so the client could not
    ask. The heartbeat interval derives from ``ack_wait``; dead-lettering on exhaustion from
    ``max_deliver``.
    """

    subjects: tuple[str, ...]
    """The agent's declared subjects this connection serves, as the agent declared them."""
    stream: str
    durable: str
    deliver_subject: str
    deliver_group: str
    ack_wait: float
    """Seconds; the consumer's own value, for the heartbeat interval (and for creating it)."""
    subject_prefix: str = ""
    """Filter subject = prefix + declared subject; stripped again before a handler sees the subject."""
    max_deliver: int | None = None
    """``None`` or ``-1``: unlimited, so exhaustion never dead-letters."""
    max_ack_pending: int | None = None
    deliver_policy: js_api.DeliverPolicy = js_api.DeliverPolicy.ALL
    manage_consumer: bool = False
    """``True``: create or update the consumer and check the stream exists. ``False``: bind only."""
    dead_letter_subject: str | None = None
    """Where a given-up-on message goes, on this connection; ``None``: term and log (plan D6)."""
    filter_subjects: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        if not self.subjects:
            raise ValueError(f"Binding of durable '{self.durable}' serves no subject.")
        if self.ack_wait <= 0:
            raise ValueError(f"Binding of durable '{self.durable}': ack_wait must be greater than 0, got {self.ack_wait}.")
        object.__setattr__(self, "filter_subjects", tuple(f"{self.subject_prefix}{subject}" for subject in self.subjects))

    def consumer_config(self) -> js_api.ConsumerConfig:
        """The consumer this binding creates when it manages its consumer."""
        return js_api.ConsumerConfig(
            name=self.durable,
            durable_name=self.durable,
            deliver_subject=self.deliver_subject,
            deliver_group=self.deliver_group,
            filter_subjects=list(self.filter_subjects),
            ack_policy=js_api.AckPolicy.EXPLICIT,
            ack_wait=self.ack_wait,
            max_deliver=self.max_deliver,
            max_ack_pending=self.max_ack_pending,
            deliver_policy=self.deliver_policy,
        )

    def local_subject(self, wire_subject: str) -> str:
        """The subject as the agent knows it: ``wire_subject`` without this binding's prefix.

        A subject that does not carry the prefix is returned unchanged; the consumer's filter
        makes that impossible for a delivery, and the topic match that follows rejects it.
        """
        if self.subject_prefix and wire_subject.startswith(self.subject_prefix):
            return wire_subject[len(self.subject_prefix) :]
        return wire_subject

    def topic_for(self, local_subject: str) -> str | None:
        """The declared subject that covers ``local_subject``, first in declaration order, or ``None``."""
        return next((subject for subject in self.subjects if subject_is_covered_by(local_subject, subject)), None)
