# Plan -- Multi-Agent Grouping

| | |
|---|---|
| **Status** | not started -- no phase implemented |
| **Spec (normative)** | `docs/specs/2026-08-28-multi-agent-grouping.md` |

This is the phased work breakdown. The spec is normative: it carries the MUST/SHOULD requirements,
the API surface, the config reference and the acceptance criteria, and where the two documents
disagree the spec wins.

**Issues:** resolves #75; unblocks #32, #35, #20; #73 is P5 below. Related: #33, #34, #36, #43, #74.

**Deployment model:** the namespace model below is implemented in full, but *which* agents share a
process is not hardcoded — it is selected at runtime from a group configuration
(`BLUEPRINT_GROUP` env var), and Kubernetes runs one Deployment per group. Group size 1 gives
per-agent process isolation; group size 20 gives the shared-process memory profile. Nothing in
Phases 0-7 changes because of this; Phases 8-9 add the loader and the deployment-facing
constraints.

The spec (sec. 3) defines seven invariants (C1-C7) that this plan must satisfy. They are
referenced by number in the phases below. C1-C6 keep regrouping invisible from outside the process; C7 (no
silent failure at agent granularity) keeps the isolation cost grouping *does* incur attributable,
and is therefore what makes the group-size dial usable in response to a real failure.

## Goals

- One app, one port, one health endpoint, one NATS/Dapr connection — shared infrastructure
  is never duplicated.
- Components gain an optional **namespace** (`""` by default). Empty namespace = today's
  single-agent world. Zero migration required for existing projects.
- **Opt-in multi-agent capability per agent.** A developer who wants their agent to
  participate in a multi-agent system makes exactly two changes: `main.py` and `Dockerfile`.
  Developers who do not opt in keep their current code and deployment unchanged.
- **Multiple named `CacheService` instances** can be registered independently, looked up
  by name from any namespace, and added at runtime after startup.
- Every phase is independently shippable and backwards compatible.
- **Per-namespace I/O isolation.** Each namespace gets its own `ThreadPoolExecutor`
  (for blocking `DiskCacheService`/SQLite calls via `run_in_executor`) and its own
  `AIClientBase` instance (separate async HTTP connection pool), so one agent's I/O
  load cannot stall another's.
- **Grouping is a deployment parameter, not an architectural commitment.** Regrouping an agent
  must never change its broker-side consumer identity (C1) or its telemetry identity (C2).
  If a change makes regrouping observable to the broker or to a dashboard, it is wrong.

---

## Prerequisites (blocking defects in the current code)

These are independent of the namespace work and would need fixing under any option. **They block
scaling any group past one replica** and must land before the multi-agent phases ship.

**P0 — Transport lifecycle: managed subscription, retry, reconnect, readiness.** Written as
PR #27 (`feature/event_handler_retries`), which is being closed in favour of landing the work
here. It is a prerequisite rather than a parallel track, because the rest of this list sits on
top of it:

- `ClientBase.subscribe(topic_callbacks)` replaces `subscribe(topic, callback)` — one call
  carrying the whole `{topic: callback}` map, non-blocking, backed by a background retry task.
  P6's per-namespace clients need exactly this shape.
- `subscriptions_ready` plus health-check gating. C4 and C7 read it, and Phase 9 drives
  `blueprint_namespace_up` from it.
- `disconnected_cb` / `reconnected_cb`, re-subscribing JetStream durables on reconnect. P2's
  correctness depends on this path: the server redelivers everything unacked after a reconnect.
- Config keys `event_client_max_retries` (default `-1`, indefinite) and `event_client_retry_delay`
  (default `5.0`).

Three gaps to close while landing it, none of which the original PR addressed:

- **No shutdown drain.** `close()` cancels the retry task and unsubscribes under
  `contextlib.suppress(Exception)`, so in-flight handlers lose their acknowledgement on every
  deploy — duplicates on the next start are certain, not merely possible. Drain in-flight work
  before unsubscribing, bounded by a timeout.
- **The `except Exception` swallow in `message_handler` must not survive the port** (see P2).
- **`DaprEventing` registers a callback map with `DaprClient` while delivery still arrives on
  `POST /events/{topic}`,** so that callback appears unused for delivery and exists only to drive
  readiness. Settle its role or remove it.

**P1 — Core NATS subscriptions have no queue group.** `clients/io/nats_client.py:250` calls
`client.subscribe(topic, cb=...)` with no `queue=`. JetStream is off by default
(`nats_use_jetstream`, `nats_client.py:102`), so the default path today is: *every replica
processes every message*. Setting `replicas: 2` silently doubles every side effect and every
inference bill. Fix: `queue=<agent-name>` — derived from the namespace, never from the group or
container (C1).

**P2 — JetStream messages are never acknowledged.** `clients/io/nats_client.py:242-247`
subscribes with `manual_ack=True`, and there is no `msg.ack()` call anywhere in the codebase.
Every message redelivers after `ack_wait` until `max_deliver`. This is already a defect at one
replica — each event is processed repeatedly — and at N replicas it presents as a scaling
problem but is not one.

The contract is normative in spec sec. 7.2: **a normal return acks, a raised exception does not.**
`ProcessingStatus` has exactly two values, `PROCESSED` and `NO_HANDLER_FOUND`, so no failure can
reach the transport as a returned value. That is why the transport edge never inspects
`ProcessingResult` — it would learn nothing — and why an event that matches no handler's
conditions acks like any other completed dispatch instead of being redelivered until
`max_deliver`.

What blocks this today is not the missing `msg.ack()` call but two layers that discard the
classification before it can reach one:

| Layer | Behaviour |
|---|---|
| `_process_cloud_event` (`io/api/eventing/event_handling_base.py`) | logs and **re-raises** — correct, keep |
| `_process_event` (`io/api/eventing/nats.py`) | catches `RetryableHandlerError`, `InvalidEventError`, `CriticalHandlerError`, logs, returns `None` |
| `message_handler` (`clients/io/nats_client.py`) | catches `Exception`, logs, returns |

Work items:

- Remove the `except` block from `_process_event` so classified exceptions reach the transport.
- In `message_handler`, ack on normal return and map exception type to `nak()` / `term()` per the
  spec table. Distinguish *before* dispatch from *during* dispatch: a payload that fails JSON or
  CloudEvent parsing terms, because it will not parse on redelivery either.
- Leave the callback type `Callable[[CloudEvent[Any]], Awaitable[None]]` unchanged. The
  classification travels as an exception, so no signature widens and P0's nine callback-type
  declarations stay untouched. Widen it only if P4's dedup or C7's in-flight gauge later needs the
  result object at the transport edge — and then once, deliberately, not twice.
- Bring Dapr into line (spec sec. 7.2): `NO_HANDLER_FOUND` → `SUCCESS` (`dapr.py:75`),
  `CriticalHandlerError` → `DROP` (`dapr.py:102`), and the same in
  `event_handling_base.handle_event`, whose returned dict *is* Dapr's acknowledgement.
- Add the unhandled-event counter and the first-occurrence WARNING per (namespace, topic), so
  acking an unmatched event does not hide a topic nobody handles.
- Configure `max_deliver` and a dead-letter destination (with P3), since nak on an unexpected
  exception otherwise redelivers forever.

**P3 — Consumer tuning is not configurable.** Expose `ack_wait` (must exceed p99 handler
duration, or long LLM work is redelivered to another replica mid-flight) and `max_ack_pending`
(the real cross-replica concurrency cap).

**P4 — Idempotency, flagged not enforced.** Competing consumers make at-least-once permanent, and
ack loss makes duplicate delivery *certain* rather than possible: a handler that finishes 60s of
inference and then cannot ack has already committed its side effects, and the broker redelivers
after `ack_wait`. But whether dedup is *correct* depends on the product built on the blueprint —
some operations are naturally idempotent, others need business-level reconciliation the framework
cannot see. So: provide an opt-in dedup mechanism (CloudEvent `id`, namespace cache, TTL, in the
handler chain before dispatch), default **off**, and surface the requirement explicitly to the
author — scaffolded handler comment, generated README, `asbs validate` notice. The author must
make a decision, not inherit one silently.

**P5 — Cron becomes an event source (#73).** `SchedulerBase.on_startup` creates an
`AsyncIOScheduler` per process with no leader election, so every cron tick fires once per replica.
Grouping widens this: one pod with 20 agents runs 20 schedulers, and two replicas duplicate all
20 agents' crons at once.

The fix is not leader election in production — it is removing the in-process timer:

```toml
scheduler_mode = "event"        # default: schedule lives outside; the tick arrives as an event
                 "in_process"   # apscheduler + leader lease, for plain Docker and local dev
```

**`"event"`** — a Kubernetes `CronJob` publishes a NATS message; the agent handles it through the
event path it already has. A ~10 MB `nats-cli` container, not a pod re-paying the 154 MB baseline
(#32). The queue group already guarantees exactly one replica picks it up, so nothing is elected;
idempotency dedup, telemetry attribution and namespace routing all apply for free. One execution
model instead of two.

The developer still **declares** the schedule in the agent; the build **generates** the `CronJob`
from that declaration, the same way manifests are generated from `deployment-groups.yaml`. Without
generation, code can expect a tick nobody scheduled.

**`"in_process"`** — the existing timer plus a NATS KV or cache-backed lease. Needed for
un-orchestrated Docker and for local dev, where a `CronJob` is not available. Cheap to keep: event
mode is "do not start the timer", since the handler path already exists.

Neither mode is exactly-once. `CronJob` is at-least-once (controller restart, missed
`startingDeadlineSeconds`) and a lease can briefly have two holders if it expires mid-tick, so P4
applies either way. Set `concurrencyPolicy: Forbid` to prevent overlap, and watch that `CronJob`
`timeZone` and apscheduler timezone handling agree across modes.

Note #43 — schedulers started twice *within* one process by two `build()` passes — is a distinct
defect; both touch scheduler startup and should be fixed together.

**P6 — Transport topology: one connection per namespace.** Not a defect, but it belongs here
because it changes `NATSClient` ownership. Per-namespace clients confine ack loss and
slow-consumer disconnects to one agent, and give named connections in `/connz` —
`nats.connect()` is called today with no `name=` at all (`nats_client.py:93`). No config knob: a
socket plus buffers against ~65 MB for a separate process (#32). For a single-agent app it is a
no-op — one namespace, one connection. `EventPublishingService` becomes per-namespace too, or
outbound traffic stays unattributable. The connection name contains the pod and **must never**
feed C1 naming.

Two scoping points, both easy to get wrong:

- **NATS only.** Under Dapr the app holds no broker connection — `DaprClient` is an `httpx` client
  against the sidecar (`dapr_client.py:89`), and the sidecar owns and multiplexes one broker
  connection per pod. Connections track pods there, and the ack-loss and slow-consumer arguments
  move into the sidecar. A per-namespace `DaprClient` is still useful for health attribution and
  C4, but it does not confine either failure.
- **Not a durability mechanism.** JetStream pending state is the server's, keyed by consumer and
  stream sequence; an ack is a publish to the per-delivery reply subject, not an entry in a
  framework-side registry. A shared connection therefore has no in-flight state to lose when the
  process dies. The topology decides how many namespaces *repeat* work after a connection drop —
  nothing more. Durability is settled by P1/P2, not here.

---

## Namespace model

```
Root Registry  (namespace="")
├── nats_client              ← shared IO transport (one connection)
├── event_publishing_service ← shared
├── actuator_api             ← one health endpoint
│
├── Named caches (flat, namespace-independent)
│   ├── "default"            ← backwards-compat alias for registry.cache_service
│   └── "orders"             ← any name, accessible from every namespace
│
├── Namespace "invoice"
│   ├── invoice_agent        (AgentRuntime)
│   ├── invoice_handler      (EventHandlerBase)
│   ├── invoice_api          (RestApiBase)  → routes at /api/invoice/...
│   ├── invoice_ai_client    (AIClientBase) ← isolated connection pool
│   └── _executor            (ThreadPoolExecutor) ← blocking I/O isolation
│
└── Namespace "order"
    ├── order_agent          (AgentRuntime)
    ├── order_handler        (EventHandlerBase)
    ├── order_api            (RestApiBase)  → routes at /api/order/...
    ├── order_ai_client      (AIClientBase) ← isolated connection pool
    └── _executor            (ThreadPoolExecutor) ← blocking I/O isolation
```

**Component resolution rule** for `get_component(Type, namespace="invoice")`:
1. Search `"invoice"` namespace — if exactly one match, return it.
2. Fall back to root `""` — if exactly one match, return it.
3. Raise only if ambiguous within the same level.

**Cache resolution** is by name only — no namespace dimension.
`registry.get_cache("orders")` works identically from any namespace.

---

## Migration path for an existing agent

**No change (stays standalone):** developer does nothing — existing `main.py` and
Dockerfile work as-is forever.

**Opt in to multi-agent:** two file changes only.

`main.py` before:
```python
app = (
    AppBuilder(config)
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_handler(OrderEnrichmentHandler)
    .with_rest_api(OrderApi)
    .with_cache()
    .build()
)
```
Dockerfile before: `CMD uvicorn src.main:app --host 0.0.0.0 --port 8000`

`main.py` after — **one declaration, no branches**:
```python
from blueprint.agents import AgentRegistration

registration = (
    AgentRegistration()
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_handler(OrderEnrichmentHandler)
    .with_rest_api(OrderApi)
)
```
Dockerfile after: `CMD python -m blueprint.agents.entrypoint`

An earlier draft of this plan used a dual-branch `main.py` —
`if __name__ == "__main__": AppBuilder(...)...run_app()` / `else: registration = ...`. That is
**rejected**: it makes the developer write the component list twice and keep both copies in sync,
and it exposes the existence of two worlds. Running a single agent is `asbs dev agents/order`,
which wraps the registration as a group of one. No `AppBuilder`, no `Config`, no `run_app`, no
`if __name__` in agent code (C6).

Because the module is imported into a shared runtime, it **must** contain only the registration —
no client construction at import time, no module-level mutable state, no `logging.basicConfig()`.
CI check: import each agent module, assert the registry is still empty and the root logger has no
handlers.

The global orchestrating `main.py` (no uvicorn, just a FastAPI app):
```python
from blueprint.agents import AppBuilder, Config
from order_agent.src.main import registration as order_reg
from invoice_agent.src.main import registration as invoice_reg

config = Config(settings_files=["settings.toml"])

app = (
    AppBuilder(config)
    .with_cache("orders")
    .with_namespace("order",   registration=order_reg)
    .with_namespace("invoice", registration=invoice_reg)
    .build()
)
```

---

## API route namespacing

`RestApiBase` subclasses require no changes. `_build_rest_endpoints` reads
`rest_api._namespace` and adjusts prefix and tags at router-inclusion time.

| Mode | Declared tag | Route | OpenAPI tag |
|---|---|---|---|
| Standalone (`namespace=""`) | `"Orders"` | `/api/orders/{id}` | `Orders` |
| Multi-agent (`namespace="order"`) | `"Orders"` | `/api/order/orders/{id}` | `order.Orders` |

---

## Component sharing rules

| Component | Sharing | Notes |
|---|---|---|
| `NATSClient` / `DaprClient` | **Per-namespace** | One named connection per agent (P6). Confines ack loss and slow-consumer kicks; single-agent apps unchanged |
| `EventPublishingService` | **Per-namespace** | Must publish on its own namespace's client, or outbound traffic is unattributable |
| `EventProcessingService` | Shared (root) | Namespace passed per-call |
| `ActuatorApi` | Shared (root) | One health endpoint |
| `CacheService` | **Namespace-scoped by default** | Explicit opt-in for genuinely shared caches. A flat store lets two independently developed agents both call `get_cache("sessions")` and silently share it once grouped. Sync ops via `run_in_executor` + namespace executor |
| `AIClientBase` | Per-namespace strongly recommended | Shared async HTTP pool causes one agent's LLM calls to starve another's |
| `ThreadPoolExecutor` | Per-namespace | Provisioned by `with_namespace`; prevents blocking DiskCache/SQLite from stalling event loop of other namespaces |
| `EventHandlerBase` | Per-namespace | Core routing unit |
| `AgentRuntime` | Per-namespace | Each agent in its own namespace |
| `RestApiBase` | Per-namespace | Routes prefixed `/api/{namespace}/` |
| `ServiceBase` (user) | Per-namespace | Typical; can be root if truly stateless and shared |
| `SchedulerBase` | Per-namespace | Typical |
| `SessionsApiClient` | Shared (root) | One sessions backend |

---

## Phase 0 — `run_app` utility + `AgentRegistration` (no breaking changes)

**Files:** `utils/utils.py`, `app_builder.py`, `__init__.py`

`run_app(app: FastAPI, config: Config) -> None` in `utils/utils.py`:
- Imports uvicorn and starts the server with dev/prod settings derived from config.
- `app_environment = "development"` → `reload=False` (reload requires a string reference,
  not an object; developers who need reload use the uvicorn CLI directly), workers=1,
  log level debug.
- `app_environment` anything else → workers from `app_workers` config (default 1),
  log level from `log_level` config (default `"info"`).
- Config keys read: `app_host` (default `"0.0.0.0"`), `app_port` (default `8000`),
  `app_environment`, `log_level`, `app_workers`.

`AgentRegistration` class in `app_builder.py`:
- Fluent collector — same `with_handler`, `with_service`, `with_agent`, `with_rest_api`,
  `with_scheduler` signatures as `AppBuilder` (and `NamespaceBuilder`), but stores
  component classes instead of instantiating them.
- No `with_cache()` — caches are global and registered on the orchestrating `AppBuilder`.
- Internal `_apply(namespace_builder: NamespaceBuilder) -> None` iterates stored entries
  and calls the corresponding `with_*` on the provided builder. Called by
  `AppBuilder.with_namespace(..., registration=reg)`.
- **Namespace injection:** at the start of `_apply`, set a module-level
  `ContextVar[str]` (defined in `component.py`) to `namespace_builder._namespace`; reset
  it in a `finally` block after all `with_*` calls complete. `Component.__init__` reads
  the ContextVar to determine its namespace — zero changes required to user-defined
  constructors. In the standalone case the ContextVar default (`""`) is never overridden.

Export both `run_app` and `AgentRegistration` from `blueprint.agents.__init__`.

---

## Phase 1 — Registry namespace + named cache support

**File:** `component/registry.py`

**Namespace storage:**
- Change `_components: dict[str, Any]` to `dict[str, dict[str, Any]]`
  (namespace → name → component). Root namespace key is `""`.
- Add `namespace: str = ""` param to `add_component`, `update_component_name`,
  `get_component`, `get_components_by_type`, `get_component_names_by_type`, `has_component`.
- `get_component` implements two-level fallback: own namespace → root `""` → raise.
- All typed convenience getters (`get_event_handler`, `get_agents`, `get_services`,
  `get_schedulers`, `get_rest_apis`, `get_clients`) accept optional `namespace=""`.
- `add_component` raises on name collision only within the same namespace.
- `get_known_namespaces() -> list[str]` returns all registered namespace keys
  (used by `NatsEventing` and `build()` to iterate all namespaces).

**Named cache storage (replaces the single `_cache_service`):**
- Replace `_cache_service: CacheService | None` with `_caches: dict[str, CacheService]`.
- `add_cache(name: str, service: CacheService) -> None` — upsert; no "already registered"
  guard, so caches can be added at any time after startup.
- `get_cache(name: str = "default") -> CacheService` — raises `ValueError` if not found.
- `get_or_create_cache(name: str, factory: Callable[[], CacheService]) -> CacheService` —
  atomic get-or-create protected by an `asyncio.Lock` for safe concurrent first-access.
- `has_cache(name: str = "default") -> bool`.
- `get_all_caches() -> dict[str, CacheService]` — returns a shallow copy of `_caches`.
  Used by `ActuatorApi` (health checks) and `CacheManagementApi` (management endpoints)
  instead of accessing `_caches` directly.
- `cache_service` property kept as alias for `get_cache("default")` — backwards compat.
- `cache_service` setter kept as alias for `add_cache("default", value)` — backwards compat.

**Executor registry:**
- Add `_executors: dict[str, ThreadPoolExecutor]` (namespace → executor).
- `add_executor(namespace: str, executor: ThreadPoolExecutor) -> None`.
- `get_executor(namespace: str = "") -> ThreadPoolExecutor` — falls back to root `""` if
  the namespace has no executor; raises `ValueError` if root is also missing.
- The root executor is provisioned in `AppBuilder.build()` (not in `with_namespace`) so
  standalone apps always have one.

**Backwards compatibility:** All callers omitting `namespace` use `""` and see today's flat
registry. Existing `registry.cache_service` access is unaffected.

---

## Phase 2 — Component namespace awareness

**File:** `component/component.py`

- Add a module-level `_current_namespace: ContextVar[str] = ContextVar("_current_namespace", default="")`.
- `Component.__init__` reads `_current_namespace.get()` and stores it as `self._namespace`.
- Pass `self._namespace` to `registry.add_component(name, self, namespace=self._namespace)`.
- Add `executor` property: returns `registry.get_executor(self._namespace)`, falling back
  to a root-level executor if none is registered for that namespace (root namespace always
  has a default executor created in `build()`). Used by `CacheService` subclasses to
  offload sync DiskCache/SQLite calls via `asyncio.get_event_loop().run_in_executor`.
- `Component.shared_registry` remains a single class-level singleton.

**Backwards compatibility:** Default `namespace=""` — existing subclasses unchanged.

---

## Phase 3 — NamespaceBuilder and AppBuilder extension

**File:** `app_builder.py`

- Add `NamespaceBuilder` class (same file):
  - Holds reference to parent `AppBuilder` and its `namespace` string.
  - Exposes `with_handler`, `with_agent`, `with_service`, `with_scheduler`,
    `with_rest_api` — each delegates to parent with `namespace=self._namespace`.
  - No `with_cache` — caches are always registered at root level.
  - `end() -> AppBuilder` for explicit block-close style.
  - All `with_*` methods return `self` for chaining.
- `AppBuilder.with_namespace(name: str, *, registration: AgentRegistration | None = None, config: Config | None = None) -> AppBuilder`:
  - Creates a `NamespaceBuilder` for `name`.
  - **C5 — namespace-scoped config.** `Config` already supports `agent_scope`
    (`config/config.py`), which tries `<scope>.<key>` before falling back to `<key>` at root.
    When `config` is omitted, `with_namespace` builds one with `agent_scope=name` from the root
    config's settings files. Prompts, model selection and usage limits become per-agent while
    infrastructure keys stay shared. Components in the namespace receive this scoped `Config`.
  - Provisions a `ThreadPoolExecutor(max_workers=config.get("executor_workers", os.cpu_count() + 4))`
    for the namespace and registers it in the registry under that namespace key.
  - If `registration` is provided, calls `registration._apply(ns_builder)` and returns
    `self` — no `.end()` needed. This is the primary multi-agent API.
  - If omitted, returns the `NamespaceBuilder` for indent-and-`.end()` style.
  - Executors are shut down gracefully (`.shutdown(wait=True)`) in the lifespan shutdown
    sequence, after all components have stopped.
- Add `namespace: str = ""` to all existing `AppBuilder.with_*` methods (except
  `with_cache`) for direct tagged calls. **Keyword-only** — `process_event` and friends already
  have positional tails.
- `AppBuilder.with_cache(enabled=True, enable_locking=True, *, name="default")` creates a
  `CacheService` via `CacheBackendFactory` with `cache_dir = {base_dir}/{name}` (when
  `name != "default"`, else the configured `cache_dir`) and calls `registry.add_cache(name, service)`.

  **`name` must be keyword-only and must follow the two existing positional parameters.** The
  current signature is `with_cache(enabled: bool = True, enable_locking: bool = True)`
  (`app_builder.py:117`). Making `name` first would turn an existing `with_cache(False)` — which
  *disables* caching — into a cache named `False`: caching silently switched on, no `TypeError`,
  no warning. This is the only signature-level break in the whole plan; get it right here.
- Executors are created **lazily on first `Component.executor` access**, not eagerly in `build()`.
  Eager creation would add ~`cpu_count + 4` idle threads to every existing single-agent app and
  works against #36's thread-count budget.

**Backwards compatibility:** `with_cache()`, `with_cache(False)` and `with_cache(True, False)` all
behave exactly as today. All existing `with_*` calls default to `namespace=""`.

---

## Phase 4 — Namespace-scoped HandlerChain and EventProcessingService

**Files:** `handler/handler_chain.py`,
`services/eventing/event_processing_service.py`

`HandlerChain`:
- Constructor accepts `namespace: str = ""`.
- `process()` fetches `registry.get_event_handler(namespace=self._namespace)`.

`EventProcessingService`:
- Add `namespace: str = ""` param to `process_event` and `process_rest_request`.
- Lazy-create one `HandlerChain` per namespace in a `dict[str, HandlerChain]`.
- Wire previously unused `runtime_name`: after chain picks winner, resolve agent via
  `get_runtime_name()` (Phase 7) within the namespace.

**Backwards compatibility:** Omitting `namespace` defaults to `""` — today's behaviour.

---

## Phase 5 — NATS per-namespace topic routing

**Files:** `io/api/eventing/nats.py`,
`io/api/eventing/cloud_event_processor_mixin.py`,
`io/api/eventing/event_handling_base.py`

`NatsEventing.on_startup()`:
- Iterate `registry.get_known_namespaces()`, collect `(namespace, topic)` pairs from each
  handler's `get_subscribed_topics()`.
- **Deduplicate within a namespace only.** Two agents subscribing to the same topic is
  legitimate and expected — both want the event. A cross-namespace "first declaration wins" rule
  silently disables one agent's subscription, and the author cannot observe it locally. Each
  `(namespace, topic)` pair gets its own subscription and its own consumer.
- Each `_subscribe_to_topic(topic, namespace)` closure passes `namespace=` to
  `_process_cloud_event`.

`CloudEventProcessorMixin._dispatch_cloud_event`:
- Accept `namespace: str = ""`, forward to `EventProcessingService.process_event`.

`NATSClient` consumer identity (**C1 — invariant, cover with a test**):
- JetStream durable: `f"{namespace}-{topic}-durable"` when namespace non-empty; config default
  otherwise.
- Core NATS queue group: `queue=namespace` (see P1).
- Both derive from the **agent/namespace name only** — never from the group name, container
  name, pod name or any deployment identifier. This is what makes replicas of a group compete
  correctly *and* makes moving an agent between groups invisible to the broker. A durable name
  that picks up the group name produces a fresh consumer on regrouping: replay from the start of
  the stream, or a silent gap, depending on the delivery policy.

One `NATSClient` **per namespace** (P6), named `f"{namespace}.{group}.{pod}"`. The connection name
contains the pod, so it must never feed durable or queue naming.

**Backwards compatibility:** No declared namespaces → single root namespace → one connection →
same as today.

---

## Phase 6 — AppBuilder.build() multi-namespace awareness + API route namespacing

**File:** `app_builder.py`

- `_eventing_component` → `list[DaprEventing | NatsEventing]` (one element initially).
- `build()` scans all known namespaces when deciding whether to create an event bus client.
- Lifespan manager and `_build_rest_endpoints` iterate the list.
- **API route namespacing** in `_build_rest_endpoints`: when `rest_api._namespace` is
  non-empty, rewrite `route.tags` to `[f"{ns}.{tag}" for tag in route.tags]` and include
  the router with `prefix=f"/api/{ns}"`. Empty namespace → unchanged behaviour.
- `CacheManagementApi`: one router, endpoints accept optional `?name=` query param
  (defaults to `"default"` for backwards compat).
- `ActuatorApi` cache health: iterates all entries in `registry._caches` at startup time.

---

## Phase 7 — Handler → Agent binding (get_runtime_name)

**Files:** `handler/event_handler_base.py`,
`services/eventing/event_processing_service.py`

`EventHandlerBase`:
- Add `get_runtime_name(event, context) -> str | None`, default returns `None`.

`EventProcessingService.process_event`:
- Call `winner.get_runtime_name(event, context)` after chain selects a handler.
- Non-`None` → `registry.get_agent(name, namespace=namespace)`.
- `None` + exactly one agent in namespace → use it (today's implicit behaviour).
- `None` + multiple agents + no name declared → raise a descriptive error.

---

## Phase 8 — Group configuration + entry point

**Files:** new `group_config.py` (`GroupConfig`), new `entrypoint.py` (runnable as
`python -m blueprint.agents.entrypoint`), `app_builder.py` (`with_group`, `from_group`),
`utils/utils.py`

Turns the group configuration into a running app. Everything here is additive; standalone
`main.py` deployments are untouched.

**Not a separate "orchestrator" component.** The split is resolution versus wiring, and the
looping-over-agents half belongs in `AppBuilder` — it already reads config to make wiring
decisions (`with_cache` picks a backend, `with_namespace` sizes an executor). What stays outside
is the I/O: env reads, file reads, `sys.exit`, and knowledge of the agent repo's file layout.
`AppBuilder` must remain a pure function of its call sequence so tests can construct exact
compositions without controlling env or filesystem — the same layering mistake as putting retry
logic in `EventHandlingBase` (see the event-client resilience decision record).

Avoid the name "orchestrator": it names the App-of-Apps supervisor process that this design
rejected, and reusing it invites confusion with a component that deliberately does not exist.

`deployment-groups.yaml` — single source of truth, read by the entry point at runtime, by the
CI gate, and by Kubernetes manifest generation (Argo CD `ApplicationSet` list generator over
`groups`, or Helm values), so the container and the cluster cannot drift:

```yaml
groups:
  - name: finance
    agents: [invoice, order, dunning]
    resources: {cpu: "2", memory: "2Gi"}
    replicas: 2
  - name: contract-analysis        # alone: CPU-heavy, isolated blast radius
    agents: [contract-analysis]
    replicas: 3
```

Agent discovery — explicit map (`agents.toml`), no convention scanning. **This one is baked into
the image**; it changes only when an agent is added or removed, which is a rebuild anyway:

```toml
[agents.invoice]
module = "agents.invoice.main:registration"
```

**Configuration delivery — both mechanisms, and they compose.** The group configuration is never
baked into the image.

1. **YAML file at a configurable path.** `BLUEPRINT_GROUP_CONFIG` (default
   `./deployment-groups.yaml`) plus `BLUEPRINT_GROUP` to pick the group. The path is
   configuration, not a constant, so one image serves a ConfigMap mount in Kubernetes, a bind
   mount in `docker run`, and the repo file in local dev. Falling back to the repo file is what
   makes `python -m blueprint.agents.orchestrator` work with no cluster and no mount.
   `BLUEPRINT_GROUP` may be omitted when the file declares exactly one group. What gets mounted
   is the **resolved slice** for one group, not the full multi-group document.
2. **Environment variables injected directly.** `BLUEPRINT_AGENTS=invoice,order,dunning` and
   `BLUEPRINT_CRITICAL_AGENTS=invoice` (feeds `readiness_policy = "critical"`, C3). No file, no
   mount. Because these live in the pod template, changing them changes the template hash and
   Kubernetes rolls automatically — a property the mounted file does not have.

**Precedence: env vars override the file, key by key** (12-factor). The file supplies the
baseline; a single Deployment can override one field without editing or duplicating it. Log the
resolution at startup: which source each value came from, and the final agent list.

Both are read **before** `Config` is constructed — group resolution decides which agents get a
`Config` at all, so it is a plain env read plus a small YAML parse, deliberately not routed
through Dynaconf. Hence the explicit `BLUEPRINT_` prefix rather than Dynaconf's `DYNACONF_`
override mechanism.

Entry point, in full:

```python
def main() -> None:
    config = Config(settings_files=["settings.toml"])
    group = GroupConfig.resolve(config)     # env + file, validated; the only I/O
    app = AppBuilder(config).with_group(group).build()
    run_app(app, config)
```

`AppBuilder.from_group(config)` collapses lines 2-3 for callers who want one call; `with_group`
takes an in-memory `GroupConfig` and performs no I/O, so tests construct one literally.

Flow:
1. `GroupConfig.resolve`: read the YAML at `BLUEPRINT_GROUP_CONFIG` if present, apply env-var
   overrides key by key, log the effective source of each value.
2. Validate every agent named in the group against the in-image `agents.toml` map. Fail fast,
   naming the group and the missing agent — this seam turns a config typo into a crash-loop with
   a readable message instead of a silently short-staffed pod.
3. Resolve each name via `importlib.import_module` + `getattr`, **lazily and per group** — only
   the modules this group needs are imported, so cold start stays proportional to group size.
4. `with_group` calls `with_namespace(agent, registration=reg)` per agent; `build()`; `run_app`.

**Resolution must complete before the first `Component.__init__`,** because namespace injection
happens through the ContextVar read during construction. No incremental resolution, no namespace
added once wiring has started.

**Startup failure policy.** There is no partial build — one process, one `build()` — so the
`critical` flag is evaluated *before* a namespace is wired, not after an exception:

| Failure | `critical: true` (default) | `critical: false` |
|---|---|---|
| Agent missing from `agents.toml` | exit non-zero | log ERROR, skip |
| Module import raises | exit non-zero | log ERROR, skip |
| `on_startup` raises | exit non-zero | mark namespace down, pause consumers (C4), continue |

Exit before the port is bound, so Kubernetes crash-loops with a readable message. Default
`critical: true`: a partially loaded group whose missing agent's queue has no consumer is worse
than no pod at all. The same flag drives `readiness_policy = "critical"` — one concept, both
startup and runtime.

**Startup log** must include the group name, the agent list, the source of each resolved config
value, and per namespace the queue group and durable names. That last item makes C1 verifiable by
diffing startup logs across a regrouping.

**Settings fragment merge.** Each agent ships an unscoped `settings.toml` in its own directory
(`model_name = "..."`, not `[default.order] model_name`). The build merges each fragment under its
own scope so C5 resolves it, without the author knowing scopes exist. Collisions between a
fragment and a root key are reported at build time.

One image for the whole platform; the group is injected at container start, not baked at build
time. Build-time dependency trimming is an opt-in optimisation for sharply diverging dependency
sets or hard tenant boundaries only — it does not change this format.

**Deployment note (agent repo, not this repo):** when mounting a file, give the ConfigMap a
content-hashed name (`finance-group-a1b2c3`) — kustomize's `configMapGenerator` default, or a
Helm `checksum/config` annotation. A plain ConfigMap edit leaves the pod template unchanged, so
nothing restarts and the orchestrator keeps running the group it resolved at startup. One
ConfigMap per group, not one shared: a shared one rolls all twenty agents whenever any group
changes.

---

## Phase 9 — Deployment-facing constraints (telemetry, probes)

**Files:** `io/telemetry/telemetry.py`, `io/api/actuators/actuator_api.py`,
`io/api/actuators/health.py`

**C2 — per-namespace telemetry identity.** `telemetry.py:39-41` currently builds one `Resource`
with one `service.name` for the whole process. Setting it to the group name would break every
dashboard, alert and SLO on the day of a regrouping. Instead: one `TracerProvider` and
`MeterProvider` per namespace, each with
`Resource({"service.name": <agent>, "deployment.group": <group>, "service.instance.id": <pod>})`,
all sharing a single exporter and `BatchSpanProcessor`. Dashboards key on agent and stay blind
to grouping.

**Empty-namespace path is mandatory.** Implemented naively, a single-agent app would get
`service.name = ""` and its dashboards would go dark on upgrade. Namespace `""` must keep
producing exactly one provider using `otel_service_name` from config, as today.

**C3 — liveness is never namespace-dependent.** If one degraded namespace fails the pod's
liveness probe, Kubernetes restarts every agent in the group, reintroducing the blast radius the
grouping was paid for.
- Liveness: process and event loop only.
- Readiness: `readiness_policy` config — `"all"` (default; any degraded namespace → not ready),
  `"critical"` (only namespaces flagged `critical` in the group config gate readiness), `"any"`
  (ready while at least one namespace is up).
- Per-namespace degradation surfaces as a `blueprint_namespace_up{agent="..."}` gauge plus an
  ERROR-level event. Alerting decides who is woken; the probe decides only where traffic goes.

**C4 — a degraded namespace stops consuming.** Readiness gates HTTP only; a not-ready pod still
holds its NATS subscriptions and still consumes events, so for an event-driven agent readiness
alone is cosmetic. With per-namespace transports (P6) this is closing that namespace's client
rather than selective unsubscription, and `ClientHealthChecker` already yields the per-agent
health entries that `readiness_policy = "critical"` needs.

**C6 — agent code cannot observe its grouping.** No supported API exposes the group name, its
membership, or the number of namespaces in the process. This is what makes regrouping incapable
of breaking agent code. `deployment.group` is set by the framework on telemetry resources and is
not readable through a public API.

**C7 — failure is never silent at namespace granularity.** Every path that stops a namespace
serving emits an ERROR-level event carrying that namespace's telemetry identity, independently of
any pod-level symptom. This is what makes the residual isolation cost of grouping manageable rather
than merely accepted: the three failure classes that take a whole group down — memory limit
breached, native crash, blocked event loop — raise no catchable exception, so careful error
handling lowers how often a group dies without changing which failures kill it. Attribution is the
only lever left, so it is normative. Work items:

- Extend the C3 gauge and ERROR event to *every* removal-from-service path, not only the ones
  readiness reads.
- Audit every framework `ensure_future` / `create_task` for a done-callback that logs exceptions
  with the namespace attached (`nats_client.py:77` is the pattern; a bare `ensure_future` is a
  violation).
- Drive `blueprint_namespace_up = 0` from per-namespace `subscriptions_ready`, so a namespace that
  silently stops consuming is visible while the process stays healthy.
- Tag in-flight handler spans with the namespace and emit a periodic per-namespace in-flight gauge,
  so a process-terminating failure can be attributed post-mortem. Without this an OOM kill is
  indistinguishable across a group's agents.

Grouping removes the pod restart that used to serve as the alert, so the alert must be emitted
deliberately.

**Dev-mode detection.** Three mistakes are harmless alone and fatal in a group, and none can be
hidden by API design — so they must be caught mechanically rather than documented:

| Mistake | Detection |
|---|---|
| Blocking the event loop | dev mode sets `loop.set_debug(True)` with a slow-callback threshold; production keeps a higher-threshold watchdog naming the executing namespace (C7) |
| Module-level side effects | CI: import each agent module, assert registry empty and root logger has no handlers |
| Non-idempotent handlers | explicit flag at scaffold time and in `asbs validate` (P4) |

---

## File change summary

| File | Phase |
|---|---|
| `utils/utils.py` | 0 |
| `app_builder.py` | 0 (`AgentRegistration`), 3 (`NamespaceBuilder` + executor provisioning), 6 |
| `__init__.py` | 0 |
| `component/registry.py` | 1 (namespace storage, named caches, executor registry) |
| `component/component.py` | 2 (`namespace` param, `executor` property) |
| `handler/handler_chain.py` | 4 |
| `services/eventing/event_processing_service.py` | 4, 7 |
| `services/infrastructure/cache_service.py` | 2 (sync ops via `run_in_executor(self.executor, ...)`) |
| `io/api/eventing/nats.py` | P2 (stop swallowing classified exceptions), 5 |
| `io/api/eventing/cloud_event_processor_mixin.py` | 5 |
| `io/api/eventing/event_handling_base.py` | P2 (ack parity in `handle_event`), 5 |
| `clients/client_base.py` | P0 (`subscribe(topic_callbacks)` abstract) |
| `clients/io/nats_client.py` | P0 (managed subscribe, retry, reconnect, drain), P1-P3 (queue group, ack/nak/term, consumer tuning), 5 (durable naming) |
| `clients/io/dapr_client.py` | P0 (same lifecycle, mirrored) |
| `io/api/eventing/dapr.py` | P2 (ack parity: `NO_HANDLER_FOUND` → SUCCESS, `CriticalHandlerError` → DROP) |
| `handler/event_handler_base.py` | 7 |
| `handler/handler_chain.py` | P4 (CloudEvent-id dedup before dispatch) |
| `io/api/scheduling/scheduler.py` | P5 (`scheduler_mode`; timer suppressed in event mode, lease in in-process mode) |
| `group_config.py` (new), `entrypoint.py` (new) | 8 |
| `io/telemetry/telemetry.py` | 9 (C2 — per-namespace providers + empty-namespace path) |
| `io/api/actuators/actuator_api.py`, `io/api/actuators/health.py` | 9 (C3, C4, C7 — gauge and ERROR event on every removal-from-service path) |
| `clients/io/nats_client.py`, `clients/io/dapr_client.py` | 9 (C7 — done-callbacks on detached tasks; `subscriptions_ready` drives the per-namespace gauge) |
| `config/config.py` | 3 (C5 — `agent_scope` wiring via `with_namespace`), 8 (fragment merge) |
| `services/eventing/event_publishing_service.py` | P6 (per-namespace client) |

**Scaffolding changes (`blueprint/agent_generator`)** — none of this exists yet:

| Piece | Change |
|---|---|
| `asbs create agent-module <name>` | new; today `asbs setup` scaffolds a whole project, one agent per repo |
| `asbs dev <agent-path>` | extend; today hardcodes `src/main.py` and `uvicorn src.main:app` (`cli/commands/dev.py`) |
| `asbs validate` | extend with the group gates below |
| `base_files/Dockerfile` | root image for the agent monorepo; `ENTRYPOINT python -m blueprint.agents.entrypoint` |
| `base_files/src/main.txt` | reduce to the single `registration = ...` declaration |
| `base_files/settings.txt` | unscoped per-agent fragment |

`asbs dev` runs one agent as a group of one using its **real** namespace, so local routes are
`/api/order/orders/{id}` — identical to production — and local consumer identity is the production
queue group. A dev mode at `namespace=""` would give every developer URLs and integration tests
that differ from production. Consequently `namespace=""` is reserved for pre-migration agents;
every newly scaffolded agent has a real namespace in every environment.

**Per-agent migration (opt-in only):**
- `main.py`: wrap builder in `if __name__ == "__main__": ... run_app(app, config)`,
  add `else: registration = AgentRegistration()...`
- `Dockerfile`: `CMD uvicorn src.main:app` → `CMD python src/main.py`

## Testing expectations

New test coverage required alongside the implementation:

- **Registry:** namespace isolation (component in `"order"` not visible from `"invoice"`),
  two-level fallback resolution, named cache CRUD, executor registry add/get/fallback.
- **`AppBuilder` / `NamespaceBuilder`:** `with_namespace` wires components into the
  correct namespace; `AgentRegistration._apply` delegates all stored entries correctly;
  ContextVar is reset after `_apply` (no namespace leak between calls).
- **Handler chain:** namespace-scoped handler selection — handlers registered under
  namespace A are not invoked when processing events for namespace B.
- **NATS:** per-namespace subscription closures capture and forward the correct namespace
  to `process_event`.
- **Consumer identity (C1):** durable name and queue group are a function of the namespace
  alone — assert they are byte-identical across two builds where the same agent sits in
  different groups. This is the test that keeps regrouping cheap; without it C1 rots silently.
- **Ack lifecycle (P2):** a handled message is acked exactly once; a retryable failure naks; a
  poison message terms. Regression test that no message is redelivered after a successful handle.
- **Ack contract (P2):** an event no handler matches is **acked**, not naked — the transport edge
  behaves identically for `PROCESSED` and `NO_HANDLER_FOUND`, proving it does not read
  `ProcessingResult`; a payload that fails CloudEvent parsing terms without dispatching; and the
  Dapr response mapping is asserted against the same outcome table as the NATS dispositions.
- **Transport lifecycle (P0):** shutdown acknowledges in-flight work before unsubscribing;
  a reconnect re-establishes JetStream durables without double-acking; `subscriptions_ready` is
  false until every topic in the map is subscribed.
- **Idempotency (P4):** the same CloudEvent `id` delivered twice dispatches to the handler once.
- **Scheduler (P5):** with three simulated replicas a cron job fires once in both modes;
  `scheduler_mode = "event"` starts no timer and the generated `CronJob` matches the declared schedule.
- **Telemetry (C2):** each namespace's spans carry `service.name = <agent>`, not the group name.
- **Silent failure (C7):** every path that stops a namespace serving emits an ERROR event and
  `blueprint_namespace_up{agent} = 0` under that namespace's identity; a namespace whose
  subscriptions vanish while the process stays healthy is reported; failing a task in each
  background path produces a logged exception carrying the namespace, never a swallowed one.
- **Probes (C3):** a degraded namespace never fails liveness; readiness follows
  `readiness_policy` under all three settings.
- **Group config (Phase 8):** every declared group resolves, imports and `build()`s without
  external I/O; an unknown agent name and a duplicate agent across groups both fail loudly.
- **Config delivery (Phase 8):** file-only, env-only, and both-together all resolve to the same
  agent list; env vars override the file key by key; a missing `BLUEPRINT_GROUP_CONFIG` path falls
  back to the repo file; an agent named in the group but absent from `agents.toml` fails at
  startup with the group and agent name in the message.
- **Backwards compat:** all existing unit tests pass unchanged with default `namespace=""`. That
  proves the API still compiles, not that behaviour is preserved — so add both of:
  - a **frozen compat suite** exercising today's usage patterns, including `with_cache(False)` and
    `with_cache(True, False)` positionally, never updated to the new API. If it needs editing, a
    break shipped.
  - a **generated-project smoke test**: `asbs setup`, then build and start the result unchanged
    against the new framework version. Catches the Dockerfile and `main.py` paths unit tests miss.

## CI gates

Run against `deployment-groups.yaml` on every change, so a bad grouping fails in CI and not at
deploy:

- Every agent appears in **exactly one** group per environment. Two groups consuming the same
  agent is duplicate processing, not a scaling strategy.
- No duplicate namespace names; no conflicting topic declarations within a group.
- Every declared group builds (import + `build()`, no external I/O).

---

## Out of scope for this plan

- Multiple simultaneous transport types (e.g. NATS + Dapr in one app).
- Cross-namespace agent calls (orchestrator → worker patterns).
- Dynamic namespace registration *after* startup. The group is resolved at process start from
  `BLUEPRINT_GROUP`; namespaces are not added or removed while the process runs.
- Ordering guarantees. Competing consumers provide no per-topic ordering; order-dependent work
  needs a partition key and one subject (and consumer) per partition.
- Lazy agent instantiation and scale-to-zero — both evaluated and rejected (spec sec. 1,
  *Non-goals*). Do not re-propose without new measurements.

---

## Planned, not yet written

Decided in discussion but not yet reflected anywhere in the repo. Each is a deliverable, not an
open question.

**Documentation**
- `docs/development-workflow.md` — the end-to-end walkthrough: scaffold an agent inside the
  monorepo, develop it, run it with `asbs dev`, test it, then how it reaches a cluster (CI gates ->
  one image -> group config -> generated manifests -> pod startup -> regrouping later). The
  per-piece changes are captured in *Scaffolding changes* above; the narrative is not.
- `docs/guides/deployment.md` **contradicts this plan and ships today.** It recommends
  `replicaCount: 2` plus an HPA as normal scaling, documents the multi-replica cache caveat, and
  says nothing about schedulers (#73) or duplicate event consumption (P1). It also assumes one
  Deployment per agent. Must be rewritten alongside Phase 8, or it actively misleads.
- A downstream repo generates `supervisord` config for multi-agent hosts. Under this decision that
  generator becomes dead code; whoever owns it needs telling.

**Issue hygiene** (nothing has been posted yet — analysis only)
- Comment the decision on #75 (deployment model: neither Model A nor Model B) and #35 (prefork vs
  multi-tenant host: multi-tenant host chosen, prefork dropped).
- Open issues for P1 and P2 — the missing queue group and the never-sent acknowledgement. They are
  live defects independent of this plan and should not be buried inside it.
- #32's success metric needs restating: "per-agent RAM" is meaningless once the interpreter is
  shared. The unit becomes *baseline per group + marginal per agent*, and its "as-is 160-250 MB per
  agent" row describes the model being retired.
- #43 (schedulers started twice within one process) should be fixed together with P5 — same code
  path, and they compound: #43 unfixed plus two replicas gives four ticks.
- #28 (resilient broker startup) looks delivered by the `event-client-resilience` work; check
  whether it can be closed.
- PR #27 (`feature/event_handler_retries`) is being closed with its work folded into P0. Say so on
  the PR and on #27's issue, so the branch is not resurrected later: the code is not abandoned,
  only relocated, and it arrives with the shutdown drain and the ack contract the PR lacked.

**Engineering spikes**
- **Ack-retry-on-reconnect.** Belongs in P0's `_on_reconnected`. Capture the acknowledgement reply subject and re-send after a
  reconnect, narrowing the duplicate window from "certain on any connection blip" to "only if the
  pod also dies". Two unknowns make this a prototype rather than a design commitment: a redelivery
  may already be in flight when the retry lands, and the behaviour of acking a stale delivery
  attempt depends on how the server keys pending state on stream sequence. **Validate against a
  real broker before relying on it.**
- **Marginal RSS per namespace.** Build N namespaces, report the resident-size delta per namespace,
  reusing #36's benchmark harness. #32 measures ~6 MB per forked child with shared libraries; a
  namespace has no separate process at all and should come in materially below that. This is the
  number that retires the lazy-agent idea for good, and it is currently an estimate.
- ~~**Broker connection ceiling.**~~ Closed, not a spike. 100 agents at 2 replicas is ~200
  connections against a self-operated broker whose default `max_connections` is orders of magnitude
  higher, and no authentication is wired today (`nats.connect()` takes URL and reconnect parameters
  only, `nats_client.py:93`). The number only needs checking where the cap is issued externally per
  account — a managed broker, or an operator-mode account JWT carrying a `conn` limit. Keep as a
  deployment note, not an engineering question.
- **`CronJob` generation.** P5 requires the schedule to stay declared in agent code and the
  `CronJob` to be generated from it. The generation path is unspecified.

---

## Open questions

Owned by the spec, sec. 13 -- they constrain the design, not the work breakdown, and duplicating
them here would let the two copies drift. The two that most affect this plan: whether the target is
20 or 100 agents, and whether the 4 GB host budget is real. Both decide how many groups the
grouping dial actually has.
