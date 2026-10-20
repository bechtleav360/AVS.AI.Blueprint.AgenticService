# Spec -- Multi-Agent Grouping

| | |
|---|---|
| **Implementation plan** | `docs/plans/2026-08-28-multi-agent-grouping.md` |
| **Resolves** | #75 (deployment model decision), #73 (duplicate cron ticks) |
| **Unblocks** | #32 (100 agents in 4 GB), #35 (shared interpreter), #20 (worker scaling) |
| **Related** | #33 (lazy heavy imports), #34 / #74 (dependency slimming), #36 (concurrency bounds + benchmark), #43 (scheduler double-start), #6 (config service) |
| **Amended by** | `docs/plans/2026-09-10-builder-unification.md` -- decided 2026-09-10, folded into sec. 2, 4, 5.3, 8, 9, 10 and 11 below. |
| **Amended by** | `docs/plans/2026-09-28-grouped-http-surface.md` -- decided 2026-09-28, folded into sec. 10 and 11.2 below. |
| **Amended by** | PR #96 review, 2026-10-19 -- brought in line with the implementation: C1 (root/agent durable clash), C2 (resolved group, per-provider metric readers, declared OTel keys), C4 (pause instead of close), sec. 2 and 11 (standalone agents at the root), 4.1 and 9 (`AgentGroup.resolve` / `from_config` / `assemble`), 4.2 (handler order restored, not refused), 5.1 (further group-file refusals), 5.3 (config refusals; process-scope keys dropped with a WARNING), 6 (resolved group; history), 7.1 and 7.2 (history; `SKIPPED`; `<undeclared>`; `max_deliver` optional), 7.4 (dedup key), 7.5 (no default mode; claim atomic on Redis only; slot from the fire time; crontab rules; `scheduler_timezone`), 9.1 (no agent left), 10 (instances refused by `build(config)`), 11.1 (`event_loop_debug`, watchdog), 12 (claim criteria scoped to Redis). Each change is marked in place. |
| **Deferred out of** | `docs/plans/2026-09-10-config-validation-unification.md` -- configuration validation is not part of this feature. |

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
| **Namespace** | The registry partition an agent's components live in. Equal to the agent name. `""` is the root namespace: where a standalone application runs -- a pre-migration single-agent app, or any agent served on its own (sec. 11). *(Amended 2026-10-19, PR #96 review: a scaffolded agent served standalone runs at the root too.)* |
| **Group** | The set of agents loaded into one process, and therefore into one pod. |
| **Declaration** | An `AppBuilder` whose `build()` has not been called -- component classes recorded without instantiation. |
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
- JetStream durable: `f"{namespace}-{topic}-durable"`; when the namespace is `""`, the configured
  `nats_durable_name` (one topic only), else `f"{topic}-durable"`. Only the topic is rewritten to
  suit a consumer name; the namespace reaches it as declared. *(Amended 2026-10-19, PR #96
  review: the root's bare form stated.)*
- Namespace alphabet: a namespace **MUST** be `""` or match `[a-z][a-z0-9_]*`, and **MUST** be
  validated where it enters the framework rather than by each consumer of it. It becomes a
  registry key prefix, a queue group, part of a durable name and a telemetry `service.name`, and
  a value each of those repairs differently is one agent under four names. Two exclusions do not
  follow from any single consumer:
  - `-` is the separator in the durable name above. With it allowed, namespace `orders-eu` on
    topic `created` and namespace `orders` on topic `eu-created` produce one durable name, so two
    agents would bind one JetStream consumer and consume each other's events.
    The exclusion separates agents from each other, not the root from an agent: the root's bare
    `f"{topic}-durable"` has no namespace segment, so root topic `orders-created` and agent
    `orders` on topic `created` still derive one name (`orders-created-durable`). That clash
    **MUST** fail rather than share a consumer: the client refuses to bind a durable whose filter
    is another subject (`JetStreamBindingError`), naming the consumer and the fix. *(Amended
    2026-10-19, PR #96 review: the root/agent clash is not prevented by the alphabet, and is
    refused at bind.)*
  - `<` and `>` keep the sec. 6 connection-name placeholders unforgeable. `>` is a NATS wildcard
    and illegal in a consumer name in any case.

**A name that crosses the process boundary MUST be validated, never repaired.** This covers every
name that becomes part of a subject, a queue group or a consumer: the namespace, `app_name` and
`nats_queue_group` where they stand in for it, and a scheduler's name where it forms the tick
subject. Silently rewriting one -- an `app_name` of `"My Service"` becoming `My_Service` in a
subject -- leaves the party on the other side of the contract, typically a `CronJob` in another
repository written by someone who has never read this framework, publishing to a subject nothing
subscribes to. The tick simply never arrives, and no log on either side says why. The side that
knows the name is unusable **MUST** fail its own startup instead, naming the key, the value and
the subject that would have been derived.

Two rewrites are permitted, and only these:

- The **topic** portion of a durable name. Dots are idiomatic in subjects and illegal in consumer
  names, so there is no alternative; it is bounded by the requirement that two topics resolving to
  one durable name is an error, and the mapping is documented. Within one client the clash is
  refused when the durables are resolved; between the root and an agent it is refused at bind
  (above). *(Amended 2026-10-19, PR #96 review.)*
- The **connection name** (sec. 6), which exists for attribution and which C1 forbids anything
  from deriving from, so no external party can depend on its spelling.

**The namespace MUST be validated in `Component.__init__`**, not in `Registry.add_component` and
not per base class. Every component passes through that constructor, including the eight that
opt out of registration, and it runs before the registry name is derived. A gate in the registry
would miss unregistered components -- among them the eventing endpoints, which become
namespace-owned in phase 2.
- The NATS **connection name** (sec. 6) is deployment-specific and **MUST NOT** be used to derive
  either of the above.

### C2 -- Telemetry identity derives from the agent

Each namespace **MUST** have its own `TracerProvider` and `MeterProvider` with
`Resource({"service.name": <namespace>, "deployment.group": <group>, "service.instance.id": <pod>})`,
subject to the declared keys below. `<group>` is the group the process resolved --
`BLUEPRINT_GROUP`, or the one group a group file declares -- and `deployment.group` is absent when
no group was resolved; `service.instance.id` is absent when the pod cannot be determined.
*(Amended 2026-10-19, PR #96 review: the group is the resolved one, not only the variable, and the
resource carries no placeholders.)*

All providers share one `BatchSpanProcessor` per exporter. Metric readers cannot be shared -- the
SDK binds a reader to the provider that registered it -- so each provider has its own reader over
the one shared metric exporter. The shared processor and exporter count the providers holding them
and are shut down by the last one; shutdown runs the agents' providers first and the root's last,
because the root's is the global provider. *(Amended 2026-10-19, PR #96 review: replaces "SHOULD
share one exporter and one `BatchSpanProcessor`"; per-provider readers and reference-counted
shutdown as implemented.)*

When the namespace is `""`, the provider **MUST** use `otel_service_name` from config, reproducing
current behaviour exactly (`io/telemetry/telemetry.py:39-41`).

**Keys the deployment declares.** *(Amended 2026-10-19, PR #96 review: describes the current
behaviour; decision D23 (c) in `docs/plans/2026-10-16-pr96-review-fixes.md` is open and may change
it.)* A key set in `OTEL_RESOURCE_ATTRIBUTES` or by `OTEL_SERVICE_NAME` is used as declared and
replaces the framework's value, on every provider. The one exception is `OTEL_SERVICE_NAME` in a
group: every agent's provider keeps `service.name = <namespace>`, the root's provider takes the
declared name, and one startup WARNING names the value and says it applies to the root only. A
`service.name` given only in `OTEL_RESOURCE_ATTRIBUTES` is not excepted, so it currently names
every agent of a group alike.

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
per-namespace transports (sec. 6) this is pausing that namespace's consumption, not closing its
client: its NATS client drains its own subscriptions and keeps its connection open, its sessions
job stream (`SessionsBus`) is paused likewise, and both resume when the namespace's health checks
pass again. A JetStream delivery that still reaches a paused namespace is nak'd without running;
under Dapr the event is not offered to the paused agent and is answered `RETRY`. *(Amended
2026-10-19, PR #96 review: paused and resumed rather than closed -- a closed client reports
unhealthy for ever, so the pause could never end, and publishing stays available.)*

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
  group-wide failure class that is detectable from inside the process. *(Amended 2026-10-19, PR #96
  review: met by the loop watchdog, on by default in every environment; it names the agents with
  work in flight, since the blocking callback has returned by the time it runs. asyncio's debug
  mode is opt-in, sec. 11.1.)*

Grouping removes the pod restart that used to serve as the alert, so the alert **MUST** be emitted
deliberately rather than inferred from a restart.

---

## 4. Public API

### 4.1 New

*(Amended 2026-10-19, PR #96 review: the names as implemented. `AgentGroup(config)` /
`.add()` / `.with_group()` / `.from_group()` / `.build()` became a constructor over named
declarations, `from_config`, `resolve` and `assemble`.)*

```python
class AgentGroup:
    """The agents one process hosts, and the single application they become."""
    def __init__(self, name: str, agents: Mapping[str, AppBuilder], *,
                 settings=None, secrets=None, roots=None, critical=None) -> None: ...

    @classmethod
    def resolve(cls, config: Config) -> "AgentGroup"          # GroupConfig.resolve + from_config

    @classmethod
    def from_config(cls, group: GroupConfig) -> "AgentGroup"  # import each module the group names

    def assemble(self, config: Config) -> FastAPI             # one root builder, one build()


class GroupConfig:
    """Resolved group composition. A value object; performs no I/O once constructed."""
    name: str
    agents: tuple[AgentSpec, ...]      # name, module path, root, critical flag
    image_root: Path
    # No cache list: an agent may use only the caches it declared itself (sec. 8).

    @classmethod
    def resolve(cls, config: Config) -> "GroupConfig":
        """Read file + env, validate against the agent map, or raise GroupConfigError."""


def run_app(app: FastAPI, config: Config) -> None: ...
```

`GroupConfig.resolve` is the only member that reads the environment, the group file or the agent
map. `AgentGroup.from_config` **MUST NOT** read the environment -- importing the agent modules a
`GroupConfig` names is not a configuration read -- so tests can construct a `GroupConfig`
literally. *(Amended 2026-10-19, PR #96 review: `from_config` replaces `with_group`; besides the
imports it checks each agent's directory layout and whether `settings.toml` / `.secrets.toml`
exist there, and `assemble` reads those files, sec. 5.3.)*

**Collection is its own class, and `AppBuilder` MUST NOT know it can be collected.** An
`AppBuilder` never absorbs another builder and exposes no group concept; `AgentGroup` constructs
its own and replays what each agent recorded. This is what keeps one fluent surface honest: the
group's restrictions belong to the thing imposing them, so `AppBuilder` stays permissive and every
refusal in sec. 4.2 is raised by `AgentGroup` -- except the instance refusal, which
`AppBuilder.build(config)` applies too (sec. 10). *(Amended 2026-10-19, PR #96 review.)*

### 4.2 Changed

```python
class AppBuilder:
    """One declaration surface. Records what it is told; wires nothing until build()."""
    def __init__(self, config: Config | None = None) -> None: ...

    # with_handler / with_service / with_agent / with_scheduler / with_rest_api:
    #   signatures unchanged. They record; nothing is constructed until build().

    def with_cache(self, enabled: bool = True, enable_locking: bool = True,
                   *, name: str = "default") -> "AppBuilder"
    def with_health_checker(self, name: str, checker) -> "AppBuilder"

    def build(self, config: Config | None = None) -> FastAPI

    @property
    def declarations(self) -> tuple[Declaration, ...]        # what AgentGroup replays
```

**Deferred wiring is normative.** A `with_*` call **MUST NOT** construct a component or enter
anything into the registry; both happen only in `build()`. This is not a style preference:
constructing a component reads the namespace from a `ContextVar` (sec. 4.3), so one built during a
`with_*` call belongs to whichever namespace was in force at that line and can never be moved
afterwards. Recording instead of constructing is what lets one class serve both the standalone and
the grouped shape, and it is why no second collector type (`AgentRegistration`, `NamespaceBuilder`)
needs to exist.

`AppBuilder.build()` wires at the **root** namespace. There **MUST** be no `with_namespace` method
and no `namespace` parameter on any `with_*` method: standalone has no namespace to name, and an
agent's name lives only in the group configuration (sec. 11).

**Configuration resolution:** `build(config)` or `AppBuilder(config)` -- giving both **MUST** be
refused -- else the default settings files. *(Amended 2026-10-19, PR #96 review: `build()` raises
when a configuration is given twice; there is no precedence between the two.)* `AgentGroup` **MUST** refuse a builder that carries its own
configuration -- one process has one settings tree and one port -- and **MUST** wire each agent
with that agent's own scoped view (C5).

**What `AgentGroup` refuses, each because a group cannot honour it:**

| Recorded call | In a group | Capability lost |
|---|---|---|
| a class plus kwargs | allowed | -- |
| a factory or lambda | allowed; called inside the namespace scope | -- |
| an already-constructed **instance** | **refused** -- its namespace and registry key were fixed before the group existed | none: the factory form recovers it |
| `AppBuilder(config)` | **refused** -- one process, one settings tree, one port | none |
| `with_cache(...)` | allowed; the name is qualified per agent (sec. 8) | -- |
| `with_health_checker(...)` | allowed; the key is qualified per agent | none |
| a builder whose `build()` already ran | **refused** -- already wired at the root | none |

Every refusal **MUST** name the agent and the fix. Refusals land at assembly, not at authoring
time: `with_cache()` runs at import, long before anything knows whether this builder will be
collected.

**Registration order keeps its meaning.** An instance is constructed by the caller at its own
source line, a class during `build()`, so an instance recorded *after* a class would register
*before* it -- which can flip equal-priority handler tie-breaking, resolved by registration order
today. `build()` knows both the recorded order and which entries were instances, and **MUST**
register the handlers in declaration order: after the replay it puts them back into the
registry slots they already hold, in the order they were declared, so nothing else the registry
holds moves. *(Amended 2026-10-19, PR #96 review: replaces "MUST raise on that combination rather
than silently reordering" -- restoring the declared order keeps tie-breaking as written without
refusing a valid declaration. The case arises only where instances are accepted -- `AppBuilder(config).build()`,
or `build()` with no argument; `build(config)` and a group refuse instances.)*

**`with_cache` is the one place where the obvious design breaks compatibility.** The current
signature is `with_cache(enabled: bool = True, enable_locking: bool = True)`
(`app_builder.py:117`). Making `name` the first parameter would turn an existing
`with_cache(False)` -- meaning *disable caching* -- into a cache named `False`, silently enabling
the cache with no `TypeError`. `name` therefore **MUST** be keyword-only and **MUST** follow the
two existing positional parameters.

### 4.3 Component

`Component.__init__` **MUST NOT** gain a namespace parameter. The namespace is read from a
module-level `ContextVar` set by `AgentGroup` around each agent's wiring, so no user subclass
constructor signature changes and no positional argument shifts.

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

Resolution **MUST** fail with `GroupConfigError`, naming the file or variable and the fix, when:
a group file declares one group name more than once; `agents` or `critical_agents` in the file
is not a list (a scalar is refused, not split); a group names one agent twice; or the critical
names (`critical_agents` / `BLUEPRINT_CRITICAL_AGENTS`) include an agent the group does not run
-- once critical names are given, every agent they do not name is non-critical, so a misspelt
name would make the whole group non-critical. *(Amended 2026-10-19, PR #96 review: refusals as
implemented.)*

Both mechanisms **MUST** be supported; neither is preferred. The file suits ConfigMap mounts and
local development, env vars suit `docker run` and CI, and env values live in the pod template so
changing them triggers a rolling update on their own.

### 5.2 Runtime keys

Defaults corrected 2026-10-15 to what ships: the NATS limits are unset unless configured, and
the server's defaults apply (feature changelog, named connections step 6).

| Key | Default | Meaning |
|---|---|---|
| `readiness_policy` | `"all"` | See C3. |
| `executor_workers` | `os.cpu_count() + 4` | Per-namespace thread pool size. Bounded per #36. |
| `nats_queue_group` | `app_name` | Queue group for the root namespace only. |
| `nats_ack_wait` | unset -- the server's (NATS: 30 s) | Seconds. **MUST** exceed p99 handler duration unless the heartbeat is on (it is by default: a running delivery reports `in_progress` every third of `ack_wait`). See sec. 7.3. |
| `nats_max_ack_pending` | unset -- the server's (NATS: 1000) | Per-consumer, shared across replicas. `-1` unlimited. Keep it near replicas x `nats_max_concurrent_runs`: what a pod receives beyond the runs it has started waits in the client's queue while its `ack_wait` runs. |
| `nats_max_deliver` | unset -- the server's (NATS: unlimited) | Attempts before the message is dead-lettered. `-1` unlimited, and then nothing is ever dead-lettered. |
| `nats_max_concurrent_runs`, `nats_extra_runs_per_process`, `nats_handler_timeout`, `nats_heartbeat_enabled` | see the configuration reference | Concurrent runs per (agent, connection), the process pool beyond each pair's guaranteed run, a per-run time limit, the `in_progress` heartbeat. Added by `docs/plans/2026-10-14-named-connections.md`. |
| `nats_connection_source`, `nats_connections_readiness`, `nats_unclaimed_subjects` | see the configuration reference | Named connections. Same plan. |
| `nats_dead_letter_subject` | `<queue group>.dead-letter` | Where a message the framework gives up on is republished. Derived from the agent's identity, as the queue group is (C1). `""` disables it and loses those payloads. **MUST NOT** be a wildcard or a subject the same namespace consumes. |
| `idempotency_enabled` | `false` | Opt-in dedup. See sec. 7.4. |
| `idempotency_ttl` | -- | Dedup window. |
| `scheduler_mode` | -- (**required** with a scheduler) | `"event"` or `"in_process"`. Deliberately without a default; per namespace. See sec. 7.5. |
| `event_publishing_enabled` | `false` | Opt into publishing without consuming. Requires `event_bus`. See sec. 7.5. |

### 5.3 Settings authoring

A group's own `settings.toml` supplies **defaults, and only defaults**. An agent author writes
plain top-level keys in their own directory's `settings.toml` (`model_name = "..."`), not
`[default.<agent>]`, and the build **MUST** merge that fragment **under that agent's scope** so C5
resolves it, without the author knowing the scope exists.

An agent may therefore set any key for itself, and **MUST NOT** be able to change what another
agent or the process sees. A fragment and a root key never occupy the same slot, and a default
restated in an agent's fragment is simply that agent's own value. Where a slot *could* be
shared, the framework **MUST** refuse rather than merge or resolve, naming the agent and the key:
*(Amended 2026-10-19, PR #96 review: replaces "there is consequently no collision to report" --
these cases exist and are refused.)*

- a root key named like the agent whose value is not a section -- merging the fragment would
  replace that value for the whole process (`ConfigError`);
- an agent named like a configuration section the process shares (`cache`, `event_publishing`,
  `runtimes`, `runtime`) -- refused by namespace validation, since its fragment would be merged
  into that shared section;
- a bare key naming another agent, read through an agent's view -- at the root it is that agent's
  whole section (`ValueError`), as is a dotted key outside the shared nested sections;
- a fragment that scopes its keys under the agent's own name (`[default.<agent>]`), which would
  nest as `<agent>.<agent>.*` and be read by nothing (`ConfigError`).

Process-scope keys in an agent fragment **MUST** be dropped at startup with a WARNING per key
naming the agent, the key, the file and the value the process uses instead (a secrets file's
values are not logged), from an explicit list: `PROCESS_SCOPE_KEYS` (`app_port`, `app_host`,
`app_workers`, `app_environment`, `envvar_prefix`, `event_bus`, `log_level`, `log_format`,
`suppress_noisy_loggers`, `health_check_interval_seconds`, `startup_retry_interval_seconds`,
`readiness_policy`, `dot_placeholder`, `nats_stream_name`, `nats_connection_source`,
`nats_extra_runs_per_process`) plus the deployment-identity keys (`blueprint_group`, `pod_name`,
`hostname`). Scoped, such a key is read by nothing and reported by nothing -- C7's failure mode
in configuration form -- and the WARNING is what lets its author discover that the value they set
is inert. *(Amended 2026-10-19, PR #96 review: replaces "MUST raise" -- every example project
declares `app_port` and `app_environment` in its settings file, so raising would bar any existing
project from a group until edited; the list is longer than the four keys first named.)*

What happens when a *required* key is absent is deliberately not specified here. It is
`docs/plans/2026-09-10-config-validation-unification.md`, kept out of this feature so that the
two cannot fail together.

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
3. **Attribution.** When this spec was written, `nats.connect()` was called with no `name=`, so
   every connection the framework opened was anonymous in `/connz`. Per-namespace named
   connections make a pod's contents legible in connection-oriented tooling. *(Amended
   2026-10-19, PR #96 review: implemented; the defect is history.)*

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
broker, or an operator-mode account whose JWT carries a `conn` limit set by someone else. Such
authentication is wired: user and password, token, an nkey seed and a credentials file
(`nats_creds_file`) reach `nats.connect()`. *(Amended 2026-10-19, PR #96 review: "no such
authentication is currently wired" is history.)*

A namespace that neither subscribes to anything nor publishes anything **MUST NOT** be given a
client. A pure-scheduler agent on `scheduler_mode = "in_process"` that does not opt into publishing
(sec. 7.5) is that case: a connection for it is a socket, a readiness dependency and a `/connz`
entry for traffic that does not exist, and it would put a pod on a broker that the agent's own
deployment may have no access to. The cost argument above justifies a connection *per namespace
that uses one*; it does not justify one per namespace that does not.

Connection name **MUST** be `f"{namespace}.{group}.{pod}"`, and **MUST NOT** feed C1 naming.
**Exception -- a standalone agent** (namespace `""` and no resolved group): the name **MUST** be
the pod alone, and **MUST** be omitted when the pod cannot be determined. Neither a namespace nor a
group exists for it, and `<root>.<ungrouped>.<pod>` would imply a grouping that is not there; an
omitted name is what a standalone agent sent before this feature. The root of a process whose
group is named keeps the full form.
The group is the one the process resolved: `BLUEPRINT_GROUP`, or the one group a group file
declares when the variable is unset. *(Amended 2026-10-19, PR #96 review: the resolved group, not
only the variable -- a group named by the file alone reached neither the connection name nor the
telemetry resource.)*
An absent segment **MUST** be filled with a placeholder rather than left empty -- `<root>` for the
root namespace, `<ungrouped>` when no group was resolved, `<unknown-pod>` when the replica
cannot be identified -- so all three positions always carry a value, a name never degenerates into
`..pod-7`, and "no group" stays distinguishable from a group whose name happens to be empty.

The placeholders **MUST** be unproducible by a real value rather than merely unlikely, because a
placeholder that collides with a legitimate name reintroduces exactly the ambiguity it was
introduced to remove. Two rules give that:

- The namespace alphabet (C1, below) excludes `<` and `>`, so no legal namespace can spell one.
- The group and the pod are supplied by the deployment and **MUST NOT** be rejected on this
  ground -- failing a rollout over a display string is the wrong trade -- so they **MUST** be
  sanitised for display instead: `<`, `>`, `.` and whitespace replaced. Replacing `.` is not
  cosmetic; it keeps a group called `a.b` from turning a three-segment name into four and
  misattributing the connection. Sanitising rather than validating is acceptable here only
  because nothing derives from the connection name (C1), so a mangled segment loses no
  information any consumer depends on.

`EventPublishingService` **MUST** publish on its own namespace's client; otherwise outbound
traffic is unattributable and reason 3 is defeated.

Per-namespace clients also make C4 a per-client pause -- the client drains its own subscriptions
and keeps its connection -- rather than selective unsubscription on a shared client, and give
`ClientHealthChecker` per-agent health entries that feed `readiness_policy = "critical"` directly.
*(Amended 2026-10-19, PR #96 review: a pause, not a close; see C4.)*

---

## 7. Event delivery

### 7.1 Competing consumers

With N replicas of a group, exactly one replica **MUST** process any given event. Core NATS
subscriptions **MUST** pass a queue group; JetStream consumers **MUST** share a durable per C1.

When this spec was written the code did neither: core subscriptions passed no `queue=`, so
`replicas: 2` doubled every side effect and every inference bill -- a defect independent of
grouping (see #20, #35). Core subscriptions now pass the queue group (C1) and JetStream consumers
share their durable with a deliver group; JetStream stays off by default (`nats_use_jetstream`).
*(Amended 2026-10-19, PR #96 review: the defect is history.)*

### 7.2 Acknowledgement

When this spec was written, JetStream subscriptions used `manual_ack=True` and **no `msg.ack()`
call existed anywhere in the codebase**, so every JetStream message redelivered until
`max_deliver` -- already a defect at one replica. Every JetStream delivery is now settled
(`ack`, `nak` or `term`) per the table below. *(Amended 2026-10-19, PR #96 review: the defect is
history.)*

**Decision: ack after the handler completes.** The alternative (ack first) converts a connection
blip from duplicate work into *lost* work, which is worse for expensive, side-effecting inference.
Consequently at-least-once is permanent, and sec. 7.4 applies.

**The contract is that a normal return acknowledges and a raised exception does not.**
`ProcessingStatus` carries no failure value -- it is `PROCESSED`, `NO_HANDLER_FOUND` or `SKIPPED`
-- so every failure already reaches the transport as an exception. *(Amended 2026-10-19, PR #96
review: `SKIPPED` added, see below.)* The transport edge **MUST NOT** inspect
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
and under a queue group a loop that visits every replica in turn. When this spec was written the
Dapr endpoint returned `RETRY` for this case; it now answers `SUCCESS`. *(Amended 2026-10-19,
PR #96 review: the defect is history.)*

**An unmatched event is acknowledged, and it is reported as a probable misconfiguration
(changed 2026-10-15).** Deciding there is nothing to do is the handler's job: a handler that is
responsible for the event and finds no work in it returns `HandlerResult.skipped(reason)` (below),
which is an ordinary outcome, logged at INFO. An event that *no* handler takes therefore no longer
stands for "the agent found nothing to do" -- it means the agent is subscribed to something none of
its handlers routes, or a handler declines what it should claim. The framework **MUST** log it at
WARNING ("No handler processed event", from the handler chain) and **MUST** still acknowledge it,
since no redelivery makes a handler appear. It **MUST NOT** accumulate per-topic state about it --
under Dapr the topic arrives from a URL path, so remembering each distinct value lets a caller grow
the process's memory. (Before 2026-10-15 this paragraph required the opposite -- no WARNING --
because "nothing to do" could only be said by declining; the chain logged a WARNING regardless.)

It **MUST** be counted per namespace and topic, for one purpose: the *proportion* of received
events a namespace declines is how a too-broad subscription shows up (sec. 7.7). A high count is a
question about the subject filter, not about the handler. Under Dapr, a topic the agent did not
declare is counted under the topic label `<undeclared>` (every topic is, with
`dapr_declarative_subscriptions`), and the real topic stays in the log line; the same label
applies to the duplicate and skipped counters. *(Amended 2026-10-19, PR #96 review: the label is
what keeps a caller-chosen URL path from minting one time series per request.)*

**A skip is the selected handler's own "nothing to do" (added 2026-10-15).** A handler that is
responsible for an event -- `can_handle_event` routed it there -- and finds that this particular
event needs nothing returns `HandlerResult.skipped(reason)`. The chain stops (no later handler is
asked, unlike `None`), the run reports `ProcessingStatus.SKIPPED`, nothing is published, the reason
is logged at INFO, and the transport acknowledges as for any return. It is counted apart from
unmatched events, as `blueprint.events.skipped` per agent and topic: a skip is the agent's relevance
rule at work, not a sign that the subscription is too broad. A REST caller gets `success = true`
with the reason as message.

**Both transports MUST map the same outcome to the same disposition.** Dapr's response dict *is*
its acknowledgement, so the table above is normative for `dapr.py` and
`event_handling_base.handle_event` exactly as it is for `nats_client.py`. When this spec was
written they disagreed in two places: `NO_HANDLER_FOUND` as above, and `CriticalHandlerError`,
which the Dapr endpoint retried -- a critical error is not made less critical by being delivered
again. Both now map per the table. *(Amended 2026-10-19, PR #96 review: the defect is history.)*

`max_deliver` **SHOULD** be configured, because nak on an unexpected exception otherwise
redelivers indefinitely. `nats_max_deliver` is optional: unset, the server's default applies
(NATS: unlimited) and nothing is ever dead-lettered; `-1` asks for unlimited explicitly and is
warned about at startup. The dead-letter destination needs no configuration: it defaults to
`<queue group>.dead-letter` (sec. 5.2). *(Amended 2026-10-19, PR #96 review: replaces "MUST be
configured" -- the framework sets no consumer limits a deployment did not configure, sec. 5.2.)*

The nak on the last delivery `max_deliver` permits **MUST** be rendered as a dead letter followed
by a term, not as a nak. The broker will not redeliver it, so a nak there differs from a term only
in that the message leaves the consumer without a trace of why, and one `ack_wait` later than it
had to. A dead letter **MUST** carry the original payload bytes unchanged -- a payload that failed
to parse is the one most worth keeping -- with the reason, origin subject, delivery count and event
id in headers rather than in the body.

Implementations **SHOULD** capture the ack reply subject and retry the ack after a reconnect,
which narrows the duplicate window from "certain on any blip" to "only if the pod also dies".
Two caveats make this a prototype rather than a design commitment: a redelivery may already be in
flight when the retry lands, and the behaviour of acking a stale delivery attempt depends on how
the server keys pending state on stream sequence. **MUST** be validated against a real broker.

### 7.3 Long handlers

`ack_wait` **MUST** exceed p99 handler duration, or a slow handler is redelivered to another
replica while the first is still working -- unless the delivery is heartbeated. Since the
named-connections work (2026-10-14) a running JetStream delivery reports `in_progress()` every
third of its consumer's `ack_wait` by default (`nats_heartbeat_enabled`), and `nats_handler_timeout`
bounds a run. Heartbeats address slow handlers; they do **not** address connection loss, since
they travel over the same connection, and they do not cover messages still waiting in the client's
queue (bound those with `nats_max_ack_pending`).

**A run knows its attempt (added 2026-10-15).** Every JetStream delivery, on the default and on
named connections, puts `nats_delivery_attempt` (1-based, from `num_delivered`) and
`nats_max_deliver` (the consumer's limit; `None` when unlimited or unknown) into the handler
context, beside `nats_topic`, `nats_subject` and `nats_connection`. Equal values mark the last
attempt, after which a failure is dead-lettered or dropped. Core NATS deliveries carry neither key.

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

- provide an opt-in dedup mechanism keyed on the CloudEvent `(source, id)` -- plus the connection
  name for a delivery from a named connection (`nats_connection`) -- backed by the namespace's
  cache with a TTL, applied in the handler chain before dispatch (`idempotency_enabled`). The
  marker is claimed atomically before dispatch and kept only when the delivery is acknowledged
  as a success; every other outcome releases it so the redelivery can run, and only the delivery
  that won the claim releases it, never a duplicate. *(Amended 2026-10-19, PR #96 review: an `id`
  is unique only within a source, and the same producer behind two connections emits the same
  ids for different data; marker lifetime as implemented. Atomic across processes on Redis only,
  sec. 7.5.)*
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
| `"event"` | No in-process timer. *(Amended 2026-10-19, PR #96 review: "Default" removed -- neither mode is the default, below.)* An external scheduler (Kubernetes `CronJob`) publishes an event; the agent handles it through its normal event path. |
| `"in_process"` | `AsyncIOScheduler` in every replica, with each tick claimed in the shared cache so one replica runs it. For un-orchestrated Docker and local development. |

`scheduler_mode` **MUST NOT** have a default: registering a scheduler without it **MUST** fail
before the port is bound. Neither value is safe to inherit. `"in_process"` is the defect of #73 --
one timer per replica, multiplied by every grouped agent in the pod -- and `"event"` needs a
publisher and a transport that a service whose only job is periodic work may not have, so
defaulting to it silences that service instead. Which value is correct depends on the deployment
rather than the code: whether a broker is reachable, whether more than one replica runs, whether an
orchestrator exists at all. The author therefore states it, exactly as sec. 7.4 requires for
`idempotency_ttl`. `"event"` **MUST** additionally fail unless `event_bus` names a transport that
carries topics, since a scheduler subscribed to nothing never ticks and reports no fault.

`scheduler_mode` **MUST** resolve per namespace through C5, not once per process. A group may host
a pure-scheduler agent that has to run `"in_process"` alongside an event-driven agent on `"event"`,
and one process-wide value cannot express that -- which is exactly the deployment freedom grouping
exists to provide.

In `"event"` mode the framework **MUST NOT** start a timer, and the tick **MUST** be delivered as
an ordinary namespaced event, so the queue group already guarantees single execution across
replicas without electing anything. The publishing container **SHOULD** be a minimal NATS client
image, not the agent image -- a `CronJob` running the agent re-pays the ~154 MB baseline (#32) for
work that fires once a night.

The schedule **MUST** remain declared in agent code, and the `CronJob` **MUST** be generated from
that declaration -- the same generation path as manifests from `deployment-groups.yaml`. Hand-authored
schedules let code expect a tick nobody scheduled.

That generation path **MUST NOT** import a project's `src/main.py`. The declaration is reachable
without it: configure from the project's settings and import the modules that define the
schedulers. Generation **SHOULD** happen where the registrations are authored, and anything the
generator cannot observe -- a registration-time rename, a scheduler needing constructor arguments
-- **MUST** be reported rather than guessed at.

Because manifests belong to a deployment group rather than to a single project once one image
serves the platform (sec. 6, and the entrypoint model), the generator's input **SHOULD** be the
group's agent map rather than one project's source tree.

Independently of the manifest, the declared crontab **MUST** be validated in both modes, before
the port is bound. `"event"` mode builds no `CronTrigger`, so nothing else parses the expression,
and an invalid one otherwise presents as a scheduler that reports itself healthy and never ticks;
`"in_process"` mode parses it only at startup and does not read it as an external cron would. It
**MUST** be the five standard cron fields: an external scheduler reads those, and apscheduler's
extensions -- a leading seconds field in particular -- are not portable to one.

The day of the week is numbered as apscheduler numbers it, `0` = Monday to `6` = Sunday, which
disagrees with a standard cron (`0` = Sunday) on every number. Day `7` **MUST** be refused in both
modes (Sunday to cron, nothing to apscheduler). In `"event"` mode, where an external cron fires
the tick, a day of the week given by number -- including `*/n`, which steps from day `0` -- **MUST**
be refused: names (`mon-fri`, `sun`) read the same to both. *(Amended 2026-10-19, PR #96 review:
replaces "validated in `"event"` mode" -- validation runs in both modes, and the weekday rules are
added.)*

**In-process coordination is a per-tick claim, not a leader lease.** An earlier form of this
section called for a NATS KV or cache-backed leader lease. A slot claim satisfies the same
requirement and is preferred, because it removes rather than answers the failover question: every
replica's timer fires, each tries to store a marker keyed on `(scheduler, minute)` in the agent's
own cache -- shared across that agent's replicas when the cache is Redis, and per sec. 8 invisible
to every other agent, so two agents each running a scheduler of the same name cannot claim each
other's slots -- and the replica that stores it runs the tick. *(Amended 2026-10-19, PR #96
review: a disk cache is not shared across processes in a way the claim can rely on, below.)*
Nothing is elected and nothing is held, so there
is no renewal task to schedule (and therefore none to leak, C7), no lease left behind by a replica
that dies holding one, and no takeover bound to specify -- the next slot is claimed from scratch by
whoever is alive.

The claim **MUST** use a set-if-absent primitive rather than a read followed by a write:
`CacheService.claim`. Two replicas racing on an `exists`-then-`set` pair both pass the check and
both tick, which is the failure this mechanism exists to prevent.

`CacheService.claim` is atomic across processes only on the Redis backend. A disk cache's claim
holds within one process: processes sharing one cache directory -- replicas on a shared volume,
or `uvicorn --workers N` run by hand -- can each win the same key. Coordinating replicas therefore
needs Redis. *(Amended 2026-10-19, PR #96 review: measured with diskcache-rs 0.4.10, several
processes on one directory each won one key; how to proceed beyond documenting it is open, D22.)*

The key **MUST** be derived from the scheduled slot rather than from the scheduler alone. Cron
granularity is one minute, so replicas firing for the same scheduled time derive the same key and
the next scheduled time derives a different one -- which is what keeps set-if-absent sufficient.
The slot is the trigger's latest scheduled fire time at or before the current time, as a UTC
minute, not the clock at run time: a run that starts late, or on a replica whose clock is a little
ahead, still claims the slot it was scheduled for, and fire times that passed without a run are
walked over rather than claimed late. Without a trigger, or before its first fire time, the clock
decides. Clock skew therefore splits a slot only when it outlasts the marker (300 s); sec. 7.4
covers that, as it covers every other repeat. *(Amended 2026-10-19, PR #96 review: replaces the
clock-minute key, whose straddle of a minute boundary let two replicas both tick.)*

With no cache registered there is nothing to claim with. The timer **MUST** still run -- the mode
exists for local development, where requiring a cache would be gratuitous -- and startup **MUST**
warn that ticks are uncoordinated, naming both remedies.

Neither mode is exactly-once: `CronJob` is at-least-once (controller restart, missed
`startingDeadlineSeconds`), and a claim fails open when the cache is unreachable, so every replica
ticks. Sec. 7.4 therefore applies in both modes. `concurrencyPolicy: Forbid` **SHOULD** be set, and
`CronJob` `timeZone` **MUST** be reconciled with apscheduler's timezone handling so the two modes
do not diverge. The reconciliation point is the opt-in `scheduler_timezone` (an IANA name, per
namespace): the `"in_process"` timer runs in it, and unset it keeps the host's local time as
before. In `"event"` mode the external cron's own timezone decides and the key changes nothing,
so the deployment sets `CronJob` `timeZone` to the same zone. *(Amended 2026-10-19, PR #96 review:
how the reconciliation is done; CronJob generation is deferred, sec. 12.)*

**Publishing and consuming are separate decisions.** A scheduler that emits a result event is a
legitimate shape and **MUST NOT** require the agent to consume anything: an application that opts
into publishing gets a transport client and no subscription, and its `event_bus` is what says a
broker exists. Publishing **MUST** stay opt-in, because a project that wants only a timer may have
no broker access at all, and a client created on its behalf becomes a readiness dependency on
infrastructure it does not run.

Note #43 -- schedulers being started twice *within* one process -- is a distinct defect with two
causes, and both **MUST** be fixed: two `build()` passes driving the lifespan hooks twice, and
`SchedulerBase` extending `RestApiBase` for its trigger route, which puts every scheduler in the
REST-API lifespan loop *and* the scheduler loop within a single pass.

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
only by the framework's own `SchedulerTickHandler`, the generated handler template selects purely
inside `can_handle_event`, and
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
select it. Together with the unhandled-event counter of sec. 7.2 this covers both directions of a
subscription that is shaped wrongly: a subject delivered to namespaces that find no work in it, and
a subject copied to far more namespaces than need it. Neither counter reports a fault on its own --
they are read as ratios against the volume a namespace receives.

Build-time gates on subject breadth belong to the implementation plan rather than here, because
they constrain projects rather than the framework. They **SHOULD** ship as warnings before they
become errors: the frozen compat suite and the generated-project smoke test cover runtime API and
would not catch a newly failing build.

---

## 8. Caches

Caches are looked up by name with no namespace dimension, which makes them a cross-agent
collision surface: two independently developed agents both calling `get_cache("sessions")` share
one cache the moment they are grouped, invisibly and only in production.

An agent **MUST** have access to exactly the caches it declared with `with_cache`, and to no
others. Cache names **MUST** be qualified by namespace, so two agents may both declare `sessions`
and receive separate stores; `get_cache(name)` **MUST** resolve within the declaring agent and
raise otherwise, with no root fallback and no shared-cache opt-in. Agents share no cache by
design, and separate stores make that isolation structural rather than dependent on a key prefix
being applied correctly at every call site.

Two things follow. A group declares no caches of its own, so `GroupConfig` carries no cache list
(sec. 4.1). And `/cache/*` is per agent: one process-wide cache endpoint would report one agent's
keys to another, which is the collision this section exists to close.

`registry.cache_service` (getter and setter) **MUST** be retained as an alias for the `"default"`
cache in the root namespace.

---

## 9. Startup

1. `GroupConfig.resolve(config)` -- file, then env overrides; log provenance.
2. Validate every agent name against the in-image agent map. Fail with the group and the missing
   agent named.
3. Import each agent module lazily; read the declaration the agent map names
   (`module = "pkg.mod:attribute"`).
4. `AgentGroup.from_config(group)` -- one unbuilt declaration per agent. Steps 1-4 together are
   `AgentGroup.resolve(config)`.
5. `assemble(config)`, then `run_app(app, config)`. Every component is constructed here, inside
   its own namespace scope; steps 1-4 construct nothing.

*(Amended 2026-10-19, PR #96 review: `with_group` / `build()` are `from_config` / `assemble()`, sec.
4.1; the declaration's attribute name comes from the agent map.)*

Resolution **MUST** complete before the first `Component.__init__`, because namespace injection
happens through a `ContextVar` read during construction. No incremental resolution.

### 9.1 Failure policy

There is no partial build: one process, one `build()`. The `critical` flag is therefore evaluated
**before** a namespace is wired, not after an exception.

| Failure | `critical: true` | `critical: false` |
|---|---|---|
| Agent missing from the agent map | exit non-zero | log ERROR, skip |
| Module import raises | exit non-zero | log ERROR, skip |
| `on_startup` raises | exit non-zero | mark namespace down, pause consumers (C4), continue; retry (below) |
| No agent left after the skips above | exit non-zero | exit non-zero |

*(Amended 2026-10-19, PR #96 review: last row added -- a pod with no agent passes its probes while
it consumes nothing, which is the failure criticality exists to prevent.)*

Exit **MUST** happen before the port is bound, so Kubernetes crash-loops with a readable message
rather than reporting a healthy pod that is silently short-staffed.

**A namespace marked down by a startup failure MUST be retried, and MUST NOT end the process.**
Every `startup_retry_interval_seconds` (default 30, process scope) the framework calls `on_startup`
again on that namespace's failed components, in their original start order, stopping at the first
that raises again. When all of them have started, the mark is released and the namespace's health
checks decide from then on. While it is marked, the readiness payload **MUST** report the namespace
`DOWN` with the failure as its reason, whatever its health checks say -- the mark exists because a
component that failed to start may still pass its check. Terminating instead is not a recovery: a
deterministic failure fails the same way after a restart, and the restart takes every healthy
namespace in the process down with it. `on_startup` **MUST** therefore be safe to call again after
it raised.

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
| `AppBuilder` fluent API | Unchanged. `AppBuilder(config)...build()` behaves as today, and no `namespace` parameter is added to anything. |
| Passing a constructed instance to `with_*` | Unchanged for an application that builds itself (`AppBuilder(config)...build()`, or `build()` with no argument). Refused when the builder is collected into a group (sec. 4.2), and by `build(config)` -- which the scaffolded `create_app()` calls -- because a declaration built by a host has the shape a group hosts. *(Amended 2026-10-19, PR #96 review: was "refused only in a group".)* |
| Component construction timing | Deferred to `build()`. Reading a component out of the registry between `with_*` calls was never supported -- collaborators resolve in `on_startup` -- and now breaks. |
| `with_health_checker` keys | Bare name at the root, so an existing readiness payload is unchanged; qualified per agent in a group. |
| OpenAPI tags and paths | Unchanged at the root: tags as the framework and the developer declare them, untagged routes under "default", every path as served today. Rewritten only per agent in a group (sec. 11.2). |
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
agent = (
    AppBuilder()
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_rest_api(OrderApi)
)
```

No `Config`, no `run_app`, no `if __name__`, no namespace, no group -- and no `.build()`: the
declaration is the file. A project that also wants to serve this agent alone adds one function and
nothing else:

```python
def create_app():           # uvicorn src.main:create_app --factory --reload
    return agent.build(Config(settings_files=["settings.toml", ".secrets.toml"], root_path=...))
```

The component list appears **once** either way. The dual-branch `main.py` of an earlier draft --
the same components repeated under `if __name__ == "__main__"` and `else:` -- **MUST NOT** be
used; two copies to keep in sync is itself a leak of the grouping model.

`asbs dev` in an image directory (one with an `agents.toml`) hosts that image's agents under
their **real** namespaces, as the deployment does. In an agent directory it serves the agent on
its own, at the root namespace, as the agent's own Dockerfile and `create_app()` do; `asbs dev
--name <agent>` serves it as a group of one under that namespace instead, so local routes are
`/api/<agent>/...` and local consumer identity is the production queue group, identical to a
grouped deployment.

An agent therefore runs at its real namespace wherever a group hosts it, and at the root when it
is served on its own. `namespace=""` is not reserved for pre-migration agents. *(Amended
2026-10-19, PR #96 review: replaces "`asbs dev agents/<name>` runs one agent as a group of one"
and "every newly scaffolded agent MUST have a real namespace in every environment" -- an agent
directory carries no name of its own, the name comes from whoever hosts it, and `--name`
reproduces the grouped shape locally.)*

### 11.1 What cannot be hidden

Three mistakes are harmless in isolation and fatal in a group. They **MUST** be caught
mechanically, because a rule that cannot be violated locally will not be followed:

| Mistake | Detection |
|---|---|
| Blocking the event loop | `event_loop_debug = true` (read as a boolean, in any environment; off unless set) sets `loop.set_debug(True)` with a slow-callback threshold; otherwise a loop watchdog, on by default in every environment, reports a block above its threshold and names the agents with work in flight (C7) *(Amended 2026-10-19, PR #96 review: debug mode is no longer on by default in development -- its overhead is too high to be a default)* |
| Module-level side effects (clients built at import, `basicConfig()`) | CI: import each agent module, assert the registry is empty and the root logger has no handlers |
| Non-idempotent handlers | explicit flag at scaffold time and in `asbs validate` (sec. 7.4) |

Two things an author still needs to know: their agent's name, and that handlers must not block.

### 11.2 An agent's HTTP surface

The first question a reader of a grouped image's Swagger UI asks is *which agent*, so an agent's
operations **MUST** form one group, and nothing an agent serves may fall outside it. Swagger UI
renders tags on one level only; the second level is therefore carried by the path, never by a
sub-tag.

Every requirement below applies to a component **with a namespace**. A root component -- every
component of a standalone agent, and the process-wide `root`, `actuators` and Dapr endpoints of a
grouped app -- keeps its declared tags and its paths (sec. 10).

- **Tags.** Every operation of agent `<ns>` **MUST** carry exactly the tag `<ns>`, replacing any
  tag the framework or the developer declared. An operation **MUST NOT** be untagged, which is what
  would file it under Swagger UI's "default" group.
- **Paths.** Every path of agent `<ns>` lives under `/api/<ns>/` (sec. 11). Within it, the
  segments `nats`, `cache` and `scheduler` are **reserved** for the framework:

  | Endpoint | Grouped path | Standalone path (unchanged) |
  |---|---|---|
  | NATS publish | `/api/<ns>/nats/events/{topic}` | `/events/{topic}` |
  | Scheduler trigger | `/api/<ns>/scheduler/<name>/trigger` | `/api/<name>/trigger` |
  | Cache management | `/api/<ns>/cache/...` | `/api/cache/...` |

  The Dapr endpoints are not an agent's: one process-wide pair at the root, fixed by Dapr's
  protocol (sec. 6).
- **Developer paths.** A developer **MAY** declare a path prefix on their REST API class. It
  applies standalone and grouped alike, so the agent's code does not depend on its grouping (C6);
  it is not required, so an existing agent joins a group without a source change. `build()`
  **MUST** refuse a grouped agent whose developer-declared route starts with a reserved segment,
  naming the component, the route and the segment -- otherwise it would silently collide with the
  framework's route of the same path.
- **Not covered.** Routes added to the `FastAPI` application directly in `main.py` do not belong
  to any agent and are not subject to these rules.

---

## 12. Acceptance criteria

Status on `feature/multi-agent-namespaces`, 2026-09-14. A ticked box names what holds it. `[~]`
means the behaviour is built and covered by unit tests against a mocked transport, while the
criterion as written asks for something only a real broker shows -- those have tests waiting in
`tests/integration/` and are tracked in `docs/plans/2026-09-11-broker-integration-tests.md`. An
unticked box is not done, and says why.

### Met

- [x] Durable and queue names byte-identical across two builds where the same agent sits in
      different groups (C1) -- `TestConsumerIdentityIgnoresTheDeployment`,
      `tests/unit/agents/clients/io/test_nats_client.py`.
- [x] Spans from namespace `invoice` carry `service.name = "invoice"`; a `namespace=""` app keeps
      `otel_service_name` (C2).
- [x] A degraded namespace: liveness `UP`, readiness per policy, `blueprint_namespace_up = 0`,
      that namespace's consumers stopped (C3, C4).
- [x] `<agent>.model_name` overrides root `model_name` for that namespace only (C5) --
      `tests/unit/agents/config/test_namespace_views.py`: `orders` reads its own, `billing` falls
      back to the root, and the two differ.
- [x] No supported API exposes group membership to agent code (C6) --
      `tests/unit/agents/test_agent_isolation.py` and `test_a_view_cannot_list_its_neighbours`.
- [x] Every path that stops a namespace serving emits an ERROR event and
      `blueprint_namespace_up{agent} = 0` carrying that namespace's identity; a namespace whose
      subscriptions vanish while the process stays healthy is reported within one scrape interval
      (C7).
- [x] File-only, env-only and combined resolution produce identical groups; env overrides the file
      key by key -- `tests/unit/agents/test_group_config.py`: `TestFromTheGroupFile`,
      `TestFromTheEnvironmentAlone`, `TestPrecedence`.
- [x] `CacheService.claim` is set-if-absent: of N concurrent callers on one key exactly one is
      told it stored the value (sec. 7.5) -- `TestClaim` in both `test_disk_cache_service.py` and
      `test_redis_cache_service.py`. Across processes this holds on Redis only; the disk
      backend's claim holds within one process. *(Amended 2026-10-19, PR #96 review: scoped to
      Redis.)*
- [x] An `"in_process"` scheduler with no cache still ticks, and warns at startup that its ticks
      are uncoordinated (sec. 7.5) -- `test_without_a_cache_every_replica_ticks` and
      `test_in_process_mode_without_a_cache_says_every_replica_runs_every_tick`.
- [x] A registered scheduler with no `scheduler_mode` fails before the port is bound, and so does
      `"event"` with no topic-carrying `event_bus` (sec. 7.5).
- [x] Two namespaces in one group resolve different `scheduler_mode` values, and only the
      `"in_process"` one starts a timer (sec. 7.5, C5).
- [x] A pure-scheduler namespace that neither subscribes nor publishes is given no transport client
      (sec. 6), and one that opts into publishing is given a client and no subscription (sec. 7.5)
      -- `test_an_agent_that_neither_consumes_nor_publishes_gets_no_client` and
      `test_a_publish_only_agent_gets_a_client_and_no_endpoint`.
- [x] A scheduler's `on_startup` and `on_shutdown` each run exactly once per lifespan, asserted
      against both lifespan loops a `SchedulerBase` appears in (#43) --
      `test_repeated_startup_starts_no_second_timer`.
- [x] An event that matches no handler is acknowledged, not redelivered: the transport edge
      behaves identically for `PROCESSED` and `NO_HANDLER_FOUND` (sec. 7.2) --
      `test_no_handler_found_still_acks`.
- [x] The same outcome yields the same disposition on both transports -- `CriticalHandlerError`
      drops on Dapr and terms on NATS, and a payload that fails to parse never naks (sec. 7.2) --
      `test_critical_error_returns_drop`, `test_critical_error_terms`,
      `test_invalid_event_error_terms`.
- [x] A handler declaring no topics and no event types is still evaluated for every event its
      namespace receives (sec. 7.7) --
      `test_a_handler_that_declares_nothing_is_a_candidate_for_everything`.
- [x] Frozen compat suite and generated-project smoke test both green (sec. 10.2) --
      `tests/unit/agents/test_frozen_compatibility.py` and
      `tests/unit/agent_generator/generator/test_generated_project.py`.
- [x] Idempotency off by default, with the requirement surfaced at scaffold time and in
      `asbs validate` -- `test_dedup_is_off_by_default`, plus the `DECIDE:` comment in the
      scaffolded handler and the notice `asbs validate` prints.

### Built, awaiting a real broker

- [~] Two agents in one process; an event on a topic both subscribe to reaches both, once each.
      Per-agent subscription and the Dapr in-process fan-out are unit-tested;
      `tests/integration/test_grouped_agents.py` is the version that settles it.
- [~] Two replicas of a two-agent group: each event processed exactly once per agent. Whether a
      queue group merges overlapping subscriptions is the broker's behaviour, not ours.
- [~] Cron fires once across three replicas in both `scheduler_mode` values (#73) -- in
      `"in_process"` mode with a Redis cache. The claim is atomic on Redis by unit test; three
      real replicas contending is not. On a disk cache the claim does not hold across processes
      (sec. 7.5). *(Amended 2026-10-19, PR #96 review: scoped to Redis.)*

### Not done

- [ ] No framework-created task is detached without a done-callback that logs exceptions with the
      namespace attached; asserted by a test that fails a task in each background path (C7).
      Done-callbacks are on the NATS, Dapr and sessions paths and individually tested; the
      *exhaustive* test the criterion asks for -- one that fails a task in every background path
      -- does not exist, so nothing stops the next path being added without one.
- [ ] The CI gate fails when an environment's group declaration omits an agent present in the
      in-image agent map (sec. 13). `asbs validate` reports it locally; no CI gate enforces it.
- [ ] `scheduler_mode = "event"` starts no timer, and the generated `CronJob` matches the schedule
      declared in agent code. The first half holds (`test_event_mode_starts_no_timer`); manifest
      generation was deliberately deferred and the renderer written for it was removed rather than
      carried as dead code, so the second half has nothing to check yet.
- [ ] Unhandled events per (namespace, topic) and namespaces-per-subject fan-out are both exposed,
      neither reported as a fault and neither keeping per-topic state (sec. 7.2, sec. 7.7).
      `blueprint.events.unhandled` carries (agent, topic), on the agent's own meter; the namespaces-per-subject fan-out
      gauge is not implemented.
- [ ] Marginal RSS per additional idle namespace measured and published, reusing #36's
      benchmark harness. #32 measures ~6 MB per forked child with shared libraries; a
      namespace should be materially below that, and this number is what retires the
      lazy-agent idea for good. No benchmark harness exists yet, so the number this feature
      exists to produce has not been measured.

### Superseded

- A namespace's derived `filter_subjects` is never narrower than its declared topics unioned with
  `nats_subscriptions`. The design moved: each agent owns its own durable filtering on its own
  subjects, which is what makes a per-namespace `filter_subjects` set unnecessary
  (`nats_client.py`). Recorded rather than deleted, because this spec is normative and a change
  of approach belongs on it.


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
- What dedup TTL is defensible against the redelivery window? (Whether the dedup cache is
  per-namespace or shared is **answered**: sec. 8 gives an agent only the caches it declared, so it
  is necessarily per-namespace.)
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
- **Do the services running schedulers today have `event_bus` configured?** It decides how much
  weight the `"in_process"` lease carries. If some have no broker at all they are permanently
  `"in_process"`, and the lease stops being a development convenience and becomes the only thing
  standing between them and duplicated ticks.
- **Does the deployment path regenerate manifests from the build?** If it does, the generated
  `CronJob` arrives with the upgrade and `"event"` costs an existing service nothing. If manifests
  are hand-maintained, the generator emits a file someone has to notice and apply, which is where a
  tick quietly stops.
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
