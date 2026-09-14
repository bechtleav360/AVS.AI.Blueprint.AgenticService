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
