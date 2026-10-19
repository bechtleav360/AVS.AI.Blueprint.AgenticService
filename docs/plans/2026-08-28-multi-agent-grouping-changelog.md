# Change Log -- Multi-Agent Grouping

| | |
|---|---|
| **Spec (normative)** | `docs/specs/2026-08-28-multi-agent-grouping.md` |
| **Implementation plan** | `docs/plans/2026-08-28-multi-agent-grouping.md` |
| **Follow-up plans** | `docs/plans/2026-09-28-grouped-http-surface.md`, `docs/plans/2026-10-14-named-connections.md` |
| **Branch** | `feature/multi-agent-namespaces` |

The record of this branch: what each phase decided and what came out of it. It doubles as the
pull-request description. **The step-by-step history -- every change, its code walkthrough and its
measurements -- is in `git log` on this branch**; this file was condensed on 2026-10-15 (it had
grown past 600 KB). User-facing changes and every breaking change are in `CHANGELOG.md` under
`[Unreleased]`, which is the list to read before upgrading.

---

## What this feature does

One agent used to mean one process, one port, one broker connection and one image, so a platform
of 100 agents paid the ~154 MB Python baseline 100 times. **Which agents share a process is now a
deployment parameter, not an architectural commitment.** Components carry an ambient
**namespace** (`""` by default, so nothing existing changes); a namespace owns its handlers, agent
runtimes, REST routes, AI client, thread pool, caches and broker connection, while the port and
the health endpoint stay shared. A group of one gives process isolation, a group of twenty the
shared-interpreter memory profile, and moving an agent between groups changes neither its
broker-side consumer identity nor its telemetry identity.

---

## Decisions and outcomes, by phase

**Spec and contracts.** Spec and phased plan extracted into the repo's conventions (`4233933`).
Acknowledgement contract: a normal return acks, an exception does not, `NO_HANDLER_FOUND` acks
(`b6ab1c9`). Selection and fan-out rules (spec sec. 7.7) with acceptance criteria (`13e4d28`,
`b94f60c`).

**P0 -- transport lifecycle.** Managed whole-map `subscribe()`, background retry, resubscription on
reconnect, readiness gated on `subscriptions_ready` (`77af507`); in-flight handlers drain before
the connection closes (`585e58c`); an undecodable payload is told apart from a failed dispatch
(`3843abf`). Dapr declared topics actually subscribe (#81, `fac528b`).

**P1 -- queue groups.** Core NATS subscriptions join a queue group derived from the agent, so a
second replica no longer processes every message again (`05083c8`).

**P2 -- acknowledgement.** Both transports render one decision table (ack / nak / term); Dapr's
`NO_HANDLER_FOUND` answers `SUCCESS`, a critical error drops (`ce17f87`). Unmatched events are
counted (`blueprint.events.unhandled`).

**P3 -- consumers.** `ack_wait`, `max_ack_pending`, `max_deliver` configurable and broker-enforced;
JetStream durables carry a deliver group; given-up messages are dead-lettered to
`<queue group>.dead-letter` (`8ce9600`). Three stream/durable naming defects fixed on the way.

**P4 -- deduplication.** Opt-in (`idempotency_enabled` + required `idempotency_ttl`), keyed on event
id and source, released on a failed dispatch; the scaffold and `asbs validate` make the author
decide; duplicates are counted apart (`d127843`).

**P5 -- scheduling.** `scheduler_mode` is **required** (breaking): `"event"` takes the tick as an
event (the queue group picks one replica), `"in_process"` claims each tick in the cache
(`CacheService.claim`, atomic on both backends) so one replica runs it. Second-timer defect (#43)
and two scaffold defects fixed; publishing no longer requires consuming
(`event_publishing_enabled`) (`662f7b5`).

**P6 -- one transport per namespace.** Clients belong to a namespace, register under a qualified
name and derive queue group and durable from it; connections are named
`namespace.group.pod` (never used broker-side, C1); one alphabet and one gate for namespace names
(`be5e489`). `/status/env` stopped returning credentials (#91).

**Config rework.** Logging leaves `Config`; one loaded tree with one view per namespace (C5); the
loader is unreachable from agent code; the env-var prefix is the project's; `/status/env` answers
per agent.

**Phases 0-7.** The namespace is ambient (`run_app`, one declaration applied alone or per agent);
the registry resolves namespace-then-root without a fallback across agents; caches are looked up
by name and namespace-scoped; one thread pool per agent, lazily; dispatch per agent with
`get_handled_event_types()` as a selection hint; transport endpoints subscribe per agent; `build()`
wires a transport per agent; an agent's HTTP surface lives under `/api/<agent>`; grouped Dapr is
routed and fanned out in-process; a handler can name its runtime, and an ambiguous name fails at
startup.

**Phase 8 / 8b -- the group runs.** `AppBuilder` only records and `build()` is the only thing that
builds; `AgentBuilder` records too and builds against its own agent's configuration; `AgentGroup`
turns named declarations into one application; four declaration surfaces became one; a cache is
private to its agent; health checks carry their agent; an agent's own settings file is its scope;
`AGENTS.md` written and its design rules guarded by `test_design_rules.py`.

**Phase 9 -- identity and failure survive grouping.** Per-agent telemetry resource and meter, a
degraded agent drives `blueprint.namespace.up = 0` and an attributed ERROR, consumption pauses
(not closes), a latched agent recovers by retry, blocked-loop watchdog.

**Phase 10 -- setup and migration.** A scaffolded project is a group of one in every environment;
`asbs validate` reports what a project has not decided; migration and deployment guides rewritten
against what ships; scaffolded settings/secrets are the ones the framework reads.

**Isolation.** The four routes by which an agent could reach a neighbour's data are closed: no root
fallback into another agent, a view names only its own agent or the root, one declaration never
hands two agents the same object, dotted keys stay inside their agent.

**Review findings and hardening.** Publishing is declared (`nats_publish_mode`,
`nats_publish_subjects`); `nats_url` no longer defaults to localhost outside development; NATS
credentials supported and URL credentials redacted; handlers see `nats_subject`; a failed result
publish fails the delivery (#1); the declared transport mode is enforced (#4); dedup claims
atomically (#6); structured output and deps types reach the agent (#2); one `AgentBuilder` serves
several agents (#10); REST payloads no longer logged (#12, #13); the sessions replay guard is
bounded (#14); a standalone agent's v0.8.1 output restored; a Dapr sidecar mock for demos.

**Grouped HTTP surface** (`2026-09-28-grouped-http-surface.md`). Reserved path segments for
framework endpoints (`nats`, `cache`, `scheduler`), one Swagger tag per agent, a developer
`path_prefix`; standalone paths and tags never change.

**Concurrency and named connections** (`2026-10-14-named-connections.md`, D1-D11).
- Deliveries run concurrently (`nats_max_concurrent_runs` per agent and connection,
  `nats_extra_runs_per_process` as a process pool), long runs send `in_progress` heartbeats
  (`nats_heartbeat_enabled`), a run can be bounded (`nats_handler_timeout`, cancel + nak).
- A `ConnectionSource` (`nats_connection_source`) supplies named connections: bindings with a
  subject prefix onto the deployment's consumers, `validate` before a run, `run_scope` around it,
  `claims` keep claimed subjects off the default connection (`nats_unclaimed_subjects`), runtime
  changes through `watch(notify)`, readiness per connection (`nats_connections_readiness`).
- A closed connection reconnects and resubscribes; reconnects are unlimited by default.
- `HandlerResult.skipped(reason)` (D11): responsible but nothing to do -- chain stops, acked, INFO,
  `blueprint.events.skipped`, `ProcessingStatus.SKIPPED`. An event no handler takes keeps its
  WARNING (spec sec. 7.2 amended to match).
- `nats_delivery_attempt` / `nats_max_deliver` in the handler context for JetStream deliveries.
- Step 6: docs, scaffold, skills and examples agree with the code (inventory:
  `docs/plans/2026-10-15-named-connections-step6-inventory.md`); `asbs validate` checks the NATS
  keys; `examples/site_readings` shows two named connections end to end.

**PR #96 review fixes** (`2026-10-16-pr96-review-fixes.md`).
- Step 1, dedup bracket (B1, M11): a delivery keeps its dedup marker only when it is acknowledged.
  The chain releases on any `BaseException` from dispatch (a handler timeout or shutdown is a
  `CancelledError`); `EventProcessingService.process_event` releases in a `finally` unless the result
  was settled and no cancellation is pending (a handler that swallowed it). Only the delivery that
  won the claim releases (`CLAIMED_CONTEXT_KEY`), so a duplicate never drops the first delivery's
  marker. Measured on JetStream (`nats_handler_timeout = 0.5`, disk cache): timeout, swallowed
  cancellation and a scalar return each lost the event before (redelivery skipped and acked), and
  run to completion on redelivery now; a real duplicate is still skipped.
- Step 2, leaks in logs and responses (B2, S8, S4, N3): `describe_validation_errors` (`models/errors.py`)
  renders a validation failure as `loc: type` only, used by the Dapr and NATS unparseable-payload lines
  and the inner Dapr event's errors (no longer logged where raised, raised `from None`); a Dapr reason
  is a `HandlerError`'s or the exception's type name; `_Link` hides `url` and `connect_options` from
  `repr`; the default and named connection lines go through `_describe_error`. Measured with a
  placeholder secret (JetStream, Dapr endpoint with the sidecar mock): in the logs and the answer
  before, in neither now. A handler's own exception text is still logged as it is, by design.
- Step 1a, connection isolation (T1): the dedup key adds `nats_connection` for a delivery from a named
  connection (the default connection keeps `(source, id)`, no migration); handler-author docs say that
  per-data-source state is keyed by that context key. Broker test on the accounts broker: the same
  `(source, id)` on connections A and B runs on both, a repeat on A is skipped; without the change B
  was skipped.
- Step 17, telemetry (S22, W1, D17): `_SharedSpanProcessor` and `_SharedMetricExporter` count their
  providers and are closed by the last; providers built with `shutdown_on_exit=False`;
  `providers.shutdown_providers()` (agents first, root last) from `TelemetryManager.on_shutdown` at the
  end of the lifespan and once from atexit; in a group an agent keeps `service.name` although
  `OTEL_SERVICE_NAME` is set, with one WARNING. Live (group 'orders' + 'billing', OTLP collector with a
  file exporter, OTEL_SERVICE_NAME set, a span and a counter in each handler's on_startup and
  on_shutdown): 4 of 4 metric points and 4 spans under 'orders'/'billing'. Control: everything under
  'platform-wide', 2 of 4 metric points, four 'Exporter already shutdown' warnings.
- Step 16, Dapr hardening (S5, S9, N5, D6): a deep copy of the CloudEvent per agent when a delivery fans
  out to more than one; a startup WARNING for a shared topic with an agent's `idempotency_enabled` off;
  `EventHandlingBase._metric_topic` hook, Dapr labels an undeclared topic `<undeclared>`; an ACK combined
  with a TERM answers SUCCESS without a reason; `DaprDeliveryRoute` wraps only `/events/{topic}`. Live (a
  group served by uvicorn, Dapr sidecar mock, agents 'orders' and 'billing' on 'orders.created'):
  'billing' read `{"order": 1}` after 'orders' changed it, the answer was `{"status": "SUCCESS"}`, 5
  random topics gave one `<undeclared>` series per agent, the WARNING named both agents. Control: no
  WARNING, reason attached, 'billing' saw the change, one series per random topic.
- Step 15, dedup without a heartbeat and Redis calls (S6, S7, D4): `HandlerChain._claim`/`release` and the
  scheduler's `_claim_tick_slot` run the cache call in `asyncio.to_thread`; a startup WARNING for dedup with
  the NATS heartbeat off and for dedup under Dapr; `cache.redis_socket_timeout` (opt-in); redis-py floor
  raised to 8.0 (its 5 s default timeout; 7.x had none). Live (Redis 7 in WSL, container paused, timeout 2 s):
  longest event-loop gap 0.06 s and the claim failed open after 2.01 s; control: the loop stood for 2.02 s.
- Step 14, scaffold and CLI (M10, S14, N6-N9, D10): `DYNACONF_APP_ENVIRONMENT` in both Dockerfiles
  (production, development in the dev stage), a Python health check in `group_Dockerfile`, `asbs setup`
  validates the name before writing, the `settings.txt` comment no longer carries the substituted token,
  `asbs create service` imports what it names, `AgentRuntime` only where agents are used, the scheduler
  template no longer claims a generated CronJob, and every `asbs dev` message says that without `--name`
  the agent is served alone at the root. Live (WSL): a scaffolded two-agent group image built from the
  working tree turned healthy in 10 s and loaded `production`; control with the old template: `curl: not
  found`, never healthy, `development`. In the same image: `BLUEPRINT_CRITICAL_AGENTS=ordrs` exits 1
  naming the typo (step 7), and a `.secrets.toml` mounted for `orders` reaches `orders` only (step 8).
- Step 13, `/status/env` masker (M12): URL userinfo fails closed (an `@` left after `://`, an
  unparseable port), secret query parameters and `Name=value;` segments are masked, a section under a
  secret key is masked whole, `pass`/`dsn`/`conn`/`sig`/`signature` count as whole words. Live (a built
  app under uvicorn, `GET /status/env`): 200 and no placeholder in the body; control: 500 with
  `${PORT}`, and without it seven placeholders returned.
- Step 12, Redis cache isolation (M6): the default store's `clear`, `list_namespaces` and `list_values`
  take only keys of its own form (`<prefix>:<namespace>:<sha256>`); a clear without `key_prefix` warns;
  no key-layout change. Live (Redis 7 in WSL, stores from `CacheBackendFactory` for root, `orders`,
  `billing`): after a root clear both agents' keys and a foreign key remain, with prefix and without;
  control: all agent keys gone, and without a prefix the whole database. The Redis integration tests
  (`BLUEPRINT_TEST_REDIS_URL`) ran for the first time on this branch: 3 passed.
- Step 11, scheduler robustness (S24-S27, D14, D15): `_started` is set only after the timer or the event
  wiring stands; one tick-age gauge per meter reports every scheduler of it (weak registry); `validate_crontab`
  runs in both modes, refuses day `7` and, in event mode, any numeric weekday; opt-in `scheduler_timezone`;
  `asbs validate` and `--group` use the runtime's mode and transport checks and count environment
  overrides. Live (real APScheduler timer, every-minute crontab, UTC, two schedulers): both ticked at the
  next minute and the gauge reported both; control: one gauge point.
- Step 10, grouped scheduler (M8, M9): the tick handler is built under `namespace_scope(self.namespace)`;
  tick subject, trigger route and handler name use `base_name`; docs agree. Live (Core NATS, a group
  with agent `orders`, scheduler `nightly`, event mode): subscribed `orders.scheduler.nightly`, handler
  in `orders`, one tick from that subject and none from the doubled one, `POST
  /api/orders/scheduler/nightly/trigger` 200 and ticks. Control: subscribed the doubled subject, handler
  at the root, the documented route 404.
- Step 9, registry and sharing guards (S15, S16, S17, W6, D11): the qualified hit in `_lookup` must
  belong to the asking namespace; `clear`, `clear_components`, `shutdown_executors` are refused on a view,
  `add_component`/`update_component_name` only for the view's own components, `get_or_create_executor`
  only for its own namespace or the root; `is_shareable` looks into a bound method's `__self__` and a
  closure's cells, and a shared declaration's factory target is checked too. W6 documented as allowed.
- Step 8, agent settings merge (M5, S11, S12, S13, D9): an agent's `.secrets.toml` is merged before its
  settings (`AgentGroup.secrets`, `merge_agent_settings(..., secret=True)` logs no value); fragments are
  layered for `current_env` and inactive environment sections are dropped; `cache`, `event_publishing`,
  `runtimes`, `runtime` are reserved namespaces and a root scalar is never replaced; a view refuses a bare
  key naming an agent's section (`Config.declare_agent`). Repro of S13 first (ENV_FOR_DYNACONF=production:
  root `prod`, fragment `frag-dev`); unit tests fail on the old code; live with the group image (step 14).
- Step 7, group config validation (M7, N2, D8): unknown critical names (also against a
  `BLUEPRINT_AGENTS`-replaced list), scalar `agents`/`critical_agents` and duplicate group names raise
  `GroupConfigError`; `AgentGroup.from_config` refuses a group left with no agent. Unit tests fail on the
  old code; the live check runs with the group image (step 14).
- Step 6, named bindings (M3, M4, S2, S3): a binding superseded before it bound is retired at once and
  hands over the binding still delivering, and a removal retires that one too; `_bind` flushes and fails
  on a refusal naming its deliver subject (compared lowercased -- nats-py lowercases the -ERR line, found
  live); a reconnect restores readiness only for `bound` bindings; binding mode answers flow control and
  drops heartbeats; `ConnectionSpec.tls` is not compared. Accounts broker: change-change and change-remove
  close the original link (control: open after 15 s), a refused deliver subject reads `retrying` with a
  permission violation (control: `bound`), an operator consumer with heartbeat and flow control delivers
  20 of 20 once with no termination (control: status messages termed). Integration suite 64 passed,
  3 skipped (Redis).
- Step 5, resume retry and C4 for sessions (M2, S18): a failed `resume_consumption` drops the partial
  subscriptions, stays paused and retries in a backoff task (cancelled by a pause and by close), a
  WARNING per attempt; `SessionsBus` gains `pause_consumption`/`resume_consumption` (stream closed,
  a job reaching it left pending) and the supervisor pauses it with the IO clients. Live (JetStream,
  health interval 2 s, a switchable check): the agent paused, its stream replaced by one blocking its
  subjects, then healthy -- attempts 1-3 failed (1, 2, 4 s apart), resumed 7 s after the blocker was
  removed, 5 of 5 events run. Control: one failed resume, still paused 36 s later. Sessions: unit
  tests only, no sessions service to run against.
- Step 4, JetStream reconnect (M1, N4, N11): `_on_reconnected` re-checks stream and consumers
  (`_ensure_broker_state`) instead of subscribing again; the message handler naks a JetStream delivery
  while paused; the first `nats.connect()` is bounded (`_first_connect_attempts`) and the configured
  count is set on the connection afterwards; a connect while paused requests a health refresh. Live
  (NATS 2.10, `/connz?subs=1`): broker restart -- 2 subscriptions before and after (control: 4), each of
  20 events run once; restart then pause -- 0 of 10 events run (control: 10); broker without storage
  replaced -- stream and consumers recreated, 20 of 20 run once; no broker at startup -- startup
  returns in 5.6 s and the agent consumes after the broker comes up (control: no return within 120 s).
  Integration suite: 60 passed, 3 skipped (Redis not started).
- Step 3, internal naming (B3): the first consumer's product name, subject prefix and module names are
  replaced by generic ones (`acme.agent.<tenant>.<agent>`, "the first consumer") in the named-connections
  plan, the accounts broker config, its connection source and three unit tests. Tree only; the
  published history keeps them (D1). The named-connection broker tests pass with the new subjects.

**Measured against a real broker** (`tests/integration`, NATS 2.10 with JetStream, plus an
accounts broker): acknowledgement exactly once, redelivery after `ack_wait`, concurrent runs,
heartbeat, run timeout, reconnect with resubscription, named connections without permission
violations, skipped results, delivery attempts.

---

## Compatibility

Every breaking change, with its migration, is listed in `CHANGELOG.md` under
`[Unreleased]` -> *Breaking*. The two that most often bite:

- **`scheduler_mode` is required** for a project with a scheduler; startup fails naming both values.
  A deliberate departure from spec sec. 7.5 (defaulting would either keep a timer per replica, #73,
  or stop ticking a service without a broker).
- **A scoped `Config`'s telemetry `service.name` is the agent's name** unless
  `<scope>.otel_service_name` is set.

`tests/unit/agents/test_frozen_compatibility.py` holds what existing projects do; it is never edited
to accommodate an API change.

---

## Open points

Still open (the closed ones, and their history, are in `git log`):

- **Pre-existing integration failure:** `test_acknowledgement_lifecycle.py::TestARetryableFailureComesBack::test_the_broker_counts_it_as_a_redelivery`
  fails on the unchanged code too: the retryable failure is nak'd at once, so all `max_deliver`
  attempts are spent before the test reads `num_redelivered`. The test's premise needs revisiting.
- **Broker-test gap -- overlapping subjects in one queue group:** a wildcard plus a literal it covers
  on one client is expected to be merged by the server into one delivery; not yet verified against
  a real broker (referenced from `NATSClient`'s docstring).
- **`test_three_replicas_run_one_tick` was flaky once** (2026-09-24); likely the disk cache's
  non-atomic takeover of an expired claim. Not investigated.
- **Spec amendments owed:** C4 (a degraded transport is paused, not closed), C2 (the metric reader
  cannot be shared across providers), the root's role under `readiness_policy`, phase 7's ambiguity
  is a WARNING rather than an error. `readiness_policy = "any"` has no acceptance criterion.
- **The tick subject `<identity>.scheduler.<name>` is provisional** (subject taxonomy unratified,
  spec sec. 13).
- **Dedup and tick claims are unbounded on disk** (logical expiry only); the dedup TTL is delegated
  to the deployment (guidance: `nats_ack_wait * nats_max_deliver`).
- **The dead-letter subject has no consumer;** draining it is an operational task.
- **`get_stats()["size"]` double-counts** the disk backend's TTL entries.
- **Spec sec. 13's shape questions** (20 or 100 agents; whether the 4 GB host budget is real).
- **Group-file diagnostics:** the "no agents resolved" message omits the sole-group route, and a
  `BLUEPRINT_GROUP_CONFIG` pointing at a directory is reported as nothing mounted.

Closed since they were listed, for readers following older references: the four isolation routes
(see `tests/unit/agents/test_agent_isolation.py`), the broker integration tests
(`docs/plans/2026-09-11-broker-integration-tests.md`, #80), the latch that never released, the
scaffold's settings and secrets files, the Windows console crash, the examples' migration, and the
missing `LICENSE`.
