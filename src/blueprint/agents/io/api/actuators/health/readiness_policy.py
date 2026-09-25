"""Which degraded agents take the pod out of service rotation (C3).

Grouping changes what a readiness probe means. In a single-agent process the question "is this
pod ready" has one answer, because there is one agent; in a group of twenty, one agent's Redis
being unreachable would, under the old rule, remove nineteen healthy agents from rotation. That
is the blast radius grouping is supposed to remove, and the probe is where it comes back.

So readiness is a policy, chosen by the deployment that knows what it is running:

========== =====================================================================================
``all``    **Default.** Any degraded namespace makes the pod not ready. Reproduces exactly what
           a single-agent application has always done.
``critical`` Only namespaces the group flagged ``critical`` gate readiness. The same flag that
           decides whether a failing import stops the process (spec sec. 9.1) -- an agent the
           deployment said it would rather run without does not get to remove the others.
``any``    Ready while at least one agent is up. For a group whose members are independent and
           whose traffic is routed per agent anyway.
========== =====================================================================================

**The root always gates, under every policy.** It is where a single-agent application's whole
world lives -- so that case must keep behaving as it does today, whatever the policy says -- and
in a grouped process it holds the shared infrastructure every agent depends on. A root that is
degraded is not a partial failure.

**The probe decides where traffic goes; it does not decide who is woken.** A degraded namespace
is reported as ``blueprint.namespace.up = 0`` and an ERROR event whatever the policy (C3, C7), so
choosing ``critical`` or ``any`` suppresses a *routing* consequence and never a signal.
"""

from collections.abc import Collection, Mapping
from enum import StrEnum

from .....component.namespace import ROOT_NAMESPACE

CONFIG_KEY = "readiness_policy"
"""The configuration key this is read from. Process-scope: one pod has one readiness probe."""


class ReadinessPolicy(StrEnum):
    """How a degraded namespace affects the pod's readiness probe."""

    ALL = "all"
    CRITICAL = "critical"
    ANY = "any"

    @classmethod
    def parse(cls, value: object) -> "ReadinessPolicy":
        """Return the policy named by ``value``, or raise naming the three that exist.

        Raises rather than falling back to the default, because the two failures look identical
        from outside the process and only one of them is safe: a misspelt ``critcal`` silently
        read as ``all`` would remove a whole group from rotation the first time a non-critical
        agent wobbled, and the operator who set the key would have no way to see that it had not
        taken effect.

        Args:
            value: The configured value, as it comes out of the settings tree.

        Returns:
            The policy.

        Raises:
            ValueError: if ``value`` is not one of the three policies.
        """
        text = str(value or "").strip().lower()
        try:
            return cls(text)
        except ValueError:
            raise ValueError(
                f"'{CONFIG_KEY}' is {value!r}, which is not a readiness policy. It must be one of "
                f"{', '.join(repr(policy.value) for policy in cls)}."
            ) from None

    def is_ready(self, namespace_status: Mapping[str, bool], critical_namespaces: Collection[str]) -> bool:
        """Return whether the pod is ready, given each namespace's health.

        Args:
            namespace_status: ``True`` where every one of that namespace's health checks passed.
                The root (``""``) is expected to be present; a namespace with no checks at all
                counts as up, because nothing about it can be failing.
            critical_namespaces: The agents the group flagged critical. Read only by
                :attr:`CRITICAL`.

        Returns:
            Whether the readiness probe should answer ``UP``.
        """
        if not namespace_status.get(ROOT_NAMESPACE, True):
            return False

        agents = {namespace: healthy for namespace, healthy in namespace_status.items() if namespace != ROOT_NAMESPACE}
        if not agents:
            # A single-agent application: the root is the whole of it, and it is up. Every
            # policy agrees here, which is what makes the key safe to set in a shared settings
            # file that standalone projects also read.
            return True

        if self is ReadinessPolicy.ALL:
            return all(agents.values())
        if self is ReadinessPolicy.CRITICAL:
            return all(healthy for namespace, healthy in agents.items() if namespace in critical_namespaces)
        return any(agents.values())
