"""The per-agent tracer and meter providers, and how a component finds its own (C2).

A leaf module on purpose. Every component reads this to get its own agent's tracer, and
``TelemetryManager`` writes it during startup -- so if the registry lived next to the manager,
``component.py`` would import the module that imports ``Config``, which imports the manager,
which imports ``component.namespace``. Nothing here imports anything from this framework, which
is what keeps that cycle from existing at all.

It is also why a component does not hold a reference to the manager: the group's shape would
then be reachable from the object graph, and C6 forbids that. A component asks for "my
namespace's tracer" and gets one whether or not anything configured it.
"""

import logging

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger(__name__)

_TRACER_PROVIDERS: dict[str, TracerProvider] = {}
"""The configured tracer provider per namespace, written once during startup."""

_METER_PROVIDERS: dict[str, MeterProvider] = {}
"""The configured meter provider per namespace, written once during startup."""


def register_providers(namespace: str, tracer_provider: TracerProvider, meter_provider: MeterProvider) -> None:
    """Record the two providers ``namespace`` records on.

    Args:
        namespace: The agent they belong to; ``""`` for the root.
        tracer_provider: The provider carrying that agent's resource.
        meter_provider: The provider carrying that agent's resource.
    """
    _TRACER_PROVIDERS[namespace] = tracer_provider
    _METER_PROVIDERS[namespace] = meter_provider


def has_providers(namespace: str) -> bool:
    """Whether ``namespace`` has already been configured."""
    return namespace in _TRACER_PROVIDERS


def tracer_provider(namespace: str) -> TracerProvider | None:
    """The tracer provider configured for ``namespace``, or ``None`` if nothing configured one."""
    return _TRACER_PROVIDERS.get(namespace)


def meter_provider(namespace: str) -> MeterProvider | None:
    """The meter provider configured for ``namespace``, or ``None`` if nothing configured one."""
    return _METER_PROVIDERS.get(namespace)


def agent_tracer(namespace: str, instrumentation_name: str) -> trace.Tracer:
    """Return the tracer ``namespace`` should record spans on.

    Falls back to the global provider for a namespace nothing configured, which is every
    namespace when OpenTelemetry is disabled and every namespace before startup has run. The
    fallback is what keeps this safe to call unconditionally: a no-op tracer records nothing and
    costs nothing, so callers never have to branch on whether telemetry is on.

    Args:
        namespace: The agent asking; ``""`` for the root.
        instrumentation_name: What is being instrumented, conventionally a class or module name.
    """
    provider = _TRACER_PROVIDERS.get(namespace)
    if provider is None:
        return trace.get_tracer(instrumentation_name)
    return provider.get_tracer(instrumentation_name)


def agent_meter(namespace: str, instrumentation_name: str) -> metrics.Meter:
    """Return the meter ``namespace`` should record instruments on.

    Falls back to the global provider on the same terms as :func:`agent_tracer`.

    Args:
        namespace: The agent asking; ``""`` for the root.
        instrumentation_name: What is being instrumented, conventionally a class or module name.
    """
    provider = _METER_PROVIDERS.get(namespace)
    if provider is None:
        return metrics.get_meter(instrumentation_name)
    return provider.get_meter(instrumentation_name)


def configured_namespaces() -> tuple[str, ...]:
    """The namespaces that have their own providers, for tests and diagnostics."""
    return tuple(_TRACER_PROVIDERS)


def shutdown_providers() -> None:
    """Flush and shut down every configured provider: the agents first, the root last (S22).

    The providers are built without an ``atexit`` hook of their own, because the interpreter
    runs those in reverse creation order and the root -- built first -- would not be last by
    design but by accident. Run by the lifespan's shutdown, and by one ``atexit`` hook as the
    fallback for a process that never reaches it; a second call finds nothing left to shut down.

    The root goes last because it is the global provider: whatever an agent's shutdown still
    records through a module-level tracer or meter lands there. A provider that fails to shut
    down is logged and the rest still are.
    """
    for namespace in [ns for ns in _TRACER_PROVIDERS if ns] + [ns for ns in _TRACER_PROVIDERS if not ns]:
        providers = (_TRACER_PROVIDERS.pop(namespace), _METER_PROVIDERS.pop(namespace, None))
        for provider in providers:
            if provider is None:
                continue
            try:
                provider.shutdown()
            except Exception as exc:
                logger.warning("Shutting down the telemetry of agent '%s' failed: %s", namespace or "<root>", exc)


def reset_providers() -> None:
    """Forget every configured provider.

    For tests. The global provider is deliberately not reset: the OpenTelemetry SDK refuses a
    second ``set_tracer_provider`` and only logs about it, so nothing this function did could
    make the next case's provider the global one anyway.
    """
    _TRACER_PROVIDERS.clear()
    _METER_PROVIDERS.clear()
