# Observability

Traces, metrics, logs and probes, and -- the part that only matters once several agents share a
process -- **which agent each of them belongs to**.

A single-agent service gets its attribution for free: one process, one agent, so a pod restart, a
latency graph and an error log all name the same thing. Grouping takes that away. Twenty agents in
one process share a port, an event loop, a memory limit and a health endpoint, so "the pod is
unhealthy" stops being an answer. Everything below exists to keep the answer per agent while the
process stays shared.

Two rules run through all of it:

- **Regrouping is invisible.** An agent's telemetry identity is its own name, not its group's, so
  moving it between deployments changes no dashboard, alert or SLO (C2).
- **Nothing fails silently at agent granularity.** Every path that stops an agent serving emits an
  ERROR event and drives a gauge to zero, whether or not anything else notices (C7).

---

## Tracing

### Configuration

```toml
[default]
otel_enabled = true
otel_endpoint = "localhost:4317"      # OTLP over gRPC; host:port, no path
otel_service_name = "document-processor"
```

| Key | Type | Meaning |
|---|---|---|
| `otel_enabled` | `bool` | Off by default. Nothing below is configured while it is off. |
| `otel_endpoint` | `str` | The OTLP gRPC collector. With no endpoint, no exporter is built and tracing stays off. |
| `otel_service_name` | `str` | The `service.name` of the **root** namespace -- see below. |

### One identity per agent

The framework does not configure *a* tracer provider; it configures one per namespace, each with
its own resource:

| Attribute | Value |
|---|---|
| `service.name` | The agent's own name, or `<agent>.otel_service_name` when the agent sets one for itself. `otel_service_name` for the root namespace. |
| `deployment.group` | The group the process resolved -- `BLUEPRINT_GROUP`, or the one group a mounted group file declares. Absent for a standalone agent and for a group nothing named (`BLUEPRINT_AGENTS` alone). Set by the framework; no supported API exposes it to an agent (C6). |
| `service.instance.id` | `POD_NAME`, else `HOSTNAME`, else the host name. When none can be told, the framework sets nothing and the OpenTelemetry SDK's own default applies. |

**What the deployment declares wins.** A key set in `OTEL_RESOURCE_ATTRIBUTES` (or
`service.name` in `OTEL_SERVICE_NAME`) is used exactly as declared; the framework sets only the
attributes the deployment left out, and never replaces a declared one. **One exception:** in a
group, `OTEL_SERVICE_NAME` names the root's telemetry only, and every agent keeps its own name as
`service.name` -- one name for all of them would make their telemetry impossible to tell apart.
Startup logs a WARNING naming the value. A `service.name` in `OTEL_RESOURCE_ATTRIBUTES` without
`OTEL_SERVICE_NAME` fails the start of a group: taken as declared it would give every agent that
name. Remove it there, or set `OTEL_SERVICE_NAME` instead. Standalone it is used as declared.

So an agent called `orders` reports `service.name = "orders"` whether it runs alone or beside
nineteen others, and a dashboard keyed on it cannot tell which. A single-agent application keeps
reporting `otel_service_name`, unchanged, because its components live in the root namespace.

All the providers share one exporter and one `BatchSpanProcessor` -- one queue and one export
thread whatever the group size, since the resource travels on the span rather than on the
processor. Metric readers cannot be shared (the SDK binds a reader to the provider that registered
it), so each provider gets its own reader over the one shared exporter.

**Shutdown.** The application's shutdown flushes and shuts down every provider after all
components have stopped, the agents first and the root last, so what an agent records in its own
`on_shutdown` is still exported. The shared exporter and span processor are closed by the last
provider to shut down, not the first. A process that never runs the shutdown gets the same at
interpreter exit.

The root's provider is also installed as the global one, so every module-level
`trace.get_tracer(...)` -- in this framework, and in any library -- resolves exactly as it did
before agents had identities.

### `@traced()`

`@traced()` wraps a `Component` method in a span named `{component.name}.{method_name}`, on
**that component's agent's** provider.

```python
from blueprint.agents.component.component import traced
from blueprint.agents.services.service_base import ServiceBase


class EmbeddingService(ServiceBase):
    async def on_startup(self) -> None:
        self._model = self.registry.get_agent("embedder")

    @traced()
    async def compute(self, text: str) -> list[float]:
        return await self._model.run(text)
```

The arguments are **parameter names to stamp onto the span**, not a span name:

```python
@traced("topic", "cloud_event")
async def handle_event(self, topic: str, cloud_event: CloudEvent) -> dict: ...
```

- A `CloudEvent`-shaped value is stamped as `event.type`, `event.source` and `event.id`.
- Anything else is stamped as `{parameter_name} = str(value)`.
- With no arguments, the first parameter that looks like a CloudEvent is stamped automatically.

Every span additionally carries `agent` -- the namespace of the component, or `<root>`. That is
redundant with the resource for a span that reaches an exporter, and it is the only record for one
that does not: a span still open when the process is killed never gets a resource applied.

An exception propagating out of the method sets the span status to `ERROR` before it is re-raised.

---

## Metrics

| Metric | Kind | Meaning |
|---|---|---|
| `blueprint.namespace.up` | gauge | `1` while an agent is serving, `0` once it is not. Carries `agent`. |
| `blueprint.namespace.inflight` | gauge | Dispatches that agent has in progress. Carries `agent`. |
| `blueprint.events.unhandled` | counter | Events an agent received and found nothing to do with. Carries `agent` and `topic`. |
| `blueprint.events.duplicate` | counter | Events an agent recognised as already processed. Carries `agent` and `topic`. |
| `blueprint.events.skipped` | counter | Events whose responsible handler returned `HandlerResult.skipped` -- the agent's own relevance rule, not a too-broad subscription. Carries `agent` and `topic`. |
| `blueprint.nats.connection.bound` | gauge | `1` while a named NATS connection is bound and delivering, `0` otherwise. Carries `agent` and `connection`. |
| `blueprint.nats.connection.permission_violations` | counter | Permission violations the broker reported on a named connection. Carries `agent` and `connection`. |
| `blueprint.events.dead_lettered` | counter | NATS deliveries the framework gave up on. Carries `agent`, `reason` (`terminal-failure` or `deliveries-exhausted`) and `kept` (whether the payload reached the dead-letter subject). |
| `blueprint.scheduler.tick_age_seconds` | gauge | Seconds since a scheduler last ticked, `-1` before its first tick. Carries `scheduler`, `agent` and `mode`. See [schedulers.md](../components/schedulers.md). |
| `llm.tokens.count` | counter | Tokens consumed, by an agent's model calls. |
| `llm.response.latency` | histogram | Model call duration. |

**The `topic` label is bounded.** Under Dapr the topic of a delivery is a segment of the request
path, which any caller of `/events/<topic>` chooses. A topic the agent did not declare is therefore
counted as `<undeclared>`; a declared one keeps its name. With `dapr_declarative_subscriptions = true`
the framework knows no topic list, and every topic counts as `<undeclared>`. The real topic stays in
the log line. Under NATS every topic is one the agent subscribed, so the label is always the name.

`blueprint.namespace.up` and `blueprint.namespace.inflight` are recorded on the agent's own meter provider, so they arrive with that agent's
`service.name` as well as with the `agent` attribute -- a dashboard can group on either, and one
of them survives a collector that drops resource attributes.

`blueprint.namespace.inflight` is counted around the handler chain rather than at a transport
edge, so it covers NATS, Dapr and the REST dispatch path with one measurement, and it means "work
this agent is doing" rather than "messages its client has taken". Its reason for existing is
post-mortem: an OOM kill, a native crash and a blocked loop raise nothing a handler could catch, so
the only attribution available is what was emitted *before* the process died.

---

## Probes

| Endpoint | Answers |
|---|---|
| `GET /health/live` | `200` while the process is running; `503` once an agent hit a transport fault no retry can fix, naming each such agent and why (C3). |
| `GET /health/ready` | `200` when the pod should receive traffic, `503` otherwise. Answered from the last poll's result at once, also while a poll is still waiting on a slow check. |
| `GET /info`, `/status/env`, `/status/llm`, `/status/build` | Service, configuration, AI-provider and build metadata. |

**A degraded agent never fails liveness, and that is a rule rather than an accident.** A failing
liveness probe restarts the pod, and in a group that restarts every agent in it -- reintroducing
exactly the blast radius the grouping was paid to remove. So liveness reflects the process and the
event loop.

**The one exception is a transport fault no retry can fix**: a durable that filters another subject, a stream the server refuses to create or widen, a grant the account lacks, a tenant's login or deliver subject refused. The broker answered and the
answer is final, so the agent consumes nothing until someone changes the broker or the deployment.
Such a fault is logged CRITICAL -- what failed, where, why it is final, what to change -- in any
agent, critical or not, and `/health/live` answers `503` with `{"status": "DOWN", "agents": {...}}`
naming each such agent and its reason. The restart is how the orchestrator makes someone look. At
startup the same fault fails the start, whatever `critical_agents` says. A fault that may heal (the
broker unreachable, a lost connection, a timeout, a stream not yet provisioned) is retried and shows
in readiness only.

**An orphaned agent fails liveness too, until it consumes again**: its resume after a degradation
keeps failing (a paused client reports healthy, so readiness alone would read UP), or its
connection loop gave up after `event_client_max_retries`. It is logged CRITICAL once, and when it
consumes again liveness comes back and a WARNING says so.

### Readiness is a policy

```toml
[default]
readiness_policy = "critical"   # "all" (default) | "critical" | "any"
```

| Value | Behaviour |
|---|---|
| `all` | **Default.** Any degraded agent makes the pod not ready. What a single-agent application has always done. |
| `critical` | Only agents the group flagged `critical` gate readiness. |
| `any` | Ready while at least one agent is up. |

The root namespace gates readiness under every policy: it holds the shared infrastructure, so its
failure is not a partial one. An agent latched down -- its startup failed and recovery retries it, or its transport failed for good -- gates readiness under every policy, critical or not: it consumes nothing for a reason that is not transient. In a single-agent application the root is the whole application, and
all three policies therefore agree -- which is what makes the key safe to set in a settings file
that standalone projects also read.

`readiness_policy` is process scope: one pod has one readiness probe, so an agent's own
`settings.toml` cannot set it.

An unrecognised value **refuses to start** rather than falling back to the default. A misspelt
`critcal` silently read as `all` would remove a whole group from rotation the first time a
non-critical agent wobbled, and the operator who set the key would have no way to see that it had
never taken effect.

The `critical` flag is the same one the group configuration uses to decide whether a failed import
stops the process, because it answers the same question -- can this deployment run without that
agent:

```yaml
# deployment-groups.yaml
groups:
  - name: finance
    agents: [orders, billing, reporting]
    critical_agents: [orders, billing]
```

### The readiness payload

```json
{
  "status": "UP",
  "policy": "critical",
  "components": {
    "orders.nats_client": {"status": "healthy", "message": "Connected to NATS server at ..."},
    "billing.cache": {"status": "unhealthy", "message": "redis is unreachable"}
  },
  "namespaces": {
    "<root>":  {"status": "UP",   "critical": true,  "failing": []},
    "orders":  {"status": "UP",   "critical": true,  "failing": []},
    "billing": {"status": "DOWN", "critical": false, "failing": ["billing.cache"]}
  }
}
```

`components` is keyed by entry name -- bare at the root, `<agent>.<name>` for an agent -- so a
single-agent payload's keys are unchanged. `namespaces` exists because the policy makes `status`
no longer derivable from `components`: the pod above answers `UP` with a failing check in it, and
without the per-agent section that reads as a contradiction.

**`policy` and `namespaces` appear only when the process hosts a group.** A standalone agent's
payload is `status` and `components`, exactly as before agents existed.

### Custom health checks

A checker is an object implementing `HealthCheckerBase`, not a callable:

```python
from blueprint.agents.io.api.actuators.health import HealthCheckerBase
from blueprint.agents.models.api import ComponentHealth


class DatabaseHealth(HealthCheckerBase):
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def health_check(self) -> ComponentHealth:
        try:
            latency = await self._database.ping()
        except Exception as exc:
            return ComponentHealth(status="unhealthy", message=str(exc))
        return ComponentHealth(status="healthy", message=f"{latency} ms")
```

Register it on the builder, where the agent it belongs to is whichever one is in force:

```python
builder.with_health_checker("database", DatabaseHealth(database))
```

Two agents may both call theirs `database`; they appear as `orders.database` and
`billing.database`. Two checks that would still collide on one entry name are refused at
registration rather than silently reduced to one.

The framework registers checks of its own: one per transport client, one per declared cache
(`cache`, or `cache:<name>` for a named one), and with a `nats_connection_source` one more per
client, `<client>:connections` (below). A check of yours under one of those names replaces the
framework's, with a WARNING at startup -- the way to override a built-in check.

### Named NATS connections

With a `nats_connection_source`, each agent's client gets one more entry,
`<agent>.nats_client:connections`. Its message lists every named connection and how it stands --
`bound`, `connecting`, `reconnecting`, `retrying` (with the last error, credentials redacted),
`failed` (a tenancy fault no retry fixes: the login or a grant refused; also logged CRITICAL and
failing liveness, above) or `paused` -- and whether the broker reported a permission violation:

```json
"orders.nats_client:connections": {
  "status": "unhealthy",
  "message": "1/2 named connection(s) bound, readiness 'all': A=bound, B=retrying (OSError: connection refused)"
}
```

Whether it can fail is the agent's `nats_connections_readiness`: `never` (default) -- it is always
healthy and only reports; `any` -- it fails while no named connection is bound; `all` -- it fails
while any one is not bound.

**It counts for readiness only, never for consumption.** A failing entry makes the agent `DOWN` in
the payload and under the readiness policy, but the agent is not paused: a tenant whose connection
is down must not stop the agent on every other tenant's connection. The default connection's
entry keeps pausing the agent as described below.

When the mode is `any` or `all`, a named connection becoming bound or unbound re-runs the checks at
once rather than at the next interval. So does the default connection coming back while the agent
is paused, so a pause its own disconnect caused ends on the reconnect.

---

## What happens when an agent stops serving

One state -- is this agent serving -- with three consequences, and they are deliberately not three
mechanisms.

1. **It is reported.** `blueprint.namespace.up` goes to `0` and an ERROR event is logged naming
   the agent, its group and its pod. This happens whatever the readiness policy says. Grouping
   removed the pod restart that used to be the alert, so the alert is emitted deliberately.
2. **It stops consuming.** Readiness gates HTTP only -- a pod removed from service rotation still
   holds its subscriptions -- so for an event-driven agent the probe alone changes nothing. Under
   NATS the agent's subscriptions are drained: runs already in progress finish and acknowledge,
   and new deliveries go to a healthy replica. A JetStream delivery that still reaches the paused
   agent is nak'd at once, so it redelivers elsewhere; Core NATS cannot nak, so what the drain
   lets through still runs. Under Dapr the sidecar delivers whatever
   the application thinks, so the fan-out answers `RETRY` for that agent without dispatching.
   Under `event_bus = "sessions"` the job stream is closed, so the agent's jobs stay pending for a
   healthy replica; jobs already running finish. The connection is kept open, because a closed client reports itself unhealthy for ever and the
   pause could then never lift.
3. **It may take the pod out of rotation**, according to `readiness_policy`.

Recovery is the reverse and needs no operator: when the agent's checks pass again, it resumes
consuming and the gauge returns to `1`. If resuming fails -- under NATS, a stream the broker no
longer has and cannot recreate -- the client retries in the background, backing off from
`event_client_retry_delay` to 60 s, with a WARNING per attempt, until it consumes again or the agent
is degraded once more.

The one exception is a startup failure. If a non-critical agent's `on_startup` raises, the process
starts without it and that agent is **latched** down -- its components can often still answer a
health check while the agent is unusable, so an observed-health signal would put it straight back
into service on the next poll. The readiness payload shows it as `DOWN` with a `reason` naming
the component and its error, even though no check is failing.

A latched agent is **retried**: every `startup_retry_interval_seconds` (default 30) the framework
calls `on_startup` again on the components that failed, in their original order, stopping at the
first that fails again. When all of them start, the latch is released and the agent's health
checks decide from there -- a transient cause, such as a database that was not reachable yet,
recovers without a restart. While it keeps failing, each attempt logs a WARNING and the payload
carries the latest error. It is retried indefinitely and never ends the process: a deterministic
failure, such as a missing key, would fail the same way after a restart, and crash-looping the pod
would take every healthy agent in it down too.

**So `on_startup` must be safe to call again after it raised.** Raise before acquiring anything, or
release what you acquired before raising; the framework's own components all do.

A critical agent's `on_startup` failure ends the startup instead, before the port is bound, so
Kubernetes crash-loops the pod with the traceback rather than reporting a replica that is silently
short a consumer.

---

## Detecting a blocked event loop

The one group-wide failure a process can detect about itself. A blocked loop raises nothing, logs
nothing and keeps the pod live, while every agent in the group stops responding at once.

| Setting | Mechanism |
|---|---|
| Default, every environment | A watchdog that measures how much longer a known sleep actually took, and names the agents that had work in flight. |
| `event_loop_debug = true` | asyncio's own debug mode, which names the exact callback and its source location. |

```toml
[default]
event_loop_debug = false                       # off unless set, in every environment
event_loop_slow_callback_seconds = 0.2         # debug mode's threshold
event_loop_watchdog_enabled = true
event_loop_watchdog_interval_seconds = 1.0
event_loop_block_threshold_seconds = 1.0
```

Never both: debug mode already reports the callback, which is strictly better than the watchdog's
"one of these agents was busy". Setting `event_loop_debug = true` is a deliberate choice -- debug
mode wraps coroutine creation and keeps tracebacks for every task, which is why it is not the
default anywhere, development included.

The watchdog cannot name the culprit. By the time it runs again the blocking callback has
returned, so it reports the agents that have work in flight *now*, which is the set the culprit is
in. That is still the difference between "the pod was slow" and "one of these two agents blocked
the loop for four seconds".

---

## Detached tasks

Every task the framework starts carries a done-callback that logs its exception with the agent
attached. Without one, a task that raised holds its exception until garbage collection and what
reaches the log is asyncio's own *Task exception was never retrieved* -- at an unpredictable time,
with no agent on it. In a process per agent that was survivable because the pod told you; in a
group it is precisely the silent per-agent failure this section exists to remove.

The same applies to code you write: a bare `asyncio.create_task(...)` in a handler or a service is
a task whose failure nobody will see.

---

## Logging

Use `%`-style lazy formatting, not f-strings, and get a module-level logger:

```python
from logging import getLogger

_log = getLogger(__name__)

_log.info("Processing document %s from %s", event.subject, event.source)
```

Never configure logging in a component. The application does it once, from `log_level` and
`log_format`; a library that adds a handler cannot be silenced by the process that hosts it.

```toml
[default]
log_level = "INFO"
log_format = "json"
```

Framework log lines that concern one agent name it -- `agent='orders'`, or `<root>` for the root
namespace -- so a grouped process's log is readable per agent without a trace backend.

---

## See also

- `docs/concepts/caching.md` -- the per-agent cache, and the checks it registers
- `docs/specs/2026-08-28-multi-agent-grouping.md` -- C2, C3, C4, C6 and C7, normatively
