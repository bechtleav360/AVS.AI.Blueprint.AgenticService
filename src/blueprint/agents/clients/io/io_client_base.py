"""Base class for IO transport clients (Dapr, NATS, etc.)."""

import re
from abc import ABC

from ...component.namespace import ROOT_NAMESPACE
from ..client_base import ClientBase


class IOClientBase(ClientBase, ABC):
    """Abstract base for IO transport clients.

    Extends ClientBase for message-bus and eventing transports (Dapr, NATS, etc.).
    Used by EventPublishingService and eventing endpoints to find the active
    transport client via the registry without matching AI clients.

    Namespace ownership
    ~~~~~~~~~~~~~~~~~~~
    A transport client belongs to one namespace, not to the process (spec sec. 6). The
    default is the root namespace ``""``, which is the whole of a single-agent
    application and registers under the bare class-derived name -- so nothing changes
    for an application that never names a namespace.

    A namespaced client registers as ``f"{namespace}_{base_name}"``, which is what
    allows two of them to exist in one registry at all: ``Registry.add_component``
    rejects a duplicate name, so before this every second instance of a transport
    client raised at construction.

    The namespace is the *agent's* identity, so it may derive broker-side consumer
    identity (queue group, durable) -- see C1. Nothing about the process, the
    deployment group or the pod may.

    Both the namespace's validation and the qualified registry name are ``Component``'s: it
    is the one gate every component passes through, so an illegal namespace cannot reach a
    registry key, a queue group, a durable name or a telemetry resource from any base class.
    See :func:`~blueprint.agents.component.namespace.validate_namespace` for the alphabet and
    why each exclusion is in it.
    """

    def __init__(self, namespace: str = ROOT_NAMESPACE) -> None:
        """Initialize the transport client for one namespace.

        Args:
            namespace: The agent this client belongs to; ``""`` for the root namespace.

        Raises:
            ValueError: if the namespace is not a legal namespace.
        """
        super().__init__(namespace=namespace)
        self._consumption_paused = False

    # ------------------------------------------------------------------
    # C4 -- a degraded agent stops consuming
    # ------------------------------------------------------------------

    @property
    def consumption_paused(self) -> bool:
        """Whether this agent has been taken off its topics because it is degraded.

        Readiness gates HTTP only: a pod removed from service rotation still holds its
        subscriptions and still consumes, so for an event-driven agent the probe alone is
        cosmetic (C4). This flag is what the transports and the Dapr fan-out read to stop
        taking work while the agent cannot do it.
        """
        return self._consumption_paused

    async def pause_consumption(self) -> None:
        """Stop taking events for this agent, leaving the connection open.

        **Paused, not closed.** Spec sec. 3's C4 describes this as closing the namespace's
        client, and closing it would satisfy the letter of it -- but a closed client reports
        itself unhealthy for ever, so the agent that triggered the pause could never be seen to
        recover and the pause would be a one-way latch on a transient fault. Keeping the
        connection also keeps publishing available, which matters because an agent that has
        stopped consuming may still need to report that it has.

        Overridden by a transport that can actually stop deliveries. The base implementation
        records the state, which is what a push transport reads at its delivery edge.
        """
        self._consumption_paused = True

    async def resume_consumption(self) -> None:
        """Start taking events again after the agent's health checks pass once more."""
        self._consumption_paused = False


TOPIC_TRANSPORTS = ("dapr", "nats")
"""Values of ``event_bus`` that produce an :class:`IOClientBase`, and therefore carry topics.

``"sessions"`` is not one of them: it wires ``SessionsApiClient`` (a service) and
``SessionsBus``, which consumes SSE job notifications and never reads
``get_subscribed_topics()``. Anything that needs to publish to a topic or subscribe to one --
``EventPublishingService``, the eventing endpoints, an event-mode scheduler -- needs one of
these two.
"""


_SUBJECT_UNUSABLE = re.compile(r"[*>\s]")
"""What a subject a component publishes to or subscribes to cannot contain."""


def subject_is_covered_by(subject: str, pattern: str) -> bool:
    """Whether ``pattern`` -- a NATS subject, possibly with wildcards -- already matches ``subject``.

    NATS has two wildcards: ``*`` stands for exactly one token, and ``>`` for one or more and only
    as the last token. A stream configured with ``orders.>`` therefore already captures
    ``orders.created``, even though the two strings are not equal.

    This exists because comparing them as strings says otherwise. A stream provisioned by an
    operator with a wildcard looks, to a set difference, as though it is missing every literal
    subject the client wants -- so the client asks the server to add them, and the server refuses
    the update with *subject "orders.>" overlaps with "orders.created"*. What the client then logs
    is that consumers filtering those subjects will fail to bind, which is false: the wildcard
    covers them and they bind perfectly well. The message is the defect, not the stream.

    Args:
        subject: A concrete subject, with no wildcards of its own.
        pattern: A stream subject, which may have them.

    Returns:
        Whether a message on ``subject`` would be captured by ``pattern``.
    """
    if pattern == subject:
        return True

    pattern_tokens = pattern.split(".")
    subject_tokens = subject.split(".")

    for index, token in enumerate(pattern_tokens):
        if token == ">":
            # Matches the rest, and there has to be a rest: 'a.>' does not match 'a'.
            return index < len(subject_tokens)
        if index >= len(subject_tokens):
            return False
        if token != "*" and token != subject_tokens[index]:
            return False

    return len(pattern_tokens) == len(subject_tokens)


def validate_publish_subject(subject: str, *, source: str) -> str:
    """Return ``subject`` unchanged, or raise if it cannot be published to.

    The sibling of :func:`validate_subject_segment`, for a whole subject rather than one of its
    segments -- so dots are legal here and only whitespace, ``*`` and ``>`` are not.

    **A wildcard is the one worth naming.** ``orders.*`` is a perfectly good thing to *subscribe*
    to and a meaningless thing to publish to: NATS treats it as a literal subject, so the message
    goes to a subject spelled with an asterisk and every subscriber to the pattern misses it.
    Nothing fails, and nothing arrives. Refusing it at startup is the only place that is cheap.

    Args:
        subject: The subject something would publish to.
        source: Where it came from, named in the error so the fix is obvious.

    Raises:
        ValueError: if the subject is empty or contains whitespace, ``*`` or ``>``.
    """
    if not subject:
        raise ValueError(f"{source} is empty, so there is nothing to publish to.")
    if _SUBJECT_UNUSABLE.search(subject):
        raise ValueError(
            f"{source} is '{subject}', which cannot be published to: whitespace, '*' and '>' are not usable in a "
            "subject a message is sent to. A wildcard is only meaningful when subscribing -- published, it is "
            "taken literally, so the message lands on a subject with an asterisk in it and no subscriber to the "
            "pattern receives it."
        )
    return subject


def validate_subject_segment(segment: str, *, source: str, subject: str) -> str:
    """Return ``segment`` unchanged, or raise if it cannot appear in a subject.

    Every name in this framework that ends up as part of a NATS subject or a queue group
    goes through here rather than being repaired, because those names are the contract with
    everything outside the process: a `CronJob` publishes to a scheduler's tick subject, and
    an operator reads a queue group in `/connz`. A name that is silently rewritten -- an
    ``app_name`` of ``"My Service"`` becoming ``My_Service`` in a subject -- leaves the
    outside party publishing to a subject nobody subscribes to, with nothing to read that
    says why. That is the one failure mode this cannot be allowed to produce, so the rule is
    to fail the startup of the side that *knows* the name is wrong.

    Sanitising is only ever acceptable for a value nothing outside the process depends on:
    the NATS connection name, which exists for attribution and which C1 forbids anything
    deriving from.

    Args:
        segment: The name to check -- a namespace, an ``app_name``, a scheduler name.
        source: Where it came from, named in the error so the fix is obvious.
        subject: The subject it would have become, for the same reason.

    Raises:
        ValueError: if the segment is empty or contains whitespace, ``*`` or ``>``.
    """
    if not segment:
        raise ValueError(f"{source} is empty, so the subject '{subject}' cannot be derived from it.")
    if _SUBJECT_UNUSABLE.search(segment):
        raise ValueError(
            f"{source} is '{segment}', which cannot appear in a NATS subject: whitespace, '*' and '>' are not "
            f"usable in one. It would have produced the subject '{subject}', which nothing outside this process "
            "could publish to or subscribe to correctly. Rename it rather than relying on it being rewritten."
        )
    return segment
