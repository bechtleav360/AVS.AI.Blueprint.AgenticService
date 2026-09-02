# Spec -- Multi-Agent Grouping

| | |
|---|---|
| **Status** | draft |
| **Implementation plan** | `docs/plans/2026-08-28-multi-agent-grouping.md` |
| **Resolves** | #75 (deployment model decision), #73 (duplicate cron ticks) |
| **Unblocks** | #32 (100 agents in 4 GB), #35 (shared interpreter), #20 (worker scaling) |
| **Related** | #33 (lazy heavy imports), #34 / #74 (dependency slimming), #36 (concurrency bounds + benchmark), #43 (scheduler double-start), #6 (config service) |

Requirement keywords (**MUST**, **MUST NOT**, **SHOULD**, **MAY**) are used in the RFC 2119 sense.

---

## 1. Scope

Allow one Python process to host several independent agents, and make the grouping of agents
into processes a deployment-time parameter rather than a code-time one.

### In scope

- A namespace dimension in the component registry, with per-namespace isolation of executors,
  AI clients, event transports and configuration.
- Group composition resolved at process start from a file and/or environment variables.
- Event delivery that is correct under horizontal pod scaling.
- Telemetry and health identities that are invariant under regrouping.
- A development workflow in which an agent author never encounters namespaces or groups.

### Non-goals

- Multiple simultaneous transport types in one process (NATS *and* Dapr).
- Cross-namespace agent calls.
- Adding or removing namespaces after startup.
- Ordering guarantees across replicas.
- Lazy agent instantiation and scale-to-zero (evaluated and rejected; do not re-propose
  without new measurements).
- Prefork / copy-on-write process sharing. #35 lists "prefork" and "multi-tenant host" as
  alternatives; this spec implements **multi-tenant host** and does not pursue prefork.

---

## 2. Terminology

| Term | Meaning |
|---|---|
| **Agent** | A unit of business capability: handlers, services, prompts, optionally a REST API and scheduler. Authored as one directory. |
| **Namespace** | The registry partition an agent's components live in. Equal to the agent name. `""` is the root namespace and means "pre-migration single-agent app". |
| **Group** | The set of agents loaded into one process, and therefore into one pod. |
| **Registration** | An `AgentRegistration` -- component classes collected without instantiation. |
| **Root** | Namespace `""`, holding process-wide shared components. |

---

## 3. Invariants

These are normative. C1-C6 exist because violating them makes regrouping observable outside the
process, which would defeat the purpose of grouping. C7 exists for a different reason: it is what
keeps the isolation cost that grouping *does* incur attributable, and therefore adjustable.

### C1 -- Consumer identity derives from the agent

Queue group names and JetStream durable names **MUST** be a pure function of the namespace.
They **MUST NOT** incorporate the group name, container name, pod name, replica index, or any
other deployment identifier.

- Queue group: `namespace`, or `nats_queue_group` (default `app_name`) when the namespace is `""`.
  It **MUST NOT** be the empty string.
- JetStream durable: `f"{namespace}-{topic}-durable"`, or the configured `nats_durable_name`
  when the namespace is `""`.
- The NATS **connection name** (sec. 6) is deployment-specific and **MUST NOT** be used to derive
  either of the above.

### C2 -- Telemetry identity derives from the agent

Each namespace **MUST** have its own `TracerProvider` and `MeterProvider` with
`Resource({"service.name": <namespace>, "deployment.group": <group>, "service.instance.id": <pod>})`.
All providers **SHOULD** share one exporter and one `BatchSpanProcessor`.

When the namespace is `""`, the provider **MUST** use `otel_service_name` from config, reproducing
current behaviour exactly (`io/telemetry/telemetry.py:39-41`).

### C3 -- Liveness is never namespace-dependent

The liveness probe **MUST** reflect only process and event-loop health. A degraded namespace
**MUST NOT** cause a liveness failure, because that restarts every agent in the group.

Already satisfied: `io/api/actuators/actuator_api.py:126-143` returns `UP` unconditionally. This
invariant exists to stop the behaviour from being changed, not to change it.

Readiness **MUST** follow `readiness_policy`:

| Value | Behaviour |
|---|---|
| `"all"` | **Default.** Any degraded namespace makes the pod not ready. Reproduces current behaviour. |
| `"critical"` | Only namespaces marked `critical` gate readiness. |
| `"any"` | Ready while at least one namespace is up. |

A degraded namespace **MUST** be reported as `blueprint_namespace_up{agent="..."} = 0` and an
ERROR-level event regardless of policy. Alerting is driven by that signal, not by the probe. C7
generalises this to every path that stops a namespace serving, not only the ones readiness reads.

### C4 -- A degraded namespace stops consuming

Readiness gates HTTP only; a not-ready pod still holds subscriptions. A namespace that becomes
degraded **MUST** stop consuming its events so they redeliver to a healthy replica. With
per-namespace transports (sec. 6) this is closing that namespace's client.

### C5 -- Configuration is namespace-scoped

Each namespace **MUST** receive a `Config` with `agent_scope` set to its namespace name, so
`<namespace>.<key>` resolves before the root `<key>`. Infrastructure keys stay at root; prompts,
model selection and usage limits become per-agent.

### C6 -- Agent code cannot observe its grouping

No API reachable from agent code **MUST** expose the group name, the group's membership, or the
number of namespaces in the process. This is what makes regrouping incapable of breaking agent
code. `deployment.group` on telemetry resources is set by the framework and is not readable
through a supported API.

### C7 -- Failure is never silent at namespace granularity

Every path that removes a namespace from service **MUST** emit an ERROR-level event carrying that
namespace's telemetry identity (C2), independently of any pod-level symptom. A failure observable
only as a pod restart, a latency regression, or a metric that stopped arriving does not satisfy
this invariant.

C7 exists for a different reason than C1-C6. Those keep regrouping invisible from outside the
process; C7 is what makes the residual isolation cost of grouping *manageable*. Three failure
classes take a whole group down, and none of them raises a catchable exception:

| Class | Why handler-level `try` / `except` cannot see it |
|---|---|
| Memory limit breached | The cgroup limit is per-pod; the kernel kills the process |
| Native extension crash | The process dies without unwinding |
| Event loop blocked | Not an error at all -- a latency and liveness symptom |

Careful exception handling lowers how often a group dies; it cannot change which failures kill it.
What remains available is attribution, so attribution is normative:

- **In-process degradation.** `blueprint_namespace_up{agent="..."} = 0` plus an ERROR event for
  every path that stops a namespace serving -- not only the paths that gate readiness (C3).
- **Detached tasks.** Every task the framework creates via `ensure_future` / `create_task`
  **MUST** carry a done-callback that logs exceptions with the namespace attached. The existing
  `self._retry_task.add_done_callback(self._on_retry_done)` (`clients/io/nats_client.py:77`) is the
  pattern; a bare `ensure_future` is a C7 violation.
- **Silent consumer loss.** A namespace whose subscriptions are gone while the process stays
  healthy **MUST** drive `blueprint_namespace_up = 0`. `subscriptions_ready`
  (`clients/io/nats_client.py:60`) already carries this per client; per-namespace clients (sec. 6)
  make it per-agent.
- **Process-terminating failures.** These cannot report themselves, so the framework **MUST** emit
  enough per-namespace context beforehand to attribute them post-mortem: the namespace on every
  in-flight handler span, and a periodic per-namespace in-flight gauge. Without it an OOM kill is
  indistinguishable across a group's agents, and the grouping dial cannot be turned in response.
- **Blocked loop.** The dev-mode slow-callback threshold (sec. 11.1) **SHOULD** also run in
  production at a higher threshold, logging the namespace of the executing handler. This is the one
  group-wide failure class that is detectable from inside the process.

Grouping removes the pod restart that used to serve as the alert, so the alert **MUST** be emitted
deliberately rather than inferred from a restart.

---

## 4. Public API

### 4.1 New

```python
class AgentRegistration:
    """Fluent collector. Stores component classes; instantiates nothing."""
    def with_handler(self, handler, *, name=None, **kwargs) -> "AgentRegistration"
    def with_service(self, service, *, name=None, **kwargs) -> "AgentRegistration"
    def with_agent(self, agent, *, name=None, **kwargs) -> "AgentRegistration"
    def with_scheduler(self, scheduler, *, name=None, **kwargs) -> "AgentRegistration"
    def with_rest_api(self, api, *, name=None, **kwargs) -> "AgentRegistration"
    # No with_cache -- caches are registered on the AppBuilder.


class GroupConfig:
    """Resolved group composition. A value object; performs no I/O once constructed."""
    name: str
    agents: tuple[AgentSpec, ...]      # name, critical flag, module path
    cache_names: tuple[str, ...]

    @classmethod
    def resolve(cls, config: Config) -> "GroupConfig":
        """Read file + env, validate against the agent map, or raise GroupConfigError."""


def run_app(app: FastAPI, config: Config) -> None: ...
```

`GroupConfig.resolve` is the only member that touches the environment or the filesystem.
`with_group` **MUST NOT** perform I/O, so tests can construct a `GroupConfig` literally.

### 4.2 Changed

```python
class AppBuilder:
    def with_namespace(self, name: str, *, registration: AgentRegistration | None = None,
                       config: Config | None = None) -> "AppBuilder | NamespaceBuilder"
    def with_group(self, group: GroupConfig) -> "AppBuilder"

    @classmethod
    def from_group(cls, config: Config) -> "AppBuilder"      # resolve + with_group

    # namespace: str = "" added to with_handler / with_service / with_agent /
    # with_scheduler / with_rest_api -- keyword-only.

    def with_cache(self, enabled: bool = True, enable_locking: bool = True,
                   *, name: str = "default") -> "AppBuilder"
```

**`with_cache` is the one place where the obvious design breaks compatibility.** The current
signature is `with_cache(enabled: bool = True, enable_locking: bool = True)`
(`app_builder.py:117`). Making `name` the first parameter would turn an existing
`with_cache(False)` -- meaning *disable caching* -- into a cache named `False`, silently enabling
the cache with no `TypeError`. `name` therefore **MUST** be keyword-only and **MUST** follow the
two existing positional parameters.

### 4.3 Component

`Component.__init__` **MUST NOT** gain a namespace parameter. The namespace is read from a
module-level `ContextVar` set by `AgentRegistration._apply`, so no user subclass constructor
signature changes and no positional argument shifts.

`Component.executor` returns the namespace's `ThreadPoolExecutor`, falling back to root. The
executor **MUST** be created lazily on first access; an app that never performs blocking work
**MUST NOT** spawn one. (Eager creation in `build()` would add ~`cpu_count + 4` idle threads to
every existing single-agent app, and works against #36's thread-count budget.)

---

## 5. Configuration

### 5.1 Group resolution

Read **before** `Config` is constructed -- group composition determines which agents get a
`Config` at all -- so these are plain environment reads plus one YAML parse, deliberately not
routed through Dynaconf. Hence the `BLUEPRINT_` prefix rather than Dynaconf's `DYNACONF_`.

| Variable | Default | Meaning |
|---|---|---|
| `BLUEPRINT_GROUP_CONFIG` | `./deployment-groups.yaml` | Path to the group file. Absent file is not an error if env vars supply the group. |
| `BLUEPRINT_GROUP` | -- | Group to load. **MAY** be omitted when the file declares exactly one group. |
| `BLUEPRINT_AGENTS` | -- | Comma-separated agent names. Supplies the group without a file. |
| `BLUEPRINT_CRITICAL_AGENTS` | -- | Comma-separated subset marked `critical`. |

**Precedence: environment variables override the file, key by key.** The resolved value of every
key, and its source, **MUST** be logged at startup.

Both mechanisms **MUST** be supported; neither is preferred. The file suits ConfigMap mounts and
local development, env vars suit `docker run` and CI, and env values live in the pod template so
changing them triggers a rolling update on their own.

### 5.2 Runtime keys

| Key | Default | Meaning |
|---|---|---|
| `readiness_policy` | `"all"` | See C3. |
| `executor_workers` | `os.cpu_count() + 4` | Per-namespace thread pool size. Bounded per #36. |
| `nats_queue_group` | `app_name` | Queue group for the root namespace only. |
| `nats_ack_wait` | -- | **MUST** exceed p99 handler duration. See sec. 7.3. |
| `nats_max_ack_pending` | -- | Per-consumer, shared across replicas. |
| `idempotency_enabled` | `false` | Opt-in dedup. See sec. 7.4. |
| `idempotency_ttl` | -- | Dedup window. |
| `scheduler_mode` | `"event"` | `"event"` or `"in_process"`. See sec. 7.5. |

### 5.3 Settings authoring

An agent author writes plain top-level keys in their own directory's `settings.toml`
(`model_name = "..."`), not `[default.<agent>]`. The build **MUST** merge each agent's fragment
under its own scope so C5 resolves them, without the author knowing the scope exists.

Collisions between an agent fragment and a root key **MUST** be reported at build time.

---

## 6. Transport topology

One `NATSClient` **per namespace**, not one per process.

**This section applies to the direct-connection transport only.** Under Dapr the application holds
no broker connection at all: `DaprClient` is an `httpx` client against the sidecar
(`clients/io/dapr_client.py:89`), subscriptions are declarative (`GET /dapr/subscribe`, then the
sidecar posts to `POST /events/{topic}`), and the sidecar owns and multiplexes the one broker
connection per pod. Broker connections therefore track pods rather than agents on that path, and
reasons 1 and 2 below move into the sidecar and out of this spec's reach. A per-namespace
`DaprClient` **MAY** still be created for health attribution and for C4, but it **MUST NOT** be
described as confining ack loss or slow-consumer disconnects, because it does not.

Per-namespace clients deliberately trade back part of the shared-connection advantage credited
to the namespace model. This is justified by three things, in order of weight:

1. **Ack loss is confined.** A handler that completes 60 s of inference and then cannot ack
   because the connection is down has already committed its side effects; the broker redelivers
   after `ack_wait`. Duplicate processing is therefore *certain*, not merely possible. On a shared
   connection one blip does this to every in-flight message across every agent in the group.
2. **Slow-consumer disconnects are confined.** The broker kicks a connection whose pending buffer
   overflows. Shared, one flooding agent takes down the group's transport and triggers a
   re-subscribe storm across all namespaces (`clients/io/nats_client.py:265-280`).
3. **Attribution.** `nats.connect()` is currently called with no `name=`
   (`clients/io/nats_client.py:93`), so every connection this framework opens is anonymous in
   `/connz`. Per-namespace named connections make a pod's contents legible in connection-oriented
   tooling.

**Durability is not among the three, and the topology MUST NOT be justified by it.** JetStream
pending state lives on the server, keyed by consumer and stream sequence; an ack is a message
published to the per-delivery `$JS.ACK...` reply subject, not an entry in a framework-side
registry. Nothing aggregates in-flight events on behalf of the namespaces sharing a process, so a
shared connection has no such state to lose when the process dies -- `ack_wait` expires and the
broker redelivers. What the topology decides is not whether work survives a failure, but **how many
namespaces repeat work** when a connection drops. The durability question is settled by sec. 7.1
and 7.2 (JetStream on, acks actually sent), not here.

Cost accepted without a config knob: connection count scales with agent count. A connection is a
socket plus buffers -- tens to low hundreds of KB -- against ~65 MB for the smallest possible
separate process (#32). Protecting a few MB with a knob nobody should use is not worth the
maintenance surface. 100 agents at 2 replicas is ~200 connections, which is not a practical
constraint against a self-operated broker's default `max_connections`. The number **SHOULD** be
checked before a large rollout only where the cap is issued externally per account -- a managed
broker, or an operator-mode account whose JWT carries a `conn` limit set by someone else. No such
authentication is currently wired: `nats.connect()` is called with URL and reconnect parameters
only (`clients/io/nats_client.py:93`).

Connection name **MUST** be `f"{namespace}.{group}.{pod}"`, and **MUST NOT** feed C1 naming.

`EventPublishingService` **MUST** publish on its own namespace's client; otherwise outbound
traffic is unattributable and reason 3 is defeated.

Per-namespace clients also make C4 a client close rather than selective unsubscription, and give
`ClientHealthChecker` per-agent health entries that feed `readiness_policy = "critical"` directly.

---

## 7. Event delivery

### 7.1 Competing consumers

With N replicas of a group, exactly one replica **MUST** process any given event. Core NATS
subscriptions **MUST** pass a queue group; JetStream consumers **MUST** share a durable per C1.

The current code does neither: `nats_client.py:250` subscribes with no `queue=`, and JetStream is
off by default (`nats_client.py:102`). Setting `replicas: 2` today therefore doubles every side
effect and every inference bill. This is a defect independent of grouping (see #20, #35).

### 7.2 Acknowledgement

`nats_client.py:242-247` subscribes with `manual_ack=True` and **no `msg.ack()` call exists
anywhere in the codebase**, so every JetStream message redelivers until `max_deliver`. Already a
defect at one replica.

**Decision: ack after the handler completes.** The alternative (ack first) converts a connection
blip from duplicate work into *lost* work, which is worse for expensive, side-effecting inference.
Consequently at-least-once is permanent, and sec. 7.4 applies.

**The contract is that a normal return acknowledges and a raised exception does not.**
`ProcessingStatus` carries no failure value -- it is `PROCESSED` or `NO_HANDLER_FOUND` -- so every
failure already reaches the transport as an exception. The transport edge **MUST NOT** inspect
`ProcessingResult` to decide acknowledgement: `ProcessingResult` is a reporting object and **MUST**
remain independent of delivery control.

| Outcome at the transport edge | NATS | Dapr response |
|---|---|---|
| Handler chain returned, any status | `ack()` | `SUCCESS` |
| `RetryableHandlerError` | `nak()` | `RETRY` |
| `InvalidEventError` | `term()` | `DROP` |
| `CriticalHandlerError` | `term()` | `DROP` |
| Any other exception raised during dispatch | `nak()`, bounded by `max_deliver` | `RETRY` |
| Payload fails JSON or CloudEvent parsing, before dispatch | `term()` | `DROP` |

**`NO_HANDLER_FOUND` MUST acknowledge.** An event that matches no handler's conditions has nothing
to do, and redelivery cannot make a handler appear: a nak is a pointless loop until `max_deliver`,
and under a queue group a loop that visits every replica in turn. `dapr.py:75` returns `RETRY` for
this case today and **MUST** change.

Acknowledging it **MUST NOT** make it invisible. A subscribed topic with no matching handler is
usually a declaration error, and the acknowledgement is what would otherwise hide it forever. The
framework **MUST** count unhandled events per namespace and topic, and **MUST** log at WARNING the
first time a given (namespace, topic) pair produces one.

**Both transports MUST map the same outcome to the same disposition.** Dapr's response dict *is*
its acknowledgement, so the table above is normative for `dapr.py` and
`event_handling_base.handle_event` exactly as it is for `nats_client.py`. They disagree in two
places today: `NO_HANDLER_FOUND` as above, and `CriticalHandlerError`, which `dapr.py:102` retries
-- a critical error is not made less critical by being delivered again.

`max_deliver` and a dead-letter destination **MUST** be configured, because nak on an unexpected
exception otherwise redelivers indefinitely.

Implementations **SHOULD** capture the ack reply subject and retry the ack after a reconnect,
which narrows the duplicate window from "certain on any blip" to "only if the pod also dies".
Two caveats make this a prototype rather than a design commitment: a redelivery may already be in
flight when the retry lands, and the behaviour of acking a stale delivery attempt depends on how
the server keys pending state on stream sequence. **MUST** be validated against a real broker.

### 7.3 Long handlers

`ack_wait` **MUST** exceed p99 handler duration, or a slow handler is redelivered to another
replica while the first is still working. `in_progress()` heartbeats address slow handlers; they
do **not** address connection loss, since they travel over the same connection.

### 7.4 Idempotency

At-least-once is unavoidable: rebalance, eviction, node drain and every rolling deploy produce
redelivery, and ack loss guarantees it.

This is a cost of *replication*, not of grouping. A single-agent process replicated twice faces the
same competing consumers, the same redelivery and the same lost ordering, so the requirement lands
identically on a pre-migration app that scales past one replica. It is specified here because
grouping is where the requirement becomes visible, not because grouping creates it.

Whether deduplication is *correct* depends on the product built on the blueprint -- some
operations are naturally idempotent, others need business-level reconciliation the framework
cannot see. The framework therefore **MUST NOT** silently enforce dedup, and **MUST**:

- provide an opt-in dedup mechanism keyed on the CloudEvent `id`, backed by the namespace's cache
  with a TTL, applied in the handler chain before dispatch (`idempotency_enabled`);
- **flag the requirement explicitly to the agent author** -- a comment in the scaffolded handler,
  a line in the generated README, and an `asbs validate` notice when a handler is registered with
  `idempotency_enabled = false`. The author must make a decision, not inherit a default silently.

### 7.5 Schedulers

`SchedulerBase.on_startup` creates an `AsyncIOScheduler` per process with no leader election
(#73), so every cron tick fires once per replica. Grouping widens the exposure: one pod hosting 20
agents runs 20 schedulers, and two replicas duplicate all 20 agents' crons simultaneously.

Two modes, selected by `scheduler_mode`:

| Mode | Behaviour |
|---|---|
| `"event"` | **Default.** No in-process timer. An external scheduler (Kubernetes `CronJob`) publishes an event; the agent handles it through its normal event path. |
| `"in_process"` | `AsyncIOScheduler` gated by a NATS KV or cache-backed leader lease. For un-orchestrated Docker and local development. |

In `"event"` mode the framework **MUST NOT** start a timer, and the tick **MUST** be delivered as
an ordinary namespaced event, so the queue group already guarantees single execution across
replicas without electing anything. The publishing container **SHOULD** be a minimal NATS client
image, not the agent image -- a `CronJob` running the agent re-pays the ~154 MB baseline (#32) for
work that fires once a night.

The schedule **MUST** remain declared in agent code, and the `CronJob` **MUST** be generated from
that declaration -- the same generation path as manifests from `deployment-groups.yaml`. Hand-authored
schedules let code expect a tick nobody scheduled.

Neither mode is exactly-once: `CronJob` is at-least-once (controller restart, missed
`startingDeadlineSeconds`), and a lease can briefly have two holders if it expires mid-tick.
Sec. 7.4 therefore applies in both modes. `concurrencyPolicy: Forbid` **SHOULD** be set, and
`CronJob` `timeZone` **MUST** be reconciled with apscheduler's timezone handling so the two modes
do not diverge.

Note #43 -- schedulers being started twice *within* one process by two `build()` passes -- is a
distinct defect. Both touch scheduler startup and **SHOULD** be fixed together.

### 7.6 Topic subscription scope

Two agents subscribing to the same topic is legitimate and expected: both want the event. Topic
deduplication **MUST** be scoped within a namespace. Each `(namespace, topic)` pair gets its own
subscription and its own consumer. A cross-namespace "first declaration wins" rule would silently
disable one agent's subscription, and the agent author could not observe it locally.

### 7.7 Selection and fan-out

Selection happens at two levels, and only one of them is enforced by the broker:

| Level | Enforced by | Mechanism |
|---|---|---|
| Which subjects reach the process | broker | subscription subject, JetStream `filter_subjects` |
| Which event a handler wants | in-process | `can_handle()` |

NATS filters on **subject only** -- there is no content or header predicate -- so any selection
finer than the subject is either encoded in the subject or paid for inside the process. Dapr can
evaluate CEL rules over the CloudEvent, but in the sidecar, after the broker has already
delivered.

This matters at scale for a reason that is not CPU. With one consumer per `(namespace, topic)`
pair (sec. 7.6), a broad subject makes the **broker** copy every message once per namespace, each
copy carrying its own delivery, ack-pending state and redelivery timer. One hundred agents
subscribed to `events.>` is a hundredfold fan-out before any handler code runs.

**Selection that the framework is expected to push down to the broker MUST be declared
statically.** `can_handle()` is imperative code and can never be pushed anywhere: it **MUST**
remain available as the final in-process selector, and **MUST NOT** be the only selector
available. Handlers **SHOULD** declare the subjects or event types they accept, and the framework
**SHOULD** resolve declared event types to subjects through the same `topic_mapping` it uses when
publishing, so publisher and consumer cannot drift.

Two rules keep this non-breaking, and both are load-bearing, because **no handler in the framework
or in any scaffolded project declares anything today**: `get_subscribed_topics()` is overridden
nowhere, the generated handler template selects purely inside `can_handle_event`, and
`nats_subscriptions` appears in no generated settings file. Any design that treats declarations as
authoritative therefore describes an empty set.

1. **A handler that declares nothing MUST continue to be evaluated for every event its namespace
   receives.** An in-process dispatch index **MAY** be keyed on declared event types as an
   optimisation, but undeclared handlers **MUST** fall into a wildcard bucket that is always
   evaluated. Without this every existing handler silently stops firing -- and because
   `NO_HANDLER_FOUND` acknowledges (sec. 7.2), the events would be consumed and discarded rather
   than accumulating visibly. This is the most destructive failure mode available in this design.
2. **A broker-side filter MUST NOT be narrower than the union of the explicitly declared subjects
   and the configured `nats_subscriptions` list.** Filters **MUST** derive from explicit
   declarations only; the framework **MUST NOT** infer a narrower filter by reading handler code or
   handler type checks. An agent subscribed to `orders.>` whose handler selects part of that space
   on payload content has to keep receiving all of it.

**Consumer reconfiguration is a migration, not a config change.** A durable's name and its filter
set are broker-side state. Depending on server version, changing the filter set is applied in place
or forces delete-and-recreate, and a recreated consumer resumes according to its delivery policy --
replaying from the start of the stream, or skipping whatever arrived in between. Any release that
changes a durable's name or filter set **MUST** state the migration explicitly, including whether
replay or a gap is expected. This binds the durable renaming that C1 requires
(`{namespace}-{topic}-durable`, replacing today's `nats_durable_name` default) exactly as it binds
filter derivation: on first deploy, every pre-existing consumer becomes a new consumer.

**Fan-out MUST be observable.** The framework **MUST** expose, per subject, how many namespaces
select it. With the unhandled-event counter of sec. 7.2 this covers both directions of the same
error: an event nobody wanted, and an event offered to far too many.

Build-time gates on subject breadth belong to the implementation plan rather than here, because
they constrain projects rather than the framework. They **SHOULD** ship as warnings before they
become errors: the frozen compat suite and the generated-project smoke test cover runtime API and
would not catch a newly failing build.

---

## 8. Caches

Caches are looked up by name with no namespace dimension, which makes them a cross-agent
collision surface: two independently developed agents both calling `get_cache("sessions")` share
one cache the moment they are grouped, invisibly and only in production.

Cache names **MUST** therefore be namespace-scoped by default, with an explicit opt-in for
genuinely shared caches. Agents share no cache by design, so isolation is the correct
default.

`registry.cache_service` (getter and setter) **MUST** be retained as an alias for the `"default"`
cache in the root namespace.

---

## 9. Startup

1. `GroupConfig.resolve(config)` -- file, then env overrides; log provenance.
2. Validate every agent name against the in-image agent map. Fail with the group and the missing
   agent named.
3. Import each agent module lazily; read its module-level `registration`.
4. `AppBuilder(config).with_group(group)` -- one `with_namespace` per agent.
5. `build()`, then `run_app(app, config)`.

Resolution **MUST** complete before the first `Component.__init__`, because namespace injection
happens through a `ContextVar` read during construction. No incremental resolution.

### 9.1 Failure policy

There is no partial build: one process, one `build()`. The `critical` flag is therefore evaluated
**before** a namespace is wired, not after an exception.

| Failure | `critical: true` | `critical: false` |
|---|---|---|
| Agent missing from the agent map | exit non-zero | log ERROR, skip |
| Module import raises | exit non-zero | log ERROR, skip |
| `on_startup` raises | exit non-zero | mark namespace down, pause consumers (C4), continue |

Exit **MUST** happen before the port is bound, so Kubernetes crash-loops with a readable message
rather than reporting a healthy pod that is silently short-staffed.

The default for an unflagged agent is `critical: true`: a partially loaded group whose missing
agent's queue has no consumer is a worse failure than no pod at all.

### 9.2 Startup log

**MUST** include: group name, agent list, the source of each resolved config value, and per
namespace the queue group and durable names. The last item makes C1 verifiable by diffing startup
logs across a regrouping.

---

## 10. Backwards compatibility

An existing single-agent project **MUST** continue to work with no source change, no Dockerfile
change, and `uvicorn src.main:app` as its entrypoint. Specifically:

| Concern | Guarantee |
|---|---|
| `AppBuilder` fluent API | Unchanged; `namespace` added keyword-only. |
| `with_cache(False)` / `with_cache(True, False)` | Unchanged (sec. 4.2). |
| `Component` subclasses | No constructor change (sec. 4.3). |
| `registry.cache_service` | Retained as alias. |
| Liveness / readiness | `readiness_policy = "all"` reproduces today. |
| Telemetry | Namespace `""` keeps `otel_service_name`. |
| Threads | Executor lazy; no threads unless used. |
| `Phase 7 get_runtime_name` | Purely additive -- `process_event` resolves no agent today; `runtime_name` is only logged (`event_processing_service.py:74`). |

`Registry._components` changes from `dict[str, Any]` to two levels. It is underscore-private, but
anything subclassing `Registry` or introspecting it breaks; this **MUST** be release-noted.

### 10.1 The exception

The transport fixes in sec. 7.1 and 7.2 change behaviour for already-deployed systems, without
changing any signature:

- Multi-replica deployments stop double-processing.
- JetStream deployments stop redelivering every message forever.

Both are bug fixes and neither is opt-out-able, since leaving them means the framework cannot be
scaled. They **MUST** ship as their own release with explicit notes, not folded quietly into the
grouping work.

### 10.2 Enforcement

- A **frozen compatibility suite** exercising today's usage patterns, including
  `with_cache(False)` and `with_cache(True, False)` positionally. It is never updated to the new
  API; if it needs editing, a break shipped.
- A **generated-project smoke test**: `asbs setup`, then build and start the result unchanged
  against the new framework version. Catches the Dockerfile and `main.py` paths unit tests miss.

---

## 11. Developer-facing surface

An agent author's `main.py` is, in full:

```python
registration = (
    AgentRegistration()
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_rest_api(OrderApi)
)
```

No `AppBuilder`, no `Config`, no `run_app`, no `if __name__`, no namespace, no group. The
dual-branch `main.py` in the current plan -- which duplicates the component list under
`if __name__ == "__main__"` and `else:` -- **MUST** be collapsed to this single declaration; two
branches to keep in sync is itself a leak of the grouping model.

`asbs dev agents/<name>` runs one agent as a group of one, using its **real** namespace. Local
routes are therefore `/api/order/orders/{id}`, identical to production, and local consumer
identity is the production queue group. A dev mode that ran at `namespace=""` would give every
developer local URLs and integration tests that differ from production.

Consequently `namespace=""` is reserved for pre-migration agents. Every newly scaffolded agent
**MUST** have a real namespace in every environment.

### 11.1 What cannot be hidden

Three mistakes are harmless in isolation and fatal in a group. They **MUST** be caught
mechanically, because a rule that cannot be violated locally will not be followed:

| Mistake | Detection |
|---|---|
| Blocking the event loop | dev mode sets `loop.set_debug(True)` with a slow-callback threshold; production **SHOULD** keep a higher-threshold watchdog that names the executing namespace (C7) |
| Module-level side effects (clients built at import, `basicConfig()`) | CI: import each agent module, assert the registry is empty and the root logger has no handlers |
| Non-idempotent handlers | explicit flag at scaffold time and in `asbs validate` (sec. 7.4) |

Two things an author still needs to know: their agent's name, and that handlers must not block.

---

## 12. Acceptance criteria

- [ ] Two agents in one process; an event on a topic both subscribe to reaches both, once each.
- [ ] Two replicas of a two-agent group: each event processed exactly once per agent.
- [ ] Durable and queue names byte-identical across two builds where the same agent sits in
      different groups (C1).
- [ ] Spans from namespace `invoice` carry `service.name = "invoice"`; a `namespace=""` app keeps
      `otel_service_name` (C2).
- [ ] A degraded namespace: liveness `UP`, readiness per policy, `blueprint_namespace_up = 0`,
      that namespace's consumers stopped (C3, C4).
- [ ] `<agent>.model_name` overrides root `model_name` for that namespace only (C5).
- [ ] No supported API exposes group membership to agent code (C6).
- [ ] Every path that stops a namespace serving emits an ERROR event and
      `blueprint_namespace_up{agent} = 0` carrying that namespace's identity; a namespace whose
      subscriptions vanish while the process stays healthy is reported within one scrape interval
      (C7).
- [ ] No framework-created task is detached without a done-callback that logs exceptions with the
      namespace attached; asserted by a test that fails a task in each background path (C7).
- [ ] File-only, env-only and combined resolution produce identical groups; env overrides the file
      key by key.
- [ ] The CI gate fails when an environment's group declaration omits an agent present in the
      in-image agent map (sec. 13).
- [ ] Cron fires once across three replicas in both `scheduler_mode` values (#73).
- [ ] `scheduler_mode = "event"` starts no timer, and the generated `CronJob` matches the schedule
      declared in agent code.
- [ ] An event that matches no handler is acknowledged, not redelivered: the transport edge
      behaves identically for `PROCESSED` and `NO_HANDLER_FOUND` (sec. 7.2).
- [ ] The same outcome yields the same disposition on both transports -- `CriticalHandlerError`
      drops on Dapr and terms on NATS, and a payload that fails to parse never naks (sec. 7.2).
- [ ] A handler declaring no topics and no event types is still evaluated for every event its
      namespace receives (sec. 7.7).
- [ ] A namespace's derived `filter_subjects` is never narrower than its declared topics unioned
      with `nats_subscriptions` (sec. 7.7).
- [ ] Unhandled events per (namespace, topic) and namespaces-per-subject fan-out are both exposed
      (sec. 7.2, sec. 7.7).
- [ ] Frozen compat suite and generated-project smoke test both green (sec. 10.2).
- [ ] Idempotency off by default, with the requirement surfaced at scaffold time and in
      `asbs validate`.
- [ ] Marginal RSS per additional idle namespace measured and published, reusing #36's benchmark
      harness. #32 measures ~6 MB per forked child with shared libraries; a namespace should be
      materially below that, and this number is what retires the lazy-agent idea for good.

---

## 13. Open questions

- **Is `deployment-groups.yaml` authored per environment, or one file with per-environment
  overrides?** This is a trade-off rather than a gap: per-environment files are
  readable without resolving inheritance and fit the difference actually being expressed
  ("collapse every group into one" for dev is a different document, not a patch), while a single
  overridden source avoids repeating the agent list and makes the *difference* the reviewable
  artifact. Whichever is chosen, the duplication risk is *forgetting* an agent rather than the
  duplication itself, and that is mechanically checkable -- the in-image agent map already
  enumerates every agent, so the CI gate **SHOULD** require each environment's declaration to
  account for all of them. Open: which shape, and how many environments actually differ.
- Is the dedup cache per-namespace or shared, and what TTL is defensible against the redelivery
  window?
- **#32's metric needs restating.** "Per-agent RAM" stops being meaningful once the interpreter is
  shared; the correct unit is *baseline per group + marginal per agent*. Its "as-is 160-250 MB per
  agent" row describes the model being retired, and its acceptance criteria should be re-expressed
  in the new unit before they are used to judge this work.
- **Is the 4 GB host budget real?** #32 says "100 agents on a 4 GB host"; this spec assumes
  Kubernetes with one Deployment per group. If 4 GB is a hard constraint, group count is capped at
  roughly 10 at today's 154 MB baseline (rising to ~20 if #33 lands), which materially narrows the
  isolation this design sells. #75 flagged the same ambiguity and it remains unanswered.
- Earlier design context assumed "20+ agents"; #32 targets **100 agents in 4 GB**. Grouping
  heuristics, connection totals and executor budgets all change materially at 100. Which figure
  is the design target?
- **For `scheduler_mode = "in_process"`, is true failover required** (a dead leader taken over
  within a bound), or is "one designated instance runs it, others no-op" enough? The cheap
  ordinal-check answer does not work under a Deployment, which has no stable ordinal, so a lease
  is likely needed either way.
- **Who owns the subject taxonomy?** Pushing selection into the subject (sec. 7.7) only works if
  publishers encode the discriminator, and the publishers are other services. `topic_mapping` lets
  the framework enforce symmetry once a scheme exists, but it cannot invent the token order.
  `<domain>.<entity>.<action>` is the usual shape. Open: who ratifies it, and how a subject is
  added.
- **What is the consumer-count budget?** One hundred agents times a few subjects each is several
  hundred JetStream consumers, each with its own ack-pending state. The connection ceiling was
  closed as a non-issue (sec. 6); consumer count is the analogous question and has not been asked.
- **Do agents eventually become separate distributions?** Build-time dependency trimming would
  require it, which is when the agent-to-module map should migrate to entry points. Not needed
  while trimming stays opt-in.