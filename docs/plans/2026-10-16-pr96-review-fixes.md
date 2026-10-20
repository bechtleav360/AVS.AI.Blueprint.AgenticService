# PR #96 review fixes -- verification and plan

**Status:** steps 1-21 implemented 2026-10-19 (not committed yet), each marked **Done** below with what ran
live; final run with containers recorded in the feature changelog. Open: D21 (N12) and the way forward
on D22 (N13); everything else in "Decisions" is settled.
**Base:** `81f6bf2` (head of `feature/multi-agent-namespaces`, unchanged since the reviews).
**Sources:** pajoma's review (2026-10-15, CHANGES_REQUESTED, 3 blockers), Develebook's review
(2026-10-16, 12 must-fix / 27 should-fix / 9 nits, inline), solicho's leftovers (2026-09-14/16).
Earlier comments (version bump, retarget to `develop`, #97) are resolved.

Every step below is one reviewable change under the multi-agent-grouping rules in `CLAUDE.md`:
one step, report with the code walkthrough, record it in
`docs/plans/2026-08-28-multi-agent-grouping-changelog.md`, then stop. NATS, Redis, Dapr and
Dockerfile steps get a live run in WSL before they are reported as done.

---

## 1. Verification result

Every finding was re-checked against `81f6bf2`: by reading the code, and for most by a throwaway
reproduction (fakes, fakeredis, InMemoryMetricReader, APScheduler/croniter, Docker in WSL).
Verdicts: **C** confirmed, **P** partly, **R** refuted. "SA" = also affects standalone agents.

### Blockers (pajoma)

| # | Finding | Verdict | SA | Step |
|---|---|---|---|---|
| B1 | Dedup marker survives `CancelledError` (handler timeout, shutdown) -> redelivery ACK'd unrun | C (repro) | yes | 1 |
| B2 | `dapr.py:46` logs `RequestValidationError` incl. payload values at ERROR | C (repro) | yes | 2 |
| B3 | Internal product name / tenant subject prefix in 6 tracked files, 8 branch commits, public repo | C | -- | 3 |

B3 detail: the name is absent from `develop`; it entered on this branch (plan `2026-10-14-named-connections.md`,
`tests/integration/{nats-accounts.conf,connection_source.py}`, three unit tests under
`tests/unit/agents/clients/io/`, and the feature changelog history). The branch is pushed, so the name is
already public. References to sibling repositories (`docs/specs/2026-08-24-...`, `sessions_bus.py`,
`key_provider.py`) predate the branch and are on `develop` too.

### Must-fix (Develebook)

| # | Finding | Verdict | SA | Step |
|---|---|---|---|---|
| M1 | JetStream reconnect re-subscribes although nats-py replays `_subs` -> orphaned duplicate subs | C (nats-py 2.15 read) | yes | 4 |
| M2 | Failed `resume_consumption` never retried; health stays green | C | yes | 5 |
| M3 | Superseded named binding keeps consuming after change-change / change-remove | C (code) | named conns | 6 |
| M4 | Subscribe permission violation reads as "bound", never rebinds | C (nats-py read) | named conns | 6 |
| M5 | Agent's own `.secrets.toml` never loaded in a group | C (repro) | no | 8 |
| M6 | Clearing the root Redis cache deletes every agent's/named cache; `key_prefix=""` -> whole DB | C (fakeredis) | yes (named caches) | 12 |
| M7 | `critical_agents` typo -> all non-critical; scalar YAML; zero-agent pod READY | C (repro) | no | 7 |
| M8 | Grouped event-mode tick handler registered in root namespace (C1) | C (repro) | no | 10 |
| M9 | Grouped tick subject / trigger route repeat the agent name; docs disagree | C (repro) | no | 10 |
| M10 | `group_Dockerfile` HEALTHCHECK uses `curl`, absent in slim image | C (WSL) | no | 14 |
| M11 | Dedup marker stays claimed when post-dispatch processing fails | C (repro) | yes | 1 |
| M12 | `/status/env` masker leaks (`/?#` in password, query tokens, `AccountKey=`) and 500s on `${PORT}` | C (repro) | yes | 13 |

### Should-fix and nits

| # | Finding | Verdict | SA | Step |
|---|---|---|---|---|
| S1 | Durable clash root `orders-created` vs agent `orders`+`created`; drift only warns | C | yes | 18 |
| S2 | Binding mode plain `subscribe` receives JetStream status/flow-control messages | C (mechanism) | named conns | 6 |
| S3 | `ConnectionSpec.tls` in `__eq__` -> every notify rebinds every `tls://` link | C (repro) | named conns | 6 |
| S4 | `_Link.connect_options` default repr leaks password/token/nkey | C (repro) | yes | 2 |
| S5 | Dapr fan-out hands the same `CloudEvent` to every agent; no shared-topic warning | C | no | 16 |
| S6 | Marker has no in-progress state: concurrent duplicate is ACK'd | C (repro) | yes | 15 |
| S7 | Sync redis-py claim/delete on the event loop | P: redis-py 8.1 has 5 s timeouts, `>=5.0` pin allows None | yes | 15 |
| S8 | Dapr returns `str(exc)` in response body (develop: fixed text) | C | yes | 2 |
| S9 | Unbounded `topic` label cardinality via `/events/<random>` | C (5000 points measured) | yes | 16 |
| S10 | `SessionsJobHandler` auto-declares its type, narrowing widened `can_handle_event` | C | yes | 19 |
| S11 | Bare key equal to another agent's namespace returns its section through a view | C (repro) | no | 8 |
| S12 | Namespaces not reserved against shared sections / root scalars | C (weaker than claimed: fill-missing keeps a set root value) | no | 8 |
| S13 | Fragments layered for first-pass `app_environment`, not the env Dynaconf loads | C (repro) | no | 8 |
| S14 | `DYNACONF_ENVIRONMENT` in scaffold Dockerfiles selects nothing | C (repro; predates PR, matters since #89) | yes | 14 |
| S15 | `_` separator ambiguity; qualified registry hit has no ownership check | C (code) | no | 9 |
| S16 | Registry mutation methods unguarded on views | C (code) | no | 9 |
| S17 | Bound methods / closures pass `is_shareable` | C (repro) | no | 9 |
| S18 | C4 missing for `event_bus = "sessions"` | C | no (no C4 on develop) | 5 |
| S19 | `deployment_group()` ignores the group resolved from the file | C | no | 20 |
| S20 | Undocumented standalone breaks: built-in health check name, handler class+instance, deferred construction | C (vs develop) | yes | 19 |
| S21 | `event_loop_debug` on by default in "development" (the default env) | C | yes | 19 |
| S22 | One OTLP exporter (and one BatchSpanProcessor) shared, closed by first provider shutdown | C (repro) | no | 17 |
| S23 | diskcache_rs exclusive lock vs "atomic across processes" docs | P: true for <=0.4.9 (redb), false for 0.4.10 (sqlite); pin `>=0.4.4` | yes | 20 |
| S24 | Crontab dialect: APScheduler Mon=0 vs croniter Sun=0; `7` rejected; host timezone | C (APS 3.11.3; predates PR) | yes | 11 |
| S25 | Scheduler `_started` set before success -> recovery reports success without timer | C (code) | partly | 11 |
| S26 | Second scheduler's tick-age gauge dropped | C (InMemoryMetricReader) | yes | 11 |
| S27 | `asbs validate` scheduler checks differ from runtime (a-e) | C (all five) | yes | 11 |
| N1 | Shutdown aborted by a failed recovery task (more than a nit); `actuator.on_shutdown` unguarded | C; `_loop_watchdog.stop()` part **R** | yes | 19 |
| N2 | Duplicate group names last-wins; scalar `agents` | C (repro) | no | 7 |
| N3 | Raw `exc` in NATS WARNING/ERROR logs | P: defensive, no real nats-py text with password found | yes | 2 |
| N4 | `pause_consumption` waits on `_change_lock`; `message_handler` has no paused gate | C | named conns | 4 |
| N5 | Dapr TERM+ACK answers SUCCESS with a reason; `route_class` applies to the whole router | C (repro) | yes | 16 |
| N6 | `asbs dev` without `--name` serves root, messages say otherwise | C | msgs only | 14 |
| N7 | `asbs setup` validates the name after writing the project | C (repro) | yes | 14 |
| N8 | `settings.txt` comment token `app_name` substituted | C | yes | 14 |
| N9 | Scheduler template docstring wrong; `asbs create service` misses imports (older) | C | yes | 14 |
| N10 | "Created JetStream consumer" INFO formats `ack_wait` with `%.1f`; unset `nats_ack_wait` is `None`, so the line is lost as a logging error | C (live, found in step 2) | yes | 18 |
| N11 | Startup against an unreachable broker did not return within 6 s (only nats-py's own "encountered error" was logged) | observed live in step 2, not analysed; check against the `max_reconnect_attempts=-1` connect | yes | 4 |
| N12 | An agent whose own subscription keeps failing reports ready: the failure degrades it, C4 pauses it, and a paused client reports healthy by design, so after one poll readiness is UP while `_retry_resume` keeps failing (backoff 5 s, 10 s, ...) and nothing is consumed | C (live, found in step 18; any persistent subscribe failure, not only S1) | open -- needs a decision on C4, see below | -- |
| N13 | `DiskCacheService.claim` is not atomic across processes: diskcache-rs 0.4.10's `add` lets several processes on one directory win one key (297 of 300 rounds, 4 processes, no error); 0.4.9 refused a second process the directory | C (live, step 20) | docs corrected; fix open as D22 | -- |
| N14 | M4's refusal check raced: nats-py 2.15 writes PING straight to the transport while the SUB still waits for the flusher, so the PONG could come back before the broker saw the SUB and the binding read as bound (`TestARefusedSubscriptionIsNotBound` failed 3 of 9 runs on the step-21 code, 1 of 2 on step 17, 0 of 2 on step 6) | C (live, final run) | **Fixed 2026-10-19**: two round trips in `_bind`; 8 of 8 runs green | -- |
| N15 | `app_environment` inside `[default]` makes `Config.get("app_environment")` answer the configured value while Dynaconf loads the default section, so a development check can read the wrong environment (found by the docs agent with a probe; the docs now say the key selects only at top level or through `DYNACONF_APP_ENVIRONMENT`) | P (probe, not re-checked) | open -- check and decide in step 22 | -- |
| N16 | `<agent>.otel_service_name` is resolved by `Config._resolve_service_name` but never reaches the resource: `TelemetryManager._configure_namespace` sets `service.name` to the namespace for every agent | C (code read by the docs agent) | open -- belongs with D23 (c) in step 22 | -- |
| N17 | `handler_chain._warn_without_a_heartbeat` compared `nats_heartbeat_enabled is False`, so `"false"` from an environment variable did not warn | C (unit test failed before) | **Fixed 2026-10-19**: read with `parse_bool` | -- |
| N18 | The generated handler's `on_startup` read `.get("input_event_type", )` -- `None` when the key is missing -- and compared it to `""`, so a handler without its event type started anyway (found by the validator agent). Making the check fire stops every fresh scaffold: `asbs setup`'s own handler has no `input_event_type` and does not use it (`can_handle_event` is a stub) -- found live on a scaffold, `ValueError` at startup | C (live, with control) | open -- the fix was withdrawn on 2026-10-20 (owner decision); what the generated handler does with the event type is decided later. `test_a_fresh_project_starts_the_way_its_container_does` keeps a scaffold startable | -- |
| N19 | The validator restates runtime rules that exist only as private methods: dedup policy and heartbeat/Dapr warnings (`HandlerChain`), the timezone check (`SchedulerBase`), the shared-topic grouping (`DaprEventing`), the `nats_url`/heartbeat/durable-count rules (`NatsClient`); pinned by tests, matched live word for word | C (code read) | open -- make them public and call them from the validator in step 22, which edits the same files | -- |
| N20 | `test_design_rules.all_markdown()` walked the whole checkout with `rglob`, `.venv` included, and filtered afterwards -- about 0.6 s per test, 47 s for the module | C (measured) | **Fixed 2026-10-20**: directories pruned before they are entered; same 91 files, 14 s | -- |

### pajoma warnings/suggestions and solicho leftovers

| # | Finding | Verdict | Step |
|---|---|---|---|
| W1 | `OTEL_SERVICE_NAME` collapses grouped identity (C2) | C (repro) | 17 |
| W2 | `in_process` claim slot from `datetime.now()` | P: correct, but practically harmless (misfire grace 1 s) | 20 |
| W3 | Omitted `namespace` = all on root registry, own on a view | C, by design; risk only for user root components in groups | 20 |
| W4 | Run slot can leak between acquire and `create_task` | P: theoretical | 18 |
| W5 | `_durable_for` docstring says nothing is renamed (dotted topics are) | C | 18 |
| W6 | Isolation guard keyed by `id(builder)` only | C; decided: document, sharing between agents is fine | 9 |
| T1 | Dedup key not scoped to the named connection -> one tenant's event can suppress another's | C (code, found 2026-10-16) | 1a |
| W7 | Stale xfail paragraph in `test_agent_isolation.py` | C | 21 |
| W8 | Hand-set `version = "0.9.0"` and dated `[0.9.0]` CHANGELOG section vs `AGENTS.md` versioning rule | C | 21 |
| W9 | PR description stale (#89, LICENSE, size), no `Closes`, no AI disclosure, #35 not linked, no rollback note | C | 21 |
| W10 | CI runs only `tests/unit` | C | out of scope (CI, needs services) |
| W11 | `NATSClient` 2,652 lines; transitional test-only members; PR size | C | out of scope (follow-up issue) |

Overlap with the 2026-09-24 defect list: M1 was item 5 there, S7 item 9. Neither had been fixed.

---

## 2. Steps

Must-fix and blockers first (steps 1-14), then hardening (15-20), then documentation and PR hygiene (21).

1. **Dedup bracket** (B1, M11). `EventProcessingService.process_event` / `HandlerChain`: one
   `try/except BaseException` from claim to settled result that releases the marker, replacing the
   publish-only release. Tests: timeout + dedup, scalar return + dedup, cancel mid-handler.
   **Done 2026-10-19** (not committed): also covers a handler that swallows the cancellation;
   measured live on JetStream with a control run against the unchanged code.
1a. **Connection isolation** (T1, user requirement 2026-10-16). The blueprint knows no tenants, only
   named connections, but no framework-owned state may be shared across connections, because each one
   stands for a different data source behind it. Checked: result publishing is refused on named
   connections (`_refuse_result_publishing`), dead letters go out on the arrival link, each run has its
   own task context. **Gap:** the dedup key is `(source, id)` only (`handler_chain.py:532`), so two
   connections delivering the same producer's event id suppress each other. Fix: add the connection
   name to the key when the delivery came from a named connection (the default connection keeps
   today's key, no migration). Test: two connections, identical `(source, id)`, both handled. Docs: a
   section for handler authors -- state that must stay per data source is keyed by the
   `nats_connection` context key. M3 (a removed connection still consumed) is the same class, step 6.
   **Done 2026-10-19** (not committed): unit tests with a control run, and a broker test on the accounts
   broker (`test_dedup_keeps_the_connections_apart`) that fails without the change.
2. **Leaks in logs and responses** (B2, S8, S4, N3). `dapr.py:46` logs `loc`/`type` only; the related
   pre-existing ERROR logs in `event_processing_service.py:307/312`; Dapr reason = `exc.reason` or type
   name; `_Link.connect_options` `repr=False`; NATS link logs via `_describe_error`.
   **Done 2026-10-19** (not committed): also the NATS decode log (same leak as `dapr.py:46`, already on
   `develop`) and `_Link.url` (`nats_url` may carry `user:pass@`); `resume_consumption`'s log is left
   to step 5. Measured live with a control run; found N10 and N11 on the way.
3. **Internal naming** (B3). Replace with generic names (`acme.agent.<tenant>.<agent>`) in the six files.
   History: see decision D1.
   **Done 2026-10-19** (not committed): also the consuming repository's internal module names in the
   named-connections plan; `git grep` finds none of them; `test_named_connections.py` passes on the
   accounts broker with the renamed subjects.
4. **JetStream reconnect** (M1, N4; N11 checked here). **Done 2026-10-19** (not committed): N11 was a
   hang -- nats-py retries the first connect itself when reconnects are unlimited; the first connect is
   now bounded, and connecting while paused re-evaluates health at once. Measured live with a control
   run (subscription counts from `/connz`, runs per event, paused runs, startup time). `_on_reconnected` stops re-subscribing under JetStream, re-checks
   stream and consumers only; `message_handler` gets a `_consumption_paused` gate (NAK under JetStream).
   Replace `test_reconnected_resubscribes_jetstream_topics` with a fake that replays `_subs`.
   Live: broker restart in WSL, count subscriptions and deliveries per message.
5. **Resume retry and C4 for sessions** (M2, S18). **Done 2026-10-19** (not committed): the sessions
   bus closes its job stream while paused and leaves a job that reaches it pending; the supervisor
   pauses it with the IO clients. Live: M2 on JetStream with a control run; the sessions part unit-only
   (no sessions service available). Unsubscribe partial subscriptions on failure, then
   per D2. `SessionsBus.pause_consumption/resume_consumption`, supervisor includes it. Test supervisor and
   client together.
6. **Named bindings** (M3, M4, S2, S3). Retire the `replaces` chain; `flush()` after subscribe and raise
   on a matching permission error; `on_reconnected` sets ready only for bound links; drop/answer status
   messages in binding mode; `tls` `compare=False`. Live: accounts broker from `tests/integration`.
   **Done 2026-10-19** (not committed): four broker tests in `test_named_connections.py`, each failing on
   the step-5 code; the live run also found that nats-py lowercases the -ERR line, so the refusal is
   matched lowercased.
7. **Group config validation** (M7, N2). Unknown critical names, non-list `agents`/`critical_agents`,
   duplicate group names -> `GroupConfigError`; empty resolved group fails at startup; D8.
   **Done 2026-10-19** (not committed): unit tests with a control run; the empty group is checked in
   `AgentGroup.from_config` (with unknown critical names refused, `resolve` cannot produce one). Live:
   with the group image in step 14.
8. **Agent settings merge** (M5, S11, S12, S13). Merge `<agent>/.secrets.toml`; reserve shared-section
   names and refuse to replace a root scalar; layer fragments for the environment Dynaconf actually
   loaded and drop inactive sections; bare-key view refusal per D9.
   **Done 2026-10-19** (not committed): the reserved names live in `namespace.py` (an import from the
   config package would be a cycle) and a test keeps them equal to `SHARED_NESTED_PREFIXES`; the bare-key
   refusal applies only where the root value is a section; `AgentGroup.assemble` declares every agent.
   Live: with the group image in step 14.
9. **Registry and sharing guards** (S15, S16, S17, W6). Ownership check on the qualified lookup branch;
   `clear`/`clear_components`/`shutdown_executors` refused on views, ownership checks in
   `update_component_name`/`get_or_create_executor`; bound methods/closures checked; W6 per D11.
   **Done 2026-10-19** (not committed): also `add_component` on a view, and a shared declaration's
   factory target; W6 documented in `_refuse_state_shared_between_agents` and the migration guide.
   Unit tests fail on the old code; live with the group image (step 14).
10. **Grouped scheduler** (M8, M9). Construct the tick handler under `namespace_scope(self.namespace)`;
    topic and trigger route from `base_name`; fix `deployment.md`, `claude_docs/CLAUDE.md`,
    `SKILL.md`, `configuration-keys.md`; literal-subject test. CHANGELOG line for alpha users of the
    doubled subject. Live: NATS in WSL, publish the documented subject, see the tick.
    **Done 2026-10-19** (not committed): also the tick handler's own name; the existing test that encoded
    the doubled subject now asserts the base name. Live with a control run.
11. **Scheduler robustness** (S24-S27). `_started` only after success; one tick-age gauge per meter with
    a multi-scheduler callback; crontab dialect/timezone per D14/D15; validate shares the runtime's checks.
    **Done 2026-10-19** (not committed): `validate_crontab(crontab, mode)` runs in both modes; S27 (a)-(e)
    through `normalise_scheduler_mode` / `delivers_ticks`; a missing `event_bus` is a notice. Live: two
    in-process schedulers with a real timer and an SDK reader, with a control run.
12. **Redis cache isolation** (M6). Default store's `clear`/`list_namespaces` skip child-store keys
    (no key-layout change); WARNING when the default store has `key_prefix=""` and is cleared.
    Live: two agents on one Redis in WSL.
    **Done 2026-10-19** (not committed): `_owns` (a 64-hex digest after exactly one namespace segment)
    filters clear, list_namespaces and list_values; `BLUEPRINT_TEST_REDIS_URL` makes the Redis
    integration tests runnable against a throwaway container. Live with a control run.
13. **`/status/env` masker** (M12 + pajoma suggestion). Fail closed on `@` after `://`, query-string
    and `Key=` segment masking, port inside `try`, secret-named dicts masked whole, `pass`/`dsn`/`conn` as
    `_`-delimited markers.
    **Done 2026-10-19** (not committed): also `sig`/`signature` as words (SAS tokens); a secret-named
    list of sections is masked whole. Live over HTTP (uvicorn) with a control run.
14. **Scaffold and CLI** (M10, S14, N6-N9). Python HEALTHCHECK in `group_Dockerfile`; environment
    variable per D10; validate the name before generating; reword the `settings.txt` comment; correct
    the `asbs dev` messages (behaviour unchanged); scheduler template docstring; service template imports.
    Live: build the group image in WSL and watch it turn healthy.
    **Done 2026-10-19** (not committed): the CLI service uses `BaseModel` (the generator derives the
    parameter name from the type, so `dict[str, Any]` produced invalid code). Live: a scaffolded group
    image (two agents) built in WSL from the working tree -- healthy after 10 s, environment
    `production`; control (the old template): `curl: not found`, never healthy, `development`. The same
    image ran the live checks of steps 7 and 8: a critical-name typo exits 1 with the message; an
    agent's mounted `.secrets.toml` is merged into that agent only.
15. **Dedup without a heartbeat, Redis calls** (S6, S7). Per D4: document the redelivery-while-running
    limit, startup WARNING when dedup runs without a heartbeat; claim/delete via `asyncio.to_thread`; opt-in `redis_socket_timeout` (default unchanged).
    **Done 2026-10-19** (not committed): S7 rechecked under the D16 rule -- redis-py 7.0.0 has no default
    timeout, 8.0.0 has 5 s (read from the tagged sources), so the floor is now `redis>=8.0.0`. The
    scheduler's tick claim moved off the loop too. Live on a paused Redis with a control run.
16. **Dapr hardening** (S5, S9, N5). Deep copy per agent in fan-out; startup WARNING for a shared topic
    with dedup off; `<undeclared>` topic label per D6; reason only when not ACK; `route_class` limited
    to `/events/{topic}`.
    **Done 2026-10-19** (not committed): the copy is made only when more than one agent receives the
    delivery. Live: a uvicorn-served group against the Dapr sidecar mock, with a control run.
17. **Telemetry** (S22, W1). Ref-counted exporter and span processor (keeps C2's "share one"); explicit
    flush and shutdown in the lifespan, root last; `OTEL_SERVICE_NAME` per D17.
    **Done 2026-10-19** (not committed): the providers are built without their own atexit hook;
    `shutdown_providers()` runs from the lifespan (in a worker thread) and once from atexit as the
    fallback. D17 applies to `OTEL_SERVICE_NAME` only: a `service.name` declared in
    `OTEL_RESOURCE_ATTRIBUTES` still names every agent. Live against an OTLP collector with a control run.
18. **NATS leftovers** (S1, W4, W5, N10). Refuse to bind on a `filter_subject` mismatch (no rename);
    run-slot release on exception; `_durable_for` docstring; the consumer INFO line renders an unset
    `ack_wait`.
    **Done 2026-10-19** (not committed): the refusal is a `JetStreamBindingError` from
    `_ensure_consumer` (a consumer listing exactly the topic in `filter_subjects` is bound);
    `filter_subject` left the drift list. Live against JetStream with a control run; found N12.
19. **Standalone compatibility** (S10, S20, S21, N1). User checker replaces a built-in one with a
    WARNING; class and instance handlers register in declaration order; `SessionsJobHandler` declares only
    when `can_handle_event` is not overridden; `event_loop_debug` off unless set (`parse_bool`);
    shutdown via `gather(..., return_exceptions=True)`, guarded `actuator.on_shutdown`; CHANGELOG entry
    for deferred construction.
    **Done 2026-10-19** (not committed): `HealthCheckEntry.builtin`; `Registry.reorder` permutes the
    declared handlers within the slots they hold (replacing `_check_declaration_order`);
    `configure_loop_debug` lost its `development` parameter. Live (standalone app, Core NATS) with a
    control run; the SessionsJobHandler and shutdown parts are unit-tested only.
20. **Smaller items** (S19, S23, W2, W3). Publish the resolved group into the deployment identity;
    diskcache per D16; floor the in-process slot to the scheduled time; W3 per D7.
    **Done 2026-10-19** (not committed): `deployment.publish_deployment_group`, called by
    `AgentGroup.resolve`; the tick slot is the trigger's latest fire time at or before now (a cursor
    walked forward, misfires passed over). D16's live check failed: diskcache-rs 0.4.10 is not atomic
    across processes (N13), so the docs drop the claim and D22 is open. Live in WSL with control runs.
21. **Docs and PR hygiene** (W7, W8, W9, D20). xfail paragraph; CHANGELOG/version per D19; licence back
    to develop's state per D20; rollback note
    (cache keys, durables, REST paths, metric label); PR description draft (#89, LICENSE, size, `Closes`
    lines, #35/#75 link, AI disclosure). The description is posted only after the user has read it.
    **Done 2026-10-19** (not committed): xfail paragraph in the past tense (no test is marked any
    more); `[0.9.0]` folded into `[Unreleased]` (one section per heading, the 0.9.0 introduction
    first, no entry lost: 170 entries before, 169 + 4 rollback points after); `pyproject.toml` at
    `0.8.2`, without `license`/`license-files`; `LICENSE` removed and its CHANGELOG entry with it;
    "Rolling back to 0.8" in the CHANGELOG. Not touched: README's MIT badge and licence section
    (develop has them too, linking a file develop does not have), and develop's MIT classifier,
    which this branch had already dropped -- D20 lists the classifier as out. PR description and
    the reply to the version-bump comment are drafts, not posted.

---

## 3. Decisions

### Settled by standing rules (no question needed)

- S1: refuse to bind on mismatch, keep today's durable names (no consumer migration).
- S7: socket timeouts as an opt-in key, default unchanged ("never change existing defaults").
- S20: restore develop's behaviour for health check replacement and handler order ("existing agents keep working").
- S21: `event_loop_debug` off unless set (develop had no debug mode).
- N6: `asbs dev` behaviour unchanged, messages corrected.
- M6: filter child keys rather than moving the default store (no cold cache).
- M9: fixed as a bug; grouped alpha users get a CHANGELOG line.
- D15 (timezone): host-local stays the default; opt-in `scheduler_timezone`.

### Open, asked one at a time

| ID | Question | Blocks step |
|---|---|---|
| D1 | B3: replace the names in the tree only, or also rewrite the published branch history? **Decided 2026-10-16: tree only, no history rewrite.** | 3 |
| D2 | M2: after a failed resume, retry in a backoff task, or report unhealthy so the supervisor cycles? **Decided 2026-10-16: backoff task in the client (cancelled by pause/close), readiness unchanged, WARNING per failed attempt.** | 5 |
| D4 | S6: in-progress TTL: opt-in key, derived from handler timeout / `ack_wait`, or document only? **Decided 2026-10-16: no in-progress state. The loss needs a redelivery while the first run is still going, which the heartbeat prevents. Document it, and log a startup WARNING when dedup runs without a heartbeat: NATS with `idempotency_enabled` and `nats_heartbeat_enabled = false`; Dapr with `idempotency_enabled` (Dapr has no heartbeat; the WARNING names the app-call timeout).** | 15 |
| D6 | S9: undeclared topics as `<undeclared>`, a capped set, or drop the `topic` label? **Decided 2026-10-19: `<undeclared>` for every topic the agent did not declare; declared topics keep their name. With `dapr_declarative_subscriptions = true` everything counts as `<undeclared>`, the real name stays in the log line.** | 16 |
| D7 | W3: change "omitted namespace" to mean root everywhere, warn only, or leave? **Decided 2026-10-19: leave the semantics, document them (grouping docs and the `Component.registry` docstring): a root component in a group sees every agent on collection lookups; `namespace=""` asks for the root only. Framework callers depend on "omitted = all" (`dapr.py:216/256`, `event_processing_service.py:66`, `cache.py:63`).** | 20 |
| D8 | M7: `BLUEPRINT_AGENTS` overriding the file -- discard the file's `critical_agents` with a WARNING, or keep and reject unknown names? **Decided 2026-10-16: keep the file's list; a critical name outside the resolved group fails startup.** | 7 |
| D9 | S11: a bare key naming another agent through a view -- `ValueError` or the default? **Decided 2026-10-16: `ValueError`, same rule as the dotted key.** | 8 |
| D10 | S14: scaffold Dockerfiles -- `DYNACONF_APP_ENVIRONMENT="production"`, or remove the line? **Decided 2026-10-19: fixed as a bug. `DYNACONF_APP_ENVIRONMENT="production"` in the production stage of `Dockerfile` and `group_Dockerfile`, `"development"` in the dev stage, a comment that a custom `envvar_prefix` renames the variable, `deployment.md:51` corrected. The docs state plainly that `app_environment` defaults to `development` and a deployment must set `production` itself (what changes: no localhost broker fallback, logging, asyncio debug).** | 14 |
| D11 | W6: refuse one mutable object handed to two separately declared agents, or document it? **Decided 2026-10-16: sharing between agents is allowed and documented. Sharing between tenants is not: see step 1a.** | 9 |
| D14 | S24: fix the crontab dialect as a bug (moves firing days of `in_process` schedulers), or keep and warn? **Decided 2026-10-19: the blueprint's dialect is `0` = Monday ... `6` = Sunday (APScheduler's), so `in_process` firing days do not move. `7` is refused with a clear message in `in_process` and in `validate_crontab` (no croniter pass-through). In `event` mode a numeric day-of-week fails startup: the external CronJob counts `0` = Sunday, so a number is ambiguous; the error says so and asks for names (`mon-fri`, `sun`), which both read the same. Docs: `0` = Monday, examples with names (`0 9 * * mon`, `*/15 9-17 * * mon-fri`; today's `1-5` example means Tue-Sat), a note that an external cron counts differently. CHANGELOG line for event-mode schedulers with numeric weekdays.** | 11 |
| D16 | S23: raise the pin to `diskcache-rs>=0.4.10`, or document disk as per-process only? **Decided 2026-10-19: raise the pin to `diskcache-rs>=0.4.10`. Live in WSL: two processes claim the same key, exactly one wins; "atomic across processes" stays in the docs only if that holds. Drop "a disk cache on a shared volume" for several replicas (`configuration-keys.md:144`, `deployment.md:386`): cross-pod dedup needs Redis, disk covers processes on one host. General rule (user, 2026-10-19): where a dependency's behaviour changed in a way that affects us, adapt to it and raise the minimum version -- S7 is re-checked under this rule in step 15 (which redis-py version brought the default socket timeouts).** | 20 |
| D17 | W1: in a group, ignore `OTEL_SERVICE_NAME` for agents with a WARNING, refuse to start, or document? **Decided 2026-10-19: in a group every agent provider keeps `service.name` = agent name even when `OTEL_SERVICE_NAME` is set, so telemetry stays filterable per agent; the root provider still takes `OTEL_SERVICE_NAME`. One startup WARNING names the value and why it does not apply to the agents. `OTEL_RESOURCE_ATTRIBUTES` stays untouched. Docs: the exception to "declared keys are never replaced". Standalone unchanged.** | 17 |
| D19 | W8: fold `[0.9.0]` into `[Unreleased]` and restore the `develop` version string, or keep as is? **Decided 2026-10-19: this PR follows its own `AGENTS.md` rule -- `[0.9.0] - 2026-09-14` (never released, only `v0.9.0a1..a15`) is folded into `[Unreleased]`, `pyproject.toml` goes back to develop's `0.8.2`; `publish.yml` sets the version from the tag anyway (L43/L66). Reply to SawwR's bump comment with the rule. Follow-up issue, not in this PR: derive the version from git tags with `setuptools-scm` so source installs report it too (drops the `sed` step); the stale `__version__ = "0.3.0"` fallback in `src/blueprint/__init__.py:8` goes with it.** | 21 |
| D20 | Is the MIT licence choice approved by the responsible owner (pajoma F)? Not a code decision. **Decided 2026-10-19: no approval exists. The licence is deferred: this PR goes back to develop's licence state (`LICENSE` from `a9a8f3b` removed, `license`, `license-files` and the MIT classifier out of `pyproject.toml`). Open point for the `develop` -> `main` merge: licence approval by the responsible owner, then add it there. The PR description says so. Already published alphas (`v0.9.0a1..a15`) carry MIT and cannot be changed.** | 21 |
| D21 | N12: a paused client whose own resume keeps failing reports healthy, so readiness is UP while the agent consumes nothing. Options: (a) while paused, report unhealthy once a resume attempt has failed, and let `_retry_resume` keep running through a re-pause (today a pause cancels it, which would then deadlock); (b) leave readiness as it is and add a `blueprint.nats.resume_failures` counter plus the failure in the readiness payload; (c) accept and document. **Open -- owner decision.** Measured (step 18, root topic `orders-created` against a consumer filtering `created`, health interval 2 s): 200 at 0-2 s, 503 at 2.1 s (degraded, paused), 200 from 4.1 s on while paused, resume attempts failing at 5 s and 10 s backoff. | -- |
| D22 | N13: make `DiskCacheService.claim` atomic across processes on one host -- an OS file lock (`fcntl.flock` / `msvcrt.locking`, or the `filelock` package) around the `add` -- or keep the disk cache per-process for claims and warn at startup when dedup or the in-process tick claim runs on a disk cache with `app_workers > 1`? **Decided 2026-10-19: document only, for now** -- the docs say per-process (claim docstring, deployment guide, configuration keys, CHANGELOG Known issues); how to proceed beyond that is to be clarified. | -- |
| D23 | Startup and tenancy faults (owner, 2026-10-19). **Principle: a critical problem or collision found at startup fails the start; a fault caused by a wrong or problematic tenancy is logged CRITICAL and the process exits -- at startup and at runtime, when a `ConnectionSource` change hands it over -- because an operator must notice it.** Critical means deterministic (a retry cannot fix it): durable clash (S1), stream not creatable/updatable (subject overlap), missing JetStream permissions, tenant login refused, tenant deliver subject refused, binding-mode consumer missing or filtering another subject. Transient faults (broker unreachable, connection lost, timeouts) keep retrying; D5 stays for those. Open before implementing: (a) do an agent's own faults respect `critical_agents` (spec sec. 9.1) or always exit; (b) is a missing binding-mode stream fatal or still transient (provisioning); (c) D17 -- refuse `service.name` in `OTEL_RESOURCE_ATTRIBUTES` in a group, and what happens to `OTEL_SERVICE_NAME`. Partly supersedes D21 (N12). **Added (owner, 2026-10-19): a constellation that leaves orphaned agents -- agents that should exist but consume nothing for a non-transient reason (startup latch, final subscription fault, a resume that keeps failing) -- makes the service at least unhealthy, possibly exits.** So D21 is decided in principle: a paused client whose resume keeps failing reports unhealthy. Open: whether "unhealthy" is readiness DOWN or liveness DOWN, and whether it overrides `readiness_policy = "critical"` for a non-critical agent. **Settled (owner, 2026-10-19):** (1) such critical faults set **liveness** DOWN, and each is logged well enough for an operator to act on (what failed, which agent/connection, why it is not transient, what to change); (2) a transient fault stays under `readiness_policy`, an orphaned agent counts regardless of the policy; (3) D17: in a group, a `service.name` declared only through `OTEL_RESOURCE_ATTRIBUTES` (no `OTEL_SERVICE_NAME`), which would name every agent alike, **fails the start**; `OTEL_SERVICE_NAME` alone or together with it stays as implemented (agents keep their names, WARNING). Still open: (a) an agent's own faults vs `critical_agents`, (b) a missing binding-mode stream. **Clarified (owner, 2026-10-19): M agents x N tenants; N = 0 (the source hands over no tenant) is a valid state -- nothing to bind, nothing fails (as implemented: "consumes on 0 named connection(s)").** (b) concerns N >= 1: a tenant handed over whose binding names a stream (or, with `manage_consumer = false`, a consumer) that does not exist. **(b) deferred (owner, 2026-10-19):** whether a missing binding-mode stream -- or, with `manage_consumer = false`, a missing consumer -- is fatal at once or after a grace period depends on whether the tenancy source hands over a tenant only once its stream is provisioned; to be clarified with the tenancy owner. Until then it stays as implemented: retried, visible in readiness only (`<agent>.nats_client:connections` reads `retrying`); with `manage_consumer = false` a missing consumer is not detected at all (the client sends no JetStream request). **(a) settled (owner, 2026-10-19): fail early.** A deterministic fault (durable clash, stream not creatable/updatable, missing JetStream permissions) is fatal in every agent, whatever `critical_agents` says: logged CRITICAL, startup fails or liveness goes DOWN. `critical_agents` and `readiness_policy` keep deciding only for faults that may be transient (startup recovery, health). | 22 |
