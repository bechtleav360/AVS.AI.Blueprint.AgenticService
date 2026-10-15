"""What a deployment tells the framework about the connections it supplies (named-connections plan).

The framework does not know what a named connection stands for. A deployment names a
:class:`ConnectionSource` factory in the process-scope key ``nats_connection_source``; the source
lists :class:`ConnectionSpec` s and answers, per agent and connection, with a
:class:`JetStreamBinding` -- which of the agent's declared subjects the connection serves, the
prefix that turns a declared subject into the subject on the wire, and the durable consumer that
carries them, every wire value verbatim (N4). Before a delivery runs, the source may reject it
(:meth:`ConnectionSource.validate`, N2), and it may wrap every run in a scope of its own
(:meth:`ConnectionSource.run_scope`, D3).

Agents never see any of this. A handler learns at most an opaque connection name, from the
``nats_connection`` context key.
"""

import importlib
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from nats.js import api as js_api

from .io_client_base import subject_is_covered_by

if TYPE_CHECKING:
    from ...models.events import CloudEvent


CONNECTION_SOURCE_KEY = "nats_connection_source"
"""Process-scope key naming the factory, ``"package.module:attribute"``; unset, nothing changes (N6)."""

NATS_CONNECTION_CONTEXT_KEY = "nats_connection"
"""Handler context key holding the name of the named connection a delivery arrived on."""

_CURRENT_CONNECTION: ContextVar[str | None] = ContextVar("blueprint_nats_connection", default=None)
"""Set inside a run that started from a named connection, and only there: each such run starts in an
empty context, so the value can never be another run's."""


def current_connection() -> str | None:
    """The named connection the current run's delivery arrived on; ``None`` outside such a run."""
    return _CURRENT_CONNECTION.get()


@dataclass(frozen=True)
class ConnectionSpec:
    """One connection a deployment supplies: a name and how to log in. Secrets are never logged."""

    name: str
    """Opaque to the framework; shows in logs, task names and the ``nats_connection`` context key."""
    url: str
    user: str | None = None
    password: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)
    creds_file: str | None = None
    nkey_seed: str | None = field(default=None, repr=False)
    inbox_prefix: str | None = None
    tls: Any = field(default=None, repr=False)
    """An ``ssl.SSLContext`` for ``tls://`` brokers with a private CA; ``None`` uses the default."""

    def __post_init__(self) -> None:
        if not self.name or any(char.isspace() for char in self.name):
            raise ValueError(f"A connection name must be non-empty and contain no whitespace, got {self.name!r}.")
        if not self.url.startswith(("nats://", "tls://")):
            raise ValueError(f"Connection '{self.name}': url must be a nats:// or tls:// URL.")
        if bool(self.user) != bool(self.password):
            raise ValueError(f"Connection '{self.name}': user and password go together.")

    def connect_options(self) -> dict[str, Any]:
        """The credential and inbox arguments for ``nats.connect()``."""
        options: dict[str, Any] = {}
        if self.user:
            options.update(user=self.user, password=self.password)
        if self.token:
            options["token"] = self.token
        if self.creds_file:
            options["user_credentials"] = self.creds_file
        if self.nkey_seed:
            options["nkeys_seed_str"] = self.nkey_seed
        if self.inbox_prefix:
            options["inbox_prefix"] = self.inbox_prefix
        if self.tls is not None:
            options["tls"] = self.tls
        return options


@runtime_checkable
class ConnectionSource(Protocol):
    """What a deployment implements to supply named connections. Built once per process.

    The factory named by ``nats_connection_source`` is called with the process ``Config`` and
    returns the source. Every agent of the process shares it, so it must hold no per-run state.

    **Runtime changes (optional).** A source may also define ``watch(notify)``: every agent's client
    calls it once with a ``notify`` callable, and the source calls ``notify()`` -- from any thread --
    whenever its connections may have changed. The client then reads :meth:`connections` and
    :meth:`binding` again and applies the difference: a new connection is bound; a changed one
    (another :class:`ConnectionSpec` or :class:`JetStreamBinding`) gets a new link, bound before the
    old one is retired; a removed one is drained, its runs get ``subscription_change_grace`` seconds,
    and what still runs then is revoked -- never acked or nak'd, ``publish`` refused with
    ``DeliveryRevokedError``, not cancelled. No consumer is ever deleted. A source without ``watch``
    is read once, at startup. ``watch`` is not part of this protocol's ``isinstance`` check, so such
    a source still qualifies. The agent's default connection keeps the subjects it had at startup.
    """

    def claims(self, agent: str, subjects: tuple[str, ...]) -> tuple[str, ...]:
        """Which of ``agent``'s declared subjects belong to named connections -- whatever connections exist now.

        Answered from the deployment's subject scheme, not from the current connections: with no
        connection yet (a fresh environment, no tenant yet) a claimed subject is still claimed, so it
        is consumed nowhere until a connection serves it, and never on the agent's default connection.
        A subject not claimed goes to the default connection only where ``nats_unclaimed_subjects =
        "default_connection"`` allows it; by default (``"fail"``) it fails the agent's startup.
        Must be a subset of ``subjects``. A binding may serve claimed subjects only.
        """
        ...

    def connections(self) -> Mapping[str, ConnectionSpec]:
        """The connections to open, by name. Read at startup, and again after each ``notify()``."""
        ...

    def binding(self, agent: str, subjects: tuple[str, ...], connection: ConnectionSpec) -> "JetStreamBinding | None":
        """How ``agent`` consumes over ``connection``, or ``None`` if the connection serves none of its subjects.

        Args:
            agent: The agent's name (its namespace, or the queue group of a standalone agent).
            subjects: Every subject the agent declared, as it declared them. The binding's
                ``subjects`` must be a subset; the rest stay on the agent's default connection.
            connection: The connection, as :meth:`connections` returned it.
        """
        ...

    def validate(self, connection: str, subject: str, event: "CloudEvent[Any]") -> str | None:
        """Why a delivery must not run, or ``None`` to let it run (N2).

        Called before any handler sees the delivery, with the subject as it arrived on the wire.
        A reason terminates the delivery: logged, never processed, never retried.
        """
        ...

    def run_scope(self, connection: str) -> AbstractContextManager[Any] | AbstractAsyncContextManager[Any]:
        """A context the framework enters inside each run from ``connection``, around the handler chain (D3).

        Entered in the run's own task, which started from an empty context, so whatever it sets
        in ContextVars is visible to this run and no other. A synchronous or an asynchronous context
        manager; a source with nothing to enter returns ``contextlib.nullcontext()``.
        """
        ...


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


def mark_connection(name: str) -> None:
    """Record ``name`` as the current run's connection. Called by the client inside a run's own task only."""
    _CURRENT_CONNECTION.set(name)


def load_connection_source(path: object, config: Any) -> ConnectionSource | None:
    """Import and call the factory named by ``nats_connection_source``; ``None`` when the key is unset.

    Resolved once per process, when the application is built, so a wrong path fails startup
    rather than the first delivery.

    Raises:
        ValueError: the value is not ``"package.module:attribute"``, the module cannot be
            imported, the attribute is missing or not callable, or what it returns is not a
            :class:`ConnectionSource`. The message names the key and the value.
    """
    text = str(path or "").strip()
    if not text:
        return None
    module_path, _, attribute = text.partition(":")
    if not module_path or not attribute:
        raise ValueError(f"'{CONNECTION_SOURCE_KEY}' is {text!r}; write it as 'package.module:attribute', naming the factory.")
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise ValueError(f"'{CONNECTION_SOURCE_KEY}': importing '{module_path}' raised {type(exc).__name__}: {exc}") from exc
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise ValueError(f"'{CONNECTION_SOURCE_KEY}': '{module_path}' has no callable '{attribute}'.")
    source = factory(config)
    if not isinstance(source, ConnectionSource):
        raise ValueError(
            f"'{CONNECTION_SOURCE_KEY}': '{text}' returned a {type(source).__name__}, which is not a ConnectionSource "
            "(connections, binding, validate, run_scope)."
        )
    return source
