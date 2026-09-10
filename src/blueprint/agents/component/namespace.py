"""Namespace naming, validation and resolution shared by namespace-owned components.

A namespace names one agent inside a process that may host several (spec sec. 3, C1).
The empty namespace is the root: it is what every component of a single-agent
application uses, so everything here is a no-op for those applications.

This module is the single definition of the root namespace and of what a namespace is
allowed to look like. Three operations recur wherever a component becomes
namespace-owned and are therefore kept in one place:

- **Validation.** A namespace becomes a registry key prefix, a NATS queue group, part
  of a JetStream durable name and an OpenTelemetry ``service.name``. Those four have
  different alphabets, so the namespace is held to the intersection and rejected at the
  point it enters the system, rather than being sanitised differently by each consumer.
- **Naming.** Two instances of the same class can now coexist in one registry, so the
  class-derived component name is no longer unique. The namespace qualifies it.
- **Resolution.** A component looking for a collaborator wants *its own* namespace's
  instance, and falls back to the root one when its namespace has none. This mirrors
  the resolution rule the spec states for ``get_component`` (namespace, then root,
  raising only on ambiguity within one level); when the registry itself grows a
  namespace dimension, these helpers become the registry's own implementation.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

ROOT_NAMESPACE = ""
"""The namespace every component of a single-agent application lives in.

Not a name but the absence of one, and therefore not configurable: ``qualified_component_name``,
the NATS queue group and the JetStream durable all branch on it being falsy, so a root
namespace with a value would rename every registry key and every broker-side consumer -- which
is exactly what C1 forbids. An application that wants its own name on the broker sets
``nats_queue_group``; an agent that wants its own identity gets a namespace, and is then not
the root.
"""

ROOT_LABEL = "<root>"
"""How the root namespace is written where a value is required, since its name is empty.

The angle brackets are what make this a *reserved* form rather than a guess: they are excluded
from the namespace alphabet below, so no legal namespace can produce this string. A bare token
such as ``root`` could not make that promise -- a namespace called ``root`` would be
indistinguishable from the absence of one, which is the ambiguity the placeholder exists to
avoid.
"""

_ALLOWED_NAMESPACE = re.compile(r"\A[a-z][a-z0-9_]*\Z")
"""Lowercase, digits and underscore, starting with a letter. See :func:`validate_namespace`."""

_DISPLAY_UNSAFE = re.compile(r"[<>.\s]+")
"""Characters a display segment cannot keep. See :func:`display_segment`."""


def validate_namespace(namespace: str) -> str:
    """Return ``namespace`` unchanged, or raise if it cannot serve as one.

    Rejected here rather than repaired, and rejected at construction rather than at first
    use: the namespace reaches a registry key, a queue group, a durable name and a telemetry
    resource, so a value that is repaired differently by each of them is four names for one
    agent. The root namespace ``""`` is always valid.

    The alphabet is ``[a-z][a-z0-9_]*``, which is the intersection of what those four
    consumers accept, plus two exclusions that are not obvious from any one of them:

    - ``-`` is the separator in the durable name ``f"{namespace}-{topic}-durable"`` (C1).
      Allowing it in a namespace makes that name ambiguous: namespace ``orders-eu`` with
      topic ``created`` and namespace ``orders`` with topic ``eu-created`` produce the same
      durable, so two agents would bind one JetStream consumer and consume each other's
      events. Use ``_``.
    - ``<`` and ``>`` are excluded so that :data:`ROOT_LABEL` and the deployment placeholders
      it is used alongside stay unforgeable. ``>`` is a NATS wildcard and illegal in a
      consumer name regardless.

    Args:
        namespace: The candidate namespace; ``""`` for the root.

    Returns:
        The namespace, unchanged.

    Raises:
        ValueError: if the namespace is padded, whitespace-only, or outside the alphabet.
            The message names what the namespace would have broken, because a namespace is
            declared once and read by four subsystems that would each fail differently.
    """
    if namespace == ROOT_NAMESPACE:
        return ROOT_NAMESPACE

    if not namespace.strip():
        raise ValueError(
            f"A namespace of whitespace only ({namespace!r}) is not the root namespace. Pass '' for the root, "
            "or a name matching [a-z][a-z0-9_]* for an agent."
        )

    if namespace != namespace.strip():
        raise ValueError(
            f"Namespace {namespace!r} has surrounding whitespace. It is not trimmed for you, because the trimmed "
            "and untrimmed forms would be one agent under two names -- one in the registry and another on the broker."
        )

    if "-" in namespace:
        raise ValueError(
            f"Namespace '{namespace}' contains '-', which is the separator in the JetStream durable name "
            f"'{namespace}-<topic>-durable'. Two namespaces could then share one durable and consume each other's "
            "events. Use '_' instead."
        )

    if not _ALLOWED_NAMESPACE.match(namespace):
        offenders = sorted({character for character in namespace if not _ALLOWED_NAMESPACE.match(f"a{character}")})
        raise ValueError(
            f"Namespace '{namespace}' is not a legal namespace: {''.join(offenders) or namespace!r} cannot appear in it. "
            "A namespace must match [a-z][a-z0-9_]*, because it becomes a registry key prefix, a NATS queue group, "
            "part of a JetStream durable name and a telemetry service name, and those do not accept the same characters."
        )

    return namespace


_CURRENT_NAMESPACE: ContextVar[str] = ContextVar("blueprint_current_namespace", default=ROOT_NAMESPACE)
"""The namespace components are being constructed for, or the root when nothing set one.

This is how a component learns its namespace **without the developer knowing namespaces exist**.
An agent is a directory of handlers, services and clients written the same way whether it runs
alone or beside five others; the only thing that differs is who builds it. So the namespace is
ambient during construction rather than an argument threaded through every constructor: a
developer writing ``class OrderService(ServiceBase)`` with ``super().__init__()`` gets a
namespaced service without a namespace appearing anywhere in their code.

A ``ContextVar`` rather than a module global because it resets deterministically and is scoped
to the context that set it. Note the limit: a component constructed in another thread or task
does not inherit it. Construction happens synchronously inside the builder, so that is the
correct shape -- and a component built lazily at request time is a root component by
construction, which is what falling back to the root gives it.
"""


def current_namespace() -> str:
    """Return the namespace being constructed for, or :data:`ROOT_NAMESPACE`.

    Read by ``Component.__init__``. Outside a :func:`namespace_scope` this is always the root,
    so a single-agent application behaves exactly as it did before this existed.
    """
    return _CURRENT_NAMESPACE.get()


@contextmanager
def namespace_scope(namespace: str) -> Iterator[str]:
    """Construct every component inside this block for ``namespace``.

    Entered once per agent by whatever applies that agent's registration, and always exited:
    leaking a namespace would silently attach the next agent -- or the framework's own root
    components -- to the wrong one, and a registry key, a queue group and a durable name would
    all be wrong together.

    The namespace is validated on entry rather than at the first component, so an illegal name
    is reported against the registration that declared it instead of against whichever component
    happened to be constructed first.

    Args:
        namespace: The agent to construct for. ``""`` is the root and makes the block a no-op.

    Yields:
        The namespace in force inside the block.

    Raises:
        ValueError: if the namespace is not a legal namespace.
    """
    token = _CURRENT_NAMESPACE.set(validate_namespace(namespace))
    try:
        yield namespace
    finally:
        _CURRENT_NAMESPACE.reset(token)


@contextmanager
def construction_scope(namespace: str) -> Iterator[None]:
    """Construct inside ``namespace``, or leave the ambient namespace exactly as it is.

    The difference matters because :func:`namespace_scope` with ``""`` is not a no-op: it
    *sets* the current namespace to the root. Anything recorded outside a scope carries ``""``,
    and entering a scope for it would reset the namespace in force -- which is what happens
    when a whole agent's declarations are replayed inside one scope, and would silently move
    every one of them back to the root.

    Lives here rather than in one of its callers because it is the guarded form of
    :func:`namespace_scope`, and every place that constructs on behalf of a namespace it was
    *handed* needs it: the builder replaying a declaration, and the cache factory, which is
    given the owning agent as an argument.

    Args:
        namespace: The agent to construct for, or ``""`` to keep whatever is already in force.

    Yields:
        Nothing; the scope is ambient.
    """
    if not namespace:
        yield
        return
    with namespace_scope(namespace):
        yield


def display_segment(value: str, placeholder: str) -> str:
    """Return ``value`` reduced to one safe segment of a dot-separated identity string.

    Used for the values a deployment owns rather than the framework -- the group name and the
    pod name in the NATS connection name (spec sec. 6). They arrive from the environment and
    cannot be validated the way a namespace is: rejecting a deployment's group name would fail
    a rollout over a display string.

    Two things are guaranteed instead. Dots and whitespace are replaced, so a group called
    ``a.b`` cannot turn a three-segment name into four and misattribute a connection; and
    angle brackets are replaced, so no environment value can forge :data:`ROOT_LABEL` or its
    sibling placeholders. An empty value becomes ``placeholder``, so every position stays
    filled and "absent" reads differently from "empty".

    Sanitising rather than validating is only acceptable because nothing derives from these
    values: C1 forbids the queue group and the durable from reading the connection name, so
    a mangled segment loses no information any consumer depends on.
    """
    return _DISPLAY_UNSAFE.sub("_", value.strip()) or placeholder


def qualified_component_name(namespace: str, base_name: str) -> str:
    """Return the registry name ``base_name`` takes inside ``namespace``.

    The root namespace keeps the bare name, so an existing application's registry keys
    -- ``nats_client``, ``event_publishing_service`` -- do not change and neither do
    the lookups and health-check entries that use them.

    Every name a component can be given passes through here: the one derived from its class, an
    explicit constructor argument, and an assignment to ``Component.name``. So a name always
    carries the agent it belongs to, which is what lets two agents' components be told apart in
    a log.

    **Deliberately not idempotent.** Skipping the prefix when a name already starts with it
    looks like a safeguard against ``orders_orders_db`` and is worse than the problem: a base
    name can legitimately begin with the namespace -- ``BillingHandler`` in namespace
    ``billing`` derives ``billing_handler`` -- and such a component would silently register
    unqualified, which is exactly the ambiguity the qualification exists to remove. "Already
    prefixed" is not decidable from the string, so it is not guessed. The cost is that a caller
    who qualifies a name itself gets it qualified twice; the result is redundant but still
    unambiguous, and no framework code does it.
    """
    return base_name if not namespace else f"{namespace}_{base_name}"


def namespace_of(component: Any) -> str:
    """Return the namespace a component belongs to, or the root for one that has none.

    Read with ``getattr`` because the namespace currently lives on the bases that own
    one (transport clients, publishing service) rather than on ``Component`` itself.
    """
    return str(getattr(component, "namespace", ROOT_NAMESPACE) or ROOT_NAMESPACE)


def resolve_for_namespace[ComponentT](
    candidates: list[ComponentT],
    namespace: str,
    *,
    description: str,
) -> ComponentT:
    """Return the one candidate belonging to ``namespace``, else the one at the root.

    Args:
        candidates: The components to choose from, typically a registry type query.
        namespace: The namespace asking. ``""`` looks only at the root.
        description: What is being resolved, for the error message.

    Raises:
        ValueError: if neither level yields exactly one candidate. Ambiguity is an
            error rather than a first-match, because picking one of two silently
            attaches an agent to another agent's transport -- which is exactly the
            attribution the per-namespace topology exists to provide.
    """
    for level in (namespace, ROOT_NAMESPACE) if namespace else (ROOT_NAMESPACE,):
        matches = [candidate for candidate in candidates if namespace_of(candidate) == level]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"Namespace '{level or ROOT_LABEL}' has {len(matches)} {description}s, so the one to use for "
                f"namespace '{namespace or ROOT_LABEL}' is ambiguous."
            )
    raise ValueError(f"No {description} is registered for namespace '{namespace or ROOT_LABEL}' or at the root.")
