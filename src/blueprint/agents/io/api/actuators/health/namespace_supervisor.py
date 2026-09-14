"""Whether each agent is serving, said out loud, and what happens when one is not (C3, C4, C7).

Grouping removes the signal that used to be free. In a process per agent, an agent that stopped
working took its pod down with it, and the restart *was* the alert: somebody was paged, a
dashboard went red, and the blast radius told you whose it was. Twenty agents in one process have
none of that -- the pod stays up, the port stays bound, nineteen agents keep answering, and the
twentieth silently stops. So C7 makes attribution normative, and this class is where it is
produced.

Three things follow from one state, and they are deliberately not three mechanisms:

- **A signal.** ``blueprint.namespace.up`` is 0 for a degraded agent and an ERROR event is
  emitted on the transition, carrying that agent's telemetry identity -- its name, its group and
  its pod. This happens whatever the readiness policy says: the policy decides where traffic
  goes, never who is woken.
- **A consequence.** A degraded agent stops consuming (C4), because readiness gates HTTP only.
  A pod removed from service rotation still holds its subscriptions, so for an event-driven
  agent the probe alone changes nothing at all -- events keep arriving at an agent that cannot
  process them, and every one of them is lost or retried against the same broken replica.
- **A verdict.** :class:`~.readiness_policy.ReadinessPolicy` reads the same per-agent state to
  decide the pod's readiness.

**Down is latched only when something latched it.** A health-driven transition is reversible:
the checks pass again, the agent resumes, and the pause was a pause. :meth:`mark_down` is the
other kind -- a startup failure (spec sec. 9.1) that no health check knows about -- and it stays
until :meth:`clear_forced_down` releases it, because nothing that observes health could ever
discover that it was wrong.
"""

import logging
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

from opentelemetry.metrics import CallbackOptions, Observation

from .....clients.io.io_client_base import IOClientBase
from .....component.namespace import ROOT_LABEL, ROOT_NAMESPACE
from .....component.registry import Registry
from .....deployment import deployment_group, pod_identity
from .....io.telemetry.providers import agent_meter

logger = logging.getLogger(__name__)

NAMESPACE_UP_GAUGE = "blueprint.namespace.up"
"""``1`` while an agent is serving, ``0`` once it is not. The C7 signal.

Recorded on the agent's own meter provider, so it arrives with that agent's ``service.name``
resource (C2) as well as the ``agent`` attribute -- a dashboard can group on either, and one of
them survives a collector that drops resource attributes.
"""


class NamespaceSupervisor:
    """Tracks which agents are serving, reports it, and stops a degraded one consuming."""

    def __init__(self, registry: Registry, namespaces: Sequence[str], *, critical: Collection[str] = ()) -> None:
        """Start supervising the agents this process hosts.

        Args:
            registry: The application's registry, used to reach an agent's transport clients
                when it has to stop consuming. The application's own rather than a view: this
                object acts on behalf of every agent, which is exactly the process-wide reach
                C6 keeps away from agent code and grants to the framework.
            namespaces: Every namespace this process serves, the root included. Supervised from
                the start rather than discovered from the first health poll, so an agent with no
                health checks of its own still reports ``blueprint.namespace.up = 1`` and is
                visibly present rather than absent.
            critical: The agents the group flagged critical, for the ``critical`` policy.
        """
        self._registry = registry
        self._critical = frozenset(critical)
        self._up: dict[str, bool] = dict.fromkeys(namespaces, True)
        self._forced_down: dict[str, str] = {}
        self._group = deployment_group()
        self._pod = pod_identity()
        self._register_gauges()

    @property
    def critical_namespaces(self) -> frozenset[str]:
        """The agents that gate readiness under the ``critical`` policy."""
        return self._critical

    @property
    def status(self) -> Mapping[str, bool]:
        """Whether each supervised namespace is currently serving."""
        return dict(self._up)

    def is_up(self, namespace: str) -> bool:
        """Whether ``namespace`` is currently serving. An unsupervised namespace counts as up."""
        return self._up.get(namespace, True)

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def _register_gauges(self) -> None:
        """Create one observable gauge per namespace, on that namespace's own meter.

        One instrument per agent rather than one instrument with an ``agent`` attribute,
        because the resource is what carries C2's identity and the resource belongs to the
        provider: an instrument created on the root's meter would report every agent's value
        under the group's ``service.name``, which is the exact thing regrouping must not change.
        """
        for namespace in self._up:
            meter = agent_meter(namespace, __name__)
            label = namespace or ROOT_LABEL
            meter.create_observable_gauge(
                NAMESPACE_UP_GAUGE,
                callbacks=[self._observe_gauge(namespace, label)],
                description="1 while this agent is serving, 0 once it has stopped",
                unit="1",
            )

    def _observe_gauge(self, namespace: str, label: str) -> Callable[[CallbackOptions], Iterable[Observation]]:
        """Return the callback the metrics reader polls for ``namespace``.

        A closure over the namespace rather than a bound method taking one, because the
        OpenTelemetry reader calls a callback with a single ``CallbackOptions`` argument and
        offers no way to pass anything else. It runs on the reader's own thread, so it does no
        more than read a dictionary.
        """

        def observe(_options: CallbackOptions) -> Iterable[Observation]:
            return [Observation(1 if self._up.get(namespace, True) else 0, {"agent": label})]

        return observe

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    async def observe(self, namespace_status: Mapping[str, bool]) -> None:
        """Take one health poll's per-agent verdict and act on what changed.

        Only transitions are acted on. A namespace that has been down for an hour must not
        re-emit its ERROR event on every poll -- that is how an alert becomes noise and stops
        being read -- and must not re-pause a client that is already paused.

        Args:
            namespace_status: ``True`` where every one of that agent's health checks passed.
                A namespace this supervisor does not know about is added, so an agent whose
                first health check appears after startup is still supervised.
        """
        for namespace, healthy in namespace_status.items():
            await self._set(namespace, healthy and namespace not in self._forced_down, self._degraded_reason(namespace))

    async def mark_down(self, namespace: str, reason: str) -> None:
        """Take ``namespace`` out of service and keep it out until it is explicitly released.

        For the failures no health check can see: spec sec. 9.1's non-critical agent whose
        ``on_startup`` raised. That agent's components may be perfectly able to answer a health
        check while being unusable, so an observed-health signal would put it straight back into
        service on the next poll.

        Args:
            namespace: The agent to take out of service.
            reason: Why, for the ERROR event and for the readiness payload.
        """
        self._forced_down[namespace] = reason
        await self._set(namespace, False, reason)

    async def clear_forced_down(self, namespace: str) -> None:
        """Release a latch set by :meth:`mark_down`, letting health decide again."""
        self._forced_down.pop(namespace, None)

    def forced_down_reason(self, namespace: str) -> str | None:
        """Why ``namespace`` was latched down, or ``None`` if it was not."""
        return self._forced_down.get(namespace)

    def _degraded_reason(self, namespace: str) -> str:
        """The reason to report for a health-driven transition."""
        return self._forced_down.get(namespace) or "one or more of its health checks failed"

    async def _set(self, namespace: str, healthy: bool, reason: str) -> None:
        """Record ``namespace``'s state and, if it changed, emit and act."""
        previous = self._up.get(namespace)
        self._up[namespace] = healthy
        if previous is None or previous == healthy:
            return

        if healthy:
            logger.info("Agent '%s' is serving again (group '%s', pod '%s')", namespace or ROOT_LABEL, self._group, self._pod)
            await self._resume_consumption(namespace)
            return

        # ERROR rather than WARNING, and unconditional: this is the alert that the pod restart
        # used to be. Every value a dashboard keys on is in the line, because a grouped
        # process's logs are the one place an agent's failure is attributable without one.
        logger.error(
            "Agent '%s' has stopped serving (group '%s', pod '%s'): %s",
            namespace or ROOT_LABEL,
            self._group,
            self._pod,
            reason,
        )
        await self._pause_consumption(namespace)

    # ------------------------------------------------------------------
    # C4 -- consequence
    # ------------------------------------------------------------------

    async def _pause_consumption(self, namespace: str) -> None:
        """Stop this agent taking events, so they redeliver to a replica that can serve them."""
        for client in self._clients(namespace):
            try:
                await client.pause_consumption()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Agent '%s' could not be paused: %s", namespace or ROOT_LABEL, exc, exc_info=True)

    async def _resume_consumption(self, namespace: str) -> None:
        """Let this agent take events again."""
        for client in self._clients(namespace):
            try:
                await client.resume_consumption()
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Agent '%s' could not resume consuming: %s", namespace or ROOT_LABEL, exc, exc_info=True)

    def _clients(self, namespace: str) -> list[IOClientBase]:
        """This agent's transport clients, and nobody else's.

        The namespace is passed explicitly even for the root, where it looks redundant: on the
        application's registry an *omitted* namespace means every namespace, so leaving it out
        would pause every agent in the process the moment the root was degraded.
        """
        return self._registry.get_io_clients(namespace=namespace or ROOT_NAMESPACE)
