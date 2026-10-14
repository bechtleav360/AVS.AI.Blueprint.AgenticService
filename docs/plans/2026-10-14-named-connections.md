# Plan -- Named NATS connections with concurrent runs

**Status:** 2026-10-14, decisions D1-D10 taken with the owner (sec. 4); ready for step 1. Supersedes
`docs/plans/2026-10-09-tenancy.md` (discarded: the framework does not take on tenancy).

**Goal in one sentence:** an agent consumes from several *named connections* that the deployment
supplies at runtime -- each with its own broker account and its own JetStream binding -- with
concurrent runs per connection, and nothing of one connection's runs ever reaches another's.

**What the framework does not know:** what a connection stands for. A deployment may map one
connection to one tenant, one region or one customer; the framework sees a name, credentials, a
binding and a validation hook. No tenant document, registry, tenant scope, tenant id or
tenant-specific key enters the framework.

**First consumer:** a multi-tenant agent application, which today does all of this beside the
framework, in a connection pool and an ingress of its own. No deployment uses the framework's NATS path
yet, so nothing has to be migrated.

---

## 1. Why

- **The framework has one connection per agent.** One credential, one stream (`nats_stream_name`,
  process scope, provisioned and widened by the client), durables, deliver subjects and deliver
  groups derived by the client. A deployment whose streams and accounts are owned by someone else
  -- one account and one stream per tenant, created by provisioning, consumers possibly created by
  an operator -- cannot be served. The broker refuses the framework's stream over subjects that
  already belong to another stream (`err_code=10065`).
- **So the first consumer built its own transport**, and with it lost every delivery guarantee the
  framework has (dispositions, dead letter, drain budget, telemetry) and had to re-implement the
  rest (settlement, heartbeat, run limit, degraded pause).
- **Concurrency.** Measured 2026-10-14: runs were strictly one at a time per subscription and
  process in both implementations. `19c4c48` fixed the framework's path
  (`nats_max_concurrent_runs`, heartbeat); this plan carries it over to every connection.

---

## 2. Invariants

- **N1 -- Isolation between (agent, connection).** A run started from a delivery on connection C for
  agent A shares no mutable state with any run of another (agent, connection):
  - each run starts in an **empty `contextvars.Context`** -- nothing is inherited from the
    dispatcher, the subscription task or another run;
  - each (agent, connection) has its own broker connection, subscription, run slots and in-flight
    accounting; the only thing shared is the per-process run cap, a counter;
  - a delivery is settled (ack / nak / term / in_progress) on the connection that delivered it;
  - the handler learns its connection from the context key `nats_connection`, set by the framework
    from the connection the message arrived on -- never from the payload.
- **N2 -- Validation before dispatch.** A deployment-supplied hook sees (connection name, subject,
  CloudEvent) before any handler runs. A rejection is terminated (`term`), logged, never processed,
  never retried.
- **N3 -- Bind, never provision, on a named connection.** The stream belongs to the binding. The
  client never creates or widens it. Consumers are created or updated only when the binding says
  so; otherwise the client binds to what exists and sends no `$JS.API` request at all.
- **N4 -- Wire values come from the deployment, byte for byte.** Durable name, deliver subject,
  deliver group and filter subjects of a named connection are taken from its binding, not derived.
  Moving that application onto the framework is then a redeploy: every `consumer_info`
  identical before and after.
- **N5 -- Composition independence.** Behaviour does not depend on how many agents or connections a
  process hosts. One slow connection does not slow another beyond the shared per-process cap.
- **N6 -- Existing agents unchanged.** Without a connection source, an agent runs exactly as today
  on its one configured connection.
- **N7 -- The same delivery semantics everywhere.** Named connections use the existing delivery
  path: run slots, `_run_delivery`, dispositions (spec sec. 7.2), heartbeat, drain, telemetry. There
  is one implementation of settling a message.

---

## 3. Shape

```
ConnectionSource (deployment code, process-wide)
  connections() -> {name: ConnectionSpec}; notifies on add / change / remove
  binding(agent, subjects, spec) -> JetStreamBinding
  validate(name, subject, event) -> None | reason
        |
        v
NATSClient (one per agent, as today)
  default connection   -- from nats_url etc., as today (N6)
  named connection "c1" -- own nats.Client, own subscription(s), own slots
  named connection "c2" -- ...
        |
        v  per delivery: validate -> run task in empty Context -> handler chain -> settle on "cX"
```

- **One `NATSClient` per agent stays.** The registry name, `NatsEventing`'s lookup, publishing and
  the supervisor's pause/resume all assume it (`component.py:153`, `nats.py:69`,
  `event_publishing_service.py:65`, `namespace_supervisor.py:222`). The client grows an internal
  set of connections instead of the registry growing several clients.
- **`ConnectionSpec`:** name, URL, credentials (secrets as `SecretStr`, never logged), connect
  options. **`JetStreamBinding`:** the declared subjects it serves on this connection (D10), its
  `subject_prefix` (filter subject = prefix + declared subject), stream, durable, deliver subject,
  deliver group, `manage_consumer`, optional dead-letter subject (D6).
- **Subjects:** an agent declares its subjects as today (`get_subscribed_topics()`,
  `nats_subscriptions`), without any prefix. The source maps them to a connection's filter subjects
  in `binding()` -- that is where a deployment adds a prefix such as `t.<x>.`. The framework never
  rewrites a subject. Example: agent `risk` declares `risk.>`; for connection `A` the source returns
  filter `t.A.risk.>`, durable `acme-agent-risk`, deliver subject
  `acme.agent.A.risk`, deliver group `risk`.
- **Context keys of a delivery on a named connection** (D10): `nats_topic` = the subscription *as
  the agent declared it* (`risk.>`), so everything that matches on the declared topic keeps working
  -- e.g. `SchedulerTickHandler` compares `nats_topic` with its own topic (`scheduler.py:195`);
  `nats_subject` = the delivered subject with the binding's prefix stripped (`risk.created`), so
  `can_handle_event` sees what the agent knows; `nats_connection` = `A`, an opaque name for logs.
  The wire subject (`t.A.risk.created`) is not in the handler context.
- **Without a source nothing changes (N6):** no `nats_connection_source`, no named connections; the
  agent's subjects are subscribed on its one connection exactly as today, durables and stream
  derived as today.
- **Runtime changes:** a connection added, changed (credentials, binding) or removed is opened,
  replaced or drained while the agent runs. Draining follows `close()`: stop deliveries, let runs
  finish within the budget, settle, close. A consumer the framework did not create is never deleted.

---

## 4. Decisions

All taken on 2026-10-14; each entry starts with the decision, followed by the analysis that led to it.

- **D1 -- Connection granularity. Decided 2026-10-14: (a), one broker connection per (agent,
  connection).** Step 1 separates a *link* (the `nats.Client`, connecting, callbacks) from a
  *binding* (subscription, run slots, settlement), one link per binding for now, so a shared link
  -- option (b) -- can be added later as its own step without reshaping the rest. Triggers for
  building (b): pod memory gets tight, or the operator sets `max_connections` per account. What (b)
  would add: a process-wide link pool with reference counting and shutdown ordering, fanning
  connection events out to every agent on the link, readiness that tells "link down" from "agent
  paused", an exception to C2's connection naming and to grouping spec sec. 6, and every acceptance
  test in both modes. The analysis that led here:
  One broker connection per (agent, connection) **(recommended)**:
  confines a dropped connection (stranded acks) and a slow-consumer kick to one agent and one
  connection, as the grouping spec does per agent (sec. 6). Cost: agents x connections connections
  per pod (19 x 10 = 190). Alternative: one per named connection shared by the agents of a process
  (what the first consumer's own pool does today) -- fewer connections, but one agent's flood or blip hits all.
  *Measured 2026-10-14* (nats-py 2.15 in `python:3.13-slim-bookworm` containers, NATS 2.10 with TLS
  (RSA 2048) and user/password, all in WSL): an idle connection costs ~313 KB in the client with TLS
  (~89 KB without) and ~80 KB in the broker; no measurable idle CPU; 400 connections open in 2.1 s.
  Broker restart under 3 pods x 400: all 1200 back within 0.7 s; 3 x 800: all 2400 within 1.6 s, broker
  CPU ~3 cores for about a second, ~2 s client CPU per pod, none given up even with the framework's
  `nats_max_reconnect_attempts = 5`. The cost of this option is memory: 300 connections ~ 95 MB per
  pod. Not covered: real network latency, a clustered broker, per-account `max_connections` set by
  the operator (agents x replicas per account under this option).
- **D2 -- Registering the source. Decided 2026-10-14: (a), the process-scope config key.** The
  builders are each agent's own declaration, and an agent must not know about the deployment's
  connections; a builder call would put the source into agent code. The key goes into
  `PROCESS_SCOPE_KEYS`; `asbs validate` checks that it imports. The analysis that led here:
  A process-scope key naming a factory,
  `nats_connection_source = "package.module:factory"` **(recommended)**: works in a group without
  any agent code, like the group file. Alternative: a builder call -- needs a process-scope
  registration a group does not have today.
- **D3 -- Run scope hook. Decided 2026-10-14: (a), the source may supply `run_scope(name)`.**
  Agents open no deployment scope themselves and cannot forget it. The analysis that led here:
  The source may supply `run_scope(name)`, a context manager the framework
  enters *inside* the run task, around the handler chain **(recommended)**. It is how a deployment
  applies per-connection settings that live in ContextVars (today: per-tenant model override) without
  agent code. Without it, every agent service has to open such scopes itself.
- **D4 -- `HandlerResult` publishing for a run from a named connection. Decided 2026-10-14: (a),
  refused for now.** A result without a topic mapping is skipped as today; an agent that has named
  connections *and* a topic mapping fails startup, so no connection's result can reach the default
  connection's subjects. Found: the first consumer's handlers return `HandlerResult`s but the
  repository has no topic mapping, so nothing is published today. **Later, when needed -- option
  (b):** publish on the delivering connection, the source mapping the target subject as it maps
  bindings (e.g. `t.A.<subject>`); needs publish rights on the connection's account. The analysis
  that led here: Today it goes out on the
  agent's default connection. Options: keep that **(recommended for this step; documented as "leaves
  the connection")**, publish on the delivering connection (needs publish rights on that account),
  or refuse. Isolation-relevant: the event leaves the connection's account.
- **D5 -- Readiness. Decided 2026-10-14:** new key `nats_connections_readiness = "never" | "any" |
  "all"`, default `never`. `never`: named connections show in the readiness payload and metrics but
  never make the agent not ready (= today's behaviour of the only user: tenant connections are
  invisible to readiness); `any` (OR): ready while at least one named connection is up; `all` (AND):
  ready only while every one is up. The **default connection keeps today's behaviour unchanged**
  (`health_check`, `nats_client.py:1106`: not connected -> unhealthy). **Required regardless of the
  mode:** a named connection's state feeds readiness only, never the supervisor's pause decision --
  one agent health bit drives both today (`namespace_supervisor.py:131`), and a pause on one dead
  connection would stop the agent on every connection. Acceptance in WSL: one account with a wrong
  password, nothing paused, readiness as the mode says. The analysis that led here:
  A named connection that is down degrades that (agent, connection) only and
  shows in the readiness payload; the agent stays ready **(recommended)**, so one broken account
  does not take every other connection's work off the pod. **Open:** whether an agent with named
  connections but none of them up should report not ready.
- **D6 -- Dead letters on a named connection. Decided 2026-10-14: (a).** Dead-lettered on the
  delivering connection only when the binding carries a dead-letter subject; otherwise term + ERROR
  log (event id, reason, delivery count) -- what the first consumer does today. Never via the
  default connection: a connection's payload must not reach another account. The analysis that led
  here: Use the binding's dead-letter subject if it has one;
  none -> term + ERROR log, payload lost **(recommended)** -- a deployment's account may not be
  allowed to publish.
- **D7 -- Run limits. Decided 2026-10-14.** Event rates differ by orders of magnitude between agents
  (once an hour to several times a minute), so a busy (agent, connection) may take many runs while
  an idle one never waits:
  - **One run per (agent, connection) is always allowed** and counts against no limit.
  - **Every further run** needs both: the (agent, connection) is below `nats_max_concurrent_runs`
    (K, the same for every connection of the agent, settable per agent), **and** a slot of the
    process-wide pool `nats_extra_runs_per_process` is free.
  - Both keys take an absolute number or a percentage of the current number of (agent, connection)
    pairs in the process (`"33%"`), recomputed when connections are added or removed. The owner's
    sizing: K up to about a third of the pairs.
  - Defaults keep today's behaviour: K = 1 (so no further runs at all), pool unset (unlimited).
  - Order of acquisition is fixed (the pair's slot, then the pool), so there is no deadlock; waiters
    are served first come, first served, so no pair starves.
  - Consequence to measure: guaranteed first runs are uncapped, so in the worst case every pair
    runs at once plus the whole pool. The step-3 stress scenario includes "every pair busy at once".
  - Per-connection K from the binding (a large tenant gets more) is not built; it can be added later
    without reshaping anything.
  The analysis that led here: `nats_max_concurrent_runs` becomes per (agent, connection) -- it was per agent
  in `19c4c48`, which is unpushed and unused -- plus a new process-scope cap
  `nats_max_concurrent_runs_per_process` across every agent and connection. Defaults: 1 and unset
  (no cap) to keep N6; the deployment sets both.
- **D8 -- Core NATS on named connections. Decided 2026-10-14: (a), JetStream only.** A binding
  without stream and consumer fails that connection's start with a clear message. Core NATS on the
  default connection is unchanged. **Later, when needed -- option (b):** Core NATS on a named
  connection, subscribing the filter subjects in the queue group with no acknowledgement, heartbeat,
  redelivery or dead letter; events published during a pause or restart are lost; every acceptance
  test then runs in both modes. The analysis that led here: JetStream only **(recommended)**: a named connection
  exists to bind an existing durable consumer.
- **D9 -- Handler timeout. Decided 2026-10-14: in this plan.** `nats_handler_timeout` (seconds,
  agent-scoped, every connection including the default one), **default unset = no limit**. At the
  limit the run is cancelled and nak'd for immediate redelivery; a `TimeoutError` the handler raises
  itself is an ordinary failure (the run's own timer is checked, not the exception type). The run's
  slot is freed only when its task has actually ended -- a handler that swallows the cancellation
  keeps holding its slot, logged, instead of running unseen beside its redelivery. The heartbeat
  (`19c4c48`) already exists and stops before the nak. The analysis that led here:
  Part A's hard limit (`nats_handler_timeout`, cancel + nak) is in
  the first consumer today and in the handler-time-bounds draft spec. Include it in this plan
  **(recommended)** -- "everything works as it does now" requires it.

- **D10 -- Which subjects go where. Decided 2026-10-14: (a), the source decides per connection.**
  Agents know their events (`risk.>`), never how connections are built (prefixes, accounts,
  streams): `can_handle_event` must be able to look at the event's subject *as the agent declared
  it* and decide whether there is work. Hence the binding expresses its mapping as a plain
  `subject_prefix` (a generic concept, not a tenant one): filter subject = prefix + declared subject,
  and the framework strips the prefix again on delivery, so `nats_subject` is always the subject the
  agent knows (`risk.created`) -- on the default connection exactly as today. The wire subject
  (`t.A.risk.created`) reaches the validation hook and the framework's logs, not the handler
  context. The analysis that led here: An agent may declare subjects that
  belong to the named connections (tenant events) and subjects that do not (a scheduler tick, a
  process-level event). Recommended: `binding()` returns, per connection, which of the declared
  subjects it serves; a subject no connection serves stays on the default connection, as today.
  The default connection then subscribes only what is left -- possibly nothing, which matters where
  the process account may not subscribe at all (the first consumer).

---

## 5. Steps

One step, one reviewable commit. Each step names its acceptance.

1. **Refactor: connections inside `NATSClient`.** The client's connection state (nats client,
   JetStream context, subscriptions, slots, in-flight, ack-wait map) moves into a `_Connection`
   object; the client holds a default one. No behaviour change, with one addition decided
   2026-10-14: `nats_heartbeat_enabled` (bool, agent-scoped, default `true`) switches the heartbeat
   of `19c4c48` off per agent, as in handler-time-bounds sec. 4.1.
   *Acceptance:* unit and integration suites unchanged; the 2026-10-14 probe (B1-B5, K1-K3) gives
   the same results.
2. **Binding mode.** A `_Connection` can bind with a `JetStreamBinding`: no stream provisioning,
   consumer created only with `manage_consumer`, wire values verbatim (N3, N4).
   *Acceptance:* broker test -- an operator-made consumer is bound with `consumer_info` identical
   before and after; with `manage_consumer` the consumer equals what the first consumer's pool
   creates for the same input.
3. **Connection source, static.** `nats_connection_source` (D2), connections opened at startup,
   validation hook (N2), empty Context per run, `nats_connection` context key, run scope hook (D3),
   per-connection slots and per-process cap (D7), handler timeout (D9).
   *Acceptance:* isolation test below; mismatch -> term; limits respected (measured overlap).
4. **Connection source, dynamic.** Add, change, remove at runtime; drain on remove; never delete a
   foreign consumer.
5. **Readiness and telemetry per connection** (D5): connection state in the readiness payload,
   metrics labelled with the connection name.
6. **Everything that describes the framework agrees with it -- no contradiction left anywhere.**
   Not only the new feature: every statement about NATS delivery, consumers, concurrency, heartbeat,
   run limits and connections is checked against the code after steps 1-5, and corrected or
   removed. Covered:
   - **Specs and plans:** `docs/specs/2026-08-28-multi-agent-grouping.md` (sec. 5.2 still lists
     300 s / 16 as defaults; sec. 6 and 7 against named connections),
     `docs/specs/2026-09-24-handler-time-bounds.md` (sec. 4.5 assumes running handlers are bounded by
     `nats_max_ack_pending`; what part A is now implemented), `docs/specs/2026-09-23-dynamic-subscriptions.md`
     (overlap with step 4), the feature changelog, `CHANGELOG.md`, `README.md`, `AGENTS.md`.
     ADRs (`docs/adr/`) are owned outside this repository: contradictions there are listed for their
     owner, not edited.
   - **Shipped docs:** `src/blueprint/agent_generator/docs/` -- concepts, guides (deployment, event
     processing, scaling), reference (configuration keys, every new key with type, default and
     scope), getting started.
   - **Agent generator:** the templates in `base_files/` (e.g. `settings.txt`, the handler template
     whose docstring and idempotency comment still put business logic in the handler), the
     generator, `asbs validate` checks for the new keys (a source that cannot be imported, a binding
     without a stream, limits below 1), `asbs docs` output.
   - **Skills and assistant docs:** `claude_docs/CLAUDE.md`, `claude_docs/agents/`
     (`blueprint-builder.md`, `blueprint-architect.md`), every skill under `claude_docs/skills/`
     (`blueprint-events`, `blueprint-config`, `blueprint-deployment`, `blueprint-multi-agent`,
     `blueprint-troubleshooting`, `blueprint-testing`, ...), and the assistant integrations -- the
     `main.py` patterns they show are known to disagree with each other and with the template.
   - **Examples:** every project under `examples/` builds and starts against the changed framework;
     `order_event_pipeline` (or a new example) shows a connection source with two named connections.
   *Acceptance:* a written inventory of every place checked, with what was changed or why nothing
   was; the repository's reference and design-rule guards green; every example started once in WSL
   against a real broker; a grep for removed or renamed keys and APIs over the whole repository
   finds nothing outside the changelogs.

Afterwards, outside this repository: the first consumer implements the source over its tenant
documents and drops its own connection pool and the receiving half of its ingress.

---

## 6. Acceptance in WSL (every step from 3 on)

Run against a broker with **real accounts** (a `nats-server` config with one account per
connection, permissions as the operator grants them: subscribe to the deliver subject, publish acks,
nothing else), not an open broker.

- **Isolation:** 2 connections x 3 agents, `nats_max_concurrent_runs` > 1, bursts on every
  (agent, connection). Every run records the connection it sees in its context, the value of a
  ContextVar set by the run scope hook, and the subject of its delivery; the test fails on any
  mismatch. A ContextVar set inside one run is never visible in another.
- **Rejection:** a delivery whose payload disagrees with its connection (validation hook) is termed,
  never reaches a handler, is not redelivered.
- **Stress scenario** from the discarded plan (sec. 9): 15 events per lane -- 9 short, 3 longer than
  twice `ack_wait`, 2 failing, 1 hanging -- `ack_wait` 3 s, limit 10 s. Nothing stuck, no live run
  redelivered, hung runs cut at the limit, failing ones dead-lettered or termed after `max_deliver`.
- **Limits:** measured maximum overlap per (agent, connection) and per process equals the configured
  values; every pair always gets its first run, even with the pool exhausted.
- **Every pair busy at once:** all (agent, connection) pairs receive a burst at the same moment;
  measured event-loop lag, heartbeat punctuality (no live run redelivered) and run times against an
  idle baseline.
- **Later, after all three steps (framework, SDK, deployment):** a mock LLM that answers only after a
  configurable number of minutes, to diagnose how a group with many tenants behaves under sustained
  high load (loop lag, memory per run, limits, redeliveries) and to size K and the pool.
- **Runtime change** (step 4): a connection added and removed while the others run; no delivery of
  the others lost or duplicated.
- **Control runs** against the code before the step, for every claim of the form "this fixes X".

---

## 7. Not in scope

Tenant documents, a tenant registry, tenant ids, `current_tenant()`, per-tenant model settings,
REST token verification, outbound backend credentials: all stay with the deployment. The framework
offers the seams (source, binding, validation hook, run scope hook) and nothing that names a tenant.
