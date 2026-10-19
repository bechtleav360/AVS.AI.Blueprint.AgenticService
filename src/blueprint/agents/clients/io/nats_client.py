"""NATS client implementation for eventing."""

import asyncio
import contextlib
import contextvars
import functools
import importlib.util
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import nats
from nats.aio.client import Client as NatsClient
from nats.js import api as js_api
from nats.js.client import JetStreamContext
from nats.errors import NoRespondersError
from nats.js.errors import APIError, NotFoundError
from opentelemetry.metrics import CallbackOptions, Counter, Observation
from pydantic import ValidationError

from ...component.namespace import ROOT_LABEL, ROOT_NAMESPACE
from ...deployment import UNGROUPED_LABEL, UNKNOWN_POD_LABEL, deployment_group, pod_identity
from ...io.telemetry.providers import agent_meter
from ...models.api import ComponentHealth
from ...models.errors import DeliveryDisposition, DeliveryRevokedError, describe_validation_errors, disposition_for
from ...models.events import CloudEvent
from ..client_base import DeliveryCallback
from .io_client_base import IOClientBase, subject_is_covered_by, validate_publish_subject, validate_subject_segment
from .nats_connections import ConnectionSource, ConnectionSpec, DeliveryAttempt, JetStreamBinding, mark_connection, mark_delivery
from .nats_run_pool import PairRuns, Release, RunLimit, RunPool

logger = logging.getLogger(__name__)

DEVELOPMENT_NATS_URL = "nats://localhost:4222"
"""The broker a development process connects to when ``nats_url`` is unset -- and only then.

In a container ``localhost`` is almost always wrong -- a broker in the same pod is the exception, and
it can say so -- and a client pointed at it retries forever while the pod looks healthy. So outside
``app_environment = "development"`` an unset ``nats_url`` fails startup instead of reaching for this.
"""


class JetStreamBindingError(RuntimeError):
    """A binding-mode binding cannot be bound as the deployment describes it (e.g. its stream is missing).

    Raised into the connection's retry loop, which retries it: provisioning may create the stream later.
    """


class JetStreamUnavailableError(RuntimeError):
    """The agent declared ``nats_use_jetstream = true`` and the server does not offer JetStream to it.

    A deployment error, not a transient one: no retry makes a server grow JetStream. It is therefore
    never retried by the connection loop, and it fails the agent -- at startup through the startup
    failure policy (spec sec. 9.1), later through the fatal handler :class:`AppBuilder` installs.
    """


SERVER_DEFAULT_ACK_WAIT = 30.0
"""Seconds: the ``ack_wait`` NATS gives a consumer created without one.

Only a fallback for a bound consumer whose config reports no ``ack_wait``; the heartbeat interval
is otherwise derived from the consumer's own value (handler-time-bounds spec sec. 4.2).
"""


CONNECTIONS_READINESS_KEY = "nats_connections_readiness"
"""Agent-scoped: whether the agent's named connections count for its readiness -- ``"never"`` (default),
``"any"`` (one bound is enough) or ``"all"`` (every one bound). Readiness only, in every mode: a named
connection never pauses the agent (named-connections plan, D5)."""

CONNECTIONS_READINESS_MODES = ("never", "any", "all")

CONNECTION_BOUND_GAUGE = "blueprint.nats.connection.bound"
"""``1`` while a named connection is bound and delivering, ``0`` otherwise; attributes ``agent`` and
``connection``. Recorded on the agent's own meter provider (C2)."""

PERMISSION_VIOLATIONS_COUNTER = "blueprint.nats.connection.permission_violations"
"""Permission violations a named connection's broker reported; attributes ``agent`` and ``connection``."""

PERMISSION_RETRY_SECONDS = 60.0
"""How often a named connection retries after the broker refused it a permission: a missing grant does
not heal in seconds, so retrying at the normal pace would only fill the log (spec 7.9)."""

CONTROL_MESSAGE_STATUS = "100"
"""The status a JetStream idle heartbeat and flow control request carry (``nats.js.api.StatusCode.CONTROL_MESSAGE``)."""

RESUME_RETRY_MAX_DELAY = 60.0
"""The longest wait between two attempts of a resume that keeps failing (M2): the delay doubles from
``event_client_retry_delay`` up to this."""

_CURRENT_BINDING: contextvars.ContextVar["_Binding | None"] = contextvars.ContextVar("blueprint_nats_binding", default=None)
"""The named binding a run's delivery arrived on; set inside that run's own task only, so ``publish``
can refuse a revoked run (dynamic-subscriptions spec 7.5)."""


FatalHandler = Callable[[str, BaseException], Awaitable[None]]
"""Called once when a client finds, after startup, that its agent cannot run at all: namespace, error."""


def redact_url(url: str) -> str:
    """Return ``url`` without its ``user:password@`` part, for logs and health messages.

    Credentials in ``nats_url`` are still accepted, so every place that shows the URL has to strip
    them: the connect log line and the ``/health`` message both used to print it verbatim.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable url>"
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit(parts._replace(netloc=f"***@{netloc}"))


DEAD_LETTERED_COUNTER = "blueprint.events.dead_lettered"
"""Events the framework gave up on, whether or not their payload was kept.

Dead-lettering was logged and counted nowhere, so "how many messages did we give up on today"
could not be answered from metrics -- and a dead letter is the one delivery outcome that has
no other trace in the running system: it is not a retry that eventually succeeds, and it is
not an error a caller sees. ``reason`` separates a payload that was rejected as unprocessable
from one whose redeliveries ran out, and ``kept`` says whether the payload survived, because a
deployment with no dead-letter subject configured is losing them.
"""


@dataclass(frozen=True)
class ConsumerTuning:
    """JetStream consumer settings, resolved once from config (spec sec. 7.3).

    Held as one object because the four values only make sense together: ``ack_wait``
    decides when an unacknowledged message comes back, ``max_ack_pending`` decides how
    many can be waiting at once, ``max_deliver`` decides how often it comes back before
    the framework gives up, and ``dead_letter_subject`` decides where it goes when that
    happens.
    """

    # None means "not configured": the setting is left out of the consumer, so the server's
    # default applies -- as it did before the framework set any of them.
    ack_wait: float | None
    max_ack_pending: int | None
    max_deliver: int | None
    dead_letter_subject: str


@dataclass(frozen=True)
class NamedConnectionState:
    """How one named connection of an agent stands, for readiness and diagnostics. Never carries a secret.

    ``state`` is ``"bound"`` (delivering), ``"connecting"`` (first attempt in progress),
    ``"reconnecting"`` (the broker was lost; the client reconnects by itself), ``"retrying"`` (an
    attempt failed; ``last_error`` says why) or ``"paused"`` (the agent is degraded and consumes
    nowhere, C4).
    """

    name: str
    state: str
    last_error: str = ""
    permission_denied: bool = False
    """The broker reported a permission violation since the connection's last attempt."""

    @property
    def bound(self) -> bool:
        """Whether the connection is bound and delivering."""
        return self.state == "bound"

    def describe(self) -> str:
        """One line for the readiness payload: name, state, and why when it is not bound."""
        details = []
        if self.permission_denied:
            details.append("permission violation")
        if self.last_error and not self.bound:
            details.append(self.last_error)
        return f"{self.name}={self.state}" + (f" ({'; '.join(details)})" if details else "")


@dataclass(eq=False)
class _Link:
    """One broker connection and what it was opened with.

    Held apart from :class:`_Binding` so that what a connection *is* (URL, credentials, the
    ``nats.Client``) and what is consumed *over* it (subscriptions, runs) can vary
    independently: today every binding has a link of its own, and a link shared by several
    bindings stays possible without reshaping either (named-connections plan, D1).
    """

    name: str = ""
    """``""`` for the agent's default connection, configured through ``nats_url`` and friends."""
    # Neither is rendered by repr (S4): connect_options holds password, token and nkey seed, and
    # a nats_url may carry user:pass@. A traceback or debugger printing a link prints its repr.
    url: str = field(default="", repr=False)
    connect_options: dict[str, Any] = field(default_factory=dict, repr=False)
    connection_name: str = ""
    nats_client: NatsClient | None = None
    js: JetStreamContext | None = None
    jetstream_mismatch: JetStreamUnavailableError | None = None
    permission_errors: list[str] = field(default_factory=list)
    """Permission violations the broker reported through ``error_cb`` since the last attempt."""
    closing: bool = False
    """We are closing this link ourselves: its disconnect is not a lost broker."""


@dataclass(eq=False)
class _Binding:
    """What one agent consumes over one link, and the runs it has in flight there.

    Every delivery is decoded, run, heartbeated and settled against the binding it arrived
    on, so nothing of one binding's runs -- slots, in-flight count, acknowledgement -- is
    shared with another's.
    """

    link: _Link
    jetstream: JetStreamBinding | None = None
    """Set: *binding mode* -- bind to the deployment's consumer with its wire values verbatim,
    never provision (plan N3, N4). Unset: the agent's own consumers, derived as before."""
    topic_callbacks: dict[str, DeliveryCallback] = field(default_factory=dict)
    durables: dict[str, str] = field(default_factory=dict)
    tuning: ConsumerTuning | None = None
    subscriptions: list[Any] = field(default_factory=list)
    subscriptions_ready: bool = False
    limit: RunLimit | None = None
    """``nats_max_concurrent_runs`` when it is set: the pair's guaranteed run plus pool runs up to K."""
    pair: PairRuns = field(default_factory=PairRuns)
    subscription_slots: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    """One slot per subscription when it is not set -- one run at a time per subscription."""
    runs: set[asyncio.Task[None]] = field(default_factory=set)
    ack_waits: dict[str, float] = field(default_factory=dict)
    """Per topic, the bound consumer's own ``ack_wait`` -- what the heartbeat interval derives from."""
    inflight: int = 0
    idle: asyncio.Event = field(default_factory=asyncio.Event)
    spec: ConnectionSpec | None = None
    """The connection as the source last described it; a named binding is replaced when it differs."""
    replaces: "_Binding | None" = None
    """The bound binding this one replaces; retired as soon as this one is bound (new before old, spec 7.4).

    Always one that delivers, never a chain: a change that supersedes a binding not yet bound retires
    that one at once and takes over what it was replacing (M3)."""
    bound: bool = False
    """The subscription is on the link: set when a bind succeeds, cleared at each attempt. A reconnect
    restores readiness only for a bound binding -- nats-py replays only the subscriptions it holds."""
    superseded: bool = False
    """A newer binding of the same connection exists; this one serves until that one is bound."""
    revoked: bool = False
    """Retired with runs still in flight after the grace period: those runs are never settled (spec 7.5)."""
    heartbeats: set[asyncio.Task[None]] = field(default_factory=set)
    last_error: str = ""
    """Why the last connect-and-bind attempt failed, redacted; ``""`` once it is bound."""
    permission_denied: bool = False
    """The last failed attempt was refused a permission by the broker."""

    def __post_init__(self) -> None:
        self.idle.set()

    def slots_for(self, topic: str) -> asyncio.Semaphore:
        """With ``nats_max_concurrent_runs`` unset: the one slot of the subscription on ``topic``, as before it existed."""
        return self.subscription_slots.setdefault(topic, asyncio.Semaphore(1))

    def enter_run(self) -> None:
        """Count one delivery in; shutdown and pause wait until the count is back to zero."""
        self.inflight += 1
        self.idle.clear()

    def exit_run(self) -> None:
        """Count one delivery out."""
        self.inflight = max(0, self.inflight - 1)
        if self.inflight == 0:
            self.idle.set()


class NATSClient(IOClientBase):
    """NATS client for subscribing to and publishing CloudEvents.

    Managed subscription lifecycle
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Call ``subscribe(topic_callbacks)`` once at startup with the full
    ``{topic: callback}`` mapping.  The client fires a background retry
    task that connects to the broker and subscribes to every topic.
    ``subscriptions_ready`` becomes ``True`` once all subscriptions are
    active; ``health_check()`` reflects this state so the readiness probe
    keeps the pod out of service rotation until then.

    On disconnect the NATS library fires ``_on_disconnected``, which clears
    the ready flag.  On reconnect the NATS library replays every subscription,
    JetStream push subscriptions included; ``_on_reconnected`` re-checks the
    JetStream stream and consumers (never subscribes again) and restores the flag.

    One connection per namespace
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    A client belongs to one namespace (spec sec. 6), so a process hosting three
    agents opens three connections rather than multiplexing one. That confines
    the two failures that are per-connection: a dropped connection strands the
    acknowledgements of only that namespace's in-flight messages, and a
    slow-consumer kick removes only the namespace that flooded its buffer. It is
    **not** a durability mechanism -- JetStream pending state lives on the server,
    so what the topology decides is how many namespaces repeat work after a drop.

    Each connection is named ``f"{namespace}.{group}.{pod}"``, which is what makes
    a pod's contents legible in ``/connz``; before this, every connection the
    framework opened was anonymous. An absent segment becomes a bracketed placeholder
    (``<root>``, ``<ungrouped>``, ``<unknown-pod>``) that no real namespace, group or
    pod can produce, so a missing value never reads as a present one. The name contains
    the pod, so it must never reach queue-group or durable naming (C1) -- those two are
    the only broker-side identifiers, and both derive from the namespace alone.

    Queue group
    ~~~~~~~~~~~
    Every Core NATS subscription joins a queue group, so exactly one replica
    receives any given message.  The name is resolved once in ``subscribe()``
    and is a pure function of the agent's own identity -- never of the pod,
    container or replica it happens to run in.

    One name covers every topic because a group is keyed by *(subject, queue
    name)*: subscriptions sharing this name on different subjects are separate
    groups, so unrelated event types never compete for the same delivery.  The
    exception is a subject overlapping another of this client's own subjects
    (a wildcard plus a literal it covers), where one message matches two of its
    subscriptions -- the server is expected to merge them into one group and
    deliver once, to either callback.  Unverified against a real broker; see the
    feature changelog's broker-test open point.

    JetStream consumer
    ~~~~~~~~~~~~~~~~~~
    Under JetStream the durable consumer is created explicitly rather than left to
    ``js.subscribe``, because every setting that makes a consumer safe to share lives on
    ``ConsumerConfig``: the deliver group that stops each replica seeing every message,
    the ``ack_wait`` that must outlast a slow handler, the ``max_ack_pending`` window and
    the ``max_deliver`` limit after which a message is dead-lettered rather than dropped.
    An existing consumer is never rewritten -- a durable's filter and deliver group are
    broker-side state, and recreating one either replays or gaps.

    Config keys
    ~~~~~~~~~~~
    ``event_client_max_retries`` (int, default -1): retries after first failure;
    ``-1`` = indefinite, ``0`` = single attempt.
    ``event_client_retry_delay`` (float, default 5.0): seconds between retries.
    ``event_client_drain_timeout`` (float, default 30.0): seconds allowed for in-flight
    handlers to finish during shutdown.
    ``nats_ack_wait`` (float, unset = server default): seconds the broker waits for an
    acknowledgement before redelivering. Must exceed p99 handler duration.
    ``nats_max_ack_pending`` (int, unset = server default): unacknowledged messages allowed
    at once across every replica sharing the consumer; ``-1`` = unlimited.
    ``nats_max_deliver`` (int, unset = server default, unlimited): delivery attempts before a
    message is dead-lettered; unlimited disables dead-lettering on exhaustion.
    ``nats_dead_letter_subject`` (str, default ``"<queue group>.dead-letter"``): where a
    message goes when the framework gives up on it; ``""`` disables it and loses the payload.
    ``nats_max_concurrent_runs`` (int, unset by default): deliveries this agent handles at once,
    shared by all of its subscriptions. Unset is the behaviour before the key existed: one run at a
    time *per subscription*, so an agent with two subscriptions runs two at once.
    ``nats_heartbeat_enabled`` (bool, default true): whether running JetStream deliveries report
    ``in_progress``; off, a run longer than the consumer's ``ack_wait`` is redelivered while it runs.
    ``nats_handler_timeout`` (float seconds, unset by default): the longest one run may take, on
    every connection. At the limit the run is cancelled and nak'd for immediate redelivery; unset,
    a run is never cut.

    Concurrent runs
    ~~~~~~~~~~~~~~~
    nats-py gives each subscription one task, and that task awaits its callback before it takes
    the next message. A callback that ran the handler itself therefore handled one delivery per
    subscription at a time, however much of the handler was spent waiting on I/O. The callback now
    only waits for a free run slot and starts the run as a task of its own, so up to
    ``nats_max_concurrent_runs`` runs of this agent are in progress at once. Unset, each
    subscription keeps one slot of its own, exactly the old behaviour. Waiting for the slot
    *inside* the callback is the back-pressure: with every slot taken, the subscription's task
    stops taking messages and they wait in the client's buffer (bounded by ``max_ack_pending``)
    rather than starting. Order within a subscription is not kept beyond one run at a time.

    While a JetStream run is in progress its delivery is reported ``in_progress`` every third of
    the bound consumer's ``ack_wait``, so a run longer than ``ack_wait`` is not redelivered while it
    still runs (handler-time-bounds spec sec. 4.1). Messages still waiting in the buffer get no
    heartbeat; their ``ack_wait`` keeps running. ``nats_heartbeat_enabled = false`` switches it off.

    Links and bindings
    ~~~~~~~~~~~~~~~~~~
    The broker connection is a :class:`_Link`; what this agent consumes over it, with its run
    slots and in-flight runs, is a :class:`_Binding`. Today the client has exactly one of each,
    the *default* ones configured by ``nats_url`` and friends, and the delivery path takes the
    binding a message arrived on as a parameter (named-connections plan, step 1).
    """

    def __init__(self, namespace: str = ROOT_NAMESPACE) -> None:
        super().__init__(namespace=namespace)
        self._link = _Link()
        self._binding = _Binding(link=self._link)
        self._started = False
        self._closing = False
        self._fatal_handler: FatalHandler | None = None
        self._fatal_reported = False
        self._use_jetstream: bool = False
        self._publish_via_jetstream: bool = False
        self._publish_subjects: set[str] = set()
        self._queue_group: str = ""
        self._subscriptions_managed: bool = False
        self._retry_task: asyncio.Task[None] | None = None
        self._resume_retry: asyncio.Task[None] | None = None
        self._max_concurrent_runs: RunLimit | None = None
        self._pool = RunPool()
        self._pairs_registered = 0
        self._heartbeat_enabled: bool = True
        self._handler_timeout: float | None = None
        self._source: ConnectionSource | None = None
        self._named: list[_Binding] = []
        self._named_tasks: dict[_Binding, asyncio.Task[None]] = {}
        self._declared: dict[str, DeliveryCallback] = {}
        self._claimed: frozenset[str] = frozenset()
        self._default_pairs = 0
        self._change_grace = 30.0
        self._change_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connections_readiness: str | None = None
        self._connection_gauge_registered = False
        self._health_refresh: Callable[[], Awaitable[None]] | None = None
        self._reconcile_task: asyncio.Task[None] | None = None
        self._reconcile_dirty = False
        self._retirements: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # The default link and binding, under the names the client used before it had them
    # ------------------------------------------------------------------
    # Transitional: unit tests reach these by name. They go once the tests address links and
    # bindings directly (named-connections plan, step 3).

    @property
    def _connection_name(self) -> str:
        return self._link.connection_name

    @_connection_name.setter
    def _connection_name(self, value: str) -> None:
        self._link.connection_name = value

    @property
    def _nats_url(self) -> str:
        return self._link.url

    @_nats_url.setter
    def _nats_url(self, value: str) -> None:
        self._link.url = value

    @property
    def _connect_options(self) -> dict[str, Any]:
        return self._link.connect_options

    @_connect_options.setter
    def _connect_options(self, value: dict[str, Any]) -> None:
        self._link.connect_options = value

    @property
    def _jetstream_mismatch(self) -> JetStreamUnavailableError | None:
        return self._link.jetstream_mismatch

    @_jetstream_mismatch.setter
    def _jetstream_mismatch(self, value: JetStreamUnavailableError | None) -> None:
        self._link.jetstream_mismatch = value

    @property
    def _nats_client(self) -> NatsClient | None:
        return self._link.nats_client

    @_nats_client.setter
    def _nats_client(self, value: NatsClient | None) -> None:
        self._link.nats_client = value

    @property
    def _js(self) -> JetStreamContext | None:
        return self._link.js

    @_js.setter
    def _js(self, value: JetStreamContext | None) -> None:
        self._link.js = value

    @property
    def _subscriptions(self) -> list[Any]:
        return self._binding.subscriptions

    @_subscriptions.setter
    def _subscriptions(self, value: list[Any]) -> None:
        self._binding.subscriptions = value

    @property
    def _topic_callbacks(self) -> dict[str, DeliveryCallback]:
        return self._binding.topic_callbacks

    @_topic_callbacks.setter
    def _topic_callbacks(self, value: dict[str, DeliveryCallback]) -> None:
        self._binding.topic_callbacks = value

    @property
    def _tuning(self) -> ConsumerTuning | None:
        return self._binding.tuning

    @_tuning.setter
    def _tuning(self, value: ConsumerTuning | None) -> None:
        self._binding.tuning = value

    @property
    def _durables(self) -> dict[str, str]:
        return self._binding.durables

    @_durables.setter
    def _durables(self, value: dict[str, str]) -> None:
        self._binding.durables = value

    @property
    def _subscriptions_ready(self) -> bool:
        return self._binding.subscriptions_ready

    @_subscriptions_ready.setter
    def _subscriptions_ready(self, value: bool) -> None:
        self._binding.subscriptions_ready = value

    @property
    def _inflight(self) -> int:
        return self._binding.inflight

    @property
    def _runs(self) -> set[asyncio.Task[None]]:
        return self._binding.runs

    @property
    def _ack_waits(self) -> dict[str, float]:
        return self._binding.ack_waits

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def subscriptions_ready(self) -> bool:
        """``True`` once all managed subscriptions are active."""
        return self._subscriptions_ready

    @cached_property
    def _dead_lettered(self) -> Counter:
        """This agent's dead-letter counter, created on first use rather than at construction.

        Cached rather than eager for the same reason ``Component.tracer`` is: a client is
        constructed by ``build()``, and the per-agent meter providers do not exist until the
        lifespan configures telemetry. An instrument created in ``__init__`` would be bound to
        the no-op global meter for the life of the process.
        """
        return agent_meter(self.namespace, __name__).create_counter(
            name=DEAD_LETTERED_COUNTER,
            description="Events this agent gave up on after exhausting redelivery or rejecting the payload",
            unit="{event}",
        )

    @property
    def queue_group(self) -> str:
        """Queue group joined by this client's subscriptions; ``""`` before ``subscribe()``."""
        return self._queue_group

    @property
    def inflight_handlers(self) -> int:
        """Number of message handlers currently executing, on every connection of this agent."""
        return self._inflight + sum(binding.inflight for binding in self._named)

    @property
    def named_connections(self) -> tuple[str, ...]:
        """Names of the connections the source gave this agent a binding on, in the source's order."""
        return tuple(binding.link.name for binding in self._named)

    @property
    def connections_readiness(self) -> str:
        """``nats_connections_readiness`` for this agent: ``"never"``, ``"any"`` or ``"all"``.

        Raises:
            ValueError: the key holds anything else. ``subscribe()`` resolves it first, so a wrong
                value fails the agent's startup rather than a health poll.
        """
        if self._connections_readiness is None:
            self._connections_readiness = self._resolve_connections_readiness()
        return self._connections_readiness

    def named_connection_states(self) -> tuple[NamedConnectionState, ...]:
        """How each current named connection stands, in the source's order; one being replaced is left out."""
        return tuple(self._state_of(binding) for binding in self._named if not binding.superseded)

    def _state_of(self, binding: _Binding) -> NamedConnectionState:
        """``binding``'s state, from what its link and its connect loop last recorded."""
        client = binding.link.nats_client
        if binding.subscriptions_ready:
            state = "bound"
        elif self._consumption_paused:
            state = "paused"
        elif client is not None and client.is_reconnecting:
            state = "reconnecting"
        elif binding.last_error:
            state = "retrying"
        else:
            state = "connecting"
        denied = binding.permission_denied or bool(binding.link.permission_errors)
        return NamedConnectionState(binding.link.name, state, binding.last_error, denied)

    def _resolve_connections_readiness(self) -> str:
        """Read ``nats_connections_readiness``; refuse anything but the three modes, naming the key."""
        raw = self.config.get(CONNECTIONS_READINESS_KEY, None)
        mode = str(raw or "never").strip().lower()
        if mode not in CONNECTIONS_READINESS_MODES:
            raise ValueError(
                f"'{CONNECTIONS_READINESS_KEY}' must be one of {', '.join(CONNECTIONS_READINESS_MODES)}, got {raw!r} "
                f"(agent '{self.namespace or ROOT_LABEL}')."
            )
        return mode

    def set_health_refresh(self, refresh: Callable[[], Awaitable[None]] | None) -> None:
        """Install what re-evaluates readiness at once, for a change a health poll would otherwise see late.

        Called after the default connection comes back while the agent is paused -- the pause its own
        disconnect caused ends on that re-evaluation rather than up to ``health_check_interval_seconds``
        later -- and, unless ``nats_connections_readiness`` is ``"never"``, whenever a named connection
        becomes bound or unbound.
        """
        self._health_refresh = refresh

    def _request_health_refresh(self, reason: str) -> None:
        """Run the installed refresh in a task of its own; a callback of nats-py must not wait for a poll."""
        if self._health_refresh is None or self._closing:
            return
        logger.debug("Agent '%s': readiness re-evaluated now: %s", self.namespace or ROOT_LABEL, reason)
        task = asyncio.ensure_future(self._health_refresh())
        task.add_done_callback(self._on_health_refresh_done)

    def _on_health_refresh_done(self, task: "asyncio.Future[None]") -> None:
        """Report a refresh that failed, naming the agent."""
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Agent '%s': re-evaluating readiness failed: %s",
                self.namespace or ROOT_LABEL,
                task.exception(),
                exc_info=task.exception(),
            )

    def _named_bound_changed(self, binding: _Binding) -> None:
        """A named connection became bound or unbound: re-evaluate readiness if the mode reads it."""
        if self._source is not None and self.connections_readiness != "never":
            self._request_health_refresh(f"named connection '{binding.link.name}' changed state")

    def _register_connection_gauge(self) -> None:
        """Create :data:`CONNECTION_BOUND_GAUGE` once, on the agent's meter, after telemetry is configured."""
        if self._connection_gauge_registered:
            return
        self._connection_gauge_registered = True
        agent = self.namespace or ROOT_LABEL

        def observe(_options: CallbackOptions) -> Iterable[Observation]:
            # Runs on the metrics reader's thread: reads the bindings, nothing more.
            return [
                Observation(1 if state.bound else 0, {"agent": agent, "connection": state.name}) for state in self.named_connection_states()
            ]

        agent_meter(self.namespace, __name__).create_observable_gauge(
            CONNECTION_BOUND_GAUGE,
            callbacks=[observe],
            description="1 while this named connection is bound and delivering, 0 otherwise",
            unit="1",
        )

    @cached_property
    def _permission_violations(self) -> Counter:
        """Counter of :data:`PERMISSION_VIOLATIONS_COUNTER`, created on first use (see ``_dead_lettered``)."""
        return agent_meter(self.namespace, __name__).create_counter(
            name=PERMISSION_VIOLATIONS_COUNTER,
            description="Permission violations the broker reported on this agent's named connections",
            unit="{violation}",
        )

    @staticmethod
    def _describe_error(link: _Link, exc: BaseException) -> str:
        """``exc`` as one short line for the readiness payload and the link's log lines: the URL redacted, no credential of the link in it."""
        text = f"{type(exc).__name__}: {exc}"
        if link.url:
            text = text.replace(link.url, redact_url(link.url))
        for key in ("password", "token", "nkeys_seed_str"):
            secret = link.connect_options.get(key)
            if isinstance(secret, str) and secret:
                text = text.replace(secret, "***")
        return text[:200]

    @property
    def consumer_tuning(self) -> ConsumerTuning | None:
        """JetStream consumer settings resolved by ``subscribe()``; ``None`` on Core NATS."""
        return self._tuning

    @property
    def connection_name(self) -> str:
        """Name this connection reports to the broker; ``""`` before the first connect."""
        return self._connection_name

    # ------------------------------------------------------------------
    # Managed subscription API
    # ------------------------------------------------------------------

    async def subscribe(self, topic_callbacks: dict[str, DeliveryCallback]) -> None:
        """Register all topic→callback mappings and start the background retry task.

        Returns immediately; connection and subscription happen in the background.

        **A client that is already paused registers and waits.** An agent marked down in the
        lifespan's client phase (spec sec. 9.1) is paused before its eventing endpoint reaches
        this call, when there is nothing yet to drain. Starting the retry loop anyway subscribed
        it, so a latched-down agent consumed events -- C4 held only for failures that happened
        after subscribing. The loop is started by :meth:`resume_consumption` instead, if the
        agent is ever released.
        """
        self._queue_group = self._resolve_queue_group()
        self._max_concurrent_runs = self._resolve_max_concurrent_runs()
        # Unset keeps one run per subscription (subscription_slots); set, the pair's guaranteed run
        # plus pool runs up to K (plan D7).
        self._binding.limit = self._max_concurrent_runs
        self._heartbeat_enabled = self._resolve_heartbeat_enabled()
        self._handler_timeout = self._resolve_handler_timeout()
        self._change_grace = self._resolve_change_grace()
        self._connections_readiness = self._resolve_connections_readiness()
        self._declared = dict(topic_callbacks)
        # What a named connection serves leaves the default connection (plan D10).
        default_topics = self._plan_named_bindings(topic_callbacks)
        self._topic_callbacks = default_topics
        if self.config.get("nats_use_jetstream", False):
            self._durables = self._resolve_durables(list(default_topics))
            self._tuning = self._resolve_consumer_tuning(list(default_topics))
        self._subscriptions_managed = True
        self._subscriptions_ready = False
        self._default_pairs = 1 if default_topics else 0
        self._register_pairs(self._default_pairs + len(self._named))
        if self._source is not None:
            self._register_connection_gauge()
        self._watch_source()
        if self._consumption_paused:
            logger.info(
                "Agent '%s' is degraded, so its %d subscription(s) are registered but not started",
                self.namespace or ROOT_LABEL,
                len(topic_callbacks),
            )
            return
        self._start_retry_task()
        self._start_named_links()

    def set_run_pool(self, pool: RunPool) -> None:
        """Install the process's pool of runs beyond each pair's guaranteed one, before ``subscribe()`` (plan D7)."""
        self._pool = pool

    def _register_pairs(self, wanted: int) -> None:
        """Hold ``wanted`` of this agent's (agent, connection) pairs in the pool; percentages are taken of the total."""
        for _ in range(wanted - self._pairs_registered):
            self._pool.add_pair()
        for _ in range(self._pairs_registered - wanted):
            self._pool.remove_pair()
        self._pairs_registered = wanted

    def set_connection_source(self, source: ConnectionSource | None) -> None:
        """Install the process's connection source, before ``subscribe()``; ``None`` keeps one connection (N6)."""
        self._source = source

    def _plan_named_bindings(self, topic_callbacks: dict[str, DeliveryCallback]) -> dict[str, DeliveryCallback]:
        """Ask the source which connections serve which of this agent's subjects; return what stays on the default one.

        Each binding gets a link of its own (plan D1) and its own run slots. A subject several
        connections serve is consumed on each of them, from each connection's own consumer.

        Raises:
            ValueError: a binding claims a subject this agent did not declare, or the agent both
                has named connections and maps handler results to topics (plan D4).
        """
        self._named = []
        if self._source is None:
            return dict(topic_callbacks)
        declared = tuple(topic_callbacks)
        self._claimed = self._claimed_subjects(declared)
        unclaimed = [subject for subject in declared if subject not in self._claimed]
        if unclaimed and self._resolve_unclaimed_policy() == "fail":
            raise ValueError(
                f"Agent '{self.namespace or ROOT_LABEL}' declares {', '.join(unclaimed)}, which the connection source does "
                "not claim, so no named connection will ever serve it. Declare only subjects the deployment's "
                "connections carry, or set 'nats_unclaimed_subjects = \"default_connection\"' to consume these on the "
                "agent's own connection."
            )
        served: set[str] = set()
        for spec in self._source.connections().values():
            jetstream = self._source.binding(self._queue_group, declared, spec)
            if jetstream is None:
                continue
            unknown = [subject for subject in jetstream.subjects if subject not in self._claimed]
            if unknown:
                raise ValueError(
                    f"Agent '{self.namespace or ROOT_LABEL}': the binding for connection '{spec.name}' serves "
                    f"{', '.join(unknown)}, which the source does not claim for this agent. A binding serves claimed "
                    "subjects only."
                )
            binding = self._new_named_binding(spec, jetstream)
            self._named.append(binding)
            served.update(jetstream.subjects)
        if self._named:
            self._refuse_result_publishing()
        logger.info(
            "Agent '%s' consumes on %d named connection(s) %s; %d claimed subject(s) served by none yet; %d unclaimed "
            "subject(s) on its default connection",
            self.namespace or ROOT_LABEL,
            len(self._named),
            ", ".join(binding.link.name for binding in self._named) or "-",
            len(self._claimed - served),
            len(unclaimed),
        )
        # Claimed subjects never go to the default connection, served now or not (plan D10).
        return {topic: callback for topic, callback in topic_callbacks.items() if topic not in self._claimed}

    def _claimed_subjects(self, declared: tuple[str, ...]) -> frozenset[str]:
        """The source's claim on this agent's subjects; refused unless it names declared subjects only."""
        if self._source is None:
            return frozenset()
        claimed = frozenset(self._source.claims(self._queue_group, declared))
        foreign = sorted(claimed - set(declared))
        if foreign:
            raise ValueError(
                f"Agent '{self.namespace or ROOT_LABEL}': the connection source claims {', '.join(foreign)}, which the "
                "agent does not declare. A claim names declared subjects only."
            )
        return claimed

    def _resolve_unclaimed_policy(self) -> str:
        """``nats_unclaimed_subjects``: ``"fail"`` (default) or ``"default_connection"`` (the explicit hybrid mode)."""
        raw = self.config.get("nats_unclaimed_subjects", None)
        policy = str(raw or "fail").strip().lower()
        if policy not in ("fail", "default_connection"):
            raise ValueError(f"'nats_unclaimed_subjects' must be 'fail' or 'default_connection', got {raw!r}.")
        return policy

    def _refuse_result_publishing(self) -> None:
        """Fail startup when an agent with named connections maps handler results to topics (plan D4).

        A result would go out on the default connection, so what a run on one connection
        produced would reach subjects outside that connection's account.
        """
        mapping = self.config.get("event_publishing.topic_mapping", {}) or {}
        if mapping:
            raise ValueError(
                f"Agent '{self.namespace or ROOT_LABEL}' consumes on named connections and maps handler results to "
                "topics ('event_publishing.topic_mapping'). A result would leave the connection its event arrived on, "
                "through the default connection, so this is refused. Remove the mapping."
            )

    def _start_named_links(self) -> None:
        """Connect and bind every named connection in a loop of its own; one failing never holds up another."""
        for binding in self._named:
            self._start_named_link(binding)

    def _start_named_link(self, binding: _Binding) -> None:
        """Start ``binding``'s connect-and-bind loop, unless one is running."""
        running = self._named_tasks.get(binding)
        if running is not None and not running.done():
            return
        task = asyncio.ensure_future(self._run_named_link(binding))
        task.add_done_callback(functools.partial(self._on_named_link_done, binding))
        self._named_tasks[binding] = task

    async def _run_named_link(self, binding: _Binding) -> None:
        """Connect ``binding``'s link and bind, retrying until it works.

        Never gives up: a named connection's stream or account may appear later (provisioning), and
        unlike the default connection its absence does not make the agent unready (plan D5).
        """
        delay = float(self.config.get("event_client_retry_delay", 5.0))
        attempt = 0
        while True:
            binding.link.permission_errors.clear()
            binding.bound = False
            try:
                await self._open_named_link(binding.link)
                if self._consumption_paused:
                    return
                binding.subscriptions.clear()
                await self._bind(binding)
                binding.bound = True
                binding.subscriptions_ready = True
                binding.last_error = ""
                binding.permission_denied = False
                self._named_bound_changed(binding)
                if binding.replaces is not None:
                    # New before old (spec 7.4): only now that this one delivers is the old one retired.
                    old, binding.replaces = binding.replaces, None
                    self._start_retirement(old, "replaced")
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                binding.subscriptions_ready = False
                denied = list(binding.link.permission_errors)
                binding.last_error = self._describe_error(binding.link, exc)
                binding.permission_denied = bool(denied)
                if denied:
                    # The broker reports a missing grant through error_cb and lets the request time
                    # out: that is permanent, not a slow broker (spec 7.9).
                    logger.error(
                        "Agent '%s': named connection '%s' was refused a permission (%s); retrying every %.0fs until "
                        "the deployment grants it",
                        self.namespace or ROOT_LABEL,
                        binding.link.name,
                        "; ".join(denied),
                        PERMISSION_RETRY_SECONDS,
                    )
                    await asyncio.sleep(PERMISSION_RETRY_SECONDS)
                    continue
                logger.warning(
                    "Agent '%s': named connection '%s' attempt %d failed, retrying in %.1fs: %s",
                    self.namespace or ROOT_LABEL,
                    binding.link.name,
                    attempt,
                    delay,
                    binding.last_error,
                )
                await asyncio.sleep(delay)

    def _on_named_link_done(self, binding: _Binding, task: asyncio.Task[None]) -> None:
        """Report a named-connection loop that died of anything but its cancellation, naming agent and connection."""
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Agent '%s': the loop of named connection '%s' failed: %s",
                self.namespace or ROOT_LABEL,
                binding.link.name,
                task.exception(),
                exc_info=task.exception(),
            )

    async def _open_named_link(self, link: _Link) -> None:
        """Open a named link, reconnecting forever once open, as the deployment's own pool did."""
        if link.nats_client is not None and not link.nats_client.is_closed:
            return
        base = self._resolve_connection_name()
        link.connection_name = ".".join(part for part in (base, link.name) if part)
        agent = self.namespace or ROOT_LABEL

        async def on_disconnected() -> None:
            if link.closing or self._closing:
                return
            for binding in self._named:
                if binding.link is link:
                    binding.subscriptions_ready = False
                    self._named_bound_changed(binding)
            logger.warning("Agent '%s': named connection '%s' lost its broker", agent, link.name)

        async def on_reconnected() -> None:
            # A plain subscription is restored by nats-py itself, and a push consumer delivers to
            # it again as soon as there is interest: nothing to re-bind, no JetStream request. Only
            # for a binding that had bound, though: one whose bind failed has no subscription to
            # restore, and reading it as bound left it never retried.
            for binding in self._named:
                if binding.link is link and binding.bound and not self._consumption_paused:
                    binding.subscriptions_ready = True
                    self._named_bound_changed(binding)
            logger.info("Agent '%s': named connection '%s' is back", agent, link.name)

        async def on_error(error: Exception) -> None:
            # Permission violations land here: a subject the deployment did not grant this account.
            if "permissions violation" in str(error).lower():
                link.permission_errors.append(str(error))
                self._permission_violations.add(1, {"agent": agent, "connection": link.name})
            # A refused login lands here too, and only here: with max_reconnect_attempts=-1,
            # nats.connect() retries it by itself and never returns, so the connect loop sees no
            # exception. Recorded so the state reads "retrying" with the reason, not "connecting".
            for binding in self._named:
                if binding.link is link and not binding.subscriptions_ready:
                    binding.last_error = self._describe_error(link, error)
            logger.error("Agent '%s': error on named connection '%s': %s", agent, link.name, self._describe_error(link, error))

        link.nats_client = await nats.connect(
            link.url,
            name=link.connection_name or None,
            max_reconnect_attempts=-1,
            reconnect_time_wait=self.config.get("nats_reconnect_time_wait", 2),
            connect_timeout=10,
            disconnected_cb=on_disconnected,
            reconnected_cb=on_reconnected,
            error_cb=on_error,
            **link.connect_options,
        )
        logger.info("Agent '%s' connected named connection '%s' as '%s'", agent, link.name, link.connection_name)

    # ------------------------------------------------------------------
    # Named connections at runtime (named-connections plan, step 4)
    # ------------------------------------------------------------------

    def _new_named_binding(self, spec: ConnectionSpec, jetstream: JetStreamBinding) -> _Binding:
        """A binding for ``spec``: a link of its own (plan D1), the declared callbacks, the agent's run limit."""
        binding = _Binding(
            link=_Link(name=spec.name, url=spec.url, connect_options=spec.connect_options()),
            jetstream=jetstream,
            topic_callbacks={subject: self._declared[subject] for subject in jetstream.subjects},
            spec=spec,
        )
        binding.limit = self._max_concurrent_runs
        return binding

    def _resolve_change_grace(self) -> float:
        """Return ``subscription_change_grace``: seconds a removed connection's runs get before revocation."""
        raw = self.config.get("subscription_change_grace", None)
        value = (
            float(self.config.get("event_client_drain_timeout", 30.0))
            if raw is None
            else self._read_float("subscription_change_grace", 0.0)
        )
        if value <= 0:
            raise ValueError(f"'subscription_change_grace' must be greater than 0, got {value}.")
        return value

    def _watch_source(self) -> None:
        """Ask the source to tell this client when its connections change, if the source can (``watch`` is optional)."""
        self._loop = asyncio.get_running_loop()
        watch = getattr(self._source, "watch", None) if self._source is not None else None
        if callable(watch):
            watch(self._connections_changed)

    def _connections_changed(self) -> None:
        """The source's notify: callable from any thread; hops onto this client's loop and coalesces."""
        loop = self._loop
        if loop is None or loop.is_closed() or self._closing:
            return
        loop.call_soon_threadsafe(self._schedule_reconcile)

    def _schedule_reconcile(self) -> None:
        """Run one reconcile at a time; a change notified while one runs makes it run once more."""
        if self._closing:
            return
        if self._reconcile_task is not None and not self._reconcile_task.done():
            self._reconcile_dirty = True
            return
        self._reconcile_task = asyncio.ensure_future(self._reconcile_loop())
        self._reconcile_task.add_done_callback(self._on_reconcile_done)

    def _on_reconcile_done(self, task: asyncio.Task[None]) -> None:
        """Report a reconcile that died of anything but its cancellation, naming the agent."""
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Agent '%s': applying a change of its named connections failed: %s",
                self.namespace or ROOT_LABEL,
                task.exception(),
                exc_info=task.exception(),
            )

    async def _reconcile_loop(self) -> None:
        while True:
            self._reconcile_dirty = False
            async with self._change_lock:
                await self._reconcile()
            if not self._reconcile_dirty:
                return

    async def _reconcile(self) -> None:
        """Bring the named bindings in line with what the source says now: add, replace, retire.

        Runs under the agent's change lock, so it never interleaves with a pause or a resume. The
        default connection's subjects stay as computed at startup: a subject a connection stops
        serving is not moved back to it, and a connection added later takes only what it claims.
        """
        source = self._source
        if source is None or self._closing:
            return
        agent = self.namespace or ROOT_LABEL
        declared = tuple(self._declared)
        wanted: dict[str, tuple[ConnectionSpec, JetStreamBinding]] = {}
        for spec in source.connections().values():
            jetstream = source.binding(self._queue_group, declared, spec)
            if jetstream is None:
                continue
            unknown = [subject for subject in jetstream.subjects if subject not in self._claimed]
            if unknown:
                logger.error(
                    "Agent '%s': connection '%s' skipped -- its binding serves %s, which the source does not claim",
                    agent,
                    spec.name,
                    ", ".join(unknown),
                )
                continue
            wanted[spec.name] = (spec, jetstream)

        current = {binding.link.name: binding for binding in self._named if not binding.superseded}
        created: list[_Binding] = []
        maps_results = bool(self.config.get("event_publishing.topic_mapping", {}) or {})
        for name, (spec, jetstream) in wanted.items():
            existing = current.get(name)
            if existing is not None and existing.spec == spec and existing.jetstream == jetstream:
                continue
            if existing is None and maps_results:
                logger.error(
                    "Agent '%s': connection '%s' not added -- the agent maps handler results to topics, and a result "
                    "would leave the connection its event arrived on (plan D4)",
                    agent,
                    name,
                )
                continue
            binding = self._new_named_binding(spec, jetstream)
            if existing is not None:
                existing.superseded = True
                if existing.bound:
                    binding.replaces = existing
                else:
                    # Never bound, so it serves nothing to keep: retired now, and what it was to
                    # replace -- the binding still delivering -- passes to the new one. Chaining
                    # instead left that one consuming for good once the middle one was retired (M3).
                    binding.replaces, existing.replaces = existing.replaces, None
                    await self._retire(existing, "changed again before it was bound")
            self._named.append(binding)
            created.append(binding)
            logger.info("Agent '%s': connection '%s' %s", agent, name, "changed; binding the new one" if existing else "added")
        self._register_pairs(self._default_pairs + len(self._named))
        if not self._consumption_paused:
            # Only the new ones: a binding that is already bound must not bind a second time.
            for binding in created:
                self._start_named_link(binding)

        for name, binding in current.items():
            if name not in wanted:
                # The binding it was to replace goes too: it is the one still delivering (M3).
                replaced, binding.replaces = binding.replaces, None
                await self._retire(binding, "removed")
                if replaced is not None:
                    await self._retire(replaced, "removed")

    def _start_retirement(self, binding: _Binding, reason: str) -> None:
        """Retire ``binding`` in the background, under the change lock (a replacement that just bound)."""

        async def retire() -> None:
            async with self._change_lock:
                await self._retire(binding, reason)

        task = asyncio.ensure_future(retire())
        self._retirements.add(task)
        task.add_done_callback(self._retirement_done)

    def _retirement_done(self, task: asyncio.Task[None]) -> None:
        self._retirements.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Agent '%s': retiring a named connection failed: %s",
                self.namespace or ROOT_LABEL,
                task.exception(),
                exc_info=task.exception(),
            )

    async def _retire(self, binding: _Binding, reason: str) -> None:
        """Stop consuming on ``binding``, give its runs the grace period, revoke the rest, close its link.

        Drained, not unsubscribed: what the client already holds still reaches a handler and is
        settled over this link. A run still going when the grace period ends is revoked -- never
        acked or nak'd (the delivery stays with the broker), its heartbeat stopped, its ``publish``
        refused, but not cancelled (spec 7.5). No consumer is deleted: it is the deployment's.
        """
        if binding not in self._named:
            return
        agent = self.namespace or ROOT_LABEL
        task = self._named_tasks.pop(binding, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        binding.subscriptions_ready = False
        binding.bound = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._change_grace
        await self._drain_subscriptions(deadline, binding)
        if binding.inflight:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(binding.idle.wait(), timeout=max(0.0, deadline - loop.time()))
        revoked = binding.inflight
        if revoked:
            binding.revoked = True
            for heartbeat in list(binding.heartbeats):
                heartbeat.cancel()
            logger.warning(
                "Agent '%s': connection '%s' %s with %d run(s) still in flight after %.1fs; revoked -- they are not "
                "settled and stay with the broker",
                agent,
                binding.link.name,
                reason,
                revoked,
                self._change_grace,
            )
        client = binding.link.nats_client
        if client is not None:
            binding.link.closing = True
            with contextlib.suppress(Exception):
                await client.close()
            binding.link.nats_client = None
        self._named.remove(binding)
        self._register_pairs(self._default_pairs + len(self._named))
        logger.info("Agent '%s': connection '%s' %s and closed (%d run(s) revoked)", agent, binding.link.name, reason, revoked)

    def _start_retry_task(self) -> None:
        """Start the background connect-and-subscribe loop, unless one is already running."""
        if self._retry_task is not None and not self._retry_task.done():
            return
        self._retry_task = asyncio.ensure_future(self._start_with_retry())
        self._retry_task.add_done_callback(self._on_retry_done)

    def _resolve_queue_group(self) -> str:
        """Return the queue group name, or raise if none can be derived.

        The name identifies the *agent*, not the process that hosts it: moving an agent
        into a different deployment group must not change which broker-side consumer it
        is (spec C1).

        A namespaced client therefore uses its namespace verbatim -- it was validated at
        construction, so it needs no checking or rewriting here -- and only the root namespace
        falls back to ``nats_queue_group`` then ``app_name`` -- which is what
        ``nats_queue_group`` is documented to be, "the queue group for the root namespace
        only". Without that branch every client in a process would resolve the same
        ``app_name``, and two co-hosted agents subscribing to one topic would form a
        single group and steal each other's messages: exactly one of them would see any
        given event.

        Resolved here rather than at subscription time so that a misconfiguration fails
        the caller's startup instead of disappearing into the background retry loop, which
        would retry a config error forever.

        Raises:
            ValueError: if neither key yields a non-empty name. NATS reads ``queue=""`` as
                "no queue group", which is precisely the every-replica-processes-every-message
                fan-out this exists to prevent, so there is no usable fallback.
            ValueError: if a configured name contains whitespace or a wildcard. ``nats-py``
                rejects such a queue name with ``BadSubjectError``, and an ``app_name`` like
                ``"My Service"`` was perfectly legal before subscriptions carried a queue group.
                A wildcard additionally reaches the default dead-letter subject, which is derived
                from this name. Reported here, naming the key and the value, rather than left to
                surface as a repeating ``BadSubjectError`` inside the background retry task. A
                *namespace* cannot reach this check: it is rejected at construction instead.
        """
        if self.namespace:
            return self.namespace

        for key in ("nats_queue_group", "app_name"):
            name = str(self.config.get(key, "") or "").strip()
            if not name:
                continue
            validate_subject_segment(name, source=f"The queue group (from '{key}')", subject=f"{name}.dead-letter")
            return name
        raise ValueError(
            "NATS subscriptions require a queue group: set 'nats_queue_group' or 'app_name'. "
            "Without one every replica processes every message."
        )

    # ------------------------------------------------------------------
    # Publishing (mode and subjects)
    # ------------------------------------------------------------------

    def _resolve_publish_mode(self) -> bool:
        """Whether this client publishes through JetStream. ``False`` means Core NATS.

        **Publishing and consuming are two decisions, and now have two keys.** They used to share
        ``nats_use_jetstream``: that key exists so *consumers* can be durable, and ``publish()``
        read the same flag -- so turning durability on for consumption silently made every
        outbound event a JetStream publish as well. Nobody chose that, and it is the wrong
        default for an event nothing needs to persist, where a Core publish is cheaper and
        cannot stall.

        ``nats_publish_mode`` is ``"core"`` or ``"jetstream"``. Unset, it follows
        ``nats_use_jetstream``, so no existing deployment changes.

        Raises:
            ValueError: for any other value, naming what each one means.
        """
        raw = self.config.get("nats_publish_mode", None)
        mode = str(raw or "").strip().lower()
        if not mode:
            return bool(self._use_jetstream)
        if mode not in ("core", "jetstream"):
            raise ValueError(
                f"Config key 'nats_publish_mode' must be 'core' or 'jetstream', got {raw!r}. 'core' is "
                "fire-and-forget: the message reaches whoever is subscribed at that moment and is not stored. "
                "'jetstream' stores it in the stream, so a consumer that was not running still receives it -- and "
                "it requires the subject to be one this client declares, see 'nats_publish_subjects'."
            )
        return mode == "jetstream"

    def _resolve_publish_subjects(self) -> set[str]:
        """The subjects this client may publish to, declared rather than discovered.

        A JetStream publish is a request/reply: the server stores the message and answers with a
        ``PubAck``. **If no stream captures the subject, no answer ever comes** -- the publish
        waits and times out, and ``EventPublishingService.publish_handler_event`` logs it and
        moves on. A Core NATS subscriber still sees the message, because the publish did go out,
        so a live listener looks healthy while nothing is stored and a JetStream consumer
        downstream receives nothing at all. That was the behaviour before this existed:
        ``_stream_subjects`` covered what the client *subscribed* to and nothing it published to.

        Two sources, because there are two ways an outbound subject is chosen:

        - ``event_publishing.topic_mapping`` -- the configured event-type-to-topic map, which is
          how a ``HandlerResult`` is routed and so where nearly every outbound subject is already
          written down;
        - ``nats_publish_subjects`` -- an explicit list, for a caller that passes ``topic=`` to
          ``publish_event`` directly and therefore never appears in the mapping.

        Every one is validated, because a wildcard published to is taken literally by NATS: the
        message lands on a subject with an asterisk in it and no subscriber to the pattern gets
        it.
        """
        subjects: set[str] = set()

        mapping = self.config.get("event_publishing.topic_mapping", {}) or {}
        if hasattr(mapping, "items"):
            for event_type, routing in mapping.items():
                topic = routing.get("topic") if hasattr(routing, "get") else None
                if topic:
                    source = f"The topic mapped from event type '{event_type}'"
                    subjects.add(validate_publish_subject(str(topic), source=source))

        declared = self.config.get("nats_publish_subjects", []) or []
        if isinstance(declared, list):
            for subject in declared:
                subjects.add(validate_publish_subject(str(subject), source="A subject in 'nats_publish_subjects'"))

        return subjects

    @property
    def publish_subjects(self) -> tuple[str, ...]:
        """The subjects this client declares it may publish to, sorted."""
        return tuple(sorted(self._publish_subjects))

    @property
    def publishes_via_jetstream(self) -> bool:
        """Whether an outbound event is stored in the stream or sent fire-and-forget."""
        return self._publish_via_jetstream

    # ------------------------------------------------------------------
    # Consumer settings (P3)
    # ------------------------------------------------------------------

    def _resolve_consumer_tuning(self, topics: list[str]) -> ConsumerTuning:
        """Read and validate the JetStream consumer settings (spec sec. 7.3).

        Resolved in ``subscribe()`` for the same reason the queue group is: a bad value
        must fail the caller's startup rather than disappear into the background retry
        task, which would retry a config error forever.

        **Each setting is opt-in.** An unset key is left out of the consumer and the server's
        default applies (NATS: ``ack_wait`` 30 s, ``max_ack_pending`` 1000, ``max_deliver``
        unlimited). The framework used to set 300 s / 16 / 5 on every consumer it created,
        which changed the server's behaviour for deployments that had configured nothing.

        Raises:
            ValueError: if a configured value is not a number, is zero, or is a negative value
                other than ``-1``.
        """
        ack_wait = self._read_optional_float("nats_ack_wait")
        if ack_wait is not None and ack_wait <= 0:
            raise ValueError(f"'nats_ack_wait' must be greater than 0, got {ack_wait}. It is the redelivery timeout, in seconds.")

        max_ack_pending = self._read_optional_int("nats_max_ack_pending")
        if max_ack_pending is not None and (max_ack_pending == 0 or max_ack_pending < -1):
            raise ValueError(f"'nats_max_ack_pending' must be a positive count or -1 for unlimited, got {max_ack_pending}.")

        max_deliver = self._read_optional_int("nats_max_deliver")
        if max_deliver is not None and (max_deliver == 0 or max_deliver < -1):
            raise ValueError(f"'nats_max_deliver' must be a positive count or -1 for unlimited, got {max_deliver}.")
        if max_deliver == -1:
            logger.warning(
                "'nats_max_deliver' is -1, so a message that keeps failing is redelivered forever "
                "and never reaches the dead-letter subject. Set a positive limit to bound it."
            )

        return ConsumerTuning(
            ack_wait=ack_wait,
            max_ack_pending=max_ack_pending,
            max_deliver=max_deliver,
            dead_letter_subject=self._resolve_dead_letter_subject(topics),
        )

    def _resolve_dead_letter_subject(self, topics: list[str]) -> str:
        """Return the subject a given-up-on message is republished to, or ``""`` if disabled.

        Defaults to ``"<queue group>.dead-letter"``, so it is derived from the agent's own
        identity exactly as the queue group is (C1) and moving the agent between deployment
        groups does not move its dead letters.

        Raises:
            ValueError: if the subject contains whitespace or a wildcard -- it is published
                to, and neither is publishable.
            ValueError: if one of this client's own subscriptions would deliver it back.
                Dead-lettering onto a subject the same client consumes turns one failure
                into an unbounded loop, and the loop only appears under load.
        """
        configured = self.config.get("nats_dead_letter_subject", None)
        subject = f"{self._queue_group}.dead-letter" if configured is None else str(configured).strip()
        if not subject:
            return ""

        if any(char.isspace() for char in subject) or "*" in subject or ">" in subject:
            raise ValueError(
                f"Dead-letter subject '{subject}' contains whitespace or a wildcard. "
                "It is a subject the client publishes to, so it must name exactly one."
            )
        for topic in topics:
            if self._subject_matches(topic, subject):
                raise ValueError(
                    f"Dead-letter subject '{subject}' is delivered by this client's own subscription "
                    f"to '{topic}', so a dead-lettered message would come straight back and be "
                    "dead-lettered again. Set 'nats_dead_letter_subject' outside the subscribed subjects."
                )
        return subject

    def _resolve_durables(self, topics: list[str]) -> dict[str, str]:
        """Map every topic to the durable consumer name that will carry it.

        A durable belongs to one filter subject, so each topic needs its own name and no
        two topics may resolve to the same one. Both failure modes are config errors and
        are raised here rather than left to surface as a JetStream API error inside the
        retry loop.

        Raises:
            ValueError: if ``nats_durable_name`` is set while more than one topic is
                subscribed, or if two topics sanitise to the same durable name.
        """
        configured = str(self.config.get("nats_durable_name", "") or "").strip()
        if configured and len(topics) > 1:
            raise ValueError(
                f"'nats_durable_name' is set to '{configured}' but {len(topics)} topics are subscribed. "
                "A JetStream durable filters one subject, so one name cannot serve them all. "
                "Remove the key to derive a durable per topic."
            )
        if configured and self.namespace:
            logger.warning(
                "Namespace '%s' is using the configured durable name '%s'. A durable is broker-side state "
                "shared by everything that binds to it, so unless this key is scoped per namespace, every "
                "namespace in this process binds to the same consumer and they consume each other's events.",
                self.namespace,
                configured,
            )

        durables: dict[str, str] = {}
        for topic in topics:
            name = configured or self._durable_for(topic)
            clash = next((other for other, existing in durables.items() if existing == name), None)
            if clash is not None:
                raise ValueError(
                    f"Topics '{clash}' and '{topic}' both resolve to durable name '{name}'. "
                    "NATS allows no '.', '*', '>' or whitespace in a consumer name, so those "
                    "characters are replaced with '_'. Rename one of the topics."
                )
            durables[topic] = name
        return durables

    def _durable_for(self, topic: str) -> str:
        """Derive a legal durable consumer name from a subject.

        NATS rejects ``.``, ``*``, ``>`` and whitespace in a consumer name, so the dotted
        subjects that are idiomatic in NATS -- ``orders.created`` -- cannot serve as one
        directly. Only the *topic* is rewritten: the namespace was validated against an
        alphabet a consumer name already accepts, so it is used as it was declared.

        A namespaced client puts its namespace in front, for the same reason its queue
        group is the namespace (C1): two co-hosted agents subscribing to one topic each
        need their own consumer, or the broker hands every message to whichever of them
        binds first. The root namespace keeps the bare ``<topic>-durable``, so a topic
        without ``.``, ``*``, ``>`` or whitespace finds the consumer 0.8 created under the same
        name. A dotted topic gets a name 0.8 did not use (``orders_created-durable``), but
        0.8's ``orders.created-durable`` is one the broker refuses, so no consumer is orphaned.

        The namespace and the topic share no reserved separator: root topic ``orders-created``
        and agent ``orders`` on ``created`` derive one name. :meth:`_ensure_consumer` refuses to
        bind a durable whose filter is another subject (S1), so such a clash fails loudly
        instead of delivering one subscription's messages to the other.

        For two agents, ``orders-orders_created-durable`` for namespace ``orders`` on topic
        ``orders.created`` reads back unambiguously because ``-`` is excluded from the
        namespace alphabet: the first ``-`` is always the boundary between the namespace and
        the topic. Were it allowed, ``orders-eu`` on ``created`` and ``orders`` on
        ``eu-created`` would name one consumer and two agents would share it.
        """
        prefix = f"{self.namespace}-" if self.namespace else ""
        return f"{prefix}{re.sub(r'[.*>\s]', '_', topic)}-durable"

    @staticmethod
    def _subject_matches(pattern: str, subject: str) -> bool:
        """Return whether a NATS subject filter would deliver a given subject.

        ``*`` matches exactly one token, ``>`` matches one or more and only as the final
        token. Used to prove the dead-letter subject is outside what this client consumes.
        """
        pattern_tokens = pattern.split(".")
        subject_tokens = subject.split(".")
        for index, token in enumerate(pattern_tokens):
            if token == ">":
                return index < len(subject_tokens)
            if index >= len(subject_tokens):
                return False
            if token != "*" and token != subject_tokens[index]:
                return False
        return len(pattern_tokens) == len(subject_tokens)

    def _read_float(self, key: str, default: float) -> float:
        raw = self.config.get(key, default)
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Config key '{key}' must be a number, got {raw!r}.") from exc

    def _read_optional_float(self, key: str) -> float | None:
        """Read ``key`` as a number, or ``None`` when it is not configured."""
        if self.config.get(key, None) is None:
            return None
        return self._read_float(key, 0.0)

    def _resolve_max_concurrent_runs(self) -> RunLimit | None:
        """Return ``nats_max_concurrent_runs`` -- a number of at least 1 or ``"N%"`` of the process's pairs -- or ``None``.

        Raises:
            ValueError: anything else, or a number below 1. It is how many deliveries a pair runs at once.
        """
        return RunLimit.parse("nats_max_concurrent_runs", self.config.get("nats_max_concurrent_runs", None), minimum=1)

    def _resolve_heartbeat_enabled(self) -> bool:
        """Return ``nats_heartbeat_enabled``: whether running JetStream deliveries report ``in_progress``.

        Raises:
            ValueError: if the value is not a boolean -- a string such as ``"false"`` would
                otherwise read as true and keep the heartbeat the operator meant to switch off.
        """
        value = self.config.get("nats_heartbeat_enabled", True)
        if not isinstance(value, bool):
            raise ValueError(f"'nats_heartbeat_enabled' must be true or false, got {value!r}.")
        return value

    def _resolve_handler_timeout(self) -> float | None:
        """Return ``nats_handler_timeout``: seconds one run may take, or ``None`` for no limit (plan D9).

        Raises:
            ValueError: anything but a number greater than 0. A boolean is refused rather than read as 1.
        """
        raw = self.config.get("nats_handler_timeout", None)
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):
            raise ValueError(f"'nats_handler_timeout' must be a number of seconds, got {raw!r}.")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"'nats_handler_timeout' must be a number of seconds, got {raw!r}.") from None
        if value <= 0:
            raise ValueError(f"'nats_handler_timeout' must be greater than 0, got {value}. Unset it for no limit.")
        return value

    def _read_optional_int(self, key: str) -> int | None:
        """Read ``key`` as an integer, or ``None`` when it is not configured."""
        if self.config.get(key, None) is None:
            return None
        return self._read_int(key, 0)

    def _read_int(self, key: str, default: int) -> int:
        raw = self.config.get(key, default)
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Config key '{key}' must be an integer, got {raw!r}.") from exc

    # ------------------------------------------------------------------
    # Connection identity (P6)
    # ------------------------------------------------------------------

    def _resolve_connection_name(self) -> str:
        """Return the name this connection reports to the broker (spec sec. 6).

        ``f"{namespace}.{group}.{pod}"``: which agent, which deployment group, which
        replica. It exists for attribution only -- ``nats.connect()`` was previously
        called with no ``name=`` at all, so every connection the framework opened showed
        up anonymous in ``/connz`` and a pod hosting several agents was unreadable.

        All three positions are always filled, using a placeholder where a value is
        absent, so the name cannot degenerate into ``"..pod-7"`` and "no group" stays
        distinguishable from "a group whose name is empty".

        **A standalone agent is named after its pod alone** -- no namespace and no group set.
        Neither exists for it, and a name reading ``<root>.<ungrouped>.pod`` would imply a
        grouping that is not there. If the pod cannot be told either, no name is sent at all,
        as before the namespace feature, rather than a name made only of a placeholder. The
        root of a *grouped* process keeps the full form: its group exists.

        **This value must never reach the queue group or the durable name.** It contains
        the pod, so a consumer identity derived from it would change on every restart and
        on every regrouping, which is precisely what C1 forbids. It is deliberately not
        stored anywhere those two are resolved from.
        """
        group = deployment_group()
        pod = pod_identity()
        if not self.namespace and group == UNGROUPED_LABEL:
            return "" if pod == UNKNOWN_POD_LABEL else pod
        return f"{self.namespace or ROOT_LABEL}.{group}.{pod}"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def on_startup(self) -> None:
        """Resolve the broker URL and credentials, so a bad one fails this agent's startup (M1, M2).

        Runs in the lifespan's client phase, before any connection is attempted. The connection
        itself is made in a background retry loop that retries every error forever -- a missing
        URL or a half-configured credential included, which are configuration errors no retry can
        fix. Resolved here, they are reported once, against this agent, as
        ``_resolve_queue_group`` reports its own.
        """
        self._nats_url = self._resolve_nats_url()
        self._connect_options = self._resolve_connect_options(self._nats_url)
        if self._jetstream_mismatch is not None:
            # Found by a connect that ran before this -- normally the actuator's first health poll,
            # which connects every client before any component starts. Probed again rather than
            # re-raised, so a retried startup (sec. 9.1) sees a server that has since been fixed.
            self._jetstream_mismatch = None
            await self.connect()
        self._started = True

    def set_fatal_handler(self, handler: FatalHandler) -> None:
        """Install what is called when this agent turns out, after startup, to be unable to run.

        Before startup has finished, such a failure is raised from :meth:`on_startup` instead, where
        the startup failure policy handles it. After it, nothing awaits the connection -- it happens
        in the retry loop or a health poll -- so it is handed to this handler, once.
        """
        self._fatal_handler = handler

    def _resolve_nats_url(self) -> str:
        """Return the configured ``nats_url``; outside development, refuse to run without one.

        Development falls back to :data:`DEVELOPMENT_NATS_URL` with a WARNING, so a broker on the
        developer's machine needs no configuration. Anywhere else there is no fallback: a pod
        pointed at ``localhost`` connects to nothing and never says so.

        Raises:
            ValueError: if ``nats_url`` is unset or empty and ``app_environment`` is not
                ``"development"``. Names the key, the environment, and how to set it.
        """
        url = str(self.config.get("nats_url", "") or "").strip()
        if url:
            return url
        environment = str(self.config.get("app_environment", "development"))
        if environment.lower() == "development":
            logger.warning(
                "Agent '%s': 'nats_url' is not set, connecting to %s because app_environment is 'development'. "
                "Set 'nats_url' for any other environment -- there, an unset one fails startup.",
                self.namespace or ROOT_LABEL,
                DEVELOPMENT_NATS_URL,
            )
            return DEVELOPMENT_NATS_URL
        prefix = self.config.envvar_prefix
        variable = f"{prefix}_NATS_URL" if prefix else "NATS_URL"
        raise ValueError(
            f"'event_bus' is 'nats' but 'nats_url' is not set (app_environment is {environment!r}). Outside "
            "development there is no default: localhost is rarely right in a container, and a client pointed at it retries "
            f"forever while the pod looks healthy. Set 'nats_url' in the group's settings.toml or as {variable}."
        )

    def _resolve_connect_options(self, nats_url: str) -> dict[str, Any]:
        """Return the credential and inbox arguments for ``nats.connect()`` (M2).

        One authentication method at most, each from its own keys:

        - ``nats_user`` and ``nats_password`` -- username and password (``user``, ``password``)
        - ``nats_token`` -- a token (``token``)
        - ``nats_creds_file`` -- a JWT + nkey credentials file, by path (``user_credentials``)
        - ``nats_nkey_seed`` -- an nkey seed, by value (``nkeys_seed_str``)

        Keeping them out of ``nats_url`` is the point: a URL carrying ``user:pass@`` makes the
        URL a secret, and every place that shows the URL has to know to strip it. The secret
        values belong in ``.secrets.toml`` or the environment; ``/status/env`` masks all four
        keys by name. The keys are read through this agent's view, so a group can give each
        agent its own account.

        ``nats_inbox_prefix`` replaces ``_INBOX`` for request/reply inboxes and JetStream API
        replies. An account restricted by subject permissions is usually not allowed
        ``_INBOX.>``, and without this every JetStream call it makes times out.

        Raises:
            ValueError: if more than one method is configured (``user:pass@`` in ``nats_url``
                counts as one), if only one of ``nats_user``/``nats_password`` is set, if
                ``nats_creds_file`` names no file, if the ``nkeys`` package that creds files
                and seeds need is not installed, or if ``nats_inbox_prefix`` is not a subject.
        """
        options: dict[str, Any] = {}
        methods: list[str] = []

        user = self._read_str("nats_user")
        password = self._read_str("nats_password")
        if bool(user) != bool(password):
            missing = "nats_password" if user else "nats_user"
            raise ValueError(f"'nats_user' and 'nats_password' go together, and '{missing}' is not set.")
        if user:
            options.update(user=user, password=password)
            methods.append("nats_user/nats_password")

        token = self._read_str("nats_token")
        if token:
            options["token"] = token
            methods.append("nats_token")

        creds_file = self._read_str("nats_creds_file")
        if creds_file:
            if not Path(creds_file).is_file():
                raise ValueError(f"'nats_creds_file' is '{creds_file}', which is not a file. Is the secret mounted there?")
            options["user_credentials"] = creds_file
            methods.append("nats_creds_file")

        seed = self._read_str("nats_nkey_seed")
        if seed:
            options["nkeys_seed_str"] = seed
            methods.append("nats_nkey_seed")

        if urlsplit(nats_url).username:
            methods.append("credentials in 'nats_url'")
        if len(methods) > 1:
            raise ValueError(
                f"NATS authentication is configured more than once: {', '.join(methods)}. The broker accepts one "
                "method per connection, and which one nats-py would send is not something to leave to chance. "
                "Keep exactly one."
            )
        if ("user_credentials" in options or "nkeys_seed_str" in options) and importlib.util.find_spec("nkeys") is None:
            raise ValueError(
                f"'{methods[0]}' needs the 'nkeys' package to sign the server's challenge, and it is not installed. "
                "Install it with: pip install nkeys"
            )

        inbox_prefix = self._read_str("nats_inbox_prefix")
        if inbox_prefix:
            validate_publish_subject(inbox_prefix, source="'nats_inbox_prefix'")
            if inbox_prefix.endswith("."):
                raise ValueError(f"'nats_inbox_prefix' is '{inbox_prefix}'. Leave out the trailing dot; nats-py adds it.")
            options["inbox_prefix"] = inbox_prefix

        logger.debug("Agent '%s' authenticates to NATS with %s", self.namespace or ROOT_LABEL, methods[0] if methods else "no credentials")
        return options

    def _read_str(self, key: str) -> str:
        return str(self.config.get(key, "") or "").strip()

    def _is_connected(self) -> bool:
        return self._nats_client is not None and not self._nats_client.is_closed and self._nats_client.is_connected

    async def connect(self) -> None:
        """Connect to the NATS server, registering disconnect/reconnect callbacks.

        Once ``subscribe()`` has registered the agent's subscriptions, the retry loop owns the
        connection: a call from anywhere else -- the health checker polls this -- only makes sure
        the loop runs. The loop connects and subscribes; while the agent is paused it connects and
        subscribes nothing, and ``resume_consumption`` subscribes once the agent is healthy again --
        which needs the connection, so a paused agent is connected too.
        """
        if self._nats_client is not None and not self._nats_client.is_closed:
            return
        if self._subscriptions_managed and not self._closing and asyncio.current_task() is not self._retry_task:
            self._start_retry_task()
            return

        if not self._nats_url:
            self._nats_url = self._resolve_nats_url()
            self._connect_options = self._resolve_connect_options(self._nats_url)
        nats_url = redact_url(self._nats_url)
        self._connection_name = self._resolve_connection_name()
        # Unlimited by default: with 5 attempts 2 s apart, an outage of about 10 s closed the
        # connection for good (review finding #10). _on_closed restarts it either way.
        reconnect_attempts = self.config.get("nats_max_reconnect_attempts", -1)
        try:
            self._nats_client = await nats.connect(
                self._nats_url,
                name=self._connection_name or None,
                max_reconnect_attempts=self._first_connect_attempts(reconnect_attempts),
                reconnect_time_wait=self.config.get("nats_reconnect_time_wait", 2),
                connect_timeout=10,
                disconnected_cb=self._on_disconnected,
                reconnected_cb=self._on_reconnected,
                closed_cb=self._on_closed,
                **self._connect_options,
            )
            # Read by nats-py on every reconnect attempt, so from here on the configured count governs.
            self._nats_client.options["max_reconnect_attempts"] = reconnect_attempts
            self._client = self._nats_client
            self._use_jetstream = self.config.get("nats_use_jetstream", False)
            self._publish_via_jetstream = self._resolve_publish_mode()
            self._publish_subjects = self._resolve_publish_subjects()
            if self._use_jetstream:
                self._js = self._nats_client.jetstream()
                await self._require_jetstream(nats_url)
                self._log_connected("with JetStream", nats_url)
            else:
                self._log_connected("(Core NATS)", nats_url)
        except JetStreamUnavailableError:
            raise
        except Exception as e:
            # Raised, not logged: the retry loop logs each failed attempt, and a caller outside it
            # decides for itself. Logging here as well doubled every connection failure.
            e.add_note(f"while connecting to NATS at {nats_url}")
            raise

    @staticmethod
    def _first_connect_attempts(reconnect_attempts: int) -> int:
        """``max_reconnect_attempts`` for the first ``nats.connect()``: bounded, whatever reconnects may do (N11).

        nats-py applies the count to the first connect as well, and with an unlimited count it
        retries a broker that is not there inside ``nats.connect()`` for ever: the call never
        returns, so neither the retry loop (``event_client_max_retries``, its WARNING per attempt)
        nor the health poll that connects before startup gets an answer, and startup hangs. The
        first connect therefore fails after two attempts and the retry loop decides what follows;
        a positive configured count is kept as it is.
        """
        return reconnect_attempts if reconnect_attempts > 0 else 1

    def _log_connected(self, mode: str, nats_url: str) -> None:
        """Log the connection; a standalone agent's line is the one it has always logged."""
        if self.namespace:
            logger.info("Connected to NATS server %s at %s as '%s'", mode, nats_url, self._connection_name)
        else:
            logger.info("Connected to NATS server %s at %s", mode, nats_url)

    async def _require_jetstream(self, nats_url: str) -> None:
        """Fail the connection if the server does not offer JetStream to this account.

        ``connection.jetstream()`` only builds a local context and asks the server nothing, so the
        fallback this replaces -- "JetStream initialization failed, falling back to Core NATS" --
        almost never fired, and when it did it silently dropped durability: no durable consumer,
        and no settlement, so every handler failure was lost. Nobody had decided that. The account
        info request is the cheapest call that the server answers only when JetStream is there.

        A timeout proves nothing either way and stays an ordinary connection failure, retried like
        any other. No responders (no JetStream on the server) and an API error (not enabled for the
        account) are answers, and they are final.

        Raises:
            JetStreamUnavailableError: the server answered, and JetStream is not available.
        """
        try:
            await self._js.account_info()  # type: ignore[union-attr]
        except (NoRespondersError, APIError) as exc:
            error = JetStreamUnavailableError(
                f"Agent '{self.namespace or ROOT_LABEL}' declares 'nats_use_jetstream = true', but the NATS server at "
                f"{nats_url} does not offer JetStream to this account ({type(exc).__name__}: {exc}). It is not retried "
                "and there is no fallback to Core NATS, which would drop durable consumers and acknowledgements "
                "without anyone deciding it. Enable JetStream on the server or account, or set "
                "'nats_use_jetstream = false' if Core NATS is intended."
            )
            await self._nats_client.close()  # type: ignore[union-attr]
            self._nats_client = None
            self._js = None
            self._client = None
            self._jetstream_mismatch = error
            self._report_fatal(error)
            raise error from exc

    def _report_fatal(self, error: BaseException) -> None:
        """Hand a fatal error found after startup to the installed handler, once."""
        if not self._started or self._fatal_handler is None or self._fatal_reported:
            return
        self._fatal_reported = True
        task = asyncio.ensure_future(self._fatal_handler(self.namespace, error))
        task.add_done_callback(self._on_fatal_handler_done)

    def _on_fatal_handler_done(self, task: asyncio.Task[None]) -> None:
        """Report a fatal handler that itself raised, naming the agent (C7)."""
        if task.cancelled() or task.exception() is None:
            return
        logger.error(
            "Agent '%s': handling a fatal transport error failed: %s",
            self.namespace or ROOT_LABEL,
            task.exception(),
            exc_info=task.exception(),
        )

    async def pause_consumption(self) -> None:
        """Drain this agent's subscriptions so its events redeliver elsewhere (C4).

        Drained rather than unsubscribed, for the same reason shutdown drains: a drain stops
        new deliveries while letting the ones already in the client's buffer reach their
        handler and be acknowledged over the connection that delivered them. An unsubscribe
        strands those, and every one of them redelivers.

        The connection stays open. See :meth:`IOClientBase.pause_consumption` for why closing
        it would make the pause permanent, and :meth:`health_check` for the other half of that.
        """
        # A resume still retrying is given up: the agent is degraded again, and the next resume starts afresh.
        await self._cancel_resume_retry()
        if self._consumption_paused:
            return
        self._consumption_paused = True
        self._subscriptions_ready = False
        async with self._change_lock:  # never interleaved with a connection change (spec 7.2)
            timeout = float(self.config.get("event_client_drain_timeout", 30.0))
            deadline = asyncio.get_running_loop().time() + timeout
            for binding in self._named:
                binding.subscriptions_ready = False
                await self._drain_subscriptions(deadline, binding)
            if self._nats_client is not None:
                await self._drain_subscriptions(deadline)
            for binding in self._named:
                await self._await_inflight(deadline, binding)
            if self._nats_client is not None:
                await self._await_inflight(deadline)
        logger.error(
            "Agent '%s' stopped consuming: its subscriptions are drained while it is degraded, so its events "
            "redeliver to a healthy replica",
            self.namespace or ROOT_LABEL,
        )

    async def resume_consumption(self) -> None:
        """Re-subscribe this agent's topics after its health checks pass again.

        **A failed re-subscribe is retried here, in the background** (M2, plan D2). The
        supervisor resumes on the transition to healthy only, and a paused client reports
        healthy, so nothing would ever call this again: the agent stayed off its topics with
        every check green. The retry backs off from ``event_client_retry_delay`` up to
        :data:`RESUME_RETRY_MAX_DELAY` with a WARNING per failed attempt, leaves readiness as it
        is, and is cancelled by a pause and by :meth:`close`. Subscriptions a failed attempt
        made are dropped first, so a retry never leaves duplicates.
        """
        if not self._consumption_paused:
            return
        self._consumption_paused = False
        if not self._subscriptions_managed:
            return
        # Each named connection re-binds in its own loop, over its still-open link.
        async with self._change_lock:
            self._start_named_links()
        if self._nats_client is None:
            # Paused before it ever connected -- subscribe() registered the topics and waited.
            # The retry loop is what connects and subscribes; a loop still running picks up the
            # cleared flag by itself.
            self._start_retry_task()
            return
        delay = float(self.config.get("event_client_retry_delay", 5.0))
        if not await self._try_resume(1, delay):
            self._resume_retry = asyncio.ensure_future(self._retry_resume(delay))
            self._resume_retry.add_done_callback(self._on_resume_retry_done)

    async def _try_resume(self, attempt: int, next_delay: float) -> bool:
        """Subscribe the default connection's topics once; on failure drop what was made and stay paused."""
        try:
            await self._subscribe_all()
        except Exception as exc:
            await self._drop_subscriptions()
            self._consumption_paused = True
            logger.warning(
                "Agent '%s' could not resume consuming (attempt %d), retrying in %.1fs: %s",
                self.namespace or ROOT_LABEL,
                attempt,
                next_delay,
                self._describe_error(self._link, exc),
            )
            return False
        self._consumption_paused = False
        self._subscriptions_ready = True
        logger.info("Agent '%s' resumed consuming: %d subscription(s) restored", self.namespace or ROOT_LABEL, len(self._subscriptions))
        return True

    async def _retry_resume(self, delay: float) -> None:
        """Retry :meth:`_try_resume` with a doubling delay until it succeeds; cancelled by a pause or close."""
        attempt = 1
        while not self._closing:
            await asyncio.sleep(delay)
            attempt += 1
            delay = min(delay * 2, RESUME_RETRY_MAX_DELAY)
            if await self._try_resume(attempt, delay):
                # The named connections' loops saw the flag back up after the first failure and stopped.
                async with self._change_lock:
                    self._start_named_links()
                return

    async def _cancel_resume_retry(self) -> None:
        """Stop a resume still retrying, if one is."""
        retry, self._resume_retry = self._resume_retry, None
        if retry is not None and not retry.done():
            retry.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retry

    def _on_resume_retry_done(self, task: asyncio.Task[None]) -> None:
        """Report a resume retry that died of anything but its cancellation, naming the agent."""
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Agent '%s': retrying the resume failed: %s",
                self.namespace or ROOT_LABEL,
                self._describe_error(self._link, task.exception()),  # type: ignore[arg-type]
            )

    async def _drop_subscriptions(self) -> None:
        """Unsubscribe whatever the default connection holds, so the next attempt starts from none."""
        for sub in self._subscriptions:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
        self._subscriptions.clear()

    async def close(self) -> None:
        """Stop consuming, let in-flight handlers finish, then close the connection.

        The order is load-bearing. An acknowledgement travels over the same connection
        that delivered the message, so closing the connection while a handler is still
        running strands that acknowledgement and guarantees redelivery. Subscriptions
        are drained first, in-flight handlers then get until ``event_client_drain_timeout``
        to finish, and only then is the connection closed. The timeout bounds the whole
        sequence, so shutdown stays inside a pod's termination grace period.
        """
        self._subscriptions_ready = False
        self._closing = True

        # A change in progress is cancelled, not finished: everything it left is cleaned up below.
        for change in [self._reconcile_task, *self._retirements]:
            if change is not None and not change.done():
                change.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await change

        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task
        await self._cancel_resume_retry()
        for task in list(self._named_tasks.values()):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._named_tasks.clear()

        self._register_pairs(0)
        # One budget for every connection: stop all deliveries, then wait for every run, then close.
        timeout = float(self.config.get("event_client_drain_timeout", 30.0))
        deadline = asyncio.get_running_loop().time() + timeout
        for binding in self._named:
            binding.subscriptions_ready = False
            if binding.link.nats_client is not None:
                await self._drain_subscriptions(deadline, binding)
        if self._nats_client is not None:
            await self._drain_subscriptions(deadline)
        for binding in self._named:
            await self._await_inflight(deadline, binding)
        if self._nats_client is not None:
            await self._await_inflight(deadline)

        for binding in self._named:
            client = binding.link.nats_client
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.close()
                binding.link.nats_client = None
        if self._nats_client is not None:
            await self._nats_client.close()
            self._nats_client = None
            self._js = None
            self._client = None

    # ------------------------------------------------------------------
    # Internal -- shutdown
    # ------------------------------------------------------------------

    async def _drain_subscriptions(self, deadline: float, binding: _Binding | None = None) -> None:
        """Stop new deliveries while letting already-queued messages reach their handler.

        Falls back to an immediate unsubscribe if a drain fails or outlives the deadline,
        so one stuck subscription cannot hold up shutdown.
        """
        binding = binding or self._binding
        for sub in binding.subscriptions:
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            try:
                await asyncio.wait_for(sub.drain(), timeout=remaining)
            except TimeoutError:
                logger.warning("Draining a NATS subscription outlived the shutdown deadline; unsubscribing instead")
                await self._force_unsubscribe(sub)
            except Exception as e:
                logger.warning("Failed to drain a NATS subscription (%s); unsubscribing instead", e)
                await self._force_unsubscribe(sub)
        binding.subscriptions.clear()

    @staticmethod
    def _decode_message(msg: Any, topic: str) -> CloudEvent[Any] | None:
        """Decode a broker message into a CloudEvent, or ``None`` if the payload is unusable.

        Kept separate from dispatch because the two failures have opposite dispositions. A
        payload that cannot become a CloudEvent will not become one on redelivery either, so
        it is terminal for that message rather than retryable: P2 terms here, and naks a
        dispatch failure (spec sec. 7.2).
        """
        try:
            event_data = json.loads(msg.data.decode())
            return CloudEvent(**event_data)
        except ValidationError as ex:
            # Where and how it failed, not str(ex): that embeds the payload's values (B2).
            logger.error("Discarding unparseable message on topic '%s': %s", topic, describe_validation_errors(ex.errors()))
            return None
        except Exception as ex:
            # JSON, UTF-8 and mapping errors name a position, a byte or a type, not the payload.
            logger.error("Discarding unparseable message on topic '%s': %s: %s", topic, type(ex).__name__, ex)
            return None

    @staticmethod
    async def _force_unsubscribe(sub: Any) -> None:
        with contextlib.suppress(Exception):
            await sub.unsubscribe()

    async def _await_inflight(self, deadline: float, binding: _Binding | None = None) -> None:
        """Give handlers that are still running a bounded chance to finish."""
        binding = binding or self._binding
        if binding.inflight == 0:
            return

        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        logger.debug("Waiting up to %.1fs for %d in-flight NATS handler(s)", remaining, binding.inflight)
        try:
            await asyncio.wait_for(binding.idle.wait(), timeout=remaining)
        except TimeoutError:
            logger.error(
                "Shutdown deadline reached with %d NATS handler(s) still running; their messages will be redelivered",
                binding.inflight,
            )

    def _enter_handler(self) -> None:
        self._binding.enter_run()

    def _exit_handler(self) -> None:
        self._binding.exit_run()

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, topic: str, event: CloudEvent[Any], routing_key: str | None = None) -> None:
        """Publish a CloudEvent to a topic.

        Args:
            topic: The topic, used for event routing.
            event: The CloudEvent to publish.
            routing_key: Ignored — NATS does not use routing keys.

        Raises:
            DeliveryRevokedError: called from a run whose connection was removed under it.
        """
        running_on = _CURRENT_BINDING.get()
        if running_on is not None and running_on.revoked:
            raise DeliveryRevokedError()
        client = await self.client

        try:
            event_data = json.dumps(dict(event)).encode()

            if self._publish_via_jetstream and client.jetstream():
                ack = await client.jetstream().publish(topic, event_data)
                logger.debug("Published event to JetStream topic '%s' (seq: %d): %s", topic, ack.seq, event.id)
            else:
                await client.publish(topic, event_data)
                logger.debug("Published event to Core NATS topic '%s': %s", topic, event.id)

        except Exception as e:
            logger.error("Failed to publish event to topic '%s': %s", topic, str(e))
            raise

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ComponentHealth:
        """Return healthy only when connected and all managed subscriptions are active.

        **A paused client reports healthy.** The pause is a consequence of the agent being
        degraded (C4), not a cause of it, and the check that actually failed is still in the
        readiness payload saying so. Reporting the pause as unhealthy would make it
        self-sustaining: the agent could never be seen to recover, so consumption would never
        resume, and a transient Redis outage would take the agent off its topics permanently.
        """
        if self._jetstream_mismatch is not None:
            return ComponentHealth(status="unhealthy", message=str(self._jetstream_mismatch))
        if not self._is_connected():
            return ComponentHealth(status="unhealthy", message="NATS client not connected")
        if self._consumption_paused:
            return ComponentHealth(status="healthy", message="connected; consumption paused while this agent is degraded")
        if self._subscriptions_managed and not self._subscriptions_ready:
            return ComponentHealth(status="unhealthy", message="connected but subscriptions not yet established")
        connected = self._nats_client.connected_url  # type: ignore[union-attr]
        server_info = redact_url(connected.geturl()) if connected is not None else "an unknown server"
        sub_info = f" ({len(self._subscriptions)} subscriptions active)" if self._subscriptions else ""
        return ComponentHealth(status="healthy", message=f"Connected to NATS server at {server_info}{sub_info}")

    # ------------------------------------------------------------------
    # Internal — retry loop
    # ------------------------------------------------------------------

    async def _start_with_retry(self) -> None:
        max_retries: int = self.config.get("event_client_max_retries", -1)
        delay: float = float(self.config.get("event_client_retry_delay", 5.0))
        attempt = 0
        while True:
            try:
                await self._connect_and_subscribe()
                if self._consumption_paused:
                    return
                self._subscriptions_ready = True
                logger.info("NATSClient connected and subscribed successfully")
                return
            except JetStreamUnavailableError:
                # Final, not transient: retrying would log the same answer forever.
                self._subscriptions_ready = False
                raise
            except Exception as e:
                attempt += 1
                self._subscriptions_ready = False
                if max_retries != -1 and attempt > max_retries:
                    raise
                logger.warning("NATSClient attempt %d failed, retrying in %.1fs: %s", attempt, delay, self._describe_error(self._link, e))
                await asyncio.sleep(delay)

    def _on_retry_done(self, task: asyncio.Task[None]) -> None:
        """Report a retry task that gave up, naming the agent whose transport it was (C7).

        The agent is in the message because this is the one record that a namespace has
        stopped consuming while the pod stays healthy: the task is detached, so nothing
        awaits it, and without this the failure is a task exception nobody retrieves.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            # No traceback: its last line is str(exc) again, unredacted (N3).
            logger.error(
                "Agent '%s' permanently failed to connect to NATS after exhausting retries: %s",
                self.namespace or ROOT_LABEL,
                self._describe_error(self._link, exc),
            )

    async def _connect_and_subscribe(self) -> None:
        await self.connect()
        # Clean up any partial subscriptions from a previous failed attempt
        await self._drop_subscriptions()
        if self._consumption_paused:
            # Paused while this loop was still connecting: stay connected, subscribe nothing.
            # resume_consumption() subscribes over this connection if the agent is released.
            logger.info("Agent '%s' connected while degraded; not subscribing", self.namespace or ROOT_LABEL)
            # The pause may have been this connection's absence -- an agent that started before its
            # broker. Re-evaluate now, so it resumes on this connect rather than one health interval later.
            self._request_health_refresh("the default connection is up while the agent is paused")
            return
        await self._subscribe_all()

    async def _subscribe_all(self, binding: _Binding | None = None) -> None:
        """Provision the stream once, then subscribe every topic -- or, in binding mode, bind.

        Shared by first connect and by reconnect, so a stream that was recreated while the
        client was away -- or a failover to a cluster peer that never had it -- is restored
        before any consumer tries to bind to it. A binding-mode binding provisions nothing.
        """
        binding = binding or self._binding
        if binding.jetstream is not None:
            await self._bind(binding)
            return
        if self._use_jetstream:
            await self._provision_stream()
        for topic, callback in binding.topic_callbacks.items():
            await self._subscribe_one(topic, callback, binding)

    def _settles(self, binding: _Binding) -> bool:
        """Whether deliveries on ``binding`` are JetStream deliveries that can be settled."""
        return binding.jetstream is not None or self._use_jetstream

    # ------------------------------------------------------------------
    # Internal -- JetStream stream and consumer
    # ------------------------------------------------------------------

    def _stream_subjects(self) -> set[str]:
        """Subjects the stream must carry for this client's consumers to bind.

        Each topic is included literally, because that is what a consumer filters on. The
        previous code stored only ``f"{topic}.>"``, which does *not* cover ``topic`` itself,
        so an explicitly created consumer filtering ``orders.created`` would be rejected by
        a stream that only captured ``orders.created.>``. The wildcard form is kept as well,
        so a stream provisioned by an earlier version keeps every subject it already had.
        """
        subjects: set[str] = set()
        for topic in self._topic_callbacks:
            subjects.add(topic)
            if "*" not in topic and ">" not in topic:
                subjects.add(f"{topic}.>")
        if self._tuning and self._tuning.dead_letter_subject:
            subjects.add(self._tuning.dead_letter_subject)
        # What this client publishes, when it publishes durably. Without these the stream has
        # no subject matching the outbound message, so the publish waits for an acknowledgement
        # that never comes -- see _resolve_publish_subjects.
        if self._publish_via_jetstream:
            subjects |= self._publish_subjects
        return subjects

    async def _provision_stream(self) -> None:
        """Create the stream, or widen an existing one to cover every needed subject.

        Called once per (re)connect rather than once per topic. The previous per-topic
        ``add_stream`` could only ever create the stream for whichever topic happened to be
        subscribed first: every later call hit "stream name already in use" and was logged
        as a warning, leaving the remaining topics uncaptured.

        Widening is additive -- subjects already on the stream are kept -- so this never
        removes a subject an operator added. A failure to update is logged rather than
        raised: the consumer that needs the subject fails immediately afterwards, and that
        failure names the consumer as well as the stream.
        """
        js = self._nats_client.jetstream()  # type: ignore[union-attr]
        stream = self.config.get("nats_stream_name", "EVENTS")
        wanted = self._stream_subjects()

        try:
            info = await js.stream_info(stream)
        except NotFoundError:
            await js.add_stream(name=stream, subjects=sorted(wanted))
            logger.info("Created JetStream stream '%s' with subjects %s", stream, sorted(wanted))
            return

        # Not a set difference: a stream an operator provisioned as 'orders.>' already captures
        # 'orders.created', and asking the server to add the literal is refused as an overlap --
        # which used to be reported as "consumers will fail to bind" when they bind fine.
        existing = set(info.config.subjects or [])
        missing = {subject for subject in wanted if not any(subject_is_covered_by(subject, pattern) for pattern in existing)}
        if not missing:
            return

        info.config.subjects = sorted(existing | missing)
        try:
            await js.update_stream(info.config)
            logger.info("Added subject(s) %s to existing JetStream stream '%s'", sorted(missing), stream)
        except Exception as exc:
            logger.error(
                "JetStream stream '%s' does not carry subject(s) %s and could not be updated (%s); "
                "consumers filtering those subjects will fail to bind",
                stream,
                sorted(missing),
                exc,
            )

    def _consumer_config(self, topic: str, durable: str) -> js_api.ConsumerConfig:
        """Build the durable consumer this client wants for one topic.

        ``deliver_subject`` is derived from the durable name rather than taken from a fresh
        inbox, because every replica must bind to the *same* one: a push consumer delivers
        to one subject, and its deliver group is the queue group on that subject. Two
        replicas generating random inboxes would create two different consumers, which is
        the fan-out P1 removed.
        """
        tuning = self._tuning or self._resolve_consumer_tuning(list(self._topic_callbacks))
        return js_api.ConsumerConfig(
            durable_name=durable,
            filter_subject=topic,
            deliver_subject=f"_DELIVER.{durable}",
            deliver_group=self._queue_group or None,
            ack_policy=js_api.AckPolicy.EXPLICIT,
            ack_wait=tuning.ack_wait,
            max_ack_pending=tuning.max_ack_pending,
            max_deliver=tuning.max_deliver,
        )

    async def _ensure_consumer(self, topic: str, durable: str) -> js_api.ConsumerConfig:
        """Return the consumer config to bind to, creating the durable if it is absent.

        An existing consumer is left exactly as it is, and the difference is reported
        instead. A durable's name, filter subject and deliver group are broker-side state
        that the stream's pending and redelivery bookkeeping hangs off; rewriting it in
        place either replays messages the consumer already handled or skips ones it never
        saw. That makes reconfiguration a migration -- delete the consumer deliberately --
        rather than something a rolling restart should do silently.

        The returned config is the server's, so replicas that start after the first one
        join the deliver group already in force rather than defining a competing one.
        """
        js = self._nats_client.jetstream()  # type: ignore[union-attr]
        stream = self.config.get("nats_stream_name", "EVENTS")
        desired = self._consumer_config(topic, durable)

        try:
            info = await js.consumer_info(stream, durable)
        except NotFoundError:
            await js.add_consumer(stream, config=desired)
            logger.info(
                "Created JetStream consumer '%s' on stream '%s': filter '%s', deliver group '%s', "
                "ack_wait %s, max_ack_pending %s, max_deliver %s",
                durable,
                stream,
                topic,
                desired.deliver_group,
                # Unset is None, which '%.1f' cannot render: the whole line was lost (N10).
                "server default" if desired.ack_wait is None else f"{desired.ack_wait:.1f}s",
                desired.max_ack_pending,
                desired.max_deliver,
            )
            return desired

        filters = [info.config.filter_subject] if info.config.filter_subject else list(info.config.filter_subjects or [])
        if filters != [topic]:
            # Another subscription's consumer under this name (S1): binding to it would deliver
            # that subscription's messages here. Not renamed -- the durable's pending state is
            # broker-side and belongs to the subscription that made it.
            raise JetStreamBindingError(
                f"JetStream consumer '{durable}' on stream '{stream}' filters {', '.join(repr(f) for f in filters) or 'nothing'}, "
                f"not '{topic}', so it belongs to another subscription and is not bound. A root topic and an agent's "
                f"topic can derive one durable name (root 'orders-created' and agent 'orders' on 'created'): rename one "
                f"of the topics, or delete the consumer if it is stale."
            )

        legacy = not info.config.deliver_group
        if legacy:
            # A consumer from before 0.9: created by js.subscribe with an inbox deliver subject and
            # no deliver group. Still used exactly as it is -- recreating it would replay or gap --
            # but only one replica can bind to it, so the form is on its way out.
            logger.warning(
                "DEPRECATED: JetStream consumer '%s' on stream '%s' was created without a deliver group, the form "
                "used before 0.9 (it delivers to '%s'). It is still used as it is, but this form will not be supported "
                "in a future release: only one replica can consume from it. Delete it during a maintenance window and "
                "the framework recreates it so that every replica shares it.",
                durable,
                stream,
                info.config.deliver_subject,
            )
        # The missing deliver group is what the deprecation already says; not repeated as drift.
        drift = self._consumer_drift(info.config, desired, ignore=("deliver_group",) if legacy else ())
        if drift:
            logger.warning(
                "JetStream consumer '%s' on stream '%s' already exists with different settings (%s). "
                "It is left unchanged: changing a durable's deliver group is a migration, "
                "not a restart. Delete the consumer during a maintenance window to apply the new values.",
                durable,
                stream,
                "; ".join(drift),
            )
        return info.config

    @staticmethod
    def _consumer_drift(actual: js_api.ConsumerConfig, desired: js_api.ConsumerConfig, *, ignore: tuple[str, ...] = ()) -> list[str]:
        """Name the settings on which an existing consumer differs from the wanted one.

        A setting the configuration leaves unset asks for nothing, so it cannot differ: the
        broker's value, default or not, is what the deployment chose by not choosing.
        """
        return [
            f"{field}: broker has {getattr(actual, field)!r}, config asks for {getattr(desired, field)!r}"
            # Not filter_subject: a consumer filtering another subject is refused before this (S1).
            for field in ("deliver_group", "ack_wait", "max_ack_pending", "max_deliver")
            if field not in ignore and getattr(desired, field) is not None and getattr(actual, field) != getattr(desired, field)
        ]

    # ------------------------------------------------------------------
    # Internal — per-topic subscription
    # ------------------------------------------------------------------

    async def _subscribe_one(self, topic: str, callback: DeliveryCallback, binding: _Binding | None = None) -> None:
        binding = binding or self._binding
        client = await self.client
        message_handler = self._message_handler(binding, topic, topic, callback)

        try:
            if self._use_jetstream and client.jetstream():
                stream_name = self.config.get("nats_stream_name", "EVENTS")
                durable_name = self._durables.get(topic) or self._durable_for(topic)

                # subscribe_bind rather than subscribe, because the queue group cannot reach a
                # durable any other way: nats-py rejects a queue subscription whose durable name
                # differs from the queue name, and the durable is per topic while the queue group
                # is per agent. Binding to a consumer we create ourselves also puts ack_wait,
                # max_ack_pending and max_deliver where the broker can enforce them.
                consumer_config = await self._ensure_consumer(topic, durable_name)
                # The broker's value, not nats_ack_wait: an existing consumer keeps its own.
                binding.ack_waits[topic] = consumer_config.ack_wait or SERVER_DEFAULT_ACK_WAIT
                sub = await client.jetstream().subscribe_bind(
                    stream=stream_name,
                    config=consumer_config,
                    consumer=durable_name,
                    cb=message_handler,
                    manual_ack=True,
                )
                if self.namespace:
                    logger.info(
                        "Subscribed to JetStream topic '%s' via durable '%s' in deliver group '%s'",
                        topic,
                        durable_name,
                        consumer_config.deliver_group or "<none>",
                    )
                else:
                    logger.info("Subscribed to JetStream topic '%s'", topic)
            else:
                sub = await client.subscribe(topic, queue=self._queue_group, cb=message_handler)
                if self.namespace:
                    logger.info("Subscribed to Core NATS topic '%s' in queue group '%s'", topic, self._queue_group)
                else:
                    logger.info("Subscribed to Core NATS topic '%s'", topic)

            binding.subscriptions.append(sub)

        except Exception as e:
            logger.error("Failed to subscribe to topic '%s': %s", topic, str(e))
            raise

    # ------------------------------------------------------------------
    # Internal -- binding mode (named-connections plan, step 2)
    # ------------------------------------------------------------------

    async def _bind(self, binding: _Binding) -> None:
        """Consume through the deployment's consumer, exactly as its binding describes it.

        One consumer carries every subject the binding serves, delivered to its deliver subject
        in its deliver group. The subscription is a plain one on that subject: the messages are
        JetStream deliveries all the same (their reply subject is the ``$JS.ACK`` one), so they
        are settled and heartbeated as usual, and no JetStream API request is needed to receive
        them. With ``manage_consumer`` unset the client sends none at all -- the account may
        only be allowed to receive and acknowledge.

        Raises:
            JetStreamBindingError: the binding manages its consumer and its stream does not
                exist. The stream belongs to whoever provisions the deployment; it is never
                created here.
        """
        spec = binding.jetstream
        if spec is None:
            raise RuntimeError("_bind needs a binding-mode binding")
        client = binding.link.nats_client
        if client is None:
            raise RuntimeError("binding mode needs a connected link")
        if spec.manage_consumer:
            await self._ensure_bound_consumer(client, spec)
        for topic in spec.subjects:
            binding.ack_waits[topic] = spec.ack_wait
        handler = self._message_handler(binding, spec.deliver_subject, None)
        sub = await client.subscribe(spec.deliver_subject, queue=spec.deliver_group, cb=handler)
        # The broker refuses a subscription the account may not make asynchronously, through
        # error_cb, so subscribe() returned and the binding read as bound for good (M4). The round
        # trip makes any refusal arrive first; one naming this subject fails the attempt, and the
        # connect loop retries it as a permission error. Compared lowercased: nats-py lowercases the
        # whole -ERR line, the subject in it included.
        await client.flush()
        subject = spec.deliver_subject.lower()
        refused = [error for error in binding.link.permission_errors if subject in error.lower()]
        if refused:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
            raise PermissionError(f"the broker refused the subscription to '{spec.deliver_subject}': {refused[0]}")
        binding.subscriptions.append(sub)
        logger.info(
            "Agent '%s' bound to consumer '%s' on stream '%s' (deliver subject '%s', group '%s', subjects %s)",
            self.namespace or ROOT_LABEL,
            spec.durable,
            spec.stream,
            spec.deliver_subject,
            spec.deliver_group,
            ", ".join(spec.filter_subjects),
        )

    async def _ensure_bound_consumer(self, client: NatsClient, spec: JetStreamBinding) -> None:
        """Create or update a binding's consumer; recreate it when the broker refuses the update.

        Unlike the agent's own consumers, which are never rewritten, a managed binding's consumer
        follows its binding: the deployment that owns the values changed them. A consumer whose
        immutable fields differ cannot be updated in place, so it is deleted and created again --
        and its unacknowledged messages are lost with it, which is why that is a WARNING.
        """
        jsm = client.jsm()
        try:
            await jsm.stream_info(spec.stream)
        except NotFoundError:
            raise JetStreamBindingError(
                f"Agent '{self.namespace or ROOT_LABEL}': stream '{spec.stream}' of consumer '{spec.durable}' does not "
                "exist. It is provisioned by the deployment, never by the framework."
            ) from None
        config = spec.consumer_config()
        try:
            await jsm.add_consumer(spec.stream, config=config)
        except APIError as exc:
            logger.warning(
                "Agent '%s': consumer '%s' on stream '%s' cannot be updated (%s); recreating it -- its unacknowledged "
                "messages are lost with it",
                self.namespace or ROOT_LABEL,
                spec.durable,
                spec.stream,
                exc.description or exc,
            )
            with contextlib.suppress(NotFoundError):
                await jsm.delete_consumer(spec.stream, spec.durable)
            await jsm.add_consumer(spec.stream, config=config)

    def _message_handler(
        self, binding: _Binding, slot_key: str, topic: str | None, callback: DeliveryCallback | None = None
    ) -> Callable[[Any], Awaitable[None]]:
        """The callback a subscription on ``binding`` delivers to.

        It runs on the subscription's one nats-py task: it waits for a run slot -- the
        back-pressure -- and returns as soon as the run is started, so the task can take the next
        message while this one is still running. ``topic`` is the declared subject of a
        per-topic subscription; ``None`` means one subscription for the whole binding, where the
        topic is found per message from its subject.
        """

        async def message_handler(msg: Any) -> None:
            if binding.jetstream is not None and await self._answer_control_message(msg, binding):
                return
            if self._consumption_paused and self._settles(binding):
                # A degraded agent runs nothing (C4). What reaches it anyway -- a delivery still in
                # the buffer while the pause waits for a connection change to finish, before it
                # can drain -- is nak'd at once, so it redelivers to a healthy replica (N4). Core
                # NATS cannot nak; its buffered messages run, as the drain lets them.
                await self._settle(msg, DeliveryDisposition.NAK, msg.subject, self._peek_event_id(msg), binding)
                return
            resolved = topic if topic is not None else self._bound_topic(binding, msg)
            if resolved is None:
                await self._settle(msg, DeliveryDisposition.TERM, msg.subject, None, binding)
                return
            release = await self._acquire_run(binding, slot_key)
            binding.enter_run()
            try:
                dispatch = callback if callback is not None else binding.topic_callbacks[resolved]
                # A run from a named connection starts in an empty context: nothing of the subscription
                # task or of another run reaches it (plan N1). The default connection keeps the copied
                # context it always had (N6).
                context = contextvars.Context() if binding.link.name else None
                run = asyncio.create_task(
                    self._run_delivery(msg, resolved, dispatch, binding),
                    name=f"nats-run-{self.namespace or ROOT_LABEL}{'-' + binding.link.name if binding.link.name else ''}",
                    context=context,
                )
                binding.runs.add(run)
                run.add_done_callback(functools.partial(self._run_finished, binding, release))
            except BaseException:
                # No run started, so no done callback will free the slot (W4).
                release()
                binding.exit_run()
                raise

        return message_handler

    @staticmethod
    async def _answer_control_message(msg: Any, binding: _Binding) -> bool:
        """Answer or drop a JetStream status message; ``True`` if ``msg`` was one (S2).

        Binding mode consumes through a plain subscription, so what nats-py's JetStream
        subscription would handle itself reaches this handler: an idle heartbeat, and a flow
        control request, after which the consumer delivers nothing until it is answered. Both
        carry status ``100`` and no event; run as a delivery, they were termed as unparseable.
        Only an operator-made consumer with ``idle_heartbeat`` or ``flow_control`` sends them.

        A heartbeat may report a stalled consumer in ``Nats-Consumer-Stalled``: a flow control
        reply subject that was never answered, which is answered here as nats-py would.
        """
        headers = getattr(msg, "headers", None)
        if not headers or headers.get(js_api.Header.STATUS) != CONTROL_MESSAGE_STATUS:
            return False
        if msg.reply:  # a flow control request; a heartbeat has no reply subject
            with contextlib.suppress(Exception):
                await msg.respond(b"")
        stalled = headers.get(js_api.Header.CONSUMER_STALLED)
        client = binding.link.nats_client
        if stalled and client is not None:
            with contextlib.suppress(Exception):
                await client.publish(stalled, b"")
        return True

    @staticmethod
    def _peek_event_id(msg: Any) -> str | None:
        """The event id of a delivery that is settled without being decoded, for its log line; ``None`` if unreadable."""
        try:
            event_id = json.loads(msg.data.decode()).get("id")
        except Exception:
            return None
        return event_id if isinstance(event_id, str) else None

    async def _acquire_run(self, binding: _Binding, slot_key: str) -> Release:
        """Wait until ``binding`` may start a run; return what frees it.

        Unset ``nats_max_concurrent_runs``: the subscription's one slot, as before the key existed.
        Set: the pair's guaranteed run, or a pool run within K (plan D7).
        """
        if binding.limit is None:
            slots = binding.slots_for(slot_key)
            await slots.acquire()
            return slots.release
        return await self._pool.acquire(binding.pair, binding.limit)

    def _bound_topic(self, binding: _Binding, msg: Any) -> str | None:
        """The declared subject a binding-mode delivery belongs to, or ``None`` (logged) if none covers it."""
        spec = binding.jetstream
        if spec is None:
            return None
        topic = spec.topic_for(spec.local_subject(msg.subject))
        if topic is not None and topic in binding.topic_callbacks:
            return topic
        logger.error(
            "Agent '%s': delivery on '%s' from consumer '%s' matches none of its subjects %s; terminating it",
            self.namespace or ROOT_LABEL,
            msg.subject,
            spec.durable,
            ", ".join(spec.subjects),
        )
        return None

    # ------------------------------------------------------------------
    # Internal -- one run
    # ------------------------------------------------------------------

    async def _run_delivery(self, msg: Any, topic: str, callback: DeliveryCallback, binding: _Binding) -> None:
        """Decode, dispatch and settle one delivery; runs as its own task, beside its heartbeat.

        The heartbeat is stopped before the delivery is settled, whatever ended the run. A
        cancelled run (shutdown past its deadline) is not settled: the broker redelivers it.
        Everything is settled against ``binding``, the one the message arrived on.

        With ``nats_handler_timeout`` set, a run that reaches the limit is cancelled and nak'd for
        immediate redelivery (plan D9). Whether the limit was hit is read from the run's own timer,
        not from the exception: a ``TimeoutError`` the handler raises itself is an ordinary failure.
        A handler that swallows the cancellation runs on and holds its slot until it returns; that
        is logged, and its delivery is nak'd all the same.
        """
        cloud_event = self._decode_message(msg, topic)
        if cloud_event is None:
            # A payload that will not parse now will not parse on redelivery either.
            await self._settle(msg, DeliveryDisposition.TERM, topic, None, binding)
            return

        attempt = self._delivery_count(msg)
        if attempt is not None:
            # The run's own task: the handler context gets it as nats_delivery_attempt / nats_max_deliver.
            mark_delivery(DeliveryAttempt(attempt=attempt, max_deliver=self._max_deliver_of(binding)))

        connection = binding.link.name
        if connection and self._source is not None:
            mark_connection(connection)
            _CURRENT_BINDING.set(binding)
            if not await self._accepted(msg, topic, cloud_event, binding):
                return

        heartbeat = self._start_heartbeat(msg, topic, binding)
        disposition = DeliveryDisposition.ACK
        # The run stays in this task (asyncio.timeout, not a new task): the run scope and the
        # connection marker are ContextVars of this task. None means no limit.
        limit = asyncio.timeout(self._handler_timeout)
        try:
            subject = binding.jetstream.local_subject(msg.subject) if binding.jetstream is not None else msg.subject
            async with limit:
                async with self._run_scope(connection):
                    await callback(cloud_event, subject)
        except DeliveryRevokedError:
            disposition = DeliveryDisposition.NAK  # never sent: a revoked delivery is not settled
            logger.warning(
                "Agent '%s': event %s on topic '%s' from connection '%s' was revoked; its result is discarded",
                self.namespace or ROOT_LABEL,
                cloud_event.id,
                topic,
                connection,
            )
        except Exception as ex:
            if isinstance(ex, TimeoutError) and limit.expired():
                disposition = DeliveryDisposition.NAK
                logger.error(
                    "Agent '%s': event %s on topic '%s'%s exceeded nats_handler_timeout (%.1fs); cancelled and nak'd for redelivery",
                    self.namespace or ROOT_LABEL,
                    cloud_event.id,
                    topic,
                    f" from connection '{connection}'" if connection else "",
                    self._handler_timeout,
                )
            else:
                disposition = disposition_for(ex)
                logger.error(
                    "Handler failed for event %s on topic '%s', will %s: %s",
                    cloud_event.id,
                    topic,
                    disposition.value,
                    ex,
                    exc_info=True,
                )
        else:
            if limit.expired():
                # The handler caught the cancellation and returned on its own, after the limit.
                disposition = DeliveryDisposition.NAK
                logger.error(
                    "Agent '%s': the handler for event %s on topic '%s'%s swallowed the cancellation at "
                    "nats_handler_timeout (%.1fs) and held its run slot until it returned; nak'd for redelivery",
                    self.namespace or ROOT_LABEL,
                    cloud_event.id,
                    topic,
                    f" from connection '{connection}'" if connection else "",
                    self._handler_timeout,
                )
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                # A heartbeat never fails the run (handler-time-bounds spec sec. 4.1).
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await heartbeat
        if binding.revoked:
            # Its connection was removed and the grace period ran out (spec 7.5): no ack, no nak.
            logger.warning(
                "Agent '%s': event %s on topic '%s' finished after its connection '%s' was retired; not settled",
                self.namespace or ROOT_LABEL,
                cloud_event.id,
                topic,
                connection,
            )
            return
        await self._settle(msg, disposition, topic, cloud_event.id, binding)

    async def _accepted(self, msg: Any, topic: str, cloud_event: CloudEvent[Any], binding: _Binding) -> bool:
        """Ask the source whether a named-connection delivery may run (plan N2); settle it if not.

        A reason terminates the delivery -- never processed, never retried. A hook that raises
        is a fault of the deployment's code, not of the event: the delivery is left for
        redelivery (nak) rather than lost.
        """
        source = self._source
        if source is None:
            return True
        connection = binding.link.name
        try:
            reason = source.validate(connection, msg.subject, cloud_event)
        except Exception as exc:
            logger.error(
                "Agent '%s': validating event %s on '%s' from connection '%s' raised; left for redelivery: %s",
                self.namespace or ROOT_LABEL,
                cloud_event.id,
                msg.subject,
                connection,
                exc,
                exc_info=True,
            )
            await self._settle(msg, DeliveryDisposition.NAK, topic, cloud_event.id, binding)
            return False
        if reason is None:
            return True
        logger.error(
            "Agent '%s': rejecting event %s (type %s) on '%s' from connection '%s': %s",
            self.namespace or ROOT_LABEL,
            cloud_event.id,
            cloud_event.type,
            msg.subject,
            connection,
            reason,
        )
        await self._settle(msg, DeliveryDisposition.TERM, topic, cloud_event.id, binding)
        return False

    @contextlib.asynccontextmanager
    async def _run_scope(self, connection: str) -> AsyncIterator[None]:
        """Enter the source's scope for ``connection`` around a run (plan D3); nothing for the default connection."""
        if not connection or self._source is None:
            yield
            return
        scope = self._source.run_scope(connection)
        if isinstance(scope, contextlib.AbstractAsyncContextManager):
            async with scope:
                yield
        else:
            with scope:
                yield

    def _run_finished(self, binding: _Binding, release: Release, run: asyncio.Task[None]) -> None:
        """Free the run's slot and count it out of the in-flight runs shutdown waits for."""
        binding.runs.discard(run)
        release()
        binding.exit_run()
        if not run.cancelled() and run.exception() is not None:
            # _run_delivery settles every handler failure itself; this is a fault in the run's own code.
            logger.error(
                "A NATS delivery run of agent '%s' failed outside its handler: %s",
                self.namespace or ROOT_LABEL,
                run.exception(),
                exc_info=run.exception(),
            )

    def _start_heartbeat(self, msg: Any, topic: str, binding: _Binding) -> asyncio.Task[None] | None:
        """Start reporting ``in_progress`` for a JetStream delivery; ``None`` on Core NATS or when switched off."""
        ack_wait = binding.ack_waits.get(topic)
        if not self._heartbeat_enabled or not self._settles(binding) or ack_wait is None:
            return None
        heartbeat = asyncio.create_task(self._keep_alive(msg, ack_wait / 3), name=f"nats-heartbeat-{self.namespace or ROOT_LABEL}")
        heartbeat.add_done_callback(self._heartbeat_finished)
        binding.heartbeats.add(heartbeat)
        heartbeat.add_done_callback(binding.heartbeats.discard)
        return heartbeat

    def _heartbeat_finished(self, heartbeat: asyncio.Task[None]) -> None:
        """Log a heartbeat that died of anything but its cancellation; the run goes on without it."""
        if not heartbeat.cancelled() and heartbeat.exception() is not None:
            logger.error(
                "The heartbeat of a NATS delivery of agent '%s' failed; the delivery may be redelivered while it runs: %s",
                self.namespace or ROOT_LABEL,
                heartbeat.exception(),
                exc_info=heartbeat.exception(),
            )

    @staticmethod
    async def _keep_alive(msg: Any, interval: float) -> None:
        """Report ``in_progress`` every ``interval`` seconds until cancelled; the first after one interval.

        A failed report (connection lost) is logged and retried at the next interval. It never
        fails the run: the settlement would fail the same way, and that already ends in a redelivery.
        """
        while True:
            await asyncio.sleep(interval)
            try:
                await msg.in_progress()
            except Exception as exc:
                logger.debug("Heartbeat for the message on %s failed: %s", msg.subject, exc)

    # ------------------------------------------------------------------
    # Internal — acknowledgement
    # ------------------------------------------------------------------

    async def _settle(
        self, msg: Any, disposition: DeliveryDisposition, topic: str, event_id: str | None, binding: _Binding | None = None
    ) -> None:
        """Tell the broker what became of a delivery (spec sec. 7.2).

        Only JetStream deliveries can be settled. Core NATS is fire-and-forget and
        ``msg.ack()`` raises ``NotJSMessageError`` there, so the JetStream flag gates the
        whole method. It gates on ``_use_jetstream`` rather than on ``msg.reply`` because a
        Core NATS request/reply message also carries a reply subject, and publishing ``+ACK``
        to a waiting requester would be worse than not acknowledging at all.

        A failure to settle is logged and swallowed. An acknowledgement is published to the
        delivering connection's reply subject, so it fails precisely when that connection is
        gone -- raising into the ``nats-py`` callback would neither deliver it nor recover it.
        The message is redelivered after ``ack_wait`` instead, which is the at-least-once
        behaviour sec. 7.4 already requires handlers to tolerate.

        A nak on the delivery the broker will not repeat is turned into a dead letter and a
        term. Naking there would be a lie: ``max_deliver`` is already reached, so nothing
        redelivers and the message leaves the consumer with no trace of why. Terming it here
        keeps the payload, on the dead-letter subject, and releases the consumer's pending
        slot immediately instead of one more ``ack_wait`` later.
        """
        binding = binding or self._binding
        if not self._settles(binding):
            return

        try:
            if disposition is DeliveryDisposition.ACK:
                await msg.ack()
            elif disposition is DeliveryDisposition.NAK and not self._deliveries_exhausted(msg, binding):
                await msg.nak()
            else:
                await self._dead_letter(msg, disposition, topic, event_id, binding)
                await msg.term()
        except Exception as exc:
            logger.error(
                "Could not %s event %s on topic '%s' (%s); it will be redelivered after ack_wait",
                disposition.value,
                event_id or "<undecodable>",
                topic,
                exc,
            )

    def _deliveries_exhausted(self, msg: Any, binding: _Binding | None = None) -> bool:
        """Whether the broker has no redelivery left for this message.

        ``max_deliver`` counts attempts, so the last one the broker makes is attempt
        ``max_deliver`` itself: naking *that* delivery buys nothing. ``-1`` means unlimited
        and is never exhausted. A message whose JetStream metadata cannot be read is treated
        as not exhausted, so an unreadable header can only cost a retry, never a payload.
        """
        max_deliver = self._max_deliver_of(binding or self._binding)
        if max_deliver is None:
            return False
        delivered = self._delivery_count(msg)
        return delivered is not None and delivered >= max_deliver

    @staticmethod
    def _max_deliver_of(binding: _Binding) -> int | None:
        """The attempts ``binding``'s consumer allows; ``None`` for unlimited or unknown.

        A named connection's binding carries the deployment's value; the agent's own consumers
        carry ``nats_max_deliver``. Not configured means the server's default, which is unlimited.
        """
        if binding.jetstream is not None:
            max_deliver = binding.jetstream.max_deliver
        else:
            max_deliver = binding.tuning.max_deliver if binding.tuning else None
        if max_deliver is None or max_deliver < 0:
            return None
        return max_deliver

    @staticmethod
    def _delivery_count(msg: Any) -> int | None:
        """Number of times the broker has delivered this message, or ``None`` if unknown."""
        try:
            return int(msg.metadata.num_delivered)
        except Exception:
            return None

    async def _dead_letter(
        self, msg: Any, disposition: DeliveryDisposition, topic: str, event_id: str | None, binding: _Binding | None = None
    ) -> None:
        """Republish a message the framework has given up on, before the delivery is termed.

        Both terminal outcomes arrive here: a payload rejected as unprocessable, and one
        whose redeliveries are spent. This is the last point at which the payload still
        exists -- the ``term()`` that follows removes it from the consumer -- so the original
        bytes are republished unchanged, including a payload that never parsed as a
        CloudEvent. What went wrong travels in headers instead, where it cannot corrupt a
        body a dead-letter consumer will try to read.
        """
        binding = binding or self._binding
        if binding.jetstream is not None:
            subject = binding.jetstream.dead_letter_subject or ""
        else:
            subject = binding.tuning.dead_letter_subject if binding.tuning else ""
        delivered = self._delivery_count(msg)
        reason = "deliveries-exhausted" if disposition is DeliveryDisposition.NAK else "terminal-failure"

        if not subject:
            self._count_dead_letter(reason, kept=False)
            logger.warning(
                "Dropping event %s from topic '%s' after %s delivery attempt(s) (%s): no dead-letter "
                "subject is configured, so its payload is lost. Set 'nats_dead_letter_subject' to keep it.",
                event_id or "<undecodable>",
                topic,
                delivered if delivered is not None else "an unknown number of",
                reason,
            )
            return

        headers = {
            "Blueprint-Dead-Letter-Reason": reason,
            "Blueprint-Original-Subject": topic,
            "Blueprint-Delivery-Count": str(delivered) if delivered is not None else "unknown",
        }
        if event_id:
            headers["Blueprint-Event-Id"] = event_id

        try:
            # On the binding's own link: a dead letter never leaves the connection it arrived on.
            await binding.link.nats_client.jetstream().publish(subject, msg.data, headers=headers)  # type: ignore[union-attr]
        except Exception as exc:
            self._count_dead_letter(reason, kept=False)
            logger.error(
                "Could not move event %s from topic '%s' to dead-letter subject '%s' (%s); its payload is lost",
                event_id or "<undecodable>",
                topic,
                subject,
                exc,
            )
            return

        self._count_dead_letter(reason, kept=True)
        logger.warning(
            "Moved event %s from topic '%s' to dead-letter subject '%s' after %s delivery attempt(s) (%s)",
            event_id or "<undecodable>",
            topic,
            subject,
            delivered if delivered is not None else "an unknown number of",
            reason,
        )

    def _count_dead_letter(self, reason: str, *, kept: bool) -> None:
        """Record one event this agent gave up on.

        Counted once per event, where the outcome is known, rather than once on entry: a
        publish that fails has still lost the payload, and counting on entry and again on
        failure would report two dead letters for one message.

        Args:
            reason: ``deliveries-exhausted`` or ``terminal-failure``.
            kept: Whether the payload reached the dead-letter subject. ``False`` is what tells a
                deployment with no subject configured that it is losing them.
        """
        self._dead_lettered.add(1, {"agent": self.namespace or ROOT_LABEL, "reason": reason, "kept": kept})

    # ------------------------------------------------------------------
    # Internal — reconnect callbacks
    # ------------------------------------------------------------------

    async def _on_disconnected(self) -> None:
        self._subscriptions_ready = False
        logger.warning("NATSClient disconnected")

    async def _on_closed(self) -> None:
        """The client gave up reconnecting: connect again and resubscribe, in the retry loop.

        Only with a finite ``nats_max_reconnect_attempts``, or a closed connection we did not close
        ourselves. Our own ``close()`` is not reconnected.
        """
        if self._closing or not self._subscriptions_managed:
            return
        self._subscriptions_ready = False
        self._subscriptions.clear()
        logger.error(
            "Agent '%s': the NATS connection closed after its reconnect attempts; connecting again and resubscribing",
            self.namespace or ROOT_LABEL,
        )
        # Paused or not: the loop connects either way and subscribes only an agent that is not paused.
        self._start_retry_task()

    async def _on_reconnected(self) -> None:
        logger.info("NATSClient reconnected")
        if not self._subscriptions_managed:
            return
        if self._consumption_paused:
            # A reconnect must not undo a pause. Without this the broker dropping and
            # restoring the connection would silently resubscribe a degraded agent, and C4
            # would hold only until the next network blip.
            logger.info("Agent '%s' stays paused after the reconnect; it is still degraded", self.namespace or ROOT_LABEL)
            # The pause may have been this connection's own loss: re-evaluate now, so the agent
            # resumes on this reconnect instead of up to one health interval later.
            self._request_health_refresh("the default connection is back while the agent is paused")
            return
        if self._use_jetstream and self._topic_callbacks:
            # nats-py replays every subscription it holds on a reconnect -- the JetStream push
            # ones too, and their deliver subject is fixed (_DELIVER.<durable>) -- so delivery
            # resumes by itself. Subscribing again added a second subscription per topic that no
            # pause, drain or close knew of (M1). What a reconnect can lose is broker state: a
            # broker restarted without storage, a failover to a peer that never had the stream.
            # That is re-checked; nothing is re-subscribed.
            try:
                await self._ensure_broker_state()
            except Exception as e:
                logger.error(
                    "Agent '%s': re-checking the JetStream stream and consumers after a reconnect failed: %s",
                    self.namespace or ROOT_LABEL,
                    self._describe_error(self._link, e),
                )
                return
        self._subscriptions_ready = True
        logger.info("NATSClient subscriptions ready after reconnect")

    async def _ensure_broker_state(self) -> None:
        """Provision the stream and every consumer this client's subscriptions deliver from, subscribing nothing."""
        await self._provision_stream()
        for topic in self._topic_callbacks:
            await self._ensure_consumer(topic, self._durables.get(topic) or self._durable_for(topic))
