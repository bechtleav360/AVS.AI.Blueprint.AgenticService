# Change Log -- Multi-Agent Grouping

| | |
|---|---|
| **Spec (normative)** | `docs/specs/2026-08-28-multi-agent-grouping.md` |
| **Implementation plan** | `docs/plans/2026-08-28-multi-agent-grouping.md` |
| **Branch** | `feature/multi-agent-namespaces` |

Running record of every change on this branch, in the order it landed, with the reasoning behind
it. It doubles as the pull-request description, so it is updated as part of each change rather
than reconstructed at the end. At release time a condensed entry goes into `CHANGELOG.md` under
`[Unreleased]`; this file keeps the detail that would not fit there.

---

## What this feature does

Today one agent means one process, one port, one broker connection and one container image, so a
platform of 100 agents pays the ~154 MB Python and library baseline 100 times. This feature makes
**which agents share a process a deployment parameter rather than an architectural commitment.**

Components gain an optional **namespace** (`""` by default, so nothing existing changes). A
namespace owns its own handlers, agent runtime, REST routes, AI client, thread pool and broker
connection, while genuinely shared infrastructure -- the port, the health endpoint, the caches --
stays single. Which namespaces a process hosts is resolved at startup from a group configuration,
and Kubernetes runs one Deployment per group: a group of one gives today's process isolation, a
group of twenty gives the shared-interpreter memory profile, and moving an agent between groups
changes neither its broker-side consumer identity nor its telemetry identity.

Reaching that requires fixing several defects that block running more than one replica of
*anything* today, which is what the prerequisites (P0-P6) cover and where the work starts.

---

## TL;DR

Design and specification:

- Normative spec and phased implementation plan, extracted from `CLAUDE.md` into the repo's
  spec/plan convention (`4233933`)
- **Acknowledgement contract**: a normal return acks, a raised exception does not; `NO_HANDLER_FOUND`
  acks (`b6ab1c9`)
- **Selection and fan-out rules** (spec sec. 7.7), including the two rules that keep a dispatch
  index and broker-side filters non-breaking (`13e4d28`)
- Acceptance criteria for both of the above (`b94f60c`)

Code:

- **P0 -- transport lifecycle**: managed whole-map `subscribe()`, background retry, reconnect
  re-subscription, `subscriptions_ready` readiness gating (`77af507`)
- **P0 -- shutdown drain**: in-flight handlers finish before the connection closes (`585e58c`)
- **P0 -- message boundary**: an undecodable payload is distinguished from a failed dispatch
  (`3843abf`)
- **Dapr subscription discovery fixed** -- declared topics now actually subscribe; `GET
  /dapr/subscribe` no longer answers 422 (#81, `fac528b`)
- **P1 -- queue groups**: Core NATS subscriptions join a queue group derived from the agent, so a
  second replica no longer processes every message a second time (`05083c8`)
- **P2 (NATS half) -- acknowledgement**: a normal return acks, a raised exception naks or terms per
  the spec table; the two layers that swallowed the classification are gone (`ce17f87`)
- **P2 (Dapr half) -- parity**: `NO_HANDLER_FOUND` answers `SUCCESS` instead of looping until
  `max_deliver`, a critical error drops instead of retrying, and an unparseable body drops instead
  of answering 422; both transports now render one shared decision (`ce17f87`)
- **P2 -- unhandled events are counted, not flagged**: `blueprint.events.unhandled` per
  (namespace, topic), read as a ratio; finding no work in an event is normal behaviour
- **P3 -- consumer tuning**: `ack_wait`, `max_ack_pending` and `max_deliver` are configurable and
  are enforced by the broker, on a `ConsumerConfig` the client creates itself
- **P3 -- JetStream shares load**: the durable carries a deliver group, so JetStream stops being
  single-subscriber; this was P1's other half
- **P3 -- dead letters**: a message the framework gives up on is republished, payload unchanged,
  to `<queue group>.dead-letter` before it is termed
- **P3 -- three defects found on the way**: the stream never covered the subject its consumer
  filtered on, only the first topic was ever added to it, and the derived durable name was illegal
  for any dotted subject
- **P4 -- opt-in deduplication**: the handler chain skips an event whose id and source it has
  already dispatched, keyed in the cache with a required TTL. Off by default, and a failed
  dispatch releases its claim so the nak's redelivery still runs
- **P4 -- the author is made to decide**: a `DECIDE:` comment in the scaffolded handler, both
  keys in the generated `settings.toml` and `CLAUDE.md`, and an `asbs validate` notice when a
  project has handlers and has declared neither
- **P4 -- duplicates are counted apart from unmatched events**: `blueprint.events.duplicate`,
  so a redelivery storm does not read as a namespace subscribed too broadly
- **P5 (`662f7b5`) -- the cron timer becomes a stated choice**: `scheduler_mode` is **required** and has no
  default. `"event"` starts no in-process timer -- the tick arrives as an ordinary event on the
  scheduler's own topic, so the queue group picks a single replica and nothing is elected;
  `"in_process"` keeps the timer for local development and plain Docker. Registering a scheduler
  without the key, or choosing `"event"` with no usable `event_bus`, fails at startup
- **P5 -- a second `build()` pass no longer starts a second timer** (#43), and the manual trigger
  route is registered before `include_router` copies it, so it is actually served
- **P5 -- two defects in the generated scheduler**: the scaffold emitted a file that did not
  parse, and its `on_startup` override never called `super()`, so a scaffolded scheduler never ran
- **P5 -- publishing no longer requires consuming**: `event_publishing_enabled` gives an
  application that only emits events a transport client and no subscription. Off by default,
  because a project that wants only a timer may have no broker access
- **P5 -- #43's other cause**: `SchedulerBase` extends `RestApiBase`, so every scheduler sat in the
  REST-API lifespan loop *and* the scheduler loop. A single lifespan started two
  `AsyncIOScheduler` instances per scheduler, and `on_shutdown` could reach only one
- **P5 -- an event-mode crontab is validated at startup**: nothing else parses it in that mode, so
  a typo used to surface as a tick that never arrives. Manifest generation itself is deliberately
  deferred, and the renderer written for it was removed rather than carried as dead code
- **P5 -- `"in_process"` fires a tick once across replicas**: every replica's timer fires and each
  tick is claimed in the shared cache, so one replica runs it. Not a leader lease: nothing is held,
  so there is no renewal task and no takeover bound -- which answers the open question the spec
  left on that mode
- **New cache primitive `CacheService.claim`**: set-if-absent, atomic on both backends (`add` on
  disk, `SET NX EX` on Redis). This is the compare-and-set operation P4 flagged as missing

Documentation and process:

- Deployment guide now warns that multi-replica is unsafe, and its examples default to one replica
  (`2d80b63`)
- New config keys documented: `event_client_drain_timeout`, `dapr_pubsub_name`,
  `dapr_declarative_subscriptions`, `idempotency_enabled`, `idempotency_ttl`, `scheduler_mode`,
  `event_publishing_enabled`
- Feature working rules in `CLAUDE.md`: one reviewable change at a time (`4cf2d51`), and a
  walkthrough whenever real code is written (`7735251`)

Issues opened along the way:

- **#80** -- 28 failing example tests assert on removed examples; the unit/integration split is
  unenforced
- **#81** -- Dapr declared topics never subscribe (fixed here)

**Breaking changes: one, and it is loud.** `scheduler_mode` is required, so an existing project
with a scheduler fails at startup until it states which mode it wants. Nothing changes behaviour
silently. See *Compatibility* at the end.

---

## Changes in detail

### Spec and plan extracted into the repo's conventions (`4233933`)

The multi-agent work breakdown lived as a 900-line section inside `CLAUDE.md`. It is now
`docs/specs/2026-08-28-multi-agent-grouping.md` (normative: scope, invariants C1-C7, public API,
configuration, transport topology, event delivery, caches, startup, backwards compatibility,
acceptance criteria, open questions) and
`docs/plans/2026-08-28-multi-agent-grouping.md` (the phased breakdown: prerequisites P0-P6 and
phases 0-9). `CLAUDE.md` keeps pointers plus the list of paths that require reading the spec first.

**Motivation.** `CLAUDE.md` is loaded into every session, so a 900-line plan costs context on every
task regardless of relevance, and it cannot be reviewed the way a document under `docs/` can. The
repo already separated spec from plan (`docs/specs/2026-07-06-...-design.md` against
`docs/plans/2026-07-06-...md`), so this follows an existing convention rather than inventing one.
Open questions live in the spec alone, so the two documents cannot drift.

### Acknowledgement contract (`b6ab1c9`)

Spec sec. 7.2 now states: **a normal return acknowledges, a raised exception does not.** The
transport edge must not inspect `ProcessingResult` to decide delivery, and `NO_HANDLER_FOUND`
acknowledges like any other completed dispatch. Both transports must map the same outcome to the
same disposition, so `CriticalHandlerError` drops on Dapr rather than retrying, and a payload that
fails to parse terms rather than naks. Acknowledging an unmatched event must not hide it: unhandled
events are counted per namespace and topic, with a warning on the first occurrence of each pair.

**Motivation.** `ProcessingStatus` has exactly two values, `PROCESSED` and `NO_HANDLER_FOUND` --
there is no failure status, so every real failure already arrives as an exception and inspecting the
result buys nothing. It does actively harm: `dapr.py` mapped `NO_HANDLER_FOUND` to `RETRY`, so an
event no handler wanted was redelivered until `max_deliver`, and under a queue group that loop
visits every replica in turn. The contract removes a check rather than adding one.

### Selection and fan-out (`13e4d28`)

Spec sec. 7.7 records that selection happens at two levels and only the subject level is enforced
by the broker: NATS has no content or header predicate, and Dapr's CEL rules are evaluated in the
sidecar after delivery. With one consumer per `(namespace, topic)` pair, a broad subject makes the
broker copy every message once per namespace.

Two rules are normative, and both exist to keep the optimisation non-breaking:

1. A handler that declares nothing must still be evaluated for every event its namespace receives.
   A dispatch index may key on declared event types, but undeclared handlers must fall into an
   always-evaluated wildcard bucket.
2. A broker-side filter must never be narrower than the declared topics unioned with
   `nats_subscriptions`, and must never be inferred from handler code.

Also normative: consumer reconfiguration is a migration, because a durable's name and filter set
are broker-side state and a recreated consumer either replays or gaps.

**Motivation.** 100 agents each evaluating every event is the wrong shape, and the fix has to go
into the subject rather than into Python. The two rules are load-bearing because **nothing declares
anything today** -- `get_subscribed_topics()` is overridden nowhere in the framework or in any
scaffolded project -- so a design that treats declarations as authoritative describes an empty set
and would silence every existing handler. Combined with the ack contract, the events would then be
acknowledged and discarded rather than accumulating visibly.

The migration rule surfaced that **Phase 5 was already a consumer migration and was not documented
as one**: renaming durables to `{namespace}-{topic}-durable` makes every pre-existing consumer a new
consumer on first deploy.

### Acceptance criteria for the above (`b94f60c`)

Five criteria added to spec sec. 12, covering the ack contract, cross-transport parity, the
undeclared-handler rule, filter derivation, and the two observability counters.

**Motivation.** Sections 7.2 and 7.7 were normative but had no entry in the acceptance criteria, so
"done" did not include them.

### P0 -- transport lifecycle (`77af507`)

Connection, retry and subscription lifecycle moved out of the eventing APIs and into the transport
clients. `ClientBase.subscribe(topic_callbacks)` replaces `subscribe(topic, callback)`: one
non-blocking call carrying the whole `{topic: callback}` map, backed by a background retry task.
Adds `subscriptions_ready` with health-check gating, `disconnected_cb`/`reconnected_cb` with
JetStream durable re-subscription, and the `event_client_max_retries` / `event_client_retry_delay`
keys. The imperative `POST /nats/subscribe/{topic}` endpoint and the `EventHandlingBase.subscribe`
abstract are removed.

**Motivation.** Previously `NatsEventing.on_startup` subscribed imperatively, so a broker that was
down at startup left the app running with no subscriptions and no record of what it had wanted.
Everything later in the plan depends on this shape: P2's acknowledgement correctness needs the
reconnect path to exist, C4 and C7 read `subscriptions_ready`, and per-namespace clients (P6) need a
single subscribe call carrying the whole map.

Originally written as PR #27; applied here as one commit without that branch's CI and version
changes, so this update can land first.

### P0 -- shutdown drain (`585e58c`)

`close()` now cancels the retry task, drains subscriptions so already-queued messages still reach
their handler, waits for running handlers, and only then closes the connection. One deadline from
`event_client_drain_timeout` (default 30 s) bounds the whole sequence. A drain that fails or
outlives the deadline falls back to an immediate unsubscribe. In-flight work is counted in
`message_handler`'s `try/finally` and exposed as `inflight_handlers`.

**Motivation.** The order is the fix. An acknowledgement is published to the delivering
connection's reply subject, so closing the connection first strands it and the broker redelivers --
every deploy guaranteed duplicate work for whatever was in flight, and P2 would have inherited that
as a permanent duplicate source. `inflight_handlers` is public because Phase 9 needs exactly that
number for the per-namespace in-flight gauge (C7).

### P0 -- message boundary (`3843abf`)

Decoding moved into `_decode_message`, which returns `None` for a payload that cannot become a
CloudEvent and logs it as discarded, naming the topic. Dispatch keeps its own catch, logging the
event id, the topic and a traceback.

**Motivation.** One `except Exception` covered both decoding and dispatch and logged a single
message for both -- no topic, no event id, no traceback. Those two failures have opposite
dispositions under spec sec. 7.2 (term versus nak), and P2 cannot act on a distinction that has
already been erased. Each failure is now logged exactly once, by the layer that knows what it means.

The boundary still catches both: a broker callback that raises into `nats-py` loses our context and
gains nothing while no code yet decides what to do with a failure. In P2 the catch becomes the
disposition.

### Dapr subscription discovery (#81, `fac528b`)

`GET /dapr/subscribe` now takes no parameters and returns a subscription array built from
`get_subscribed_topics()` -- one entry per declared topic, routed to `/events/{topic}`, using the
`dapr_pubsub_name` key the publisher already reads. `dapr_declarative_subscriptions` (default
`false`) serves an empty document for deployments that declare subscriptions as Kubernetes
resources.

**Motivation.** Three defects, found while resolving P0's last gap. The endpoint's signature was
`subscribe(self, topic: str, queue_group: str | None = None)`, and since the path holds no
`{topic}`, that was a **required query parameter** -- so the sidecar's parameter-less GET was
answered 422 by FastAPI before any framework code ran. The body returned `{}` where Dapr expects an
array. And the declarations were collected into a callback map handed to `DaprClient`, which only
pings `/v1.0/healthz` and never reads it, because Dapr delivers over HTTP rather than through a
client-side callback. Net effect: under Dapr, a handler's declared topics subscribed to nothing.

The callback map is kept deliberately and documented for what it is -- the input that starts the
sidecar-reachability retry and feeds `subscriptions_ready`. Removing it, which "delete the unused
map" invites, would have silently disabled the readiness gating added in P0.

### P1 -- queue groups on Core NATS subscriptions (`05083c8`)

Every Core NATS subscription now passes `queue=`, so the server delivers each message to exactly
one member of the group instead of to every subscriber. The name is resolved once, in
`subscribe()`, from `nats_queue_group` falling back to `app_name`, and is exposed as the public
`queue_group` property; the resolved name is logged with each subscription, which is what makes C1
checkable by diffing two deployments' startup logs.

Three details carry the invariant:

- **The name identifies the agent, not the process.** C1 requires the queue group to be a pure
  function of the agent's own identity, so that regrouping is invisible to the broker. Only
  `nats_queue_group` and `app_name` feed it -- never a pod, container or replica name. When
  namespaces land, the namespace supplies the name directly and these keys stay as the root-namespace
  fallback.
- **An underivable name raises rather than defaults.** NATS reads `queue=""` as *no queue group*, so
  any silent fallback would reintroduce exactly the fan-out being fixed, and would do it invisibly.
  `subscribe()` raises `ValueError` instead, naming both keys.
- **It is resolved in `subscribe()`, not at subscription time.** `subscribe()` is called by the
  caller's startup path, while the actual subscribing happens inside the background retry task. A
  config error raised in that task would be retried indefinitely (`event_client_max_retries`
  defaults to `-1`) and would surface only as a readiness probe that never goes green. Raising in
  `subscribe()` fails startup where a human is looking.

**Motivation.** JetStream is off by default, so the default transport path was plain Core NATS with
no queue group: `replicas: 2` meant both replicas received and processed every event -- every side
effect twice, every inference billed twice. This is a defect at any replica count above one,
independent of grouping, and it is what makes the deployment guide's multi-replica warning
removable later.

**JetStream is deliberately untouched, and still single-subscriber.** nats-py rejects a queue
subscription whose durable name differs from the queue name
(`cannot create queue subscription '<queue>' to consumer '<durable>'`), so passing the queue group
next to the existing per-topic durable would raise at subscribe time. A durable shared across
replicas needs its deliver group set on an explicitly constructed `ConsumerConfig` and bound with
`subscribe_bind`, which is the same object P3 has to build anyway for `ack_wait` and
`max_ack_pending`. Doing it there is one change instead of two, and the constraint is recorded as a
comment at the call site so it does not read as an oversight. Until then a second replica on
JetStream fails to subscribe loudly (`consumer is already bound to a subscription`) rather than
double-processing silently -- the safer of the two failures, and readiness gating keeps such a pod
out of rotation.

New config key: `nats_queue_group` (default: `app_name`), documented in
`docs/reference/configuration-keys.md`.

**What this buys, and what it depends on.** The group key is *(subject, queue name)*, so with the
name set per agent the two properties a multi-agent platform needs hold together: different agents
on one subject are different groups and each receives its own copy (fan-out), while replicas of one
agent share a group and one of them handles each message (round-robin). Adding a replica never adds
a copy; adding an agent always does. Plain non-queue subscribers, such as a monitoring tap, are
unaffected and still receive everything.

Both properties rest on the names being distinct per agent, and two things can break that:

- **Default-valued `app_name`.** Scaffolding writes the project name
  (`settings_part_generator.py:11`), but the config validator falls back to `agent_blueprint` if the
  key is removed, and `asbs create agent` outside a scaffolded project writes `generated-agent`
  (`create.py:580`). Two services on either default would join one group and steal each other's
  events -- the failure this fixes, moved from replicas to agents. Candidate for an `asbs validate`
  notice when `event_bus = "nats"`.
- **JetStream durables are keyed by topic, not by agent** (`nats_durable_name`, default
  `f"{topic}-durable"`). Two agents subscribing to the same topic both try to bind one durable and
  the second fails. Cross-agent fan-out under JetStream therefore does not work until the Phase 5
  rename to `f"{namespace}-{topic}-durable"`, which is the functional reason that rename is
  load-bearing rather than cosmetic. Separately, a project that sets `nats_durable_name` explicitly
  collapses all its topics onto one durable name; pre-existing, and worth fixing where Phase 5
  touches that line.

### P2 -- acknowledgement at the NATS transport edge (`ce17f87`)

JetStream messages were subscribed with `manual_ack=True` and never acknowledged, so every event
redelivered until `max_deliver` -- a defect at a single replica, not just at scale. The transport
edge now settles every delivery, and the classification needed to settle it correctly survives the
trip from the handler.

**The disposition table lives in one place.** `models/errors.py` gains `DeliveryDisposition`
(`ACK`/`NAK`/`TERM`) and `disposition_for(exc)`, next to the exceptions it classifies. Spec sec. 7.2
requires both transports to map the same outcome to the same disposition, so encoding the table once
is what makes that checkable rather than aspirational -- and a new `HandlerError` subclass is now
added in the same file that decides what its failures do to a delivery. Matching is by `isinstance`,
so a project's own subclass inherits its parent's disposition. The function never returns `ACK`:
acknowledgement is what a *normal return* means, and the edge decides that without asking.

**`NATSClient._settle` applies it.** `message_handler` acks on normal return, terms an undecodable
payload before dispatch, and otherwise settles with whatever `disposition_for` says. Two details:

- It gates on `_use_jetstream`, not on `msg.reply`. Core NATS is fire-and-forget and `msg.ack()`
  raises `NotJSMessageError` there, but a Core NATS *request/reply* message does carry a reply
  subject -- gating on the subject would publish `+ACK` to a waiting requester.
- A failure to settle is logged and swallowed. The acknowledgement is published to the delivering
  connection's reply subject, so it fails exactly when that connection is gone; raising into the
  `nats-py` callback would neither deliver it nor recover it. The message redelivers after
  `ack_wait`, which is the at-least-once behaviour sec. 7.4 already requires handlers to tolerate.

**Two swallowing layers removed.** `NatsEventing._process_event` caught the three classified handler
errors, logged them and returned normally -- which, once the edge acks on normal return, would have
acknowledged every failed event as processed. `EventHandlingBase._process_cloud_event` logged each
exception and re-raised it; the logging is gone and the exception now passes through untouched. Both
transports already log at their own edge, where the topic and the disposition are known, so the
removed logging was duplicate output that knew less than the line beside it. It also brings the
method in line with the repo's log-or-raise rule.

**Still open in P2**, each its own step: Dapr parity (`NO_HANDLER_FOUND` -> `SUCCESS`,
`CriticalHandlerError` -> `DROP`, and the same in `handle_event`), the unhandled-event counter with
its first-occurrence warning, and `max_deliver` plus a dead-letter destination, which lands with P3
because a nak on an unexpected exception otherwise redelivers forever.

### P2 -- Dapr parity (`ce17f87`)

Dapr acknowledges by response body, so `POST /events/{topic}` is its `_settle`. It disagreed with
the spec table in two places, and both disagreements were live defects:

- **`NO_HANDLER_FOUND` returned `RETRY`.** An event no handler wanted was redelivered until
  `max_deliver`, and now that P1 puts every replica in a queue group, that loop visits each replica
  in turn before giving up. It answers `SUCCESS`.
- **`CriticalHandlerError` returned `RETRY`.** A critical error is not made less critical by being
  delivered again. It answers `DROP`, matching NATS's `term`.

An unexpected exception previously raised `HTTPException(500)`. That is a third behaviour rather than
a disposition: the sidecar sees a failed call and applies whatever its own resiliency policy says,
which need not be retry and is not visible from this code. It now answers `RETRY` explicitly, as the
table requires. **The tradeoff is deliberate**: a 500 showed up in HTTP metrics and traces as a
failure, and a 200 with `RETRY` does not, so an unexpected handler exception is now visible only in
the log line and in Dapr's own retry counters until the P2 counters land.

**One `except`, not four.** The four per-error-type blocks collapsed into a single one that calls
`disposition_for(exc)` and renders the result. The rendering lives in a new
`io/api/eventing/dapr_response.py` -- three lines of mapping from `DeliveryDisposition` to
`SUCCESS`/`RETRY`/`DROP`. It sits there rather than in `models` so Dapr's vocabulary does not leak
into the shared layer, and rather than in `dapr.py` so `EventHandlingBase.handle_event` can render
identically without importing a subclass. What an outcome deserves is decided once; each transport
only says it in its own words, and adding a new error type can no longer update one transport and
miss the other.

`EventHandlingBase.handle_event` got the same treatment: acknowledge whatever status the chain
returned, warn when nothing matched, and let exceptions through to the edge.

**Unparseable deliveries now drop, which changes an HTTP response.** A payload that cannot become a
CloudEvent must `DROP` (spec sec. 7.2), but under Dapr the body is parsed by FastAPI before any
framework code runs, so that payload was answered **422** and the sidecar retried it to
`max_deliver` -- the one row of the table where the transports disagreed for a structural reason
rather than a coding one. `DaprDeliveryRoute`, an `APIRoute` subclass, wraps the route handler and
converts `RequestValidationError` into `200 {"status": "DROP"}`.

*This is a deliberate behaviour change*: `POST /events/{topic}` no longer answers 422 for a malformed
body under Dapr. That is the correct answer to a *REST caller* and the wrong answer to a *sidecar
delivery*, and the same path serves both roles. The wrapper is therefore scoped to the component
that asks for it via a new `RestApiBase.route_class` hook -- an application-wide
`RequestValidationError` handler would have answered `DROP` for ordinary REST endpoints too, where
422 is right. `NatsEventing`, which owns the same path for the outbound direction, keeps the default
route class and still answers 422; there is a test for exactly that.

### P2 -- unhandled-event accounting, and a spec correction

An event that matches no handler is acknowledged, and it is also **ordinary**. Deciding there is
nothing to do is the handler's job and an ordinary outcome of doing it: an agent reads an event,
finds no work in it, and says so. Why is the agent's business -- wrong tenant, wrong state, a
condition that is not met -- and none of it is the framework's concern.

`_process_cloud_event` therefore does exactly two things with such a dispatch: increments
`blueprint.events.unhandled` with `namespace` and `topic` attributes, and logs at DEBUG.

- **Counted, because the ratio is the signal.** A namespace declining nearly everything it receives
  is subscribed too broadly (spec sec. 7.7). That is a question about the subject filter, and it is
  only answerable against received volume -- so the count must not be deduplicated.
- **Not flagged, because nothing is wrong.** No WARNING, no error.
- **No state kept.** Under Dapr the topic comes from a URL path, so remembering distinct topics
  would let a caller grow this process's memory.

It lives in `_process_cloud_event`, shared by both transports, because an unmatched dispatch is a
property of the dispatch rather than of the transport carrying it -- and both edges keeping their
own copy of a delivery rule is how they came to disagree about `NO_HANDLER_FOUND` in the first
place. The interim per-event warnings the Dapr work left in `publish` and `handle_event` are gone.

`_process_cloud_event` gains a `topic` parameter. The topic is already in `context`, but each
transport spells its key differently (`nats_topic`, `dapr_topic`) and those keys reach user
handlers, so they cannot be unified without breaking them.

`EventHandlingBase.ROOT_NAMESPACE` is the one place the "no namespaces yet" assumption is written
down; phase 2 replaces it and the counter's `namespace` attribute starts varying.

**The spec was wrong and is corrected.** Sec. 7.2 had required a WARNING on the first
(namespace, topic) pair and called an unmatched event "usually a declaration error"; sec. 7.7 called
it one of "both directions of the same error". That premise is false -- it treats a handler's
domain decision as a framework fault -- and it was implemented before being questioned. Sec. 7.2 now
forbids reporting it as a fault and forbids per-topic state, sec. 7.7 frames both counters as ratios
rather than faults, and the acceptance criterion carries the same conditions. A first
implementation with the tracker, the warning and an accumulating set was replaced rather than
committed.

### P3 -- consumer tuning, deliver groups and dead letters (`8ce9600`)

Four settings, one object. `ack_wait`, `max_ack_pending`, `max_deliver` and the deliver group all
live on `ConsumerConfig`, so the client stops letting `js.subscribe` invent a consumer and builds
one itself: `_ensure_consumer` creates the durable through `add_consumer` and `_subscribe_one` binds
to it with `subscribe_bind`. That is the only route by which P1's queue group can reach JetStream --
`nats-py` refuses a queue subscription whose durable name differs from the queue name, and the
durable is per topic while the queue group is per agent -- so **JetStream stops being
single-subscriber**, which was the half of P1 that had to wait.

New keys, all defaulting to working behaviour: `nats_ack_wait` (300 s), `nats_max_ack_pending` (16),
`nats_max_deliver` (5), `nats_dead_letter_subject` (`<queue group>.dead-letter`). They are resolved
and validated in `subscribe()` alongside the queue group, for the same reason: a config error must
fail the caller's startup rather than repeat forever inside the background retry task.

**Two defaults are opinions, and the reasoning is worth keeping.** `ack_wait` is 300 s against a
NATS default of 30 s, because handlers here call models and a redelivery mid-inference costs the
work twice. `max_ack_pending` is 16 rather than the NATS default of 1000, because a `nats-py` push
subscription runs its callbacks one at a time: everything the broker pushes beyond what is actually
being processed sits in the client's queue with its `ack_wait` already running down. A large window
does not buy throughput here, it manufactures expiries.

**Dead letters.** `_settle` gained one branch: a nak on the last delivery `max_deliver` permits is
turned into a dead letter plus a term. Naking there is a lie -- the broker will not redeliver it --
and it differs from a term only in that the message leaves the consumer with no trace of why, one
`ack_wait` later than it needed to. `_dead_letter` republishes the **original bytes**, unchanged, so
a payload that never parsed as a CloudEvent survives; what went wrong travels in
`Blueprint-Dead-Letter-Reason`, `-Original-Subject`, `-Delivery-Count` and `-Event-Id` headers, where
it cannot corrupt a body some dead-letter consumer will try to read. Terminal failures --
`InvalidEventError`, `CriticalHandlerError`, an unparseable payload -- take the same path. Setting
the subject to `""` disables it, and then each drop is logged as a lost payload rather than passing
silently.

The dead-letter subject is derived from the queue group, so it follows the agent's identity exactly
as C1 requires, and it is validated at startup: a wildcard is rejected because it is published to,
and a subject the same client subscribes to is rejected because dead-lettering onto a consumed
subject turns one failure into an unbounded loop -- the kind that only shows up under load.

**Three defects surfaced while building it**, none visible from P3's description, all of which
blocked explicit consumer creation:

1. **The stream never covered the subject its consumer filtered on.** `add_stream` was called with
   `subjects=[f"{topic}.>"]`, which does not match `topic` itself. `js.subscribe` had been papering
   over it by letting the server pick; an explicitly created consumer filtering `orders.created` is
   simply rejected by a stream that only captures `orders.created.>`.
2. **Only the first topic was ever added to the stream.** `add_stream` ran once per topic with the
   same stream name; every call after the first answered "stream name already in use" and was logged
   as a warning, leaving the remaining topics uncaptured. Provisioning now happens once per connect,
   in `_provision_stream`, with the union of every subscribed subject plus the dead-letter subject,
   and widens an existing stream additively rather than replacing it.
3. **The derived durable name was illegal for any dotted subject.** NATS allows no `.`, `*`, `>` or
   whitespace in a consumer name, so `f"{topic}-durable"` could not work for `orders.created` -- that
   is, for essentially every idiomatic NATS subject. `_durable_for` replaces those characters, and
   `_resolve_durables` rejects at startup both the collision that substitution can create and
   `nats_durable_name` set while several topics are subscribed, since one durable filters one
   subject.

**An existing consumer is never rewritten.** `_ensure_consumer` reads `consumer_info` first and, when
the durable already exists, binds to the server's config and logs which settings differ. A durable's
filter subject and deliver group are broker-side state that the stream's pending and redelivery
bookkeeping hangs off; rewriting one in place either replays messages it already handled or skips
ones it never saw. The spec already called consumer reconfiguration a migration, and this is that
rule in code -- a rolling restart must not perform one silently. The practical consequence is that
an existing deployment upgrading into this change keeps its old consumer, without a deliver group,
until someone deletes it deliberately; the warning names exactly which settings are not in force.

The deliver subject is derived from the durable name rather than taken from a fresh inbox, because
every replica has to bind to the same one -- two replicas generating random inboxes would define two
consumers, which is the fan-out P1 removed.

### P4 -- opt-in deduplication, and the decision forced on the author (`d127843`)

At-least-once delivery is permanent (spec sec. 7.4). P2 and P3 made acknowledgement correct, which
narrows redelivery to the cases where it is unavoidable -- a lost ack, a pod restart, a rolling
deploy -- but does not remove them: a handler that finishes 60 s of inference and then cannot ack
has already committed its side effects, and the broker sends the event again. Whether replaying
those side effects is *correct* is a property of the product, not of the framework, so P4 provides
the mechanism and refuses to make the choice.

**The chain claims before it dispatches.** `HandlerChain.process` no longer runs the handler loop
directly; it calls `_claim`, and only then `_dispatch` (the loop, moved verbatim). `_claim` returns
whether to dispatch: with dedup off it always returns `True`, and with dedup on it asks the cache
whether a marker for this event exists, writes one with the configured TTL if it does not, and
returns `False` if it does. A `False` makes `process` set `DUPLICATE_CONTEXT_KEY` in the context,
stamp `event.duplicate` on the span, and return `None` without touching a handler.

**A failed dispatch releases the claim.** This is the part that is easy to leave out and expensive
to leave out:

```python
try:
    return await self._dispatch(event, context)
except Exception:
    self._release(event, policy)
    raise
```

The claim has to be taken *before* dispatch -- that is the only point at which it can stop a
concurrent duplicate -- which means a dispatch that raises has left a marker behind for an event
that was never processed. The exception it re-raises is what P2 turns into a nak, and the broker
sends the same event back. Without `_release`, that redelivery is swallowed as a duplicate, and so
is the next one, until `max_deliver` is exhausted and the message is dead-lettered having never
reached a handler. The test that pins this asserts the handler is entered on both attempts.

**The key carries the source as well as the id.** `_idempotency_key` returns
`{"id": ..., "source": ...}`. The spec says "keyed on the CloudEvent `id`", but the CloudEvents
specification requires an id to be unique only *within* a source, so two producers may both legally
emit id `"1"` and keying on the id alone would let one publisher's event suppress another's. It is
sent as a dict because the cache sorts a dict by key before hashing it, which a two-element list --
which the cache sorts by *value* -- would not preserve. An event missing either field is dispatched
untracked with a warning rather than dropped.

**`idempotency_ttl` is required, and deliberately has no default.** `_resolve_idempotency_policy`
raises at startup if dedup is enabled without it. The window has to outlast the redelivery window it
exists to cover -- `nats_ack_wait * nats_max_deliver` under JetStream, whatever the component's
retry policy says under Dapr -- and neither number is one the dispatch layer can read without
reaching into a transport it must not know about. A default here would ship a dedup window that
silently expires before the last redelivery arrives, which presents exactly like dedup not working
at all. So enabling dedup is two keys, and the second one is the decision spec sec. 7.4 asks the
author to make. The same method rejects a non-boolean `idempotency_enabled`, a non-positive or
non-numeric TTL, and -- the one that would otherwise fail silently -- dedup enabled with no cache
registered, where there is nowhere to keep the markers.

**Startup runs, because something now calls it.** `HandlerChain` is created by
`EventProcessingService` with `should_register=False`, so nothing in the lifespan ever called its
lifecycle hooks; its `on_startup` was a no-op and could stay one. It resolves the policy now, so
`EventProcessingService.on_startup`/`on_shutdown` delegate to the chain -- a bad dedup setting has
to fail the pod, not the first event that arrives on it. `process` also resolves the policy on first
use if startup never ran, because a chain constructed outside `AppBuilder` inheriting "dedup is off"
from a missed wiring step is the one failure this feature must not have.

**A duplicate is counted apart from an unmatched event.** At the transport edge,
`_process_cloud_event` checks the context flag before it looks at the status:

```python
if context.get(DUPLICATE_CONTEXT_KEY):
    _DUPLICATE_EVENTS.add(1, {"namespace": self.ROOT_NAMESPACE, "topic": topic})
elif processing_result.status is ProcessingStatus.NO_HANDLER_FOUND:
    _UNHANDLED_EVENTS.add(1, {"namespace": self.ROOT_NAMESPACE, "topic": topic})
```

A deduplicated event arrives here looking exactly like an unmatched one -- no handler ran, so no
result came back -- but the two say opposite things about the subscription. An unmatched event is
one this namespace had no use for, and `blueprint.events.unhandled` is read as a ratio to spot a
namespace subscribed too broadly (spec sec. 7.7); a duplicate is an event it *did* use, once.
Counting them together would make a redelivery storm read as a bad subscription. The flag travels in
`context` rather than as a third `ProcessingStatus` value because that enum is normative in spec
sec. 7.2 -- it carries two values precisely so that no failure can reach the transport as a returned
value, and adding to it invites exactly that. `context` is already the channel handlers use to pass
information along the chain, and it is mutated in place all the way down.

**Both dispositions are unchanged.** A duplicate acks, like any completed dispatch. Redelivering it
forever would be the one outcome worse than processing it twice.

**The claim is not a lock, and this is written into the class docstring.** `exists` then `set` is
not atomic on either cache backend, so two replicas handed the same event at the same instant can
both pass the check; a cache that is unreachable fails open, because both `DiskCacheService` and
`RedisCacheService` swallow their own errors and return `False`/`None`. Dedup narrows the duplicate
window, it does not close it, and a handler whose side effects must never repeat still needs its own
reconciliation. The cache calls are also synchronous inside an async method, like every other cache
call in the framework today; phase 2 moves them onto the namespace executor.

**Surfacing the requirement (spec sec. 7.4, the second half).** The mechanism is only half of P4 --
the author has to be told the choice exists:

- **Scaffolded handler** (`base_files/src/handlers/handler.txt`): a `DECIDE:` comment at the top of
  `handle_event` explaining that redelivery is normal behaviour rather than an edge case, naming
  both ways out (write a repeatable handler, or set the two keys), and asking to be deleted once the
  decision is made. `asbs setup` and `asbs create handler` share this template, so one edit covers
  both.
- **Generated `settings.toml`** (`base_files/settings.txt`): both keys, commented, inside `[default]`
  -- not after `[default.logging]`, where uncommenting them would silently put them in the wrong
  table.
- **Generated project docs** (`claude_docs/CLAUDE.md`): a bullet under EventHandler and the two keys
  in the settings example.
- **`asbs validate`**: a new `Notices` section. `_idempotency_notice` reports when a project has
  handlers and its `settings.toml` does not declare `idempotency_enabled` -- in any environment
  table, since dynaconf environments are top-level tables. Declaring it `false` silences the notice
  as much as `true` does: the point is that a decision was made, not which one. A project with no
  handlers is not notified, and an unparseable `settings.toml` is left to the check that already
  reports it rather than guessed at.

There is no generated README to put the spec's third line in -- `asbs setup` does not write one --
so the generated `CLAUDE.md` and `settings.toml` carry it instead. Listed under *Open points*.

Tests: dedup off by default and repeat deliveries dispatching twice; the same event dispatching once
and the second delivery flagged in context; the claim written with the configured TTL into its own
cache namespace; the same id from a different source not being a duplicate; a failed dispatch
releasing the claim and the retry reaching the handler; an event missing a source dispatching
untracked; six policy-resolution failures and the string form an environment variable delivers; the
duplicate counter firing while the unhandled counter does not, and the reverse; and seven cases for
the `asbs validate` notice.

### P5 -- the cron timer becomes a stated choice, and the tick becomes an event (`662f7b5`)

`SchedulerBase.on_startup` created an `AsyncIOScheduler` per process with no leader election
(#73), so every replica fired every cron tick. Grouping widens that: one pod hosting 20 agents
runs 20 timers, and two replicas duplicate all 20 agents' crons at once. The fix spec sec. 7.5
asks for is not leader election -- it is taking the timer off the path nobody chose.

**`scheduler_mode` selects what calls `tick()`, and it has no default.** `_resolve_mode` reads the
key, lower-cases and strips it, rejects an absent or empty value, and then accepts only `"event"`
or `"in_process"`:

```python
raw = self.config.get("scheduler_mode", None)
mode = str(raw or "").strip().lower()
if not mode:
    raise ValueError(
        f"Scheduler '{self.name}' is registered but 'scheduler_mode' is not set, and it has no default. "
        f"Set it to '{SCHEDULER_MODE_EVENT}' to take the tick as an event on '{self.tick_topic}', published "
        f"by an external CronJob -- exactly one replica then runs it. Set it to '{SCHEDULER_MODE_IN_PROCESS}' "
        "to run an APScheduler timer inside the process, which is correct for local development and plain "
        "Docker but fires once per replica."
    )
if mode not in SCHEDULER_MODES:
    raise ValueError(f"Config key 'scheduler_mode' must be one of {', '.join(SCHEDULER_MODES)}, got {raw!r}.")
```

The error names both values and what each one costs, because it is the only thing an existing
project sees. The result is cached on the instance, so the mode cannot change under a running
scheduler. *Why there is no default* is argued below -- it is a deliberate departure from spec
sec. 7.5, which names `"event"` as the default.

**Event mode without a transport fails too.** `_require_event_transport`, called from `wire()`
before the handler is created, insists on `event_bus` being one of `EVENT_MODE_TRANSPORTS =
("dapr", "nats")`. `"sessions"` is excluded on purpose: `SessionsBus` consumes SSE job
notifications and never reads `get_subscribed_topics()`, so a tick published to a topic would not
arrive. Without this check, event mode with no broker is the one failure that is pure silence --
the scheduler starts, subscribes to nothing, and never ticks.

**In event mode nothing in the process keeps time.** `on_startup` now branches:

```python
if self._started:
    logger.warning("Scheduler '%s' is already started; ignoring the repeated startup", self.name)
    return
self._started = True
self.wire()

if self.scheduler_mode == SCHEDULER_MODE_EVENT:
    logger.info(..., self.name, self.tick_topic, self._crontab)
    return

trigger = CronTrigger.from_crontab(self._crontab)
self._scheduler = AsyncIOScheduler()
self._scheduler.add_job(self.tick, trigger, name=self.name)
self._scheduler.start()
```

The `AsyncIOScheduler` block is unchanged and now runs only under `"in_process"`. `on_shutdown`
clears `_scheduler` and `_started` after shutting the timer down, so a stop/start cycle in one
process starts one timer again rather than none.

**`SchedulerTickHandler` is what turns an external tick into a `tick()`.** A new
`EventHandlerBase` subclass in the same module, holding a scheduler and a topic:

```python
def get_subscribed_topics(self) -> list[str]:
    return [self._topic]

async def can_handle_event(self, event, context) -> bool:
    return any(context.get(key) == self._topic for key in _TOPIC_CONTEXT_KEYS)

async def handle_event(self, event, context) -> dict[str, Any]:
    logger.info("Scheduler '%s' ticking from event '%s' on topic '%s'", self._scheduler.name, event.id, self._topic)
    await self._scheduler.tick()
    return {"status": "ticked", "scheduler": self._scheduler.name}
```

That is the entire event mode. Declaring the topic is what makes the transport subscribe --
`NatsEventing.on_startup` and `DaprEventing._declared_topics` both walk
`registry.get_event_handler()` and call `get_subscribed_topics()` -- so the tick arrives on the
path the framework already has, and the queue group is what guarantees a single replica runs it.
Nothing is elected. Dedup, the unhandled/duplicate counters and the P2 acknowledgement contract
apply to a tick exactly as they do to any other event: a `tick()` that raises reaches the
transport edge and is naked or termed there, which is why `handle_event` does not catch.

Three details in that class are load-bearing:

- **It matches the topic, not the event type.** `_TOPIC_CONTEXT_KEYS = ("nats_topic",
  "dapr_topic", "topic")` -- every key a transport spells the delivery topic with. Those keys
  reach user handlers and were deliberately left un-unified
  (`EventHandlingBase._process_cloud_event` says so), so a consumer that wants the topic has to
  read all three. Matching the topic rather than a type string also means a hand-published tick
  during development works with any body.
- **`PRIORITY = 10`, ahead of the default 100.** A handler that declares nothing is still
  evaluated for every event its namespace receives (spec sec. 7.7, rule 1), so a permissive
  `can_handle_event` in user code would otherwise claim the tick first.
- **It renames itself in `__init__`.** `Component.__init__` registers under the class-derived
  name, and `Registry.add_component` raises on a duplicate, so a second scheduler's handler would
  collide with the first on `scheduler_tick_handler`. Assigning `self.name = f"{scheduler.name}_tick"`
  immediately pops that key back out of the registry, which is what leaves it free for the next
  instance. A test builds two schedulers against a real `Registry` to pin it.

**The tick topic derives from the agent, not the deployment.** `_resolve_topic` returns
`f"{namespace}.scheduler.{self.name}"`, falling back to `app_name` while `ROOT_NAMESPACE` is still
`""` -- the same identity the queue group derives from, so moving a scheduler between deployment
groups does not change the subject a `CronJob` publishes to (C1). It raises if no identity is
available, and rejects `*` and `>` in either the derived or the `topic=`-overridden form -- a
wildcard would subscribe the scheduler to traffic that is not its tick. Whitespace is treated
asymmetrically: rejected in an explicitly named topic, but rewritten to `_` in a derived one, the
way `NATSClient._durable_for` already rewrites a subject into a legal durable name.
`app_name = "Health Monitor"` is legal and common -- `examples/health_monitor` uses exactly that --
and since the topic is derived rather than typed there is no author mistake to catch, only a name
to make usable. The `topic=` override exists because the subject taxonomy is still unratified
(spec sec. 13): an agent whose ticks are already published on someone else's subject can name it.

**`wire()` runs at build time, and that placement is the fix for two silent failures.**

```python
def wire(self) -> SchedulerTickHandler | None:
    self.register_trigger_route()
    if self.scheduler_mode != SCHEDULER_MODE_EVENT:
        return None
    if self._tick_handler is None:
        self._tick_handler = SchedulerTickHandler(self, self.tick_topic)
    return self._tick_handler
```

`AppBuilder.build()` calls it in a new step 2, before the existing `if registry.get_event_handler():`
block that creates the transport and the eventing endpoint:

```python
for scheduler in registry.get_schedulers():
    tick_handler = scheduler.wire()
    if tick_handler is not None:
        logger.info(
            "Scheduler '%s' is in event mode; its tick arrives on topic '%s' (crontab '%s')",
            scheduler.name, tick_handler.topic, scheduler.crontab,
        )
```

- **Without that ordering, an application whose only event consumer is a scheduler gets no
  transport.** `build()` creates `NATSClient`/`DaprClient` and the eventing component only when a
  handler is registered. A tick handler created during `on_startup` would arrive after that
  decision, so the scheduler would be registered, subscribed to nothing, and never ticked.
- **The manual trigger route was already broken, and this is where it gets fixed.**
  `POST /{name}/trigger` was added to `self.router` inside `on_startup`, but
  `_build_rest_endpoints` calls `app.include_router` during `build()`, and `include_router` copies
  the routes a router holds *at that moment*. Every route added during startup therefore existed
  on the scheduler's own router and was served by nothing. `register_trigger_route` is idempotent
  and now runs from `wire()`, before the copy. It stays out of `__init__` because
  `with_scheduler(name=...)` can rename the component afterwards and the path carries the name.

`on_startup` still calls `wire()` itself, so a scheduler driven without `AppBuilder` gets its
handler and its route; both calls are no-ops the second time.

**#43 -- and it had a second cause, worse than the one on record.** The plan describes two
`build()` passes driving the lifespan hooks twice over the same registry; the `_started` guard
covers that. But it happens in a *single* pass too, and it always has:

```python
print([x.name for x in registry.get_schedulers()])   # ['nightly_scheduler']
print([x.name for x in registry.get_rest_apis()])    # ['nightly_scheduler']
```

`SchedulerBase` extends `RestApiBase` -- that is how `POST /{name}/trigger` reaches the app -- so
every scheduler is in `get_rest_apis()` as well as in `get_schedulers()`, and the lifespan iterates
both lists. `on_startup` therefore ran twice on the same object in one startup, and the old
implementation created a fresh `AsyncIOScheduler` each time and overwrote `self._scheduler`. The
first one was already started and stayed started, holding the same job, while the attribute pointed
at the second -- so **every cron job fired twice in a single replica, and `on_shutdown` could only
ever stop one of the two timers.** `on_shutdown` was likewise called twice, which for a subclass
doing anything non-idempotent in either hook is its own problem.

Two changes, because the two failures are different:

- `SchedulerBase.on_startup` guards on `_started` and warns on a repeated call. That absorbs both
  causes and is the safety net.
- `AppBuilder._lifecycle_rest_apis` removes schedulers from the REST-API lifespan loops, so the
  double drive stops happening at all:

  ```python
  return [rest_api for rest_api in registry.get_rest_apis() if not isinstance(rest_api, SchedulerBase)]
  ```

  Their routers are still mounted from `get_rest_apis()` in `_build_rest_endpoints`, which is where
  that inheritance is wanted. Without this the guard would fire a warning on every startup of every
  scheduler, which is a fix that reports itself as a fault forever.

An integration test asserts a scheduler's hooks run once per lifespan and that no "already started"
warning is emitted.

**Publishing no longer requires consuming.** Both transport clients were constructed only inside
`build()`'s `if registry.get_event_handler():` branch, and `EventPublishingService` only when an IO
client existed -- so a scheduler-only application could not publish an event at all, whatever its
`event_bus` said. A nightly job that emits `reconciliation.completed` had no way to do it. The two
decisions are now separate:

```python
consumes = bool(registry.get_event_handler())
publishes = self._publishing_requested()
event_bus_type = str(self._config.get("event_bus", "") or "").strip().lower()

if publishes and event_bus_type not in TOPIC_TRANSPORTS:
    raise ValueError(...)

if consumes or publishes:
    if event_bus_type == "dapr":
        DaprClient()
        if consumes:
            self._eventing_component = DaprEventing()
    elif event_bus_type == "nats":
        NATSClient()
        if consumes:
            self._eventing_component = NatsEventing()
    ...
```

`event_publishing_enabled` (bool, default `False`) is the opt-in, and it stays opt-in on purpose: a
project that wants only a timer may have no broker access at all, and a client created on its
behalf becomes a readiness dependency on infrastructure it does not run. An absent or empty value
both mean off -- an unset environment override arrives as `""` -- while a non-empty non-boolean
raises, through a new shared `parse_bool` in `utils` that `HandlerChain._read_bool` had implemented
privately for `idempotency_enabled`.

The publish-only shape gets a client and **nothing else**: no eventing component, so no
`GET /dapr/subscribe`, no `POST /events/{topic}`, no subscription and no consumer. That is the
property that makes it safe for an agent that was never meant to consume -- it cannot accidentally
receive anything, because nothing was subscribed. `EventProcessingService` is still keyed on
`consumes`, and `EventPublishingService` still on the client existing, so a consuming application
keeps the publishing it has always had without touching the new key.

`TOPIC_TRANSPORTS = ("dapr", "nats")` now lives next to `IOClientBase` -- the class that exists only
for those two -- rather than in the scheduler module, because two callers need the same fact:
publishing needs a client, and an event-mode scheduler needs a subscription. `"sessions"` is
excluded from both; it wires `SessionsApiClient` and `SessionsBus`, which consumes SSE job
notifications and never reads `get_subscribed_topics()`.

**Two defects in the generated scheduler, found on the way.**

- **`asbs create scheduler` emitted a file that does not parse.** The template's `tick` body was a
  `try:` containing only comments, followed by `except Exception as e:` -- a `SyntaxError`, so the
  scaffolded module could not even be imported. The `try` is gone; `tick` is now a documented
  TODO that lets its exceptions out, which is also what the acknowledgement contract needs (and
  the old body logged *and* re-raised).
- **The scaffolded `on_startup` never called `super().on_startup()`.** It overrode the base method
  with a comment-only body, so a scaffolded scheduler that did parse would have started no timer
  and registered no trigger route -- in either mode. Both hooks now call `super()`, with a comment
  saying what breaks without it. The same omission was in the scheduler example in the generated
  `CLAUDE.md` and is fixed there too.

**Why `scheduler_mode` has no default (a departure from spec sec. 7.5).** The spec names `"event"`
as the default. It is not implemented that way, and the reasoning belongs on the record because it
is the first question a reviewer will ask.

Neither value is a defensible thing to inherit silently:

- **`"in_process"` as the default would ship the defect.** It *is* #73 -- a timer in every replica,
  so scaling past one fires every tick N times, and a pod hosting 20 grouped agents runs 20 timers.
  Defaulting to it means only the projects that read the release notes closely enough to opt in get
  the fix, and the ones that do not are precisely the multi-replica production deployments that can
  least afford duplicated side effects.
- **`"event"` as the default would ship silence.** It is correct under an orchestrator, but it needs
  something outside the process to publish the tick and a transport to receive it. A service whose
  only job is periodic work may have neither -- `examples/health_monitor` registers two schedulers
  and configures no `event_bus` at all -- and for those, event mode is not a line of config but a
  broker they do not have. On upgrade they would simply stop ticking.

Which value is right depends on facts this layer cannot read: whether a broker is reachable,
whether more than one replica runs, whether an orchestrator exists at all. That is the same shape
as `idempotency_ttl` in sec. 7.4, and it gets the same answer -- the framework provides the
mechanism and the author states the choice. The cost is one line of config per existing project,
paid once, against a startup error that names both options.

The counter-argument, for the record: `"in_process"` as the default would have made this change
fully backward-compatible, and a required key does break every existing project with a scheduler.
That is accepted deliberately -- the break is loud, one-time and actionable, where the alternative
is a wrong default that stays wrong. It should be an amendment to spec sec. 7.5 rather than an
implementation detail that quietly contradicts it.

**What is surfaced to the author.** `scheduler_mode = "event"` is written explicitly into the
scaffolded `settings.toml` as `"in_process"` -- the right value for the local `asbs dev` loop a new
project starts in -- with the trade-off and the requirement in a comment, the generated `CLAUDE.md`
gains three bullets on the two modes and the `super()` requirement, and
`docs/reference/configuration-keys.md` gains a `## Scheduling` section.
`examples/health_monitor`, the one project in this repository with schedulers, states
`"in_process"` and says why in a comment. That reference was also missing `idempotency_enabled` and
`idempotency_ttl` from P4 -- documented there now, in a `## Event Deduplication` section, together
with both keys in the example `settings.toml`.

Tests: both modes read back, case tolerance, an absent/empty/whitespace value and an absent key
each rejected with both values named, rejection of an unknown value, single resolution; topic
derivation from `app_name` and from a renamed scheduler, the `topic=` override, a missing identity,
two wildcards, whitespace rejected in an explicit topic and rewritten in a derived one; `wire()`
creating a handler in event mode only, its idempotency, one trigger route in both modes, event mode
refusing three unusable `event_bus` values and accepting both broker transports, and in-process
mode needing no transport; `parse_bool` accepting a bool, the four true/false strings and rejecting
anything else; `on_startup` starting no timer in event mode, starting and
scheduling one in in-process mode, and starting no second timer or route when called twice (#43);
shutdown allowing a restart; the tick handler's declared topic, priority, name, the three context
keys it accepts, the topics it declines, the tick it runs, the absence of a published event, a
failing tick reaching the transport edge, and two schedulers registering distinct names against a
real `Registry`; `build()` wiring an event-mode scheduler before the transport decision and
creating no transport for an in-process one; and six assertions on the generated scaffold,
including that it parses.

One offline integration test (`tests/integration/test_scheduler_event_mode.py`) exercises the
whole of event mode with nothing listening anywhere, which the Dapr transport makes possible: a
real `Config`, a real `build()`, the tick topic appearing in `GET /dapr/subscribe`, a CloudEvent
posted to `POST /events/<tick topic>` answering `SUCCESS` and the scheduler's `tick()` having run
once. It also pins the two things a unit test cannot see, both about what `build()` hands to
FastAPI: `POST /api/<scheduler>/trigger` answering 200, and an in-process scheduler producing no
subscription document at all. Two more assert the loud failures at `build()`: a scheduler with no
`scheduler_mode`, and `"event"` with no `event_bus`. Three more cover the publish-only shape end to
end -- a pure scheduler that opts in gets a client and a publishing service while
`GET /dapr/subscribe` and `POST /events/...` both answer 404, one that does not opt in gets
neither, and a scheduler's lifecycle hooks run exactly once per lifespan (#43).

Seven unit tests on `build()` cover the publish/consume split: no client without the opt-in, the
opt-in creating a client but no eventing component and no `EventProcessingService`, the string form
an environment variable delivers, and three rejections -- no transport, `"sessions"`, and a
non-boolean value -- plus the regression that a consuming application still publishes without the
key.

### P5 -- the event-mode crontab is validated, and the manifest generator was tried and dropped (`662f7b5`)

Event mode has no publisher yet: the schedule is declared in agent code and something outside the
process has to fire it. A `CronJob` renderer was written for that, reviewed, and then **removed
before it was ever committed** -- the image and entrypoint model is about to change what a manifest
even belongs to (see *Open points*), and an unused module in the framework would only mislead the
next reader. What survives is the one part that was not specific to generating manifests, plus a
record of what the attempt established.

**`validate_crontab` stays, in `scheduler.py`, called from `wire()`.** In `"in_process"` mode
`CronTrigger.from_crontab` parses the expression, so a typo fails the pod. In `"event"` mode
nothing parsed it at all -- the tick arrives from outside -- so a bad expression surfaced as a
scheduler that reported itself healthy and never ticked:

```python
if not croniter.is_valid(expression):
    raise ValueError(f"The declared crontab '{crontab}' is not a valid cron expression.")

fields = expression.split()
if len(fields) != 5:
    raise ValueError(
        f"The declared crontab '{crontab}' has {len(fields)} fields. An external scheduler reads the five standard "
        "ones (minute hour day-of-month month day-of-week); seconds and year are apscheduler extensions it will not "
        "understand."
    )
```

`croniter` rather than apscheduler's parser, because the consumer is an external cron reading the
five standard fields and apscheduler accepts extensions -- a leading seconds field among them --
that no cron implementation does. That six-field form is rejected explicitly, since it is the
mistake an author familiar with apscheduler would actually make.

**What the removed renderer established**, kept here because each of these is a trap that will have
to be avoided again wherever the generation ends up living:

- **A Dapr publisher has to shut its own sidecar down.** The injected sidecar never exits, so the
  Job stays `Running` -- and with `concurrencyPolicy: Forbid`, which the spec requires, every later
  tick is then suppressed. A nightly job would fire exactly once and afterwards look like a broken
  scheduler. `POST /v1.0/shutdown` after the publish is what lets the Job complete.
- **The tick's CloudEvent `id` must vary per run, and the shell quoting is where that breaks.** A
  fixed id makes every tick after the first a duplicate once `idempotency_enabled` is on, so the
  scheduler runs once and never again. Writing `$TICK_ID` inside a single-quoted JSON body -- the
  obvious way to write it -- publishes the literal characters, because a single-quoted shell string
  expands nothing. The quote has to be closed, the variable inserted double-quoted, and the quote
  reopened. String assertions did not catch this; executing the generated script did.
- **The tick needs a `source`.** The dedup key is `(id, source)` and an event missing either is
  dispatched untracked (sec. 7.4).
- **`time` is better left out.** The CloudEvent model defaults it correctly; a shell-formatted
  timestamp can fail its ISO-8601-with-timezone validator.
- **A NATS URL can carry credentials, and a manifest is a repository file.** `nats://user:pass@host`
  in `settings.toml` would be committed verbatim by any generator that inlines the configured URL.
  It has to be detected and replaced with a secret reference.
- **Derived Kubernetes names must fail rather than truncate.** 63 characters minus the job and pod
  suffixes leaves 52; truncating lets two schedulers differing only past the cut collapse into one
  object, where the second silently overwrites the first.

### P5 -- `"in_process"` fires once across replicas, and the cache gains a claim primitive (`662f7b5`)

`"in_process"` mode was still #73 exactly as reported: an `AsyncIOScheduler` per replica, so three
replicas fired every cron job three times. Event mode was fixed by the queue group; this is the
other half, and it is the last thing that stood between the feature and the acceptance criterion
*cron fires once across three replicas in **both** `scheduler_mode` values*.

**`CacheService.claim` -- set-if-absent, and the reason it had to exist.** P4's dedup and this
tick guard both use the cache to decide *which one of several processes does a piece of work*, and
`exists` followed by `set` cannot do that: two callers racing on one key both pass the check before
either write lands, and both believe they hold it. P4 recorded that as an open point ("a
compare-and-set primitive on `CacheService` (Redis `SET NX`) would close most of it and is not
written yet"). It is written now, as a new abstract method with an implementation per backend.

Redis is the easy half -- one server-side operation, and expiry is the server's job:

```python
stored = self._client.set(full_key, json.dumps(value), nx=True, ex=effective_ttl)
return bool(stored)
```

The disk backend needed a measurement first. `diskcache_rs.Cache.add` is set-if-absent and atomic
across processes sharing the directory, because the cache is opened with file locking. But its
`expire` argument is **not honoured**: an entry added with `expire=1` was still readable minutes
later. That is presumably why `DiskCacheService` already keeps TTLs in a parallel metadata entry,
and it is what shapes the implementation:

```python
if not self._cache.add(namespaced_key, value):
    if not self._logically_expired(ttl_key):
        return False
    self._cache.set(namespaced_key, value)

if effective_ttl is not None:
    self._cache.set(ttl_key, str(time.time() + effective_ttl))
```

Had the backend's own expiry been trusted, a claim would never have expired and the scheduler would
have ticked exactly once and then never again -- the same shape of failure as a fixed CloudEvent id
under dedup. The stale branch is the one non-atomic path: `add` refuses a key whose *logical* TTL
has passed because physically it is still there, and taking it over is a read then a write. It is
only reached by a caller that reuses a key beyond its TTL, which the scheduler never does -- see
the key choice below. Both implementations fail **open** on an unreachable cache, matching every
other operation on the service: a cache that cannot answer must not stop the caller from working.

**The scheduler claims the slot, not a lease.** The timer now runs a wrapper rather than `tick`:

```python
async def _claimed_tick(self) -> None:
    if not self._claim_tick_slot():
        logger.debug("Scheduler '%s' did not win this tick; another replica is running it", self.name)
        return
    await self.tick()

def _claim_tick_slot(self) -> bool:
    if not self.registry.has_cache():
        return True
    slot = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
    return self.registry.cache_service.claim(
        {"scheduler": self.name, "slot": slot},
        {"claimed_at": time.time()},
        namespace=TICK_CACHE_NAMESPACE,
        ttl=TICK_CLAIM_TTL_SECONDS,
    )
```

`add_job(self._claimed_tick, ...)` replaces `add_job(self.tick, ...)`, so nothing else about the
timer changes.

**Why a slot claim instead of the leader lease the spec asked for.** This is a deliberate
departure, argued because it *removes* the question rather than answering it. Spec sec. 13 asked
whether that mode needs true failover -- a dead leader taken over within a bound -- or whether "one
designated instance runs it, others no-op" is enough, and noted that the cheap ordinal answer does
not work under a Deployment. With a per-tick claim there is no leader:

- Nothing is held, so there is **no renewal task** to schedule -- and therefore no framework-created
  background task to leak, which C7 exists to prevent -- and no lease left behind by a replica that
  dies holding one.
- There is **no takeover bound to specify**, because the next slot is claimed from scratch by
  whoever is alive. The failover question dissolves; the spec's open item is deleted rather than
  answered.

**The key is the slot, and that is what keeps set-if-absent sufficient.** `(scheduler, minute)`,
not `scheduler`. Cron granularity is one minute, so every replica firing for the same scheduled
time derives the same key and the next scheduled time derives a different one. Keying on the
scheduler alone would need a compare-*and-swap* on every tick after the first -- read the stored
slot, decide it is stale, write yours -- which is the racy path all over again. With a fresh key
per slot, the atomic `add` path is the normal path and the stale branch is never taken.

The consequence, stated because it is real: replicas whose clocks differ enough to straddle a
minute boundary derive different slots and both tick. Container clock skew is milliseconds, and
sec. 7.4 covers a repeated tick as it covers every other repeat.

**No cache means the mode behaves as it did before, loudly.** There is nothing to claim with, so
`_claim_tick_slot` returns `True` and every replica ticks. That is deliberate -- `"in_process"`
exists for local development, and demanding `.with_cache()` there would be gratuitous -- so
`on_startup` warns once, at startup, rather than per tick:

```
Scheduler 'x' started an in-process timer with crontab '...' and NO cache is registered, so its
ticks cannot be coordinated: every replica of this process will run every tick. Add '.with_cache()'
to the AppBuilder chain, or use 'scheduler_mode = "event"' where an orchestrator schedules the tick.
```

Event mode does **not** claim. The queue group already delivers a published tick to one replica, so
a claim there would be a second mechanism doing the same job; a test pins that the event path
touches the cache not at all.

**Spec amended** (sec. 7.5): the modes table and the coordination paragraph now describe a per-tick
claim, the set-if-absent requirement and the slot-derived key are normative, the no-cache warning
is required, and the sec. 13 failover question is deleted. Three acceptance criteria were added --
the three-replica case for both modes, `claim` being set-if-absent on both backends, and the
no-cache warning.

Tests: the tick claim (winner ticks, loser does not, the key carries scheduler and minute, the
namespace and TTL are passed, **three replicas sharing a real `DiskCacheService` run one tick
between them**, a later slot is claimable again, no cache means every replica ticks, startup warns,
the timer is wired to the wrapper, and event mode claims nothing); and `claim` on both backends
(first wins, second refused, the loser does not overwrite, exactly one of five concurrent callers
wins, TTL behaviour, namespace isolation, stale takeover on disk, and failing open).

### Deployment guide corrected (`2d80b63`)

The guide recommended `replicaCount: 2`, an HPA, and `--set replicaCount=3` as ordinary scaling. It
now opens with a warning naming the three defects that make multi-replica incorrect rather than
merely inefficient, its examples default to one replica, and the HPA section says to leave
autoscaling off for now. Also dropped the spec's ADR-derived `Status: draft` row, since `draft`
belongs to ADR vocabulary while this repo uses Status as a revision marker.

**Motivation.** This is the only piece of *existing, shipped* documentation that could cause harm
before any code changes: following it doubles every side effect and every inference bill, and
duplicates every cron tick.

### Working rules for this feature (`4cf2d51`, `7735251`)

`CLAUDE.md` gained two rules scoped to this feature: work in reviewable steps, one change at a time,
reported before the next begins; and explain new code, not just its arrival -- a walkthrough of the
mechanism whenever real implementation lands, with lint, typing, tests and docs exempt.

**Motivation.** The feature is delivered across many sessions and unreviewed batches are expensive
to unpick.

---

## Compatibility

**One breaking change has landed: `scheduler_mode` is required.** A project that registers a
scheduler and does not set it fails at `build()` with an error naming both values and what each
one costs. Nothing changes behaviour silently: the alternative -- defaulting the key -- would
either keep firing a timer per replica (#73) or stop ticking a service that has no broker, and
neither is safe to inherit. The reasoning, including the counter-argument, is under *P5* above; it
is a deliberate departure from spec sec. 7.5 and needs a spec amendment.

**Migrating an existing service with a scheduler** is one line, and which line depends on the
deployment:

| Situation | Set |
|---|---|
| No `event_bus`, or plain Docker, or local development | `scheduler_mode = "in_process"` |
| Kubernetes with `event_bus = "dapr"` / `"nats"`, more than one replica | `scheduler_mode = "event"`, plus a `CronJob` publishing to `<app_name>.scheduler.<scheduler_name>` |

`"in_process"` reproduces today's behaviour exactly, including its once-per-replica firing -- it is
the no-op migration. `"event"` is the one that fixes #73, and until P5's second half generates the
`CronJob` the publisher has to be written by hand, which is why the second row is not yet the
recommended answer for anyone.

Everything else remains non-breaking. Specifically:

- `ClientBase.subscribe`'s abstract signature changed from `(topic, callback)` to
  `(topic_callbacks)` in P0. This is the one signature change in the feature so far; it affects
  implementations of the transport-client interface, of which the repo contains two (`NATSClient`,
  `DaprClient`), both updated. It must not change again -- a third-party transport would break.
- `EventHandlingBase.subscribe` (abstract) and `POST /nats/subscribe/{topic}` were removed. The
  removed endpoint triggered subscription over HTTP, which the managed lifecycle makes meaningless.
- `DaprEventing.subscribe`'s signature changed, but no working caller can exist: the old signature
  answered 422 to the only intended caller. Overrides are unaffected, because `_wire_routes`
  registers `getattr(self, name)` walking the MRO subclass-first, so an override's own signature is
  what FastAPI sees.
- The Dapr subscription document is empty for every project **in this repository**, since
  `get_subscribed_topics()` is overridden nowhere here. That is not a guarantee about downstream
  projects: the method is a documented override point (`event_handler_base.py:164`, with an example
  in its docstring), so a consumer project may well override it. For such a project the discovery fix
  changes Dapr behaviour by design -- declared topics went from subscribing to nothing to
  subscribing -- and if it *also* declares the same topics as Kubernetes `Subscription` resources,
  the sidecar now holds a declarative and a programmatic subscription for one topic.
  `dapr_declarative_subscriptions = true` exists for exactly that case, but it defaults to `false`.
  Whether Dapr merges the two or delivers twice needs checking against a real sidecar; it belongs on
  the broker-test list.
- New config keys all default to current behaviour.
- **`EventHandlingBase._process_cloud_event` takes a third argument, `topic`.** A protected method,
  so this affects only a third-party transport implementation that called it -- of which the repo
  contains two, both updated.
- **`POST /events/{topic}` answers `200 {"status": "DROP"}` instead of `422` for a body that is not
  a CloudEvent -- but only on `DaprEventing`.** Chosen so the two transports dispose of an
  unparseable payload identically; NATS already terminated it. A caller that treated 422 from this
  path as its error signal sees a 200 instead. The same path on `NatsEventing` is unchanged and
  still answers 422, since there the caller is a REST client rather than a sidecar.
- `nats_queue_group` is new and defaults to `app_name`, so no deployment has to set it. It does
  change broker-side behaviour for anyone already running more than one replica on Core NATS:
  duplicate processing stops, which is the point. A deployment whose correctness depended on every
  replica seeing every message would be affected, but that shape cannot be built on this framework
  today -- there is no way to opt a subscription out of the queue group.
- **`app_name` values containing whitespace are now rejected at startup.** `nats-py` raises
  `BadSubjectError` for a queue name containing a space, so an `app_name` like `"My Agent Service"`
  -- legal, and working, before subscriptions carried a queue group -- would have failed inside the
  background retry task and retried forever behind a red readiness probe. `_resolve_queue_group`
  checks for whitespace and raises at startup naming the key and the value, so the cause is visible.
  Affected projects set `nats_queue_group` to a whitespace-free name. This is the one case where a
  single-replica deployment that worked before does not start after the upgrade.
- **Single-replica Core NATS behaviour is otherwise unchanged**: a group of one receives everything,
  exactly as an ungrouped subscription did. The exception is an agent subscribing to overlapping
  subjects (a wildcard plus a literal it covers), where the count of dispatches per message may drop
  from two to one -- see the broker-test open point.
- **Dapr is untouched by P1.** The queue group is a NATS concept; `DaprClient` has no equivalent, and
  no Dapr code path reads the new key. Delivery under Dapr is unchanged by this change.
- **Dapr is untouched by P3 as well.** Consumer tuning, deliver groups and dead-lettering are
  JetStream concepts; under Dapr the sidecar owns retries and its own dead-letter topic, configured
  on the Dapr component rather than here. No Dapr code path reads the new keys.
- **Core NATS is untouched by P3.** The new keys are read only when `nats_use_jetstream = true`, and
  `_settle` still returns immediately on Core NATS, where there is nothing to acknowledge.
- **A JetStream deployment that already has a durable consumer keeps it, unchanged.** The client
  binds to what the broker has and logs the difference. Until that consumer is deleted, the new
  `ack_wait`, `max_ack_pending`, `max_deliver` and -- importantly -- the deliver group are not in
  force, so such a deployment is still single-subscriber. This is deliberate: recreating a durable
  replays or gaps.
- **The JetStream stream may gain subjects on startup.** An existing stream is widened to cover each
  subscribed subject and the dead-letter subject. Widening is additive and never removes a subject,
  but it is a write against a resource an operator may consider theirs. A stream the application
  cannot update is reported as an error naming the missing subjects, and the consumer bind then
  fails visibly rather than silently consuming nothing.
- **`nats_durable_name` set together with more than one subscribed topic now fails at startup.** It
  could not have worked: a durable filters one subject, so the second consumer would have been
  rejected by the broker. The error names both topics.
- **Durable names change for dotted topics** -- `orders.created` now yields `orders_created-durable`
  rather than the illegal `orders.created-durable`. No migration is possible or needed, because a
  consumer under the old name could never have been created.
- **JetStream now publishes to a second subject.** With dead-lettering enabled, which is the default,
  the client publishes to `<queue group>.dead-letter`. A deployment whose broker permissions allow
  publishing only to specific subjects has to grant that one, or set `nats_dead_letter_subject = ""`.

- **P4 changes nothing for a project that does not opt in.** `idempotency_enabled` defaults to
  `false`, and with it off `_claim` returns immediately and the cache is never touched. The handler
  loop itself is unchanged -- it moved from `process` into `_dispatch` verbatim.
- **`EventProcessingService.on_startup` and `on_shutdown` are no longer no-ops.** They delegate to
  the handler chain's hooks. A subclass overriding either without calling `super()` now skips the
  chain's startup, and with dedup enabled would run with an unresolved policy -- which `process`
  then resolves on first use, so it degrades to a late error rather than a silent one.
- **Enabling dedup without `idempotency_ttl`, or without a cache, fails at startup.** Both are
  deliberate: the first is the decision the spec requires the author to make, and the second would
  otherwise disable dedup silently at the moment it was switched on.
- **`blueprint.events.duplicate` is a new counter.** `blueprint.events.unhandled` no longer counts a
  deduplicated event, but it could not have: nothing could be deduplicated before this change.
- **The `idempotency` cache namespace is new.** It shares the registered cache with application
  data but not its namespace, so nothing an application stores can collide with a marker. A
  deployment sizing its cache should account for one small entry per event within the TTL window.

- **A spaced `app_name` no longer breaks an event-mode scheduler.** Whitespace in a *derived* tick
  topic is rewritten to `_`, so `app_name = "Health Monitor"` yields
  `Health_Monitor.scheduler.<name>`. An explicitly passed `topic=` is not rewritten and still
  fails on whitespace, and a wildcard fails in either form.
- **P5 adds a subscription and a publish permission an event-mode scheduler needs.** The scheduler
  subscribes to `<app_name>.scheduler.<scheduler_name>`, and whatever publishes its tick has to be
  allowed to publish there. Under JetStream that subject also has to be covered by the stream, which
  the client widens on startup.
- **A registered scheduler now makes the application create a transport, in event mode only.** The
  scheduler contributes a tick handler, and `build()` creates `NATSClient`/`DaprClient` and the
  eventing endpoint when any handler is registered. A project that had a scheduler and no handlers
  previously started no transport at all; in event mode it now requires `event_bus`, enforced by
  `_require_event_transport` rather than left to the generic "no valid event_bus configured"
  warning. In `"in_process"` mode nothing is contributed and no transport is created.
- **`POST /api/{scheduler_name}/trigger` starts working.** It was added to the router during startup,
  after `include_router` had already copied it, so it was never served. Anything relying on it
  answering 404 sees a behaviour change.
- **A subclass overriding `on_startup` without calling `super()` was already broken and still is.**
  The base method is what starts the timer, wires the tick handler and registers the trigger route.
  The scaffold and the generated docs no longer show an override without the `super()` call.
- **`SchedulerBase.__init__` gained a keyword-only `topic` parameter.** Positional callers are
  unaffected; `crontab` is still the first positional argument.
- **A scheduler's `on_startup` and `on_shutdown` now run once per lifespan instead of twice.** A
  subclass that relied on the second call -- for instance by counting on an idempotent resolve
  happening twice -- changes behaviour. Every scheduler in this repository and in the scaffold is
  unaffected. The visible effect is the opposite of a regression: an in-process scheduler now runs
  one timer where it used to run two.
- **`event_publishing_enabled` is new and defaults to off**, so no existing application creates a
  client it did not create before. A consuming application is unaffected: its handler already
  implies the client, and `EventPublishingService` is still keyed on the client existing rather
  than on the new key. Setting it with no `event_bus`, or with `event_bus = "sessions"`, fails at
  startup rather than at the first publish.
- **`parse_bool` is new in `blueprint.agents.utils`** and is exported from that package. Nothing
  was removed: `HandlerChain._read_bool` keeps its signature and behaviour.
- **`CacheService` gained an abstract method, `claim`.** Both bundled backends implement it. A
  third-party subclass of `CacheService` outside this repository will not instantiate until it
  does too -- the one signature change in this step, and it is additive to the interface rather
  than a change to an existing method.
- **An `"in_process"` scheduler now consults the cache on every tick.** With a cache registered
  the tick fires once per scheduled slot across all replicas instead of once per replica, which is
  the fix; a deployment that was (knowingly or not) relying on N replicas each doing the work will
  see it done once. With no cache registered nothing changes except a startup warning.
- **An event-mode scheduler's crontab is now validated at startup.** A project whose declared
  expression is not a five-field cron -- including an apscheduler six-field form with seconds --
  fails `build()` where it previously started and waited for a tick. In `"in_process"` mode nothing
  changes: `CronTrigger.from_crontab` already rejected the same expressions.
- **`blueprint.agents.io.api.scheduling` exports exactly what it did before**, plus
  `SchedulerTickHandler` and the three `SCHEDULER_MODE*` names. `validate_crontab` is importable
  from `...scheduling.scheduler` but is not part of the package's public surface.

The spec's one deliberate future break is `with_cache`'s `name` parameter (sec. 10.1), which must
stay keyword-only and last, or an existing `with_cache(False)` would silently become a cache named
`False`.

---

## Open points

- **P0-P5 have landed. P6 is next**, and two requirements for it were settled during P5 (see the
  namespace bullet below). What remains open from P5 is deferred work rather than unfinished work:
  both modes now fire a cron once across three replicas, which was P5's acceptance criterion.
  Still open, in rough order of how much it matters:
  - **Manifest generation is deliberately deferred** (decided 2026-09-04), and the renderer
    written for it was removed rather than left unused. Two constraints settled the shape of the
    missing caller and then removed the ground it would stand on:
    - **Nothing may import a project's `src/main.py`.** Stated as an absolute rule. The
      declaration is readable without it -- configure `Config` from the project's
      `settings.toml`, import the leaf modules under `src/schedulers/`, instantiate each
      `SchedulerBase` subclass and read its `crontab`, `scheduler_mode` and `tick_topic` --
      verified against
      `examples/health_monitor`. What that cannot see is a `with_scheduler(Klass, name=...)`
      rename, which changes both the tick topic and the object name, and a scheduler whose
      `__init__` takes arguments passed at registration.
    - **The image and entrypoint model is about to change underneath it.** Phase work turns
      `main.py` into a pure `AgentRegistration` declaration with no `build()` call and the
      Dockerfile's command into `python -m blueprint.agents.entrypoint`, with one image for the
      platform and the group injected at container start. Manifests then belong to a *group*,
      not to a project, and the agent-to-schedule map falls out of the in-image agent map the
      entrypoint already has to construct. A per-project CLI written now would target a project
      shape that is being replaced.

    The design decisions to carry forward when it resumes: **generate at scaffolding time**,
    where the tool authored the registrations itself and therefore knows them; **a developer who
    then edits the registration by hand owns the drift**; and **fail loudly** on anything the
    generator cannot see rather than emitting a manifest that publishes to a subject nobody
    subscribes to. The six traps the removed renderer surfaced are listed in the *P5* section
    above, so they do not have to be rediscovered.
  - **Timezone is not reconciled between the two modes.** Spec sec. 7.5 requires them not to
    diverge. `"in_process"` uses apscheduler's timezone handling for the declared crontab; whatever
    ends up publishing the tick in `"event"` mode will have its own. A scheduler tested locally in
    one zone and deployed in another fires at a different hour, and nothing would notice. Dormant
    while manifest generation is parked, since there is no second timezone to disagree with yet.
  - **The tick claim is verified against a real cache but not a real cluster.** Three replicas
    are simulated in one process against one `DiskCacheService` directory, which exercises the
    set-if-absent path but not file locking across genuinely separate processes, nor Redis under
    contention. Both belong on the broker/integration list below.
  - **`asbs validate` says nothing about schedulers.** A project in `"event"` mode with no
    generated `CronJob` is the remaining silent-failure case -- the missing `event_bus` and the
    missing mode both fail at startup now, but a mode and a transport with nothing publishing
    does not. Validate is where it should be caught.
- **Two requirements this raised for later phases, now written into the spec.**
  `scheduler_mode` **must** resolve per namespace through C5 rather than once per process, or a
  group cannot host a pure-scheduler agent on `"in_process"` next to an event-driven agent on
  `"event"` -- which is precisely the deployment freedom grouping exists to provide. Today
  `Config` is scope-aware only when `agent_scope` is set on the single shared instance, so every
  scheduler in a process shares one mode. And P6 **must not** create a client for a namespace that
  neither subscribes nor publishes: sec. 6 argues connection count is cheap and refuses a knob,
  which is right per namespace that uses a connection and wrong for one that does not. Both are
  recorded in spec sec. 7.5 and sec. 6 with acceptance criteria; neither is implemented.
- **Exclusivity between scheduling and event consumption is not enforced, and deliberately so.**
  `scheduler_mode = "in_process"` with no handlers already produces a process that subscribes to
  nothing and opens no connection, and publish-only produces one that subscribes to nothing while
  still emitting -- so the shapes are expressible without a new switch. A third key would only
  overlap `event_bus` and `scheduler_mode` and create a contradiction to resolve. What is *not*
  covered is making it observable: spec sec. 9.2 already requires the startup log to carry each
  namespace's queue group and durable names, and extending that to "namespace X consumes: nothing"
  is what would let a regrouping be checked by diffing logs. If a hard guarantee is wanted later,
  the right form is an opt-in per-namespace declaration validated at build time, not an execution
  mode.
- **The tick subject is provisional.** `<identity>.scheduler.<scheduler_name>` is a choice this
  change had to make, and the subject taxonomy is explicitly unratified (spec sec. 13: who owns
  `<domain>.<entity>.<action>`, and how a subject is added). Changing it later moves a subscription,
  which under JetStream means a durable's filter changes -- a migration, not a config change
  (sec. 7.7). The `topic=` override exists so an agent can opt out of the guess, but the default is
  what the generated `CronJob` will encode.
- **Nothing observes a tick.** A tick is counted as an ordinary event, so a `CronJob` that stopped
  publishing looks like silence, not a fault: no metric says "this scheduler has not ticked within
  two intervals". The declared crontab is in the process and the last tick is knowable, so this is
  cheap, and it belongs with the telemetry work in phase 9. Until it exists, event mode trades a
  duplicated tick for a possibly missing one, and only the second failure is invisible.
- **There is no generated README**, so the third surfacing channel spec sec. 7.4 asks for has
  nowhere to go. `asbs setup` writes a Dockerfile, settings, secrets and source, and the
  generated `CLAUDE.md` and `settings.toml` carry the idempotency note instead. If a README is
  ever generated, the note belongs in it too.
- **Dedup is best-effort and unverified against a real broker.** `exists` then `set` is not
  atomic on either cache backend, so two replicas handed the same event simultaneously can both
  dispatch, and a cache error fails open. Whether that window is ever hit in practice depends on
  how the broker distributes a redelivery, which belongs on the broker-test list below. A
  compare-and-set primitive on `CacheService` (Redis `SET NX`) would close most of it and is not
  written yet.
- **Nothing bounds the dedup cache, and the same now applies to tick claims.** Every dispatched
  event writes one entry for `idempotency_ttl` seconds, and every scheduler tick writes one for
  `TICK_CLAIM_TTL_SECONDS`. On Redis both expire server-side. On disk they expire *logically* --
  `exists` and `get` honour the TTL metadata -- but the bytes are reclaimed only when the entry is
  read again, and a slot key is never read again. One small entry per tick is negligible next to a
  per-event marker, but it is unbounded on the same terms. Every dispatched event writes one entry
  for `idempotency_ttl` `DiskCacheService` expires lazily -- an entry is removed when it is next read, so
  markers nobody asks about again stay on disk. A long TTL on a high-volume topic grows the cache
  directory without limit, and no metric reports its size.
- **The dedup TTL question in spec sec. 13 is not answered, it is delegated.** Requiring the key
  puts the number in the deployment that knows its own redelivery window; it does not tell that
  deployment what the number is. Guidance -- worked from `nats_ack_wait * nats_max_deliver` --
  belongs in the deployment guide and is not written.
- **The dead-letter subject has no consumer.** Messages accumulate on it and are subject to the
  stream's retention, so a deployment that never reads it will silently lose dead letters when the
  stream ages them out. Draining it is an operational task the framework does not do, and no
  guidance for it is written yet.
- **Nothing observes dead-lettering.** It is logged, but there is no counter, so "how many messages
  did we give up on today" cannot be answered from metrics. It belongs with the telemetry work in
  phase 9, next to `blueprint.events.unhandled`.
- **Local NATS and Dapr integration environment.** Everything above is covered by unit tests with
  mocked transports. Once the feature is implemented, stand both brokers up locally (compose file
  plus a CI job) and cover the behaviour that only a real broker exhibits: queue-group distribution
  across replicas, ack/nak/term and redelivery after `ack_wait`, JetStream durable survival across
  reconnect, the shutdown drain acknowledging in-flight work, `filter_subjects` behaviour on a
  durable that already exists, and the Dapr sidecar actually fetching the discovery document and
  delivering to `/events/{topic}`. Depends on the unit/integration split in #80 being settled first,
  since `tests/integration/` is currently not run by CI at all. P3 adds several items that only a
  real broker can settle: whether `subscribe_bind` against a shared durable actually distributes
  across replicas, whether widening a live stream's subjects behaves as expected, what the server
  does with an `add_consumer` whose config differs from an existing durable, and whether the
  delivery count read from `msg.metadata.num_delivered` lines up with `max_deliver` the way the
  dead-letter trigger assumes. Add to that list: **what a queue
  group does when one agent's subjects overlap** -- a wildcard plus a literal it covers, both in the
  same group, both matching one message. `nats-server` is expected to merge subscriptions by queue
  name across matching nodes and deliver once (to either callback, non-deterministically), which
  would also end the double dispatch such a pair caused before P1. If it does not merge, the agent
  receives the event twice and P2 acks both copies as ordinary work, so the answer changes what P2
  has to handle. P5's in-process claim adds two that no unit test reaches: whether
  `diskcache-rs` file locking actually makes `add` atomic across separate processes sharing a
  volume, and whether Redis `SET NX` holds up under real contention from several replicas firing in
  the same instant. P5 adds two more: whether a `CronJob` publishing to the scheduler's
  subject is in fact delivered to exactly one replica through the queue group, and what a
  `CronJob` restart or a missed `startingDeadlineSeconds` actually produces -- both modes are
  at-least-once, so the answer decides whether an event-mode scheduler needs `idempotency_enabled`
  on by default in the generated settings.
- **The two design questions in spec sec. 13** that change the shape rather than the parameters: 20
  or 100 agents, and whether the 4 GB host budget is real.
- **#80** -- the failing example tests and the unenforced test split.
