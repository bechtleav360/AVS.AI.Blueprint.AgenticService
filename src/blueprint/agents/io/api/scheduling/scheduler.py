"""Abstract base class for scheduled background tasks.

Subclasses implement :meth:`tick` and are registered with :class:`AppBuilder`
via ``with_scheduler()``. What calls ``tick()`` depends on ``scheduler_mode``
(spec sec. 7.5):

``"event"``
    Nothing in this process keeps time. The schedule is declared here and lives
    outside -- an external scheduler publishes to the scheduler's own topic and
    :class:`SchedulerTickHandler` turns that delivery into a ``tick()``. The queue
    group already picks exactly one replica, so no leader is elected. Requires
    ``event_bus``.

``"in_process"``
    An APScheduler timer in every replica, for un-orchestrated Docker and local
    development where no external scheduler exists. Every replica's timer fires, and
    each tick is claimed in the shared cache so exactly one replica runs it. With no
    cache registered there is nothing to claim with and every replica runs every tick,
    which startup warns about.

The key has **no default**: registering a scheduler without it fails at startup. Neither
value is safe to inherit silently, and which one applies depends on the deployment rather
than on the code -- see :meth:`SchedulerBase._resolve_mode`.

A REST endpoint for manual triggering is registered under ``/{name}/trigger`` in
both modes.

Example::

    class CleanupScheduler(SchedulerBase):
        def __init__(self) -> None:
            super().__init__(crontab="0 * * * *")

        async def tick(self) -> None:
            await self.registry.cache_service.clear()
"""

from __future__ import annotations

import logging
import time
from abc import abstractmethod
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ....clients.io.io_client_base import TOPIC_TRANSPORTS, validate_subject_segment
from ....component.component import traced
from ....component.namespace import ROOT_NAMESPACE
from ....handler.event_handler_base import EventHandlerBase
from ....models.events import GenericCloudEvent
from ..rest_api_base import RestApiBase

logger = logging.getLogger(__name__)

SCHEDULER_MODE_EVENT = "event"
"""No in-process timer; the tick arrives as an ordinary namespaced event."""

SCHEDULER_MODE_IN_PROCESS = "in_process"
"""An APScheduler timer inside every replica of the process."""

SCHEDULER_MODES = (SCHEDULER_MODE_EVENT, SCHEDULER_MODE_IN_PROCESS)

TICK_CACHE_NAMESPACE = "scheduler_tick"
"""Cache namespace holding the per-tick claims, kept away from application data."""

TICK_CLAIM_TTL_SECONDS = 300
"""How long a claimed tick slot is remembered.

It only has to outlast the spread between replicas firing for the *same* slot, which is
clock skew plus scheduler jitter -- seconds. Five minutes is generous. It does not have to
outlast the interval between ticks, because the next tick claims a different key.
"""


def validate_crontab(crontab: str) -> str:
    """Return the crontab if an external cron can read it, else raise.

    In ``"in_process"`` mode ``CronTrigger.from_crontab`` parses the expression, so a typo
    fails the pod. In ``"event"`` mode nothing parses it at all -- the tick arrives from
    outside -- so without this a typo surfaces as a tick that never comes, long after the
    process reported itself healthy.

    ``croniter`` is used rather than apscheduler's parser because the consumer of this
    expression is an external scheduler reading the five standard fields, and apscheduler
    accepts extensions such as a leading seconds field that no cron implementation does.

    Raises:
        ValueError: if the expression is empty, is not a valid cron expression, or does not
            have exactly the five standard fields.
    """
    expression = crontab.strip()
    if not expression:
        raise ValueError("The declared crontab is empty.")

    from croniter import croniter

    if not croniter.is_valid(expression):
        raise ValueError(f"The declared crontab '{crontab}' is not a valid cron expression.")

    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(
            f"The declared crontab '{crontab}' has {len(fields)} fields. An external scheduler reads the five standard "
            "ones (minute hour day-of-month month day-of-week); seconds and year are apscheduler extensions it will not "
            "understand."
        )
    return expression


_TOPIC_CONTEXT_KEYS = ("nats_topic", "dapr_topic", "topic")
"""Every key a transport spells the delivery topic with.

``NatsEventing`` writes ``nats_topic``, ``DaprEventing`` writes ``dapr_topic`` and the
REST path writes ``topic``. Those keys reach user handlers, so they cannot be unified
(see ``EventHandlingBase._process_cloud_event``) -- a consumer that wants the topic has
to accept all three.
"""


class SchedulerTickHandler(EventHandlerBase):
    """Routes an externally scheduled tick to one scheduler's :meth:`SchedulerBase.tick`.

    This is the whole of ``scheduler_mode = "event"``: the schedule lives outside the
    process and the tick is an ordinary event, so the queue group picks exactly one
    replica (spec sec. 7.5) and dedup, telemetry and the acknowledgement contract all
    apply to it unchanged. Nothing is elected because nothing keeps time here.

    The handler claims an event only when the delivery arrived on the scheduler's own
    topic, which no other component subscribes to. Matching the topic rather than the
    event type is deliberate: it makes a hand-published tick (``POST /events/<topic>``
    during development) work without the publisher having to know a type string.
    """

    PRIORITY = 10
    """Ahead of the default handler priority of 100.

    A handler that declares nothing is still evaluated for every event its namespace
    receives (spec sec. 7.7, rule 1), so a permissive ``can_handle_event`` in user code
    would otherwise claim the tick before the scheduler ever saw it.
    """

    def __init__(self, scheduler: SchedulerBase, topic: str) -> None:
        """Bind this handler to one scheduler and the topic its ticks arrive on."""
        super().__init__(priority=self.PRIORITY)
        # Renamed here rather than by the caller, and not for readability: Component.__init__
        # registers under the class-derived name, so a second scheduler's handler would
        # collide with the first one on "scheduler_tick_handler". Renaming pops that key
        # out of the registry again, which is what leaves it free for the next instance.
        self.name = f"{scheduler.name}_tick"
        self._scheduler = scheduler
        self._topic = topic

    @property
    def topic(self) -> str:
        """The topic a tick for this scheduler arrives on."""
        return self._topic

    @property
    def scheduler(self) -> SchedulerBase:
        """The scheduler this handler ticks."""
        return self._scheduler

    async def on_startup(self) -> None:
        """No startup of its own; the scheduler it ticks owns the lifecycle."""

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    def get_subscribed_topics(self) -> list[str]:
        """Declare the tick topic so the transport actually subscribes to it."""
        return [self._topic]

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        """Accept anything delivered on this scheduler's own topic."""
        return any(context.get(key) == self._topic for key in _TOPIC_CONTEXT_KEYS)

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> dict[str, Any]:
        """Run the scheduler's tick, letting a failure reach the transport edge.

        Returns a plain dict rather than a :class:`HandlerResult`: it is non-``None``, so
        the chain stops here and the tick is not counted as an unhandled event, and it
        carries no ``event_type``, so nothing is published downstream.
        """
        logger.info("Scheduler '%s' ticking from event '%s' on topic '%s'", self._scheduler.name, event.id, self._topic)
        await self._scheduler.tick()
        return {"status": "ticked", "scheduler": self._scheduler.name}


class SchedulerBase(RestApiBase):
    """Abstract base class for cron-based background schedulers.

    Extends :class:`RestApiBase` so subclasses have access to ``self.registry``,
    ``self.config``, and a REST endpoint for manual triggering.

    Config keys
    ~~~~~~~~~~~
    ``scheduler_mode`` (str, **required**, no default): ``"event"`` starts no timer and
    expects the tick as an event on :attr:`tick_topic`, which needs ``event_bus`` set to
    one of ``TOPIC_TRANSPORTS``; ``"in_process"`` runs an APScheduler timer in every
    replica, with each tick claimed in the cache so one replica runs it. See
    :meth:`_resolve_mode` for why there is no default.

    Args:
        crontab: Standard cron expression (e.g. ``"*/5 * * * *"``). Declared here in both
            modes: the schedule stays in agent code even when an external scheduler is what
            fires it (spec sec. 7.5), and it is validated in event mode because nothing else
            parses it there.
        topic: Overrides the derived :attr:`tick_topic`. For an agent whose ticks are
            already published on a subject someone else owns.
    """

    def __init__(self, crontab: str, *, topic: str | None = None) -> None:
        super().__init__()
        self._crontab = crontab
        self._topic_override = topic.strip() if topic else None
        self._tick_topic: str | None = None
        self._mode: str | None = None
        self._tick_handler: SchedulerTickHandler | None = None
        self._scheduler: AsyncIOScheduler | None = None
        self._started = False
        self._trigger_route_registered = False

    @abstractmethod
    async def tick(self) -> None:
        """Called on every cron interval.

        Implement your scheduled logic here. Has access to
        ``self.registry`` and ``self.config``.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Declaration
    # ------------------------------------------------------------------

    @property
    def crontab(self) -> str:
        """The declared cron expression, in both modes."""
        return self._crontab

    @property
    def scheduler_mode(self) -> str:
        """The resolved ``scheduler_mode``, read from config on first access.

        Raises:
            ValueError: if the key is unset or unrecognised. It has no default.
        """
        if self._mode is None:
            self._mode = self._resolve_mode()
        return self._mode

    @property
    def tick_topic(self) -> str:
        """The topic a tick for this scheduler arrives on, resolved on first access."""
        if self._tick_topic is None:
            self._tick_topic = self._resolve_topic()
        return self._tick_topic

    @property
    def tick_handler(self) -> SchedulerTickHandler | None:
        """The handler routing ticks to this scheduler, or ``None`` outside event mode."""
        return self._tick_handler

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def wire(self) -> SchedulerTickHandler | None:
        """Resolve the mode and create what it needs, before the application is built.

        Called from :meth:`AppBuilder.build` rather than from :meth:`on_startup`, for two
        reasons that both produce a scheduler that looks registered and does nothing:

        - ``build()`` creates a transport and an eventing endpoint only when a handler is
          registered. A project whose only event consumer is an event-mode scheduler would
          otherwise get no transport at all, and nothing could ever tick it.
        - ``include_router`` copies the routes a router holds *at that moment*. The trigger
          route was added during startup, which is after the copy, so it lived on the
          scheduler's own router and was served by nothing.

        Idempotent: a second call returns the same handler and adds no second route.

        Returns:
            The tick handler in event mode, ``None`` in in-process mode.

        Raises:
            ValueError: if ``scheduler_mode`` is unset or unrecognised, if event mode has no
                transport that can deliver the tick, or if the tick topic is unusable.
        """
        self.register_trigger_route()

        if self.scheduler_mode != SCHEDULER_MODE_EVENT:
            return None

        self._require_event_transport()
        # Nothing else ever parses the crontab in event mode -- no CronTrigger is built -- so a
        # typo would otherwise surface as a tick that never arrives, long after this process
        # reported itself healthy.
        validate_crontab(self._crontab)
        if self._tick_handler is None:
            self._tick_handler = SchedulerTickHandler(self, self.tick_topic)
        return self._tick_handler

    def register_trigger_route(self) -> None:
        """Add ``POST /{name}/trigger`` to this scheduler's router, once.

        Registered outside ``__init__`` because ``with_scheduler(name=...)`` may rename the
        component afterwards, and the route path carries the name.
        """
        if self._trigger_route_registered:
            return

        self.router.post(
            f"/{self.name}/trigger",
            tags=["Scheduler"],
            summary=f"Manually trigger {self.name}",
        )(self._trigger_tick)
        self._trigger_route_registered = True

    def _resolve_mode(self) -> str:
        """Read and validate ``scheduler_mode``, which has no default (spec sec. 7.5).

        Registering a scheduler without stating the mode is a startup failure, and neither
        value is a defensible thing to inherit silently. ``"in_process"`` runs a timer in
        every replica and coordinates them through the cache, so it fires a tick once only
        where a cache is registered (#73), and a pod hosting 20 grouped agents runs 20
        timers. ``"event"`` is correct under an
        orchestrator but needs something outside the process to publish the tick and a
        transport to receive it -- a service whose only job is periodic work may have
        neither, and would simply go quiet. Which one applies depends on facts this layer
        cannot read: whether a broker is reachable, whether more than one replica runs,
        whether an orchestrator exists at all. So the author states it, exactly as
        ``idempotency_ttl`` is stated rather than defaulted (sec. 7.4).

        Raises:
            ValueError: if the key is absent or empty, or holds any other value. A typo must
                not fall back to either mode.
        """
        raw = self.config.get("scheduler_mode", None)
        mode = str(raw or "").strip().lower()
        if not mode:
            raise ValueError(
                f"Scheduler '{self.name}' is registered but 'scheduler_mode' is not set, and it has no default. "
                f"Set it to '{SCHEDULER_MODE_EVENT}' to take the tick as an event on '{self.tick_topic}', published "
                f"by an external CronJob -- exactly one replica then runs it. Set it to '{SCHEDULER_MODE_IN_PROCESS}' "
                "to run an APScheduler timer inside the process, which is correct for local development and plain "
                "Docker but fires once per replica."
            )
        if mode not in SCHEDULER_MODES:
            raise ValueError(f"Config key 'scheduler_mode' must be one of {', '.join(SCHEDULER_MODES)}, got {raw!r}.")
        return mode

    def _require_event_transport(self) -> None:
        """Fail unless a transport that can deliver a tick is configured.

        In event mode the tick is an ordinary event, so without ``event_bus`` there is
        nothing to subscribe to and the scheduler would run forever without ticking --
        the one failure mode of event mode that is otherwise pure silence.

        Raises:
            ValueError: if ``event_bus`` is unset or set to a transport that cannot carry
                a topic subscription.
        """
        bus = str(self.config.get("event_bus", "") or "").strip().lower()
        if bus not in TOPIC_TRANSPORTS:
            raise ValueError(
                f"Scheduler '{self.name}' is in '{SCHEDULER_MODE_EVENT}' mode, which delivers its tick as an event on "
                f"'{self.tick_topic}', but 'event_bus' is {bus or 'not set'!r}. Set 'event_bus' to one of "
                f"{', '.join(TOPIC_TRANSPORTS)}, or set 'scheduler_mode = \"{SCHEDULER_MODE_IN_PROCESS}\"' to run "
                "an in-process timer instead."
            )

    def _resolve_topic(self) -> str:
        """Derive the tick topic from the agent's own identity, or take the override.

        ``f"{namespace}.scheduler.{name}"``, falling back to ``app_name`` while the
        namespace is the root one -- the same identity the queue group derives from, so
        moving the scheduler between deployment groups does not change the subject a
        ``CronJob`` has to publish to (C1).

        A derived topic is **validated, not repaired**, and both of the names it is derived
        from -- the identity and the scheduler's own name -- are checked. This subject is the
        contract with whatever publishes the tick: a ``CronJob`` in another repository, written
        by someone who has never read this method. Rewriting ``app_name = "Health Monitor"``
        into ``Health_Monitor.scheduler.nightly`` leaves that author publishing to a subject
        this scheduler does not subscribe to, and nothing anywhere says why -- the tick simply
        never arrives. Failing the startup of the side that knows the name is unusable is the
        only version of this that is debuggable.

        Raises:
            ValueError: if no identity is available, or if the identity, the scheduler name or
                an explicit ``topic`` contains whitespace or a wildcard. All are startup
                failures rather than a silently unsubscribed scheduler.
        """
        if self._topic_override:
            topic = self._topic_override
            validate_subject_segment(topic, source=f"The tick topic given to scheduler '{self.name}'", subject=topic)
            return topic

        # ROOT_NAMESPACE is still "" for every component; phase 2 is what gives this a value.
        identity = ROOT_NAMESPACE or str(self.config.get("app_name", "") or "").strip()
        if not identity:
            raise ValueError(
                f"Scheduler '{self.name}' runs in event mode but its tick topic cannot be derived: "
                "set 'app_name', or pass topic=... to SchedulerBase.__init__."
            )

        topic = f"{identity}.scheduler.{self.name}"
        source = "'app_name'" if not ROOT_NAMESPACE else "The scheduler's namespace"
        validate_subject_segment(identity, source=source, subject=topic)
        validate_subject_segment(self.name, source=f"The name of scheduler '{self.name}'", subject=topic)
        return topic

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_startup(self) -> None:
        """Start the in-process timer, or leave the tick to the event path.

        Guarded against a repeated call (#43). Two ``build()`` passes in one process drive
        the lifespan hooks twice over the same registry, and an unguarded second call
        started a second ``AsyncIOScheduler`` on the same crontab -- one process firing
        every tick twice, which no amount of broker-side grouping can fix, because both
        timers sit behind the same queue-group member.

        A subclass overriding this **must** call ``super().on_startup()``, or the scheduler
        is registered and never runs.
        """
        if self._started:
            logger.warning("Scheduler '%s' is already started; ignoring the repeated startup", self.name)
            return
        self._started = True

        # Normally already done by AppBuilder.build(); repeated here so a scheduler driven
        # without the builder still gets its handler and its route.
        self.wire()

        if self.scheduler_mode == SCHEDULER_MODE_EVENT:
            logger.info(
                "Scheduler '%s' is in event mode: no in-process timer. Its tick arrives as an event on topic '%s', "
                "on the declared crontab '%s'.",
                self.name,
                self.tick_topic,
                self._crontab,
            )
            return

        trigger = CronTrigger.from_crontab(self._crontab)

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(self._claimed_tick, trigger, name=self.name)
        self._scheduler.start()

        if self.registry.has_cache():
            logger.info(
                "Scheduler '%s' started an in-process timer with crontab '%s'; each tick is claimed in the cache, so one replica runs it",
                self.name,
                self._crontab,
            )
        else:
            logger.warning(
                "Scheduler '%s' started an in-process timer with crontab '%s' and NO cache is registered, so its ticks "
                "cannot be coordinated: every replica of this process will run every tick. Add '.with_cache()' to the "
                "AppBuilder chain, or use 'scheduler_mode = \"event\"' where an orchestrator schedules the tick.",
                self.name,
                self._crontab,
            )

    async def on_shutdown(self) -> None:
        """Shut down APScheduler, waiting for any running tick to finish."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
        self._scheduler = None
        self._started = False
        logger.info("Scheduler '%s' stopped", self.name)

    # ------------------------------------------------------------------
    # In-process coordination
    # ------------------------------------------------------------------

    async def _claimed_tick(self) -> None:
        """Run ``tick`` if this replica wins the slot, otherwise do nothing.

        This is what the timer calls in ``"in_process"`` mode, and it is what makes that
        mode survive more than one replica (#73). Every replica's own timer fires, and each
        one tries to claim the same slot in the shared cache; the one that stores the marker
        runs the tick and the rest return.

        Spec sec. 7.5 calls for a leader lease. A *slot claim* is used instead, and it is a
        better fit for the same requirement:

        - Nothing is elected and nothing is held, so there is no renewal task to schedule --
          and therefore no framework-created background task to leak (C7) -- and no lease to
          be left behind by a replica that dies holding it.
        - It answers the question spec sec. 13 leaves open, whether that mode needs true
          failover or "one designated instance runs it, others no-op", by removing it: a
          dead replica takes nothing with it, because the next slot is claimed from scratch
          by whoever is alive. There is no takeover bound to specify.
        - The failure it cannot prevent is the one the spec already accepts either way: a
          cache that cannot be reached fails open, so every replica ticks. Deduplication
          (sec. 7.4) is what makes a repeated tick safe, and it applies to both modes.

        With no cache registered there is nothing to claim with, so the tick runs
        unconditionally. That is the behaviour this mode had before, and ``on_startup`` warns
        about it once rather than on every tick.
        """
        if not self._claim_tick_slot():
            logger.debug("Scheduler '%s' did not win this tick; another replica is running it", self.name)
            return
        await self.tick()

    def _claim_tick_slot(self) -> bool:
        """Claim the current tick slot, reporting whether this replica may run it.

        The key is the *slot*, not the scheduler: ``(scheduler, minute)``. Cron granularity
        is one minute, so every replica firing for the same scheduled time derives the same
        key, and the next scheduled time derives a different one. Keying on the scheduler
        alone would need a compare-and-swap on every tick after the first; keying on the
        slot needs only set-if-absent, which is what :meth:`CacheService.claim` provides
        atomically.

        The consequence to be aware of: replicas whose clocks differ enough to straddle a
        minute boundary derive different slots and both tick. Container clock skew is
        milliseconds, and a repeated tick is what dedup covers.
        """
        if not self.registry.has_cache():
            return True

        slot = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
        return self.registry.cache_service.claim(
            {"scheduler": self.name, "slot": slot},
            {"claimed_at": time.time()},
            namespace=TICK_CACHE_NAMESPACE,
            ttl=TICK_CLAIM_TTL_SECONDS,
        )

    # ------------------------------------------------------------------
    # Manual trigger
    # ------------------------------------------------------------------

    @traced()
    async def _trigger_tick(self) -> dict[str, Any]:
        """Manually trigger a tick via REST.

        Returns:
            Status dictionary confirming the trigger.
        """
        logger.info("Scheduler '%s' manually triggered via REST", self.name)
        await self.tick()
        return {"status": "triggered", "scheduler": self.name}
