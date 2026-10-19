"""Where this process runs: the deployment group, and which replica this is.

Two values, read straight from the environment, that describe the *deployment* rather than the
application. They are not configuration and are deliberately unreachable through ``Config``
(C6): an agent that can read its group can be written to depend on it, and regrouping then
breaks it. See ``DEPLOYMENT_IDENTITY_KEYS`` in ``config/config.py`` for the other half of that
rule -- this module is where framework code reads them instead, and no agent can follow.

They live here rather than in the one client that first needed them because two subsystems now
read the same two values and must agree on them: the NATS connection name (spec sec. 6) and the
telemetry resource (C2). Two copies would be two answers to "which pod is this" the day one of
them learned about a new environment variable.

Both are passed through :func:`~blueprint.agents.component.namespace.display_segment`, because
these values are owned by the deployment and cannot be validated the way a namespace is:
rejecting a group name would fail a rollout over a display string. Sanitising is only safe
because nothing derives from them -- C1 forbids the queue group and the durable from reading
either -- so a mangled segment loses no information a consumer depends on.
"""

import os
import socket

from .component.namespace import display_segment

UNGROUPED_LABEL = "<ungrouped>"
"""Stands in for an unset ``BLUEPRINT_GROUP``, so every position that names a group stays filled.

Bracketed for the same reason as ``ROOT_LABEL``: ``display_segment`` strips brackets from every
environment-supplied segment, so no real group can produce this string and "not deployed as part
of a group" cannot be confused with a group that happens to be called ``ungrouped``.
"""

UNKNOWN_POD_LABEL = "<unknown-pod>"
"""Stands in when neither the environment nor the host can say which pod this is."""


_resolved_group: str | None = None
"""The group ``AgentGroup.resolve`` resolved for this process; ``None`` until one did (S19)."""


def publish_deployment_group(name: str | None) -> None:
    """Record the group this process resolved, so :func:`deployment_group` reports it (S19).

    Called by ``AgentGroup.resolve``. A group can be named by the group file alone -- a file that
    declares one group needs no ``BLUEPRINT_GROUP`` -- and that name reached neither the NATS
    connection name nor the telemetry resource, which read only the environment. ``None``
    forgets it again, for tests.
    """
    global _resolved_group
    _resolved_group = name


def deployment_group() -> str:
    """Return the deployment group this process runs as, or :data:`UNGROUPED_LABEL`.

    The group ``AgentGroup.resolve`` published, else ``BLUEPRINT_GROUP`` -- read straight from
    the environment rather than through ``Config``: group composition decides which agents get a
    configuration view at all, so it cannot itself come from one.

    The group is deployment identity, so it belongs in the connection name and on the telemetry
    resource, and nowhere near the queue group or the durable (C1).
    """
    raw = _resolved_group if _resolved_group is not None else os.environ.get("BLUEPRINT_GROUP", "")
    return display_segment(raw, UNGROUPED_LABEL)


def pod_identity() -> str:
    """Return the replica this process runs in, for attribution only.

    ``POD_NAME`` is the Kubernetes downward-API convention and is preferred because a deployment
    can set it explicitly; ``HOSTNAME`` is what the kubelet sets anyway and is the pod name in
    practice; the host name covers plain Docker and local runs.

    Sanitised on the same terms as the group: a host name is frequently an FQDN, and its dots
    would otherwise split one segment into several.
    """
    for variable in ("POD_NAME", "HOSTNAME"):
        value = os.environ.get(variable, "").strip()
        if value:
            return display_segment(value, UNKNOWN_POD_LABEL)
    try:
        return display_segment(socket.gethostname(), UNKNOWN_POD_LABEL)
    except OSError:
        return UNKNOWN_POD_LABEL
