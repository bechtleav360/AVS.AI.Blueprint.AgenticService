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
namespace owns its own handlers, agent runtime, REST routes, AI client, thread pool, caches and
broker connection, while genuinely shared infrastructure -- the port and the health endpoint --
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

- **P6 review follow-up -- namespace identity**: one definition of the root namespace, one
  alphabet validated where a namespace enters the framework, an unambiguous durable name and
  unforgeable connection-name placeholders (`be5e489`)
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
- **P6 -- the transport client belongs to a namespace, not to the process**: clients take a
  namespace, register under a namespace-qualified name so two can coexist in one registry, and
  derive queue group and durable from the namespace alone -- without that, two co-hosted agents
  subscribing to one topic would share a queue group and each see half its events
- **P6 -- connections are no longer anonymous**: `nats.connect()` is called with
  `name=f"{namespace}.{group}.{pod}"`, which makes a pod's contents legible in `/connz`. The name
  carries the pod, so nothing broker-side may derive from it (C1) -- asserted by test
- **P6 -- `EventPublishingService` publishes on its own namespace's client**, resolved namespace
  first then root, raising rather than guessing when that is ambiguous

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
phases 0-10). `CLAUDE.md` keeps pointers plus the list of paths that require reading the spec first.

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

### P6 -- one transport connection per namespace, and named connections (`be5e489`)

The transport client stops being a process singleton and becomes namespace-owned. Nothing
creates a second one yet -- Phases 5 and 6 do that -- so for every application that exists
today this is a no-op with one visible change: connections are no longer anonymous.

**`IOClientBase` takes a namespace, and derives the registry name from it.**
`IOClientBase.__init__(namespace="")` stores the namespace, exposes it as a public
`namespace` property, and registers the component as `qualified_component_name(namespace,
camel_to_snake(cls.__name__))` -- `nats_client` at the root, `orders_nats_client` under a
namespace. That last part is what makes the topology possible at all: `Registry.add_component`
raises on a duplicate name, so before this a second transport client of the same class raised
at construction. `NATSClient` and `DaprClient` both forward the parameter.

Naming had to move *into* the constructor to work. `Component.__init__` registers the instance,
so the pre-existing pattern of renaming afterwards (`AIClientBase` still does it) cannot help:
the collision happens during `super().__init__()`, before any rename could run. `Component`
therefore gained a `name: str | None = None` parameter that overrides the class-derived name,
forwarded through `ClientBase` and `ServiceBase`. Both default to the old behaviour.

**Connections are named `f"{namespace}.{group}.{pod}"`.** `nats.connect()` was called with no
`name=`, so every connection this framework opened was anonymous in `/connz` and a pod hosting
several agents was unreadable from the broker side. `_resolve_connection_name()` fills the three
positions from the namespace, `BLUEPRINT_GROUP` and `POD_NAME`/`HOSTNAME`/`socket.gethostname()`,
and `connect()` passes the result and records it on a public `connection_name` property.

The group and pod are read from `os.environ` rather than through `Config`, because group
composition decides which agents get a `Config` at all (spec sec. 5.1) -- the group loader that
will own the variable arrives with the group configuration in Phase 8. Absent segments get a
placeholder (`root`, `ungrouped`, `unknown-pod`) rather than being left empty, so a name cannot
degenerate into `..pod-7` and "no group" stays distinguishable from a group whose name is empty.
The spec was amended to state that rule.

**Consumer identity follows the namespace, which is the part that had to land with the
ownership change rather than after it.** Once two clients can share a process, the queue group
and the durable name can no longer come from process-wide config:

- `_resolve_queue_group()` returns the namespace when there is one. Only the root namespace still
  falls back to `nats_queue_group` then `app_name` -- which is what `nats_queue_group` is
  documented to be, "the queue group for the root namespace only". Without the branch, every
  client in a process resolves the same `app_name`, and two co-hosted agents subscribing to one
  topic form a single queue group: the broker then hands each event to exactly one of the two
  agents, so each silently sees about half of what it subscribed to.
- `_durable_for()` prefixes the namespace, so `orders` on `orders.created` binds
  `orders-orders_created-durable`. Same failure otherwise, one layer down: two namespaces
  resolving one durable name bind to the same JetStream consumer and consume each other's
  events. The whole name is still sanitised, so a dotted namespace stays a legal consumer name.
- A configured `nats_durable_name` under a namespace now warns, naming the consequence. It is
  legitimate when the key is scoped per namespace, and fatal when it is not, and the framework
  cannot yet tell which -- config scoping (C5) is Phase 1.

The durable prefix is Phase 5's item in the plan, taken early deliberately: P6 is what makes
co-hosted clients possible, so shipping it without namespace-qualified durables would ship a
latent cross-agent collision. It is dormant until a namespace exists -- the root namespace keeps
`<topic>-durable` -- so no deployment of this change is a consumer migration. Phase 5's own
migration note still applies to the filter-set work.

**Deployment identity must never reach broker identity (C1).** The connection name contains the
pod, so a queue group or durable derived from it would change on every restart and every
regrouping. It is deliberately not stored where either is resolved, and a test asserts that a
junk `BLUEPRINT_GROUP` and `POD_NAME` leave both untouched.

**`EventPublishingService` becomes per-namespace.** It takes a `namespace`, registers under the
qualified name, and `on_startup` resolves *its own* namespace's client instead of asking the
registry for "the" `IOClientBase`. Publishing another namespace's events down a shared
connection would make outbound traffic unattributable, which is the whole of reason 3.

Resolution is the spec's rule -- own namespace, then root, raising rather than guessing -- and
lives in the new `component/namespace.py` alongside the naming helper, because the registry has
no namespace dimension yet (Phase 1) and both operations recur wherever a component becomes
namespace-owned. `resolve_for_namespace` raises on ambiguity instead of taking the first match:
picking one of two silently attaches an agent to another agent's transport. A namespace with no
client of its own falls back to the root one, so a namespaced agent in a process with a single
shared transport keeps working.

**What P6 does not do, on purpose.** `DaprClient` accepts a namespace for health attribution and
C4, and its docstring says plainly that it confines neither ack loss nor slow-consumer
disconnects: it holds no broker connection, the sidecar owns and multiplexes one per pod, and
there is correspondingly nothing to name. Nothing in `app_builder.py` changed -- it still creates
one root-namespace client, which is exactly what a single-agent application should get, and the
rule that a namespace which neither subscribes nor publishes gets no client is already the
process-level behaviour there. `NatsEventing` still resolves the client by type; Phase 5 owns that
call site and reworks it per namespace.

**Tests.** 50 new unit tests: namespace naming and resolution (`test_namespace.py`), client
ownership and coexistence, queue-group and durable derivation including the two-namespaces-on-one-topic
cases, the connection-name shape and every fallback in it, the C1 assertion that deployment identity
reaches neither, the Dapr namespace parameter, and the publishing service's resolution and its four
failure modes. Two existing publishing-service tests were updated: client resolution moved from
`get_component(IOClientBase)` to `get_io_clients()` plus the namespace filter.

**Documentation.** `configuration-keys.md` gains a *Deployment Identity (environment only)*
section for `BLUEPRINT_GROUP`, `POD_NAME` and `HOSTNAME`, and the `nats_queue_group` and
`nats_durable_name` rows now say what a namespace does to them. Spec sec. 6 gains the placeholder
rule.

### P6 review follow-up -- the namespace gets one definition, one alphabet, one gate (`be5e489`)

Four defects found reviewing P6, all of which turned out to be the same defect: nothing said what
a namespace is allowed to look like, so each consumer of it decided separately. `component/namespace.py`
is now the single answer, and the four symptoms fall out of it.

**One definition of the root namespace.** `ROOT_NAMESPACE` was declared three times -- in
`component/namespace.py`, as a class attribute on `EventHandlingBase` (`event_handling_base.py:48`)
and at module level in `scheduler.py:66`, the last two predating P6. Both now import the one in
`namespace.py`; the metric labels in `handle_event` read the imported constant instead of
`self.ROOT_NAMESPACE`. The constant's docstring now also says why it is not configurable: three
call sites branch on it being falsy, so a root namespace with a value renames every registry key
and every broker-side consumer, which is what C1 exists to prevent.

**One alphabet, enforced at the point of entry.** New `validate_namespace()`: a namespace is `""`
or matches `[a-z][a-z0-9_]*`, and is rejected rather than repaired. It is called from
`IOClientBase.__init__` and `EventPublishingService.__init__`, replacing the `.strip()` that used
to silently repair `"  orders  "` while `"my orders"` blew up much later. Two exclusions carry
their reason in the error message: `-`, because it separates the fields of the durable name, and
`<`/`>`, because they are what make the connection-name placeholders unforgeable.

The check it replaces was in `_resolve_queue_group()`, which is reached only by a NATS client that
subscribes -- so a publish-only namespace, or a Dapr one, kept an illegal name in its registry key,
its durable and (from C2) its telemetry resource without anything raising. Validation at
construction covers all of them, and the queue group now returns the namespace verbatim.

**The durable name became unambiguous.** Forbidding `-` in a namespace is what makes
`f"{namespace}-{topic}-durable"` readable back: the first `-` is always the namespace boundary.
Before, namespace `orders-eu` on topic `created` and namespace `orders` on topic `eu-created`
produced the same durable, so two agents would have bound one JetStream consumer and consumed each
other's events -- the exact failure the namespace prefix was added to prevent. `_durable_for` now
rewrites only the topic (`f"{prefix}{re.sub(...)}-durable"` rather than sanitising the whole
string), because the namespace was already validated against an alphabet a consumer name accepts.

**The connection-name placeholders became unforgeable.** `UNNAMED_NAMESPACE = "root"` collided with
a namespace actually called `root`, which is the ambiguity the placeholders were introduced to
remove. There is now one bracketed spelling -- `ROOT_LABEL` (`"<root>"`), reused for messages and
for the connection name -- plus `UNGROUPED_LABEL` and `UNKNOWN_POD_LABEL`. Since `<` and `>` are
outside the namespace alphabet, no namespace can spell one.

The group and the pod are not ours to validate: they arrive from a pod template, and failing a
rollout over a display string is the wrong trade. New `display_segment()` sanitises them instead --
`<`, `>`, `.` and whitespace become `_` -- so a group called `eu.west` cannot turn a three-segment
name into four (`<root>.eu_west.pod-1`), an FQDN in `HOSTNAME` stays one segment, and nothing from
the environment can forge a placeholder. Sanitising is acceptable only because C1 forbids anything
deriving from the connection name, so a mangled segment loses no information downstream.

**The gate moved from the two namespace-owned bases into `Component.__init__`, and `Component`
now owns the namespace.** `Component.__init__(should_register, name, namespace="")` validates the
namespace, then derives the registry name from it through `qualified_component_name`, and exposes a
public `namespace` property. `IOClientBase.__init__` collapsed to `super().__init__(namespace=namespace)`
-- its `_namespace` assignment, its `namespace` property and its `_base_component_name` classmethod
are all gone, and `EventPublishingService` lost the same three. `ClientBase` and `ServiceBase`
forward the parameter.

Two reasons this is not `Registry.add_component`, which was the other candidate. Coverage: eight
components construct with `should_register=False` -- `agent_runtime`, `handler_chain`,
`actuator_api`, `cache`, `root`, `telemetry`, and the `nats.py` and `dapr.py` eventing endpoints,
the last two of which become namespace-owned in phase 2 -- and a gate in the registry never sees
them. Ordering: `Component.__init__` runs before the name is derived and before registration, so
the illegal namespace never becomes a registry key even transiently. Having `Component` own the
namespace outright is what makes the gate sound: reading it back off a subclass attribute would
have left the check dependent on every subclass assigning `_namespace` before calling
`super().__init__()`.

**Names that cross the process boundary are validated, not repaired.** New
`validate_subject_segment(segment, *, source, subject)` in `io_client_base.py`, applied at three
call sites, replacing two silent rewrites and one partial check:

- `SchedulerBase.tick_topic` derived the subject as `re.sub(r"\s+", "_", f"{identity}.scheduler.{self.name}")`.
  That subject is the contract: a `CronJob`, usually in another repository, publishes to it. An
  `app_name` of `"Health Monitor"` silently became `Health_Monitor.scheduler.nightly`, so the
  manifest author -- who cannot see the rewrite -- publishes to a subject this scheduler does not
  subscribe to, the tick never arrives, and neither side logs anything. Both derived parts are now
  validated instead, and the error names the key, the value and the subject it would have produced.
  The scheduler's own name is checked too, because `with_scheduler(name=...)` reaches the subject.
- The explicit `topic=` override kept its whitespace check but had a separate wildcard check below
  it; both are now the one helper, so the two paths cannot drift apart again.
- `_resolve_queue_group()`'s root fallback checked whitespace only. A queue group is read in
  `/connz` *and* seeds the default dead-letter subject `<queue group>.dead-letter`, so an
  `app_name` of `my*service` produced a wildcard subject that the framework then publishes to.
  Now rejected with the rest.

The two rewrites that stay are named in the helper's docstring and in the spec: the topic portion
of a durable name (dots are legal in subjects, illegal in consumer names, so there is no
alternative -- bounded by the existing collision error) and the connection name (attribution only,
and C1 forbids anything deriving from it, so nothing outside can depend on its spelling).

**One defect introduced and caught during this change:** inserting the `namespace` property between
`Component.name`'s getter and its `@name.setter` silently deleted the setter, which
`with_agent(name=...)`, `with_scheduler(name=...)`, `with_rest_api(name=...)` and `AIClientBase`
all assign through. `mypy` caught it as eight errors across four files; the property now sits below
the setter.

**Tests.** 1337 unit tests pass (up from 1323). `test_namespace.py` gains `TestValidateNamespace`
and `TestDisplaySegment`, including the assertion that `ROOT_LABEL` cannot be produced by a legal
namespace. Four NATS tests changed to match the new behaviour rather than the old: whitespace and
dotted namespaces are now rejected at construction instead of trimmed or rewritten, and a
hyphenated one is rejected with the collision named. Three new connection-name tests cover the
dotted group, the forged placeholder and the FQDN host name. Five scheduler tests changed or were
added around the tick subject: the spaced `app_name` case inverted from "is rewritten" to "is
rejected", plus a wildcard identity, a spaced scheduler name, and an assertion that the error names
the key, the value and the subject. One NATS test gained the wildcard queue group; another had its
message assertion reordered.

**Documentation.** Spec sec. 6 gains the unforgeability rule and the sanitise-not-validate rule for
group and pod; C1 gains the namespace alphabet and both exclusions with their reasons.
`configuration-keys.md` gains a *Namespace names* table, a *Names that become subjects are never
rewritten for you* section and the corrected placeholder spellings. C1 also gains the
validate-never-repair rule for boundary-crossing names, the two permitted exceptions, and the
requirement that the namespace gate live in `Component.__init__`.

### `/status/env` stopped returning credentials (#91)

Found auditing configuration handling for the config rework, and **pre-existing on `main` and
`develop`** -- introduced in `4e6421b`, unrelated to this feature. Filed as #91 and fixed here
because the grouped-process work makes the same endpoint cross-agent.

`ActuatorApi._sanitize_config` masked a key only when the whole key equalled one of four words
(`api_key`, `secret`, `token`, `password`), so every compound key this framework actually uses was
returned in clear by `GET /status/env`: `openai_api_key`, `nats_password`, `azure_client_secret`,
any `*_token`. Lists were not walked either, so a list of provider entries was returned verbatim,
and a URL carrying inline credentials passed through because its key names nothing sensitive.

`_sanitize_config` now delegates per pair to `_sanitize_value`, and the rules are stated in order:

- `SECRET_KEY_MARKERS` is matched as a **substring** of the lowercased key (`key`, `secret`,
  `token`, `password`, `passwd`, `pwd`, `credential`, `auth`, `private`, `salt`). Deliberately
  over-broad -- `api_key_header` is masked although it holds nothing -- because a lost diagnostic
  line is cheaper than a published credential, and the docstring says so.
- Dicts **and lists** are walked.
- `_strip_url_userinfo` removes `user:password@` from any string that parses as a URL carrying
  userinfo, whatever its key, so `redis://admin:pw@cache:6379/0` under `redis_url` becomes
  `redis://cache:6379/0` and stays diagnostic instead of becoming `***`. It returns non-URLs
  unchanged -- unlike `_sanitize_redis_url`, which is handed a value already known to be a Redis
  URL and can safely fall back to a placeholder. The docstring records why the two differ, so they
  are not unified wrongly.
- Booleans pass through even under a matching key: a flag cannot carry a credential, and
  `auth_enabled` is what someone reads this endpoint for.

**Tests.** 17 new cases: ten compound keys as a parametrised set, secrets inside a list of dicts
and inside a list of strings, URL userinfo stripped under an innocuous key, a URL without userinfo
left alone, IPv6 brackets preserved, a boolean passing through, and a plain string containing `@`
left alone. 1354 unit tests pass.

One unrelated formatting fix rode along: the nested conditional in `llm_status` was the one hunk
`black` wanted to rewrite in this file, and `ruff-format` accepts its version, so the file is now
clean under both formatters.

### Phase 10 added to the plan -- migration and setup documentation, last

Recorded on the user's prompt so it is not rediscovered later. No code: it adds a phase to
`docs/plans/2026-08-28-multi-agent-grouping.md` after Phase 9, and moves the phase range to 0-10 in
the plan's status line, `CLAUDE.md` and this changelog's header.

**Why last rather than now.** Everything a migration guide would describe -- `AgentRegistration`,
group configuration, the entry point, the single image -- is built in phases 0, 2 and 8. Written
before them, a guide documents an API that does not exist, and a reader cannot tell which half is
aspiration. The plan already carries the migration *design* (*Migration path for an existing
agent*); what Phase 10 adds is the part a developer can read and run.

**What it covers:** a new `docs/guides/multi-agent-setup.md` (scaffolding a group; migrating a
single-agent project; the section listing what stays byte-identical and why, which is what decides
whether anyone trusts the migration; and the one decision to make before migrating, since the agent
name becomes the queue group and part of the durable); `asbs setup` / `asbs create agent` /
`asbs validate` support; and the rewrite of `docs/guides/deployment.md`, which ships today and
contradicts this design.

**One deliberate omission, stated in the phase:** there is no `asbs migrate` command. `main.py` is
the developer's own declaration, so a rewriter either guesses at intent or breaks on hand edits; a
checklist plus a `validate` that names what is missing is the honest shape.

P6 is what makes the guide's central claim checkable rather than asserted: an existing project
keeps every registry key, queue group and durable name because the root namespace keeps them, and
that is now enforced by tests.

### Config rework, step 1 -- logging leaves `Config`, and `app_port` leaves the scope

The two prerequisites for one `Config` per namespace (C5). Neither is a namespace feature; both are
things that only work once, and therefore break the moment a process holds N of them.

**`Config.__init__` no longer configures logging.** The call at the end of the constructor is gone;
the body it called is now the public `Config.configure_logging()`, and `AppBuilder.__init__` makes
the call before any `with_*()` runs, so components are constructed with the format already set.

Two reasons, and the second is the one that forced it now. It is the application's decision, not
the loader's -- a library that configures logging on construction takes the root logger from
whatever imported it and cannot be silenced by the caller. And one `Config` per namespace means N
constructions per process: each one built a fresh `LoggingManager`, whose `_configured` flag is
per-instance and therefore never helped, so each re-attached the correlation and health-check
filters, logged "Logging configured" again, and let the last namespace's `log_level` win. Verified
before the change by constructing three scoped `Config`s in one process: three configuration lines.

Existing projects are unaffected, because they all reach `AppBuilder`. What does change: code that
builds a `Config` and never an `AppBuilder` -- a script, a test -- now gets Python's default
logging until it calls `configure_logging()` itself, which is the correct behaviour for a library
and is why the method is public rather than private.

**`app_port` is a root key even when a `Config` is scoped.** The scoped validator required
`<scope>.app_port` alongside `<scope>.app_name`. A group is one process behind one HTTP server, so
only one port can ever be bound: requiring it per agent makes every agent declare a value that all
but one of them cannot have. `app_name` stays scoped -- it is the agent's identity and reaches
telemetry and the queue group -- while the port is validated at root with the same `default=8000`
the unscoped path uses.

**Tests.** 1361 unit tests pass (up from 1354). `TestLoggingIsTheApplicationsDecision` asserts that
construction configures nothing, that `configure_logging()` does, that it passes the resolved
settings, and that three constructions still configure nothing. `TestLoggingOwnership` asserts
`AppBuilder` makes the call exactly once and that a later `with_*()` does not repeat it. The
`app_port` test inverted from "missing scoped port raises" to two cases: a scoped config reads the
root port, and falls back to 8000 when there is none.

`config.py` remains on `black`'s pre-existing reformat list: the nested conditional in
`_process_dynabox` is one of the places where `black` and `ruff-format` genuinely disagree -- unlike
the `actuator_api.py` hunk, `ruff-format` rejects `black`'s version here -- so it was left as it is
rather than picking a winner inside an unrelated change.

### Config rework, step 2 -- one loaded tree, one view per namespace (C5)

`Config` becomes the loader and the owner of the settings tree; each agent reads through a view of
it. This is C5 ("each namespace **MUST** receive a `Config` with `agent_scope` set"), implemented
without N loads and without giving each agent a window on its neighbours.

**`Config.for_namespace(namespace)` returns a scoped view sharing the loaded tree.** The view is a
shallow copy differing only in `_agent_scope`, so `for_namespace("orders").get("model_name")`
resolves `orders.model_name` and falls back to the root `model_name`, while `nats_url` and the rest
of the infrastructure keys stay shared. The files are parsed once per process, not once per agent:
a test asserts `view._settings is config._settings`. Views are cached per namespace, so a component
asking twice gets the same object.

This cost almost nothing because every read already funnelled through one place: the nine typed
getters call `self.get()` 25 times and never touch the tree directly, so scoping `get` scopes all
of them. A test covers that rather than trusting it.

`for_namespace("")` returns the object itself -- not an optimisation but the definition, since the
root namespace *is* the unscoped configuration. Calling `for_namespace` **on a view raises**: a
view is one agent's window, not a factory for other agents' windows, and allowing it would hand
every namespace an unlogged route to its neighbours' keys.

**`Component.config` returns the component's own view.** A root-namespace component gets the
configuration object unchanged, so every existing application reads exactly what it read before;
a namespaced one gets `shared_config.for_namespace(self._namespace)`. This is what makes the view
more than an unused abstraction, and it is available now only because P6 put the namespace on
`Component` itself.

**The raw tree becomes an audited escape hatch.** `self.settings` was a public attribute; it is now
a property over `self._settings` that logs on every access. The user asked for a hatch that logs
rather than a wall, so isolation here is **audited, not enforced** -- and the docstring says so,
because the difference matters to anyone relying on it. Enforcing it would mean making the tree
unreachable, which breaks the actuator environment endpoint and any project reading a key the typed
getters do not model.

The level distinguishes the two cases, which is what keeps the audit useful rather than noisy: the
loader is the application's own object and owns the tree, so its access is DEBUG; a **namespaced
view** handing out the whole tree is an agent reading past its own subsection, so that is WARNING
and names the namespace. An existing single-agent application therefore logs nothing new.

**Deployment identity is refused, not returned as `None`.** New `DEPLOYMENT_IDENTITY_KEYS`
(`blueprint_group`, `pod_name`, `hostname`) raises from `get()` with the reason: code that can read
its group or pod can be written to depend on them, and regrouping then breaks it (C6). `None` would
have read as "not configured" and sent the caller hunting for a missing setting. The check sits in
`get()`, the single reader every typed getter funnels through, and it is case-insensitive. This is
also the prerequisite for step 3: with `envvar_prefix` disabled Dynaconf absorbs the entire process
environment -- `BLUEPRINT_GROUP` included -- and this is what keeps it out of reach.

**Tests.** 1387 unit tests pass (up from 1361). New `test_namespace_views.py`: scoped resolution and
root fallback, two agents disagreeing only where they override, the root being the object itself,
caching, the shared tree, the view-of-a-view refusal, the typed getters being scoped, the C6
refusals including case and the `default=` argument, and the audit -- a view warns and names itself,
the loader does not, and the hatch still returns the whole tree. `TestConfigIsScopedToTheNamespace`
covers the `Component` side.

**Two test-fixture changes the production change forced, both worth noting.** Six `mock_config`
fixtures are `MagicMock(spec=Config)`, so `for_namespace()` returned a *different* mock and any test
asserting on `mock_config.get` for a namespaced component broke; they now set
`config.for_namespace.return_value = config`, so the mock stands in for both the loader and its
views. And `tests/unit/agents/agent/conftest.py` builds `AgentRuntime` with `object.__new__`,
bypassing `Component.__init__`, so it now supplies `_namespace` the way it already supplied `_name`.
The alternative -- making `Component.config` tolerate a missing `_namespace` via `getattr` -- was
rejected deliberately: it would hide a real ordering bug in any subclass that reads configuration
before calling `super().__init__()`, which is exactly the failure that should be loud.

### Config rework, step 2b -- the loader stops being reachable from agent code

Found by review immediately after step 2: the scoped view and its audit could be walked past. Every
class in this framework is a `Component`, so `Component.shared_config` was in reach of every
handler, service and client -- and it hands out the **unscoped loader**, so a read through it is
neither namespaced nor logged.

It was worse than a class-level name. `configure()` assigns through `cls`, so the value lands on the
`Component` class itself, which *is* in the instance MRO: `self.shared_config` resolved too, which
is the easiest thing to type and the least likely to look wrong. Probed rather than assumed -- all
four of `self.shared_config`, `Component.shared_config`, `type(self).shared_config` and
`type(self).config` returned the loader.

**`shared_config` is now `_shared_config`, with no public read path at all.** The only route to
configuration is the instance property `Component.config`, which returns the component's own view
(C5) and logs any raw-tree read. Two small public additions on the metaclass replace what tests
were using the attribute for: `has_config()` reports whether configuration has been injected without
handing over the loader, and `reset_shared_state()` clears the process-wide state, which a suite
building more than one application has to do between cases. 13 assignments and 3 reads across the
suite moved onto them.

**The metaclass `config` property is deleted, and it was the sharper trap.** It returned
`cls._shared_config` -- the *unscoped loader* -- under the name that means *scoped view* on an
instance, so `MyHandler.config` and `self.config` were two different things one character apart.
Nothing used it: a grep for class-level `.config`/`.registry` access across `src/` and `tests/`
found no hits, so it was dead code as well as a trap.

**`shared_registry` deliberately stays public.** Hiding it protects nothing: looking up
collaborators is the registry's whole purpose, every component already reaches it through the public
instance property, and `AppBuilder` needs it before any component instance exists. A class-level
property named `registry` was tried and reverted -- it collides with the instance property of the
same name, and mypy resolves the instance one in preference to the metaclass one, so
`Component.registry.cache_service` failed to type-check. The reverted attempt is recorded in the
metaclass docstring so it is not retried.

**Tests.** 1391 unit tests pass (up from 1387). `TestTheConfigLoaderIsNotReachable` asserts the
class-level accessor is gone, that no instance answers to `shared_config`, and that `has_config()`
and `reset_shared_state()` do their jobs. Three `Component.registry` class-level reads in
`test_component.py` moved to `shared_registry`, since deleting the metaclass property is what made
them resolve to the property object rather than the registry.

`tests/integration/test_sessions_startup_resilience.py` keeps its pre-existing formatting: `black`
wants to rewrite one assertion there and `ruff-format` rejects the result, so the file stays on the
known-debt list rather than having a winner picked inside an unrelated change.

### Config rework, step 3a -- the environment-variable prefix becomes the project's to choose

Until now the only spelling an environment override could have was Dynaconf's own `DYNACONF_<KEY>`.
That is a library's name in a deployment's interface: a chart for a platform hosting several
Blueprint groups has no way to say which of them a variable is meant for, and an operator reading
`DYNACONF_MODEL_NAME` cannot tell it belongs to this framework at all.

**`envvar_prefix` is now a top-level key in the settings file, overridable in the environment by
`BLUEPRINT_ENVVAR_PREFIX`.** Precedence is environment, then file, then `DYNACONF` -- so a project
that declares nothing behaves exactly as before, which is the point: every existing chart keeps
working untouched.

**It is resolved in the first Dynaconf pass, not the second.** `Config.__init__` already had a
bootstrap pass whose only job was to read `app_environment` before the real load. The prefix has to
be known before the tree that uses it exists, so it is resolved there, from the files read through
the default prefix -- the one spelling that is always available.

**That pass then runs a second time whenever the resolved prefix is not the default.** Without it,
`<PREFIX>_APP_ENVIRONMENT` would be invisible to the only read that consumes it: the main pass
would load the `[development]` section while every other key honoured the override, and nothing
would report the mismatch. The repeat is skipped entirely for the default prefix, so the common
case still parses the files twice, not three times.

**Four declarations are rejected rather than repaired**, each because the alternative is silent:

- **A lowercase prefix.** Dynaconf does `prefix = prefix.upper()` before matching the environment
  (`loaders/env_loader.py`), so a declared `myapp` looks for `MYAPP_<KEY>`. On Linux the
  `myapp_<KEY>` that was actually exported is then never read, and nothing says so. Windows hides
  the bug -- its environment is case-insensitive -- so this is exactly the defect that ships. The
  alphabet is `[A-Z][A-Z0-9_]*`; commas are excluded too, because Dynaconf reads a comma-separated
  prefix as a *list* of prefixes and one override spelling is enough.
- **`BLUEPRINT` and `POD`.** Dynaconf strips the prefix to form the key, so `envvar_prefix =
  "BLUEPRINT"` turns `BLUEPRINT_GROUP` into the readable key `group` -- and the C6 blocklist names
  `blueprint_group`, not `group`. A prefix could therefore have quietly reopened the hole
  `DEPLOYMENT_IDENTITY_KEYS` exists to close. The rejected set is *derived* from that blocklist
  (`_ENVVAR_PREFIX_IDENTITY_COLLISIONS` takes the segment before the first underscore), so a new
  identity variable closes its own hole without anyone remembering to.
- **`envvar_prefix = true`**, which names no prefix, and any non-string.
- **A prefix declared inside a section.** This is the mistake a developer will actually make:
  putting it under `[default]` next to `app_name`. The resolving pass runs with
  `environments=False`, so a section is one opaque value to it and the key inside is invisible --
  and it has to run that way, because the prefix is what decides how `app_environment` is read.
  Left there it would name no prefix, so *every* override relying on it would be ignored at once.
  `_reject_sectioned_envvar_prefix` walks the bootstrap tree and raises naming the path it found
  (`development.envvar_prefix`).

**`envvar_prefix = false` disables the prefix**, and this is a footgun that ships documented rather
than hidden. Dynaconf then absorbs the entire process environment: probed on this machine, 88 keys
against a 5-key settings file, `PATH`, `BLUEPRINT_GROUP`, `POD_NAME` and every `*_API_KEY` in the
shell among them. It is *safe* only because step 2 put `DEPLOYMENT_IDENTITY_KEYS` in front of
`get()` -- with the prefix off, `BLUEPRINT_GROUP` lands in the tree as `blueprint_group`, which is
the exact spelling the C6 blocklist refuses, and a test asserts that for all three identity keys.
The environment spellings that mean off are `false`, `0`, `no` and the empty string, matching
`parse_bool` rather than inventing a second boolean vocabulary. The guide recommends a short
project prefix and describes what disabling it exposes.

**One Dynaconf behaviour is worth stating because it is not optional.** `DYNACONF_*` is loaded
whatever the prefix is, and cannot be turned off:

```python
if global_prefix is False or global_prefix.upper() != "DYNACONF":
    load_from_env(obj, "DYNACONF", ...)
```

So declaring a prefix **adds** a spelling rather than replacing one, and because the custom prefix
is loaded second it wins for the same key. Verified both ways. This is good for migration -- an old
chart keeps working while a new one moves -- and bad for anyone who declares a prefix believing
they have closed the `DYNACONF_` door. Both directions are tested and both are in the docstring.

`Config.envvar_prefix` is a public read-only property, because "my variable is ignored" and "my
variable is misspelled" are otherwise indistinguishable; the startup log now names the resolved
prefix (or says the environment is read unprefixed). A namespace view shares it: the prefix is a
property of the process, and `for_namespace` copies it with the rest of the loader.

**Tests.** 1421 unit tests pass (up from 1391), 30 of them new in
`tests/unit/agents/config/test_envvar_prefix.py`: resolution and precedence, the environment
selected through the resolved prefix, `DYNACONF_` surviving alongside a custom prefix and losing to
it, every rejection above, the four falsy spellings, and C6 still holding with the prefix disabled.
An autouse fixture strips ambient `DYNACONF_*` from the environment, since the developer's own shell
can otherwise satisfy or defeat the very lookup under test.

`src/blueprint/agents/config/config.py` keeps its pre-existing `black` disagreement in
`_process_dynabox`, which this change does not touch: it is on the known-debt list because
`ruff-format` reverts what `black` wants there.

### Config rework, step 3b -- the environment endpoint answers per agent, and reads the tree once

`GET /status/env` flattened the whole settings tree into one dictionary. In a grouped process that
is every co-hosted agent's configuration in one blob, with nothing saying which agent a key belongs
to -- and worse, nothing saying what any agent actually *resolves*, because an agent reads its own
subsection overlaid on the root keys and neither half alone is the answer.

**`Config.resolved_settings(namespace)` builds the dictionary an agent reads.** Root keys, minus
every other namespace's subsection, with this namespace's own subsection overlaid. `""` returns the
whole tree, which is what the root namespace resolves -- so a single-agent application is
unaffected. The overlay skips `None`, matching `_scoped_get`, where `None` at a scoped key means
"not set" and falls back to the root while `""` and `[]` do not.

Two bugs in the first version of that overlay, both caught by probing it against `get()` key by key
rather than asserting it looked right:

- **`as_dict()` upper-cases only the top level of the tree**, leaving a subsection's own keys as
  written. So the overlay landed `app_name` *beside* `APP_NAME` instead of on it, and the resolved
  dictionary reported the root value while `get()` answered the agent value. Fixed by upper-casing
  the overlay key.
- That also silently broke the `None`-versus-empty distinction: `billing`'s `model_name = ""`
  resolved to the root `"root-model"` in the flattened dictionary and to `""` through `get()`. The
  same fix covers it, and a test now asserts equality with `get()` for both agents key by key.

**`Config.namespaces` lists the namespaces that have asked for a view**, sorted. That is group
membership as configuration sees it, and it is the only reliable source: a namespace subsection and
an ordinary nested table such as `[default.cache]` are indistinguishable in the tree, so the
endpoint cannot discover agents by inspecting it.

**Both are root-only, and raise on a view -- this is C6, not tidiness.** A view is what agent code
holds (`Component.config` returns one for a namespaced component), so `namespaces` on a view is an
agent asking who it is grouped with, and `resolved_settings("other")` on a view is an agent reading
a neighbour's configuration. Both raise `RuntimeError` naming the namespace that asked, the same
rule `for_namespace` already applies to itself. C6 is thereby enforced at the two new entry points
rather than being left to the endpoint to respect.

**`env_status` now returns three things instead of two.** `settings` is what the root resolves,
`namespaces` carries one masked entry per agent, and `envvar_prefix` reports what step 3a resolved
(`null` when the prefix is disabled -- unambiguous for a JSON consumer in a way `""` is not).
`namespaces` is empty for every existing single-agent deployment, so the response is additive.

**The per-namespace breakdown is masked exactly like the root tree.** It is a second copy of the
same values, so `_sanitize_config` runs over each entry; a test asserts that no marker string from
a secret in either the root or an agent section appears anywhere in the serialised response.

**The raw tree is read once per request.** `env_status` read `config.settings` three times
(`as_dict`, `current_env` for the log, `current_env` for the response) and `build_status` twice.
`Config.settings` is the *audited* property added in step 2 -- every read logs -- so one operator
request produced three records, and would produce a WARNING per read if the actuator ever holds a
view. Both endpoints now take one reference and read fields off it, and a test asserts the property
is touched exactly once per request. `build_status` also stopped reaching for `current_env` and
`settings_files` as bare attributes, which is what made the endpoint depend on the shape of a
Dynaconf object in two places instead of one.

**An agent-scoped actuator reports only its own scope.** `ActuatorApi` is a root component by the
plan's sharing table, so this is the branch that should never be taken -- but if it is, the
endpoint must not call the two root-only methods and turn a status request into a 500. It falls back
to the tree it holds and an empty breakdown.

**Tests.** 1443 unit tests pass (up from 1421). 13 new in `test_namespace_views.py`
(`TestResolvedSettings`, `TestNamespacesIsRootOnly`) and 9 in `test_actuator_api.py`
(`TestEnvStatus`). The endpoint tests use a **real** `Config` rather than a `MagicMock`: what is
under test is how the endpoint uses the real scoping and audit behaviour, and a mock would assert
only which methods were called.

`src/blueprint/agents/io/api/actuators/actuator_api.py` keeps a pre-existing `ruff-format`
disagreement in `llm_status`, untouched by this change, and `config.py` keeps its pre-existing
`black` one in `_process_dynabox`. The new fixture writes its settings text through a named local
rather than a nested `write_text(textwrap.dedent(...))` call, because the two formatters disagree
about that construct and neither has to win.

### Phase 0, part 1 -- `run_app`, and the worker count it refuses

First piece of phase 0. `run_app(app, config)` in `utils/utils.py`, exported from
`blueprint.agents`, is the one line a project needs to become runnable by
`python src/main.py`: host, port and log level come from the same settings tree as everything
else instead of a uvicorn invocation duplicated in a Dockerfile, a compose file and a README.

Development (`app_environment = "development"`) differs in exactly two ways -- the server logs at
`debug`, and it runs one worker whatever the configuration says.

**`reload` is never enabled, and that is not an omission.** Auto-reload requires uvicorn to import
the application itself, so it needs an import string; it cannot restart an object that has already
been built. The plan said this; the docstring now says it too, because "why does reload not work"
is otherwise a question that gets answered by adding a broken parameter.

**`app_workers > 1` raises instead of being passed through**, which is a departure from the plan's
"workers from `app_workers` config (default 1)". Two independent reasons, and either alone settles
it:

- **uvicorn cannot honour it here.** With an application *object* rather than an import string,
  `workers > 1` makes uvicorn log `You must pass the application as an import string to enable
  'reload' or 'workers'` against its own logger and call `sys.exit` (`uvicorn/main.py:603-607`,
  verified against uvicorn 0.52.4). So the plan's version produces a process that dies before
  binding a port, with a message naming a setting the operator did not touch.
- **It is the wrong shape for this framework even where it works.** Every uvicorn worker is a
  separate process that builds the application again: N workers open N transport connections, join
  the queue group N times, and start N in-process scheduler timers. Scaling is what replicas are
  for, and the queue group (P1) and the per-tick claim (P5) are what make replicas correct. The
  error message says this and names the alternative for anyone who wants it anyway.

**The log level is translated, not validated.** The framework spells levels as `logging` does
(`"INFO"`), uvicorn wants them lower-case and has one level `logging` does not (`"trace"`). An
unrecognised value logs a warning and falls back to `"info"` rather than raising: this level
decides only how uvicorn narrates itself, nothing outside the process can depend on it, and the
application's own logging was already configured from the same key by `Config.configure_logging`.
That is the other side of the P6 rule -- names that cross the process boundary are validated, and
this one does not cross it.

`DEFAULT_APP_HOST = "0.0.0.0"` carries a `# nosec B104`: bind-all is the only useful default
inside a container, which cannot know the address of the interface its traffic arrives on. **Not
verified locally** -- bandit is not installed in this working copy (see `CLAUDE.local.md`), so
whether the marker satisfies the hook is unconfirmed.

**No caller in this repository yet, deliberately.** The examples end at `app = builder.build()` and
are served by the Dockerfile's `uvicorn src.main:app`, and phase 8 is what turns `main.py` into a
declaration served by `python -m blueprint.agents.entrypoint` -- which is the caller this exists
for. It is public API from today regardless, so it is usable rather than dormant.

**Tests.** 1462 unit tests pass (up from 1443), 19 new in `tests/unit/agents/utils/test_run_app.py`:
the arguments uvicorn is handed, the two development differences, the level translation and its
fallback, `reload=False`, and the worker refusal -- including that it happens before `uvicorn.run`
is called at all.

### Phase 0, part 2 -- the namespace becomes ambient, so a developer never writes one

The constraint this serves, stated by the user while phase 0 was in progress and now the test the
design is held to: **a developer using the blueprint should not have to care about namespaces at
all**, and a project should read the same whether it runs as a single agent or inside a group --
with `main.py` the only file that may differ.

Threading a namespace through constructors fails that immediately: every handler, service and
client would carry a parameter that exists only because of how it is deployed. So the namespace is
**ambient during construction** instead.

`component/namespace.py` gains three things -- placed there rather than in `component.py` as the
plan said, because that module already declares itself the single definition of what a namespace
is, and the scope validates through `validate_namespace` two functions above it:

- `_CURRENT_NAMESPACE`, a `ContextVar[str]` defaulting to `ROOT_NAMESPACE`.
- `current_namespace()`, read by `Component.__init__`.
- `namespace_scope(namespace)`, a context manager: validate, set, and reset in `finally`. A
  leaked namespace would attach the next agent -- or the framework's own root components -- to the
  wrong one, and the registry key, the queue group and the durable name would all be wrong
  together, so the reset is not left to a caller to remember. Nested scopes restore the enclosing
  namespace rather than the root, and the namespace is validated **on entry**, so an illegal name
  is reported against the registration that declared it instead of against whichever component
  happened to be built first.

**`Component.__init__` now resolves `namespace or current_namespace()`**, and the direction of that
`or` is the whole change:

```python
self._namespace = validate_namespace(namespace or current_namespace())
```

The obvious reading -- an explicit argument wins over the ambient scope -- is wrong here, and
quietly so. `ServiceBase`, `ClientBase`, `IOClientBase` and `EventPublishingService` all declare
`namespace: str = ROOT_NAMESPACE` and forward it **unconditionally**, so a developer writing

```python
class OrderService(ServiceBase):
    def __init__(self) -> None:
        super().__init__()
```

passes an explicit `""` down to `Component`. Treating that as a decision would pin every
developer-written component to the root and leave the ambient scope applying to nothing that
matters -- the exact components the constraint is about. A *non-empty* argument still wins, which
is what the framework's own namespace-owning components (the transport clients, the publishing
service) rely on. The alternative -- a `None` sentinel threaded through four base classes -- was
rejected: it changes four public signatures to express what one `or` expresses, and it would have
to be repeated by every base class added later.

**Nothing changes for a single-agent application.** Outside a scope `current_namespace()` is
`ROOT_NAMESPACE`, so `namespace or current_namespace()` is `""` exactly as before, and
`qualified_component_name` keeps the bare registry name. The 1462 tests that passed before this
change still pass unmodified.

**One limit worth stating.** A `ContextVar` is not inherited by another thread or task, so a
component constructed off the builder's thread does not see the scope. That is the correct shape
rather than a gap: construction happens synchronously inside the builder, and anything built
lazily at request time is a root component by construction, which is what the fallback gives it.

**Tests.** 1476 unit tests pass (up from 1462), 14 new. `TestAmbientNamespace` in
`test_namespace.py` covers the default, setting, exit, exit **on exception**, nesting,
the root scope as a no-op and validation on entry. `TestNamespaceComesFromTheAmbientScope` in
`test_component.py` covers the part that matters: a `ServiceBase` subclass whose `__init__` takes
no namespace and calls bare `super().__init__()` comes out namespaced, the same class registers
under two different qualified names in two scopes, and an explicit non-empty namespace still wins.

### Phase 0, part 3 -- one declaration, applied alone or once per agent

Completes phase 0. `AgentRegistration` collects component *classes* and builds none of them;
`AppBuilder.with_registration(registration, namespace="")` is what builds them, inside
`namespace_scope`. Together with part 2 that satisfies the constraint end to end: a project
declares its components once, and the same object serves both deployment shapes.

```python
registration = AgentRegistration().with_service(OrderService).with_handler(OrderHandler)

app = AppBuilder(config).with_registration(registration).with_cache().build()   # alone
# a group applies the same object once per agent, under that agent's namespace
```

Verified rather than asserted: applying one registration under `orders` and again under
`billing` produces `orders_order_service` and `billing_order_service`, each resolving its own
`app_name` and `model_name` through its own scoped `Config` view -- with the word "namespace"
appearing nowhere in `OrderService` or in the declaration.

**`with_registration` is new public API that the spec does not list.** Spec sec. 4.2 has only
`with_namespace(..., registration=...)`, which is phase 3. Added now because without a caller
`AgentRegistration` would be a collector nothing could consume for three phases, which is worse
than an extra method: it is a published API that does not work yet. It is also the exact call
phase 8's entry point needs per agent, so phase 3 narrows the gap rather than replacing this.

**An already-built component is refused, and this is the part that would otherwise bite.** Four
of the five examples pass instances today -- `with_rest_api(MonitorApi())`,
`with_agent(agent)` -- which an `AppBuilder` chain accepts. In a registration that object is
constructed at import time, *before any namespace exists*, so it belongs to the root whichever
agent declared it; two grouped agents each declaring one would collide on its registry name, and
until they collided the misattribution would be silent. `_add` raises `TypeError` on any
`Component` instance, and the message names the class, the method and the fix.

**Factories are accepted for the case a class cannot express.** `examples/document_summarizer`
builds its agent as `AgentBuilder(config, runtime_name=...).with_model_from_config()...build()`
-- a fluent chain, not a class plus keyword arguments. A zero-argument callable is therefore a
legal target, called *inside* the scope, so the model and prompt resolve in the agent's own
namespace instead of at import time. `apply` distinguishes the two:

```python
target = entry.target if isinstance(entry.target, type) else entry.target()
appliers[entry.kind](target, name=entry.name, **entry.kwargs)
```

A class is handed to the builder, which instantiates it -- still inside the scope. A factory has
to be called here, because the builder would otherwise take the callable itself for a built
component.

**`apply` is public, departing from the plan's `_apply`.** It is called from another class, and
this repo's convention is that a leading underscore means internal to the defining class.

**There is no `with_cache`,** per spec sec. 4.1: a cache is process-wide and belongs to the
`AppBuilder` hosting the group. An agent that declared its own would duplicate a neighbour's or
quietly take it over. `AttributeError` plus the class docstring is the whole of that story -- a
method existing only to raise seemed worse than one not existing.

`RegisteredComponent` is a frozen dataclass (`kind`, `target`, `name`, `kwargs`) and
`AgentRegistration.components` exposes the tuple in declaration order. Order is preserved
because it is meaningful -- handler priority and scheduler wiring read it -- and the tuple is
what phase 8 will validate against `agents.toml` and what spec sec. 9.2's startup log needs.

**Tests.** 1498 unit tests pass (up from 1476), 22 new in
`tests/unit/agents/app_builder/test_agent_registration.py`: nothing is constructed at
declaration time (asserted through `Component.shared_registry` still being `None`), order and
kwargs survive the round trip, the instance and non-callable refusals, root application keeping
the bare registry name, one declaration becoming two independently configured agents, the scope
being left behind afterwards, and a factory both deferred and called inside the namespace.

**Not done, and the obvious next proof:** no example uses this yet. Migrating one project's
`main.py` to a registration would demonstrate the "only `main.py` differs" claim in the tree
rather than in a test -- and would have to convert its `with_rest_api(MonitorApi())` to the
class form, which is precisely the change the refusal above forces.

### Phase 1, part 1 -- the registry resolves per namespace, without a namespace dimension

Every lookup on `Registry` now takes an optional `namespace`, so two agents can own the same
component class in one process and each find its own. Verified: `orders` and `billing` both
declaring `OrderService` produce `orders_order_service` and `billing_order_service`, each
resolvable as the bare `order_service` from its own namespace, with a root-registered
`shared_audit` inherited by both.

**The storage was not changed, and the plan's `dict[str, dict[str, Any]]` is not what this
needs.** The plan predates P6, which made every registry name namespace-qualified
(`qualified_component_name`). With qualified names, a namespace → name → component nesting
duplicates the namespace in the outer key and the inner name at once, and either the inner key is
the qualified name -- in which case the outer level carries no information -- or it is the bare
name, in which case `get_component("orders_order_service")` stops resolving and every existing
lookup, health-check entry and log line that uses `Component.name` breaks. So the namespace
dimension the plan asked for is already present in the key space, and what was missing was only
the ability to *ask* through it.

Two kinds of question, and they resolve differently on purpose:

- **"Find me the one X"** -- `get_component`, `get_service`, `get_scheduler`, `get_client`,
  `get_agent` -- resolves **namespace first, then root**, because infrastructure stays shared
  while an agent overrides what it owns. For a name that is `_lookup`, a new private helper that
  tries `<namespace>_<name>` before `<name>`; for a class it is `resolve_for_namespace`, which
  P6 already wrote for this and whose docstring said it would become the registry's
  implementation when the registry grew a namespace. It now is.
- **"Give me all the Xs"** -- `get_components_by_type`, `get_services`, `get_schedulers`,
  `get_rest_apis`, `get_clients`, `get_event_handler` -- filters to **that namespace exactly**,
  since iterating one agent's components must not sweep in a neighbour's.

**`namespace=None` is the default and means every namespace, not the root** -- a departure from
the plan's `namespace: str = ""`. With `""` as the default, `build()` calling
`get_event_handler()` would have quietly seen only root handlers: correct on a single-agent
application, and silently short-staffed on a grouped one, which is the worst possible shape for
a default. `None` keeps today's behaviour exactly, so every existing caller is unaffected.

Filtering is on the component's own `namespace` attribute, not on its registry name. An explicit
`name=` overrides the qualified name (documented on `Component.__init__`, used by
`AIClientBase`), so a name-based filter would lose exactly those components.

**Ambiguity raises rather than picking a first match.** A class lookup with a namespace goes
through `resolve_for_namespace`, which refuses two candidates at the same level; without a
namespace the pre-existing "Multiple components of type X found" applies. Silently handing an
agent a neighbour's collaborator is the attribution the whole topology exists to provide.

**`get_known_namespaces()` was NOT added, because C6 forbids it.** The plan asks for it so
`NatsEventing` and `build()` can iterate namespaces. But C6 says no API reachable from agent code
may expose the group's membership or size, and `Component.registry` is a public property on every
component -- so a `get_known_namespaces()` here is precisely the API C6 rules out, reachable by
`self.registry.get_known_namespaces()` from any handler. The builder already knows the group
composition, because it was told: it passes each namespace to the wiring that needs one, which is
also the layering the plan argues for elsewhere ("`AppBuilder` must remain a pure function of its
call sequence"). A test asserts the method does not exist, so it cannot be added back without the
reason being read.

**Tests.** 1514 unit tests pass (up from 1498), 16 new in `test_registry.py`
(`TestNamespacedNameLookup`, `TestNamespacedTypeLookup`, `TestC6`): the fallback in both
directions, an already-qualified name still resolving, a bare name *not* resolving without a
namespace, the error naming where it looked, `None` returning every namespace, filtering by
attribute rather than name, ambiguity refused both across and within a namespace, and the absence
of `get_known_namespaces`.

Still to do in phase 1: named caches (spec sec. 8) and the per-namespace executor. Note that the
executor has its own plan-versus-spec conflict to settle -- the plan provisions the root executor
eagerly in `build()`, while spec sec. 4.3 requires it to be created **lazily on first access**, so
that an application which never performs blocking work spawns no threads.

### Phase 1, part 2 -- caches are looked up by name, and never substituted for one another

`_cache_service: CacheService | None` became `_caches: dict[str, CacheService]`, with
`add_cache(name, cache)`, `get_cache(name="default")`, `has_cache(name="default")` and
`get_all_caches()`. `DEFAULT_CACHE_NAME = "default"` names the one every existing application
has, and `registry.cache_service` -- getter and setter -- is retained as an alias for it, which
spec sec. 8 requires. Every existing caller (`with_cache`, `HandlerChain`, the scheduler tick
claim, the cache management endpoints, the health check) reads the alias and is untouched.

**`get_cache` has no fallback to the default cache, deliberately.** Spec sec. 8: two
independently written agents both asking for `"sessions"` must not silently share one store the
moment they are grouped. A missing name is therefore an error naming what *is* registered, not
an invitation to hand over some other cache. This is the opposite of how components resolve --
where namespace-then-root is right, because infrastructure is shared on purpose -- and the two
sit next to each other in the same class, so the module docstring and both docstrings say which
is which and why.

**One behaviour change: registering a second cache under one name now replaces it and warns,
where the setter used to raise.** The plan asks for an upsert so a cache can be added after
startup, and an alias for `add_cache` cannot be stricter than the method it aliases. Replacing
silently would be worse than either, because the usual way to arrive twice at `"default"` is two
calls to `with_cache()` -- so it logs at WARNING with both backend types named. Two tests
asserted the old raise and were rewritten to assert the new behaviour;
`test_cache_sharing_via_registry.py` now protects the invariant that actually matters -- both
services still resolve one object, and `get_all_caches()` still has exactly one entry.

`clear()` clears and drops every cache rather than the single one.

`get_or_create_cache` from the plan was **not** written. It is specified as "atomic get-or-create
protected by an `asyncio.Lock`", but every registry method here is synchronous and every cache is
registered during `build()`, before a loop exists -- a lock that cannot be awaited protects
nothing, and nothing in the framework creates a cache lazily for it to protect. When something
does, it can be added with a mechanism that matches how it is actually called.

### Phase 1, part 3 -- one thread pool per agent, and only if something needs one

`Registry.get_or_create_executor(namespace, max_workers)` returns a namespace's
`ThreadPoolExecutor`, creating it on first use; `Component.executor` is the property a component
reaches it through:

```python
    @cached_property
    def executor(self) -> ThreadPoolExecutor:
        return self.registry.get_or_create_executor(self._namespace, self.config.get("executor_workers"))
```

One pool per namespace, so an agent doing blocking work -- DiskCache, SQLite, a synchronous SDK
-- cannot exhaust the pool another agent is waiting on. Threads are named
`blueprint-<namespace>_N`, so a stack dump says which agent a blocked thread belongs to.

**Created on first access, not provisioned in `build()`, which is a departure from the plan and
required by spec sec. 4.3.** The plan says "the root executor is provisioned in
`AppBuilder.build()` (not in `with_namespace`) so standalone apps always have one". That would
add `cpu_count() + 4` idle threads to every application that has no blocking work at all --
including every single-agent application that exists today -- and works directly against the
thread budget in #36. Verified: with nothing asking, the process has one thread and
`_executors` is empty.

**The plan's root fallback is subsumed rather than implemented.** `get_executor` was to fall back
to the root when a namespace had no pool; with creation on demand a namespace can never be
missing one, so that branch could never be taken. For the same reason there is no `add_executor`:
nothing needs to hand a pool in.

**Sizing is per namespace, and the first asker wins.** `executor_workers` is read through
`Component.config`, which is the namespace's scoped view (C5), so one agent can be sized
differently from its neighbour. A live pool cannot be resized, so a later component of the same
namespace passing a different value is ignored rather than raising -- failing an application over
a number nobody chose deliberately would be worse than using the first one.

**The pools are shut down with the application.** `Registry.shutdown_executors()` waits for
running work and clears the map, and it is called at the very end of the lifespan shutdown --
after every `on_shutdown`, because a component may well run its last blocking call there -- and
from `Registry.clear()`, so a test suite building many applications does not accumulate pools.
This is not optional tidiness: a `ThreadPoolExecutor`'s workers are non-daemon threads, so
leaving them running keeps the interpreter alive past the point the container was asked to stop.

No public read accessor for the executors was added; nothing in `src/` needs one, and the two
tests that check the map is empty read the private attribute rather than growing the API for
their own convenience.

**Tests.** 1538 unit tests pass (up from 1514), 24 new. `TestNamedCaches` (11) covers lookup by
name, the absence of a fallback, the error listing what is registered, the alias in both
directions, `get_all_caches` returning a copy, and `clear` clearing every cache.
`TestExecutors` (9) covers nothing existing until asked, creation then reuse, isolation between
namespaces, sizing on the creating call and being ignored afterwards, thread naming, and
shutdown from both entry points. `TestExecutorBelongsToTheNamespace` (5) covers the component
side: its own namespace's pool, two agents not sharing, two components of one agent sharing, and
sizing from the scoped configuration.

**Phase 1 is complete.** `Component.executor` belongs to spec sec. 4.3 rather than to phase 1
strictly, and was written here because the registry half is unreachable without it -- an
executor store with no way to reach it is the unused surface this repo keeps out.

### Phase 2 -- a component's registry answers for its own agent

Phase 2 is titled "component namespace awareness", and three of its four bullets were already
satisfied by earlier work: the `ContextVar` and `Component.__init__` reading it landed in phase 0
part 2, `Component.executor` in phase 1 part 3, and `shared_registry` was never going to stop
being a class-level singleton. Its fourth -- passing `namespace=` to `add_component` -- is
obsolete: phase 1 kept the flat store precisely because P6 had already made the registry name
namespace-qualified, so the namespace is in the key.

What was actually missing is the half phase 1 enabled and nothing used. Every lookup on `Registry`
took a `namespace`, and **no caller passed one**, so a grouped process would have resolved
collaborators at random or refused to choose. Two examples from the framework's own code, both
written long before namespaces:

```python
self._client = self.registry.get_component(NATSClient)          # io/api/eventing/nats.py:33
handlers = sorted(self.registry.get_event_handler())             # handler/handler_chain.py:130
```

With one transport client per namespace (P6) the first raises "Multiple components of type
NATSClient found" the moment a second agent joins the process, and the second dispatches one
agent's event to another agent's handlers. Neither call site may grow a namespace argument,
because the constraint is that no code names a namespace unless it is about namespaces.

**`Registry.for_namespace(namespace)` returns a view, and `Component.registry` hands each
component its own.** The mechanism is the one `Config.for_namespace` established in the config
rework, deliberately: a shallow `copy` sharing `_components`, `_caches` and `_executors` by
reference -- one registry per process, a view is a lens on it -- differing only in what an
*omitted* `namespace` argument means.

```python
    def _effective_namespace(self, namespace: str | None) -> str | None:
        return self._default_namespace if namespace is None else namespace
```

- On the application's registry, an omitted namespace still means **every namespace**, so
  `build()` and the lifespan keep iterating everything. Nothing about a single-agent application
  changes; `for_namespace("")` returns the registry itself, as `Config.for_namespace("")` does.
- On a view it means **that agent**, so `self.registry.get_service(OrderService)` resolves this
  agent's service, and `self.registry.get_service(EventProcessingService)` still finds the shared
  root one through the namespace-then-root fallback.
- An explicit argument wins on either.

**Calling `for_namespace` on a view raises**, as on `Config`: a view is one agent's lens, and
letting it mint another agent's would hand every component a route to its neighbours, which is
what C6 forbids.

Verified with a service written the way a project writes one -- no namespace anywhere in it:

```
  orders   self.registry.get_service(OrderService) -> orders_order_service   Audit -> audit
  billing  self.registry.get_service(OrderService) -> billing_order_service  Audit -> audit
```

One declaration, two agents, each wiring itself correctly, plus a root-registered `Audit` shared
by both.

**A hand-rolled resolution was deleted.** `EventPublishingService.on_startup` called
`resolve_for_namespace(self.registry.get_io_clients(), self.namespace, ...)` by hand, because P6
needed namespace resolution before the registry could do it. It is now
`self.registry.get_io_client(IOClientBase)` -- the view resolves it -- which is what P6's own
changelog predicted would happen to that helper.

**A bug the test rewrite caught, worth recording because the shape recurs.** `get_component`
gathered its candidates with `self.get_components_by_type(name_or_class, None)`, passing `None`
to mean "every namespace". On a *view* `None` means *this* namespace, so the resolver was handed
only the asking agent's components and its root fallback could never fire: a namespaced service
in a process with one shared root transport failed to find it. Fixed with `_all_of_type`, a
namespace-blind helper used by the two callers that must not have their argument reinterpreted
-- the class-resolution path and the message that lists candidates when it cannot choose. The
six `EventPublishingService` ownership tests were rewritten from a `MagicMock` registry onto a
**real** one for exactly this reason: the mock version asserted that a stub returned what it was
told to, and would not have caught this.

While there, the class-lookup failure message stopped printing a class repr:
"No IOClientBase is registered for namespace 'orders' or at the root" rather than
"No <class '...IOClientBase'> is registered ...".

**Tests.** 1554 unit tests pass (up from 1538). `TestNamespaceViews` (12) covers the root
identity, caching, the shared store, the C6 refusal, omitted-means-this-agent, the root fallback
for both name and class lookups, plural lookups returning one agent, an explicit override, and
the application registry still seeing everything. `TestRegistryIsScopedToTheComponent` (4) covers
the component side. The six rewritten ownership tests now exercise the real resolution.

### Still open after phase 2: cache names are not namespace-scoped yet

Spec sec. 8 requires cache *names* to be namespace-scoped by default, with an explicit opt-in for
genuinely shared caches, so that two agents both asking for `"sessions"` do not silently share a
store. Phase 1 gave the registry the name dimension that policy needs, and phase 2 gave every
component a namespace-aware view -- but `get_cache` on a view still resolves the bare name, so
the policy is not enforced.

It is left open rather than guessed at because the obvious implementation collides with something
that already exists: `CacheService.get/set/delete` take their own `namespace=` argument, which is
a *partition inside* a cache and is what a project already uses (`CACHE_NAMESPACE` in two
examples). So there are two plausible designs and they are not equivalent -- qualify the cache
*name* on the way in (`orders_sessions`, one backend per agent per name), or prefix the
*partition* the agent's calls land in (one backend, agent-scoped keys). The first isolates
storage and multiplies backends; the second keeps one backend and has to compose with the
developer's own partition argument without either silently winning. That is a decision, not an
implementation detail.

### Cache names become namespace-scoped (spec sec. 8), and the pod filesystem decides how

Sec. 8's requirement -- two independently written agents both asking for `"sessions"` must not
silently share a store once grouped -- had two plausible implementations, and the deployment
constraint settled it rather than taste.

**The constraint.** A pod may write only where its process user is allowed to, and under
`readOnlyRootFilesystem: true` only where a volume is mounted -- a mount declared in the pod spec,
not discovered at runtime. `DiskCacheService` is a directory; `RedisCacheService` is a connection.
So the design that registers **one cache backend per agent per name** multiplies the writable
paths a group needs, gives each agent its own `size_limit` over one node-backed `emptyDir` (five
agents at the 1 GB default is 5 GB against one volume, and an `emptyDir` over its limit evicts the
pod), and turns "add an agent to this group" into a change to the pod spec. The design that
**prefixes the partition** needs no new path at all.

**So the partition carries the agent.** New `services/infrastructure/agent_scoped_cache.py`:
`AgentScopedCache` wraps one shared backend and prefixes every call's `namespace` argument with
the agent, so `orders` writing `"prices"` lands in `orders.prices` and `billing` writing the same
name lands in `billing.prices`. One directory, one connection, one budget, whatever the group
size.

`Registry.get_cache` (and the `cache_service` alias) returns that lens **when asked through a
namespace view**, and the raw backend at the root -- which is unchanged behaviour for every
single-agent application, and is also sec. 8's "explicit opt-in for genuinely shared caches":
framework code holding `Component.shared_registry` gets the shared store. The lens is cached per
name per view. Nothing at a call site changes: a service writing
`self.registry.cache_service.set(key, value, namespace="prices")` is isolated without naming a
namespace, because phase 2 already gave it a namespace-aware registry.

The separator is `.`, not `:`: `:` already separates the partition from the hashed key
(`cache_key_mixin._make_key`) and `list_namespaces` splits on the first one, so `orders:prices`
would read back as the partition `orders`. A namespace cannot contain `.`, so stripping
`<agent>.` back off is unambiguous whatever the agent called its own partition.

Three methods needed more than a prefix:

- **`clear(None)` means this agent's partitions, never the whole cache.** The backend's own
  `clear(None)` would take the neighbours' data with it -- the exact accident this class exists to
  prevent -- so the lens enumerates the partitions it owns and clears those.
- **`list_namespaces()`** returns this agent's partitions with the prefix stripped, so an agent
  sees the names it used.
- **`close()` raises.** The backend belongs to the process; closing it from one agent's lens would
  take every other agent's cache down with it, silently.

`get_stats()` forwards the backend's numbers and adds the agent's name: size, hits and eviction
are properties of the one shared store, and there is nothing per-agent to report.

`ServiceBase.__init__` gained a keyword-only `should_register: bool = True`. `CacheService` is a
`ServiceBase`, so the lens is a component by inheritance, and one per agent per cache would
otherwise add a registry entry each. `RestApiBase` has taken the same parameter since before
namespaces, so this is the existing pattern rather than a new one.

### The same constraint exposed a pre-existing defect: the disk cache cannot create its directory

Read from the generated Dockerfile rather than observed in a cluster, and independent of grouping:

- `cache.cache_dir` defaults to the **relative** `.cache/blueprint`, resolved against the working
  directory, so `/app/.cache/blueprint` in the image.
- `DiskCacheService.__init__` creates it at **runtime** (`mkdir(parents=True, exist_ok=True)`).
- The image does `WORKDIR /app` **before** `USER appuser`, so `/app` is root-owned, and only
  `src/` and `settings.toml` are `--chown`ed. Creating `/app/.cache` as `appuser` therefore fails
  with EACCES.

So a container built from the generated Dockerfile, running as the user it declares, with the
default cache backend, cannot start. It has not been noticed because tests and local runs have a
writable working directory. Three changes:

- **The image creates the directory and hands it over**:
  `RUN mkdir -p /app/.cache && chown -R appuser:appuser /app/.cache`. A project scaffolded before
  this needs the same two lines.
- **The failure explains itself.** The `mkdir` is wrapped, and an `OSError` becomes a
  `RuntimeError` naming the path and the four ways out -- create and chown it in the image, mount
  a volume if the root filesystem is read-only, point `cache.cache_dir` somewhere writable, or use
  the redis backend, which needs no filesystem. The original error is kept as `__cause__`.
- **`docs/guides/deployment.md` gained "Writable Cache Directory"**: the ownership requirement,
  the `readOnlyRootFilesystem` + `emptyDir` manifest with `sizeLimit` matched to
  `cache.size_limit`, the note that a grouped process needs no additional paths, and redis as the
  filesystem-free alternative.

**Tests.** 1577 unit tests pass (up from 1554). 21 new in `test_agent_scoped_cache.py`, against a
**real** `DiskCacheService` rather than a mock, since what is under test is which keys end up
where: isolation of values, absence rather than a neighbour's value, one backend, the partition
carrying the agent, per-agent `list_namespaces`, the scoped default partition, per-agent `delete`
and `claim` (two schedulers must not steal each other's tick slots), both `clear` shapes, the
`close` refusal, the root-namespace refusal, not registering itself, and the six paths through the
registry. Two more in `test_disk_cache_service.py` cover the unwritable directory: the message
names the path and the options, and the original `PermissionError` survives as the cause.

### Not fixed, found while doing this: `app_environment` in `[default]` selects nothing

The bootstrap pass runs with `environments=False`, so it sees only top-level keys -- `[default]`
arrives as one opaque value. All five examples declare `app_environment` *inside* `[default]`, where
that pass cannot read it, so it never selects an environment: it only lands in the loaded tree as a
value that `config.get("app_environment")` returns. A project that adds a `[production]` section and
sets `app_environment = "production"` under `[default]` gets `[development]` loaded and no warning.
Only a top-level `app_environment`, or `DYNACONF_APP_ENVIRONMENT`, actually switches sections.

Pre-existing and out of this step, and the fix is not obviously safe -- honouring the sectioned key
would change which section an existing project loads. Left as a decision to take, not a defect to
patch inside a config change.

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

### Phase 3, part 1 -- a namespace can be named at the call site, and a group can be written by hand

Phase 0 part 3 made the namespace ambient, and phase 1 and 2 made the registry answer per
namespace. What was still missing is the *entry point*: nothing outside `AgentRegistration.apply`
could put a component in a namespace, and there was no way to assemble a group at all. This step
adds the three builder-side pieces of phase 3; `with_cache(name=...)` follows as part 2.

**The five `with_*` methods take a keyword-only `namespace`, and it never reaches the component.**
Their bodies were five copies of "build it if it is a class, adopt it if it is not, rename it if
asked", so they now share one helper and differ only in the type check `with_handler` performs:

```python
    def with_handler(
        self, handler: type[HandlerT] | HandlerT, *, name: str | None = None, namespace: str = ROOT_NAMESPACE, **kwargs: Any
    ) -> "AppBuilder":
        if isinstance(handler, type) and not issubclass(handler, EventHandlerBase):
            raise TypeError(f"Expected EventHandlerBase subclass, got {handler.__name__}")
        self._register(handler, namespace, kwargs, name=name, method="with_handler")
        return self
```

`AppBuilder._register` is where the namespace is turned into a scope rather than an argument:

```python
        if isinstance(target, type):
            with _construction_scope(namespace):
                instance = target(**kwargs)
```

This is the point of the whole ambient mechanism, and it is why the parameter cannot simply be
forwarded. The builder passes `**kwargs` straight to the constructor, and a project's component
takes the arguments its author wrote -- `StrictService(retries=3)`, no namespace anywhere -- so
`with_service(StrictService, namespace="orders", retries=3)` must construct
`StrictService(retries=3)` *inside* namespace `orders` and let `Component.__init__` read the
namespace from the context variable. Forwarding it would be a `TypeError` on every component a
developer has ever written.

**`_construction_scope` exists because `namespace_scope("")` is not a no-op** -- it *sets* the
current namespace to the root:

```python
@contextmanager
def _construction_scope(namespace: str) -> Iterator[None]:
    if not namespace:
        yield
        return
    with namespace_scope(namespace):
        yield
```

Without that branch this step would have broken the mechanism it is extending.
`AgentRegistration.apply` opens one `namespace_scope("orders")` and then calls
`builder.with_service(target, name=...)` with no namespace argument -- so an unconditional
`namespace_scope(namespace)` would reset every component of every agent back to the root, with no
error, and every registration applied per agent would have produced a root component. There is a
test for exactly this (`test_the_default_does_not_reset_an_ambient_namespace`), because the failure
is invisible: the app builds, and the registry keys are simply wrong.

**An explicit `name=` is now qualified with the namespace the component ended up in:**

```python
        if name is not None:
            instance.name = qualified_component_name(namespace_of(instance), name)
```

A defect, not a refinement. `Component.__init__` qualifies a *derived* name but uses an explicit
one verbatim, so `AgentRegistration().with_service(OrderService, name="db")` applied to two agents
registered both as `db` and the second failed with "Component with name db already exists" -- the
one-declaration-per-group case, which is the primary API. Qualifying costs the caller nothing:
`Registry._lookup` tries `<namespace>_<name>` before `<name>`, so `get_component("db")` from
inside the agent still finds it. `namespace_of(instance)` rather than the `namespace` argument,
because the instance may have come from the ambient scope instead.

**An already-built instance offered to a namespace is refused rather than silently rerouted.**
A component's namespace and its registry key are fixed by the scope it was constructed in, so
`with_service(instance, namespace="orders")` cannot do what it says:

```python
            built_in = namespace_of(target)
            if namespace and built_in != namespace:
                raise ValueError(
                    f"{type(target).__name__} was passed to {method}() as an instance for namespace '{namespace}', "
                    f"but it was already built in namespace '{built_in or ROOT_LABEL}', and a component cannot change "
                    ...
                )
```

Ignoring the argument would register the component at the root while the caller believed it
belonged to an agent -- the same trap `AgentRegistration._add` already refuses instances for, and
the message points the same way: pass the class. An instance built inside the matching scope is
accepted, since nothing is being changed.

**`NamespaceBuilder` is one agent's view of the builder**, and it holds no build state: five
`with_*` that delegate with `namespace=` filled in, `with_registration`, and `end()` returning the
parent. Registering a component therefore still has exactly one implementation, and this class only
decides which namespace it goes to. It has no `with_cache` -- a cache is process-wide (spec sec. 8),
and an agent registering its own would duplicate or quietly take over a neighbour's.

**`AppBuilder.with_namespace(name, *, registration=None)`** is the entry point:

```python
        namespace = validate_namespace(name)
        if not namespace:
            raise ValueError("with_namespace('') names no agent: ...")
        if namespace not in self._namespaces:
            self._namespaces.append(namespace)
            logger.info("Hosting agent namespace '%s'", namespace)
        if registration is None:
            return NamespaceBuilder(self, namespace)
        return self.with_registration(registration, namespace)
```

`with_namespace("")` is refused: the root is the absence of an agent, and returning a block that
registers into it would be a silent no-op dressed as a declaration. The namespace is recorded
*before* anything is built, so a registration that fails half way through still leaves the agent
declared -- the startup log (spec sec. 9.2) and the readiness policy have to be able to say an
agent was meant to be here.

**Two spec departures, both argued rather than assumed.**

- **The `AppBuilder | NamespaceBuilder` union is kept, but no caller sees it.** Spec sec. 4.2
  types `with_namespace` as returning the union, which would make every call site narrow a type
  it already knows statically. Two `@overload`s resolve it instead: `registration=<a
  registration>` is an `AppBuilder`, `registration` omitted is a `NamespaceBuilder`. The runtime
  behaviour is exactly what the spec asks for; the union survives only as the implementation
  signature.
- **The `config: Config | None` parameter is not accepted.** Spec sec. 4.2 and the plan both list
  it, and the plan says `with_namespace` should build a `Config` with `agent_scope=name` from the
  root config's settings files. Config rework step 2 made that obsolete: `Config.for_namespace`
  returns a view sharing the one loaded tree, and `Component.config` already hands each component
  the view for its own namespace, which tries `<agent>.<key>` before `<key>` (C5). A `Config`
  passed here would have no reader -- components do not consult the builder -- so it would be
  either ignored outright or re-parse the same files once per agent and then be ignored. Accepting
  a parameter that does nothing is worse than not having it: it reads as per-agent configuration
  support that is not there. **Needs a spec amendment**; listed under *Open points*.

**`AppBuilder.namespaces`** exposes the declared agents in declaration order, root excluded, so
phase 6 can iterate them. It lives on the builder because it may not live on the registry:
`Registry` is reachable from every component (C6), so a `get_known_namespaces()` there would let
an agent enumerate its neighbours, and grouping is supposed to be invisible from inside. The
builder is the object that was *told* which agents to host and is not reachable from a component.
A tagged `with_service(X, namespace="orders")` deliberately does *not* record a namespace: the
list is what the builder was told to host, not every namespace a component was tagged with.

`NamespaceBuilder` is exported from `blueprint.agents`, since it is a return type callers can hold.

Tests: `tests/unit/agents/app_builder/test_namespace_builder.py`, 36 cases -- the namespace
qualifying the registry key and reaching the component; the constructor *not* receiving it; the
ambient namespace surviving the default and being overridden by an explicit one; an explicit name
qualified, unchanged at the root, and one declaration with an explicit name serving two agents; an
instance refused for another namespace and accepted for its own; both `with_namespace` forms; the
root and an illegal namespace refused; `namespaces` order, dedup and its indifference to tagged
calls; and the block delegating, chaining, closing and carrying constructor arguments.

### Phase 3, part 2 -- a cache has a name, and a name buys it its own store

Phase 1 part 2 gave the registry `add_cache(name, cache)` / `get_cache(name)` and no fallback
between names. The builder never used any of it: `with_cache()` still went through the
`cache_service` setter, so a process could hold exactly one cache. This step is the builder side,
and three defects had to be fixed for it to work at all.

**The signature change, and why the parameter order is the whole point:**

```python
    def with_cache(self, enabled: bool = True, enable_locking: bool = True, *, name: str = DEFAULT_CACHE_NAME) -> "AppBuilder":
        if not enabled:
            logger.info("Caching disabled; cache '%s' is not registered", name)
            return self

        cache_config = _cache_config_for(self._config.get_cache_config(), name)
```

`name` is keyword-only and follows the two existing positional parameters, as spec sec. 4.2
requires. Had it come first, `with_cache(False)` -- which *disables* caching in projects that
exist today -- would have become a cache named `False` with caching silently switched on, no
`TypeError` and no warning. `with_cache()`, `with_cache(False)` and `with_cache(True, False)` all
still mean exactly what they meant, and there are tests for the three of them.

**Turning a name into isolated storage lives in `CacheBackendFactory`, not in the builder.**
It was written in `app_builder.py` first and moved on review, and the review was right: the
builder would have been the one place that knew disk caches isolate by directory and Redis caches
by key prefix. Anyone adding a third backend edits the factory and has no reason to open the
builder, so their backend would have inherited one store shared across every name -- the exact
failure the scoping exists to prevent, arrived at by writing new code in the obvious place. So
`create` takes the cache name and each `_create_*` scopes what its own backend needs:

```python
    @staticmethod
    def create(config: CacheConfig, enable_locking: bool = True, name: str = DEFAULT_CACHE_NAME) -> CacheService:
        CacheBackendFactory._validate_name(name)
        if config.backend == "redis":
            return CacheBackendFactory._create_redis(config, enable_locking, name)
        return CacheBackendFactory._create_disk(config, enable_locking, name)
```

`create` is the single door through which a cache is built, so the name cannot arrive
unvalidated and a backend cannot be reached without having answered how it separates one name
from another. The builder is left with one line and no cache knowledge:

```python
        cache_service = CacheBackendFactory.create(self._config.get_cache_config(), enable_locking=enable_locking, name=name)
```

`config` reaches the factory **unscoped**. That matters for the fallback: `_create_redis` scopes
a key prefix, and when Redis is unreachable it hands `_create_disk` the original config plus the
name, so the fallback isolates by directory rather than carrying a prefix that means nothing to
it. Pre-scoping both fields before the branch -- what the first version did -- only worked because
it scoped fields no chosen backend would read.

The two derivations, each on the backend that needs it. The default name returns the configured
value untouched, so an existing application's cache directory and Redis keyspace do not move:

```python
    def _scoped_cache_dir(config: CacheConfig, name: str) -> str:
        if name == DEFAULT_CACHE_NAME:
            return config.cache_dir
        return str(PurePosixPath(config.cache_dir.replace("\\", "/")) / name)

    def _scoped_key_prefix(config: CacheConfig, name: str) -> str:
        if name == DEFAULT_CACHE_NAME:
            return config.key_prefix
        return f"{config.key_prefix}:{name}" if config.key_prefix else name
```

- **Disk: `<cache_dir>/<name>`, a subdirectory and not a sibling.** The plan says
  `{base_dir}/{name}` without saying which directory `base_dir` is, and only one reading is always
  writable: a deployment may mount its volume *at* `cache.cache_dir`, and under
  `readOnlyRootFilesystem` a sibling of the mount cannot be created -- see "Writable Cache
  Directory" in `docs/guides/deployment.md`. The cost is that a named cache's directory sits
  inside the default cache's own store. diskcache ignores directories it did not create, and the
  alternative fails in production only.
- **Redis: the name is appended to `cache.key_prefix`.** *Not in the plan, and without it naming a
  cache would have isolated nothing on Redis.* The disk backend separates caches by directory and
  Redis has no analogue -- `RedisCacheService` scopes every key by `key_prefix` alone -- so two
  caches registered as `sessions` and `prompts` against one Redis with one configured prefix would
  have written the same keys. That is precisely the silent cross-cache sharing spec sec. 8 exists
  to prevent, and here the name is the only thing meant to tell them apart.

**The cache name is validated, because it is now a filesystem path segment:**

```python
_ALLOWED_CACHE_NAME = re.compile(r"\A[a-z0-9][a-z0-9_.-]*\Z")
```

`with_cache(name="../evil")` would otherwise write outside the cache directory entirely. Lower
case only, and that is not tidiness: a directory whose name differs only by case is one directory
on a developer's macOS or Windows machine and two on the Linux node, so `Sessions` and `sessions`
would be one cache locally and two in production. Validation runs before anything is constructed,
so a refused name never creates a directory.

**Three defects fixed to get here.**

1. **Two caches collided on one registry name.** A `CacheService` is a `ServiceBase` and therefore
   a `Component`, so it registers itself under a derived name -- and a second `DiskCacheService`
   raised `Component with name disk_cache_service already exists`. Registering a named cache
   without a component entry was not an option: the lifespan closes caches by iterating
   `registry.get_services()`, so an unregistered one would leak its file handle or Redis
   connection for the life of the process. `DiskCacheService.__init__` and
   `RedisCacheService.__init__` therefore take `component_name`, forwarded to
   `super().__init__(name=...)`, and `CacheBackendFactory.create` passes it through:

   ```python
    @staticmethod
    def _component_name(name: str) -> str | None:
        return None if name == DEFAULT_CACHE_NAME else f"cache_{name}"
   ```

   `None` for the default, so `disk_cache_service` stays the key existing lookups and health
   entries already use. `cache_<name>` rather than `<class>_<name>` because `fallback_to_local`
   swaps `RedisCacheService` for `DiskCacheService` at construction -- a registry key that depends
   on whether Redis answered the startup ping is worse than one that does not name the backend.
   Both fallback paths therefore produce the same registry name as the Redis service would have.

2. **`with_cache()` as an application's first builder call crashed.** `Component.shared_registry`
   is `None` until the first `Component.__init__` creates it, and a cache service is what creates
   it here. Reading the registry before building the service is an `AttributeError` on `None`; the
   old code happened to read it afterwards. The order is now explicit and commented, because
   nothing about the line says it matters:

   ```python
        cache_service = CacheBackendFactory.create(cache_config, enable_locking=enable_locking, component_name=component_name)
        registry: Registry = Component.shared_registry  # type: ignore[assignment]
        registry.add_cache(name, cache_service)
   ```

3. **`registry.add_cache` replaced the `cache_service` setter.** The setter still exists as the
   spec sec. 8 alias and still reads and writes the `"default"` cache, so `registry.cache_service`
   keeps working; the builder simply no longer goes through it.

`CacheBackendFactory.create`'s third parameter is `name`, not `component_name`: the registry name
is derived from the cache name, so there is one name to pass rather than two that must agree.

**Not done here, and deliberately.** Readiness and the management endpoints still see only the
default cache -- `if registry.has_cache(): health_providers["cache"] = ...` and the `CacheManagementApi`
mount are both keyed on the default name. Plan phase 6 owns both ("`CacheManagementApi`: one router,
endpoints accept optional `?name=`" and "`ActuatorApi` cache health: iterates all entries"), so a
project that registers only a named cache gets no cache health check until then. Nothing regresses:
those call sites are guarded by `has_cache()` and simply do not fire.

Also noted rather than fixed: `add_cache`'s documented replace-and-warn path is unreachable from
the builder, because two `with_cache()` calls with one name now collide on the *component* name
first. That was already true before this change, and the resulting error names the colliding key.

Tests, split the way the code is. `tests/unit/agents/app_builder/test_named_caches.py`, 33 cases,
covers what is visible through `with_cache`: the default cache keeping its name, directory,
registry key and `cache_service` alias; `with_cache()` working as an application's first builder
call; the three positional forms; a named cache getting its own directory (asserted on disk), its
own registry name, coexisting with the default, and appearing in `get_services()` so the lifespan
closes it; an unregistered name raising instead of yielding the default; and eleven rejected names.
`tests/unit/agents/services/infrastructure/test_cache_backend_factory.py` gains 34 cases for the
isolation itself: the derived registry name and its independence from the backend; the disk
subdirectory including a Windows separator in the configured path; the Redis prefix, asserted both
on the derivation and on the kwargs the service is constructed with; both fallback paths isolating
as disk rather than as Redis; and the name being validated before any directory is created.

### Phase 4, part 1 -- dispatch happens per agent, and the root stops reaching into one

Phase 1 and 2 made the registry answer per namespace and gave every component its own view of
it. The dispatch path never used any of that: one `HandlerChain` served the process, and it asked
the *application's* registry for handlers -- which in a grouped process means every agent's. This
step makes an event reach one agent's handlers and no other's. The dispatch index (spec sec. 7.7,
the second half of plan phase 4) is a separate step and is not in this one.

**A `HandlerChain` now belongs to a namespace, and that is the only line about it in the class:**

```python
    def __init__(self, namespace: str = ROOT_NAMESPACE) -> None:
        super().__init__(should_register=False, namespace=namespace)
```

Everything else follows from `Component.registry` and `Component.config` handing a component its
own namespace's view: the handlers it dispatches to, the `idempotency_enabled` / `idempotency_ttl`
it reads, and the cache partition the dedup markers are claimed in (the agent-scoped lens from
spec sec. 8) are all that agent's already, with no further plumbing. Two agents in one process can
therefore run different dedup windows, and the tests assert exactly that against one settings
tree.

**The namespace is named explicitly in `_dispatch`, and that is the load-bearing part:**

```python
        handlers = sorted(self.registry.get_event_handler(namespace=self.namespace))
```

It looks redundant -- the registry view already defaults to its own namespace -- and it is not.
`Registry.for_namespace("")` returns the registry *itself*, whose `_default_namespace` is `None`,
and on the registry an omitted namespace means **every namespace**. So a root chain in a grouped
process would have dispatched one delivery through every agent's handlers. Naming the namespace
makes the root chain mean strictly the root, which in a single-agent application is every handler
there is -- unchanged. `test_the_root_chain_does_not_reach_into_an_agent` is the test for it.

There is deliberately **no fallback to root handlers** either, unlike the singleton lookups that
resolve namespace-then-root. A handler registered at the root of a grouped process would
otherwise run for every agent in it, and nothing in a handler's code could tell its author that
was happening.

**`EventProcessingService` keeps one chain per agent and stays a single root service.** What it
does -- correlation context, request ids, Dapr unwrapping, normalising handler output -- is the
same for every agent; what differs is the dispatch. So:

```python
        self._handler_chains: dict[str, HandlerChain] = {ROOT_NAMESPACE: HandlerChain()}
```

The root chain always exists, so an application that never mentions a namespace behaves exactly
as it did. `_chain_for(namespace)` creates the others:

```python
        chain = self._handler_chains.get(namespace)
        if chain is None:
            chain = HandlerChain(namespace=namespace)
            self._handler_chains[namespace] = chain
```

**The chains are built at startup, not on first delivery**, and the namespaces come from the
handlers rather than from a list of agents:

```python
        for namespace in sorted({namespace_of(handler) for handler in self.registry.get_event_handler()}):
            self._chain_for(namespace)

        for namespace, chain in self._handler_chains.items():
            await chain.on_startup()
```

A chain's startup resolves its idempotency policy, and the existing guarantee is that a
misconfigured dedup window fails the pod rather than the first event. That guarantee is *per
agent*: built lazily, a group whose second agent has a bad `idempotency_ttl` would start cleanly
and fail on a delivery hours later, while the first agent's clean startup said nothing about it.

Reading the namespaces off the registered handlers is not a way around C6. The registry
deliberately cannot enumerate agents, and this service is not the builder -- but what it needs is
not "which agents exist", it is "which namespaces have handlers to dispatch to", and the handlers
are the authority on that. `_chain_for` stays lazy for anything that arrives later, because a
handler registered after startup should produce a dispatch that finds nobody -- an outcome the
acknowledgement contract already has a disposition for -- rather than a failed delivery.

**`process_event` and `process_rest_request` take a keyword-only `namespace`.** Keyword-only
because both already have positional tails that existing callers use; `""` is the root, which is
what every caller that does not know about agents gets.

**The publishing-service lookup became namespace-aware, and that was a latent crash:**

```python
                    # This agent's publishing service, falling back to a root one. Not the
                    # unscoped lookup this used to be: with one publishing service per
                    # namespace (P6) that finds several and refuses to choose, so a grouped
                    # process would fail on the first handler that returns an event_type.
                    publisher = self.registry.get_component(EventPublishingService, namespace=namespace)
```

P6 already gives each namespace its own `EventPublishingService`. The old call passed no
namespace, which on the application's registry means "search every namespace and raise if more
than one matches" -- so the first handler in a grouped process to return a `HandlerResult` with an
`event_type` would have raised `Multiple components of type EventPublishingService found`. With
`namespace=""` the lookup is restricted to the root, which is where the only publishing service in
a single-agent application lives.

**The two call sites pass their own namespace**, which is what makes the parameter reach anything:

- `CloudEventProcessorMixin._dispatch_cloud_event` passes `namespace=self.namespace` -- the
  namespace of the transport endpoint that received the delivery. Its docstring's contract grew
  from "a class that supplies a `registry` attribute" to `registry` and `namespace`.
- `RestApiBase._process_resource` passes `namespace=self.namespace`, so a REST call into one agent
  is not offered to another agent's handlers.

Both are the root today, so both are today's behaviour today; they become per-agent the moment
phase 5 and 6 give each namespace its own endpoints.

**Not in this step.** The plan's third phase-4 bullet -- "wire previously unused `runtime_name`:
after the chain picks a winner, resolve the agent via `get_runtime_name()`" -- depends on
`EventHandlerBase.get_runtime_name`, which phase 7 adds. The spec's own compatibility table
(sec. 10) records `runtime_name` as only logged today, so it stays logged; the namespace is now
logged alongside it.

Tests: `tests/unit/agents/services/eventing/test_event_processing_namespaces.py`, 18 cases against
real `Config`, `Registry`, `HandlerChain` and handler subclasses rather than mocks -- an event
reaching one agent's handler and not the other's; a namespace with no handler returning
`NO_HANDLER_FOUND` rather than raising; the root chain not reaching into an agent; a root handler
not running for an agent; a single-agent application dispatching as before over both `process_event`
and `process_rest_request`; one chain per namespace with handlers, each carrying its own namespace
and resolving its own agent's dedup policy from one settings tree; a chain created on first use for
an unknown namespace and reused across deliveries; an illegal namespace refused; and four cases for
`HandlerChain` itself, including that it is still not a registered component. The three
mock-based lifecycle tests in `test_event_processing_service.py` were updated to the chain map and
one added for the per-namespace startup.

### Phase 4, part 2 -- a handler can say what it wants, and stops being asked about the rest

`_dispatch` asked every registered handler's `can_handle` in turn until one said yes, so a
process hosting fifty handlers awaited fifty coroutines to find the one that wanted the event.
Grouping multiplies exactly that, because a group's handlers all live in one process. Spec
sec. 7.7 asks for an in-process dispatch index; this is it.

**The declaration: `EventHandlerBase.get_handled_event_types()`**, defaulting to `[]`. It joins
the two declaration methods already on the class (`get_published_event_types`,
`get_subscribed_topics`) and is a *selection hint, not a selector* -- `can_handle_event` still
decides, and a declared handler is still asked and may still say no.

**The default means "offer me everything", and getting that backwards is the whole risk.** No
handler in this framework or in any scaffolded project declares an event type today, so an index
that read an empty declaration as an empty set would silence every handler that exists -- and
because an unhandled event acknowledges (spec sec. 7.2), the deliveries would be consumed and
discarded rather than piling up anywhere visible. Spec sec. 7.7 calls this "the most destructive
failure mode available in this design".

**`DispatchIndex`** is a frozen dataclass with two fields and one question:

```python
    by_type: dict[str, tuple[EventHandlerBase, ...]]
    wildcard: tuple[EventHandlerBase, ...]

    def candidates(self, event_type: str) -> tuple[EventHandlerBase, ...]:
        return self.by_type.get(event_type, self.wildcard)
```

`by_type[t]` already holds the *merged* candidate list -- the handlers that declared `t` plus
every wildcard handler -- so dispatch is one dictionary lookup and no per-event merging or
sorting. An event type nobody declared falls back to `wildcard`, because a type no handler named
is not a type no handler wants.

**The candidate lists are built by filtering the priority-sorted order, not by concatenating
buckets:**

```python
        wildcard = tuple(handler for handler, declared in declarations if not declared)
        by_type = {
            event_type: tuple(handler for handler, declared in declarations if not declared or event_type in declared)
            for event_type in {event_type for _, declared in declarations for event_type in declared}
        }
```

Concatenating `typed + wildcard` and sorting would have put declared handlers ahead of undeclared
ones *of equal priority*, and priority ties are currently resolved by registration order --
something a project may be relying on without having said so. Filtering the already-sorted list
means the sequence a handler is tried in is exactly the sequence it would have been tried in
without an index. There is a test comparing the two orders.

**A declaration that looks like a pattern is refused, at startup:**

```python
        if _WILDCARD_IN_DECLARATION.search(event_type):
            raise ValueError(
                f"Handler '{handler.name}' declares the event type '{event_type}', which looks like a pattern. "
                "Declarations are matched by equality, so this handler would never be asked about any event. ..."
            )
```

This is not defensive tidiness, it closes a hole the new API opens. Declarations are matched by
equality, so `get_handled_event_types() -> ["order.*"]` is a type no event ever has: the handler
would go in the typed bucket for the literal string and never be asked about anything -- the same
silent silencing, reintroduced by the very method meant to avoid it. Blank declarations are
refused for the same reason. Both fail while the pod is starting, naming the handler.

**The index is built once at startup, and checked on every dispatch.** `on_startup` builds it (so
a malformed declaration fails the pod) and logs how many handlers are offered every event against
how many event types are declared -- the observable evidence that nothing was silenced. But
`_candidates` re-reads the handlers:

```python
        handlers = self._handlers()
        if self._index is None or handlers != self._indexed:
            self._indexed = handlers
            self._index = DispatchIndex.build(handlers)
        return self._index.candidates(event_type)
```

Before the index, the chain queried the registry per event, so a handler registered after startup
was picked up automatically. A purely startup-built index would drop it silently, which is the
class of failure this design is most careful about. The check costs exactly what the old code
already paid -- one registry query and now a tuple comparison instead of a sort -- while the index
still removes the `can_handle` await per handler, which is the expensive part. `HandlerChain`
being unregistered means nothing calls its `on_startup` when it is used outside `AppBuilder`, and
the same branch covers that.

**`SessionsJobHandler` opts in without its subclasses writing anything.** Its `can_handle_event`
was `event.type == f"sessions.job.created.{self.JOB_TYPE}"`; that string now has one definition:

```python
    @property
    def job_created_event_type(self) -> str:
        return f"sessions.job.created.{self.JOB_TYPE}"

    def get_handled_event_types(self) -> list[str]:
        return [self.job_created_event_type]
```

`can_handle_event` reads the same property. Written out twice the two could drift, and a
declaration that no longer matches the check is a handler the index never offers an event to --
which is why the property exists rather than a second f-string. A subclass opts in by setting the
`JOB_TYPE` class variable it already had to set.

`_dispatch` was also split: `_handlers()` now owns the namespace-scoped registry query (with the
explanation of why the namespace is named explicitly, from part 1), and `_dispatch` itself asks
`_candidates(event.type)`. The `handlers.count` span attribute keeps its meaning -- how many
handlers this dispatch will walk -- and the debug line now reports candidates against the total.

Tests: `tests/unit/agents/handler/test_dispatch_index.py`, 24 cases -- an undeclared handler being
a candidate for every event type, including alongside a declared one, and an undeclared-only
application indexing to nothing at all; declarations narrowing who is asked, every declared type
keyed, and an unknown type falling back to the wildcard handlers or to nobody; candidate order
identical to the unindexed order and priority still deciding; dispatch asking only the candidates,
the chain-of-responsibility fallthrough surviving, and an event no candidate wants returning
`None`; a pattern and a blank declaration refused with the handler named, and the refusal landing
on `on_startup`; the index built at startup, not rebuilt when nothing changed, rebuilt for a
handler registered afterwards, and built on demand for a chain nobody started; and two agents in
one process indexing only their own handlers. One mock-based test in
`test_event_processing_service.py` grew a small stub handler, because a bare `MagicMock` is no
longer sortable now that startup indexes.

### Phase 5, part 1 -- a transport endpoint subscribes for one agent, and only for one agent

P6 gave each namespace its own `NATSClient`, with the queue group and the durable derived from
the namespace. What still ran once for the whole process was the thing that decides *what to
subscribe to*: `NatsEventing` and `DaprEventing` each collected topics from
`registry.get_event_handler()` with no namespace, which on the application's registry means every
agent's handlers, and deduplicated the result globally.

Both of those are wrong in a group, and the second is wrong in the way spec sec. 7.6 singles out.

**The endpoints are namespace-owned.** `NatsEventing(namespace=...)` and
`DaprEventing(namespace=...)`, so phase 6 can build one per agent:

```python
    def __init__(self, namespace: str = ROOT_NAMESPACE) -> None:
        super().__init__(should_register=False, namespace=namespace)
```

That needed `RestApiBase.__init__` to accept a namespace, since `EventHandlingBase` is a
`RestApiBase`:

```python
    def __init__(self, should_register: bool = True, *, namespace: str = ROOT_NAMESPACE) -> None:
        super().__init__(should_register, namespace=namespace)
```

Keyword-only, defaulting to the root, and every existing subclass already calls
`super().__init__()` or `super().__init__(should_register=False)` by keyword -- so nothing
changes for a developer's API, which still gets its namespace from the ambient scope. The
framework's own per-agent endpoints are constructed outside any scope, which is why they name it.

**Each endpoint resolves its own agent's client:**

```python
        self._client = self.registry.get_component(NATSClient, namespace=self.namespace)
```

Unscoped, this raised `Multiple components of type NATSClient found` the moment a second agent
joined the process -- P6 created the clients but nothing had been taught to pick between them.
With `namespace=""` the lookup is restricted to the root, which is where a single-agent
application's only client is.

**`NatsEventing._declared_topics` is new and is where the per-agent scope lands:**

```python
        topics: dict[str, None] = {}
        for handler in self.registry.get_event_handler(namespace=self.namespace):
            for topic in handler.get_subscribed_topics():
                if topic:
                    topics[topic] = None
        for topic in self.config.get_nats_subscription_config():
            if topic:
                topics[topic] = None
        return list(topics)
```

Two sources, handler declarations first and the configured list second, both already scoped to
this agent -- `self.registry` and `self.config` are this namespace's views, so
`orders.nats_subscriptions` resolves before the shared list (C5) with nothing here saying so.
`DaprEventing._declared_topics` took the same namespace argument, which scopes both halves of the
Dapr path at once: the sidecar's subscription document and the readiness hand-off to `DaprClient`.

**Deduplication is now per agent because it cannot be anything else.** The `dict` above lives
inside one endpoint, and one endpoint serves one namespace, so a cross-agent "first declaration
wins" is not something that has to be avoided -- it is unreachable. That is the point of spec
sec. 7.6: two agents subscribing to one topic both want the event, and a global dedup would
silently disable one of them, invisibly to an author who runs that agent alone.

**The unhandled and duplicate counters were attributing every event to the root.** Both are
documented as per-namespace and both were hardcoded:

```python
-            _DUPLICATE_EVENTS.add(1, {"namespace": ROOT_NAMESPACE, "topic": topic})
+            _DUPLICATE_EVENTS.add(1, {"namespace": self.namespace, "topic": topic})
```

In a group that would have reported one agent's over-broad subscription as everybody's, which is
precisely the signal spec sec. 7.7 wants those counters to carry. The value is the namespace
verbatim rather than `ROOT_LABEL`, so a single-agent application keeps emitting `""` and its
existing dashboards do not suddenly see a new label value.

**Two plan bullets are already satisfied, and one of them must not be implemented as written.**

- **"`NATSClient` consumer identity (C1)"** -- the durable `f"{namespace}-{topic}-durable"` and
  `queue=namespace` landed with P6. Part 2 of this phase adds the invariant test the plan asks
  for.
- **"Give each namespace's JetStream consumer a `filter_subjects` set"** -- already true, in a
  better form, and building it as written would make things worse. The client creates **one
  durable per `(namespace, topic)` pair** with `filter_subject=topic`
  (`nats_client.py:_consumer_config`), so the filter set of a namespace *is* the union of its
  declared topics and its `nats_subscriptions`, one consumer per element. The plan's own
  objection to a multi-subject filter is the reason to keep it that way: "a filter that follows
  handler churn turns adding one handler into a consumer reconfiguration -- and possibly a
  redelivery storm on deploy". With one consumer per topic, declaring a new topic *adds* a
  consumer and never rewrites one, so there is no reconfiguration to be had. Collapsing several
  topics into one consumer with a `filter_subjects` set would reintroduce exactly that.

  The fan-out the bullet worries about is not removable at this layer either: spec sec. 7.6
  *requires* one consumer per `(namespace, topic)`, so a broad subject selected by three agents
  is copied three times by definition. Sec. 7.7 asks for that to be *observable*, not absent, and
  the plan puts the reporting in `asbs validate`.

**Also not implemented as written: "iterate `registry.get_known_namespaces()`".** That method
deliberately does not exist -- the registry is reachable from every component, so it would let an
agent enumerate its neighbours (C6). It is not needed: with one endpoint per agent, each one
knows only its own namespace, which is all the collection needs.

**Still to come in phase 6.** The Dapr path mounts `POST /events/{topic}` and
`GET /dapr/subscribe` on the endpoint's router, and two agents' routers would collide on both
paths. Phase 6 owns the route namespacing and the `_eventing_component` list that creates these
per agent; nothing in this step creates more than one, so nothing collides yet.

Tests: `tests/unit/agents/io/api/eventing/test_eventing_namespaces.py`, 18 cases -- an endpoint
subscribing its own handlers' topics and not another agent's; two agents on one topic both
getting it, for both transports; a topic declared twice inside one agent subscribed once; the
agent's own `nats_subscriptions` winning and falling back to the shared list; handler topics
ordered before configured ones; each endpoint resolving its own namespace's client and a root
endpoint resolving the root one; only this agent's topics reaching the client; the Dapr
subscription document holding one agent's topics and a root document unchanged; and namespace
ownership, including that an illegal namespace is refused and that endpoints stay unregistered.

### Phase 5, part 2 -- C1 gets the regression test the plan asks for

No production change. The plan marks the consumer identity "**C1 -- invariant, cover with a
test**", and the invariant was the one thing about P6's naming that nothing checked: the durable
and the queue group are derived from the namespace, and the tests proved they *are* -- but nothing
proved a deployment value cannot get in.

That is the failure worth a permanent guard rather than a review. A durable that picks up the
group name becomes a *different* durable the moment the agent is moved between groups, and a
fresh JetStream consumer resumes according to its delivery policy: the agent either replays the
stream from the beginning or silently skips whatever arrived while it was being renamed. Nothing
in the process reports either. And the temptation is real, because the connection name
(`f"{namespace}.{group}.{pod}"`) is right there in the same class and carries both values.

`TestConsumerIdentityIgnoresTheDeployment` in `tests/unit/agents/clients/io/test_nats_client.py`,
four cases. Each derives the queue group and the durable, changes the deployment, and derives them
again from the same client -- so what is asserted is the derivation rather than a value cached at
subscribe time:

- the group name changing leaves both identifiers untouched;
- the pod name changing leaves both untouched (a pod name in a durable would mean a new consumer
  on every restart);
- the connection name *does* change across the same edit, which is the positive half: the
  deployment is visible where attribution needs it and nowhere else;
- the JetStream `ConsumerConfig` carries `durable_name`, `filter_subject` and `deliver_group`
  derived from the namespace and the topic, and neither the group nor the pod appears anywhere in
  it.

**The tests were verified to fail.** Injecting `BLUEPRINT_GROUP` into `_durable_for`'s prefix
fails three of the four; injecting `POD_NAME` fails all four. An invariant test that passes
against a broken implementation is worse than no test, so this was checked rather than assumed.

The last case doubles as the record of why part 1 does not build a `filter_subjects` set: one
durable per `(namespace, topic)` filtering one subject means declaring a topic *adds* a consumer
and never rewrites one, so there is no filter to churn and no reconfiguration to migrate.

### Phase 6, part 1 -- build() wires a transport per agent, and none for an agent that needs one not

Phase 5 made a transport endpoint able to subscribe for one agent. Nothing created more than one:
`build()` still made a single client and a single endpoint for the whole process, so every agent
in a group would have shared the root's connection and the root's subscription set -- which is
neither what spec sec. 6 asks for nor what phase 5's endpoints were built to do.

**`_eventing_component` became `_eventing_components: list[...]`**, and the decision moved into
one method per agent:

```python
        event_bus_type = str(self._config.get("event_bus", "") or "").strip().lower()
        for namespace in self.hosted_namespaces:
            self._wire_transport(registry, namespace, event_bus_type)
```

`event_bus` is read once, from the root: one transport type per process is a stated boundary of
this plan (mixing NATS and Dapr is out of scope). What is decided per agent is *whether* that
agent gets a client, and whether it gets an endpoint.

**`AppBuilder.hosted_namespaces`** is the list `build()` iterates -- the root first, then each
declared agent. It is deliberately not `namespaces`, which is only what `with_namespace` was
told: that property answers "which agents was this builder asked to host", this one answers
"which namespaces does `build()` have to walk", and they differ by exactly the root. The root
cannot be conditional, because it is where a single-agent application's components live and where
the framework's own root components go.

**`_wire_transport` is where the per-agent gates live:**

```python
        consumes = bool(registry.get_event_handler(namespace=namespace))
        publishes = self._publishing_requested(namespace)
        ...
        if not (consumes or publishes):
            logger.debug("Namespace '%s' neither consumes nor publishes events; it is given no transport client", agent)
            return

        if event_bus_type == "dapr":
            DaprClient(namespace=namespace)  # auto-registers
            if consumes:
                self._eventing_components.append(DaprEventing(namespace=namespace))
        elif event_bus_type == "nats":
            NATSClient(namespace=namespace)  # auto-registers
            if consumes:
                self._eventing_components.append(NatsEventing(namespace=namespace))
```

The early return is a spec requirement, not an optimisation: **an agent that neither consumes nor
publishes must not be given a client** (sec. 6). A pure-scheduler agent in `in_process` mode that
has not opted into publishing is that case, and a connection for it would be a socket, a
readiness dependency and a `/connz` entry for traffic that does not exist -- on a broker its own
deployment may have no access to. The same gate is what makes the root pass a no-op in a grouped
application, where every handler belongs to a namespace and the root holds nothing.

**Publishing became a per-agent opt-in.** `_publishing_requested` now takes a namespace and reads
through that agent's configuration view:

```python
        raw = self._config.for_namespace(namespace).get("event_publishing_enabled", False)
```

So one agent in a group can emit events while its neighbours do not (C5). `for_namespace("")`
returns the loader itself, so a single-agent application reads exactly the key it always read.
The error for "publishing enabled, no transport" now names the agent that asked, because in a
group "somebody set this" is not a usable message.

**One `EventPublishingService` per agent that has a client**, which is what spec sec. 6 requires
for outbound attribution -- an agent's events go out on its own connection:

```python
        for namespace in self.hosted_namespaces:
            if registry.get_io_clients(namespace=namespace):
                EventPublishingService(namespace=namespace)
```

Keyed on the client rather than on `publishes`, so a consuming agent keeps the publishing service
it has always had without opting in. `EventProcessingService` stays single and at the root, since
phase 4 gave it a chain per agent instead.

**The lifespan and the router mount iterate the list**, shutdown in reverse, and both log the
namespace of the endpoint they are driving -- in a group "eventing component startup failed" with
no agent named is not attributable, which is C7.

**Three sessions components gained a namespace** (`SessionsApiClient`, `SessionKeyProvider`,
`SessionsBus`), because the sessions branch of `_wire_transport` creates them per agent like the
other two. `SessionsBus` is the one that matters beyond naming: it dispatches through
`CloudEventProcessorMixin`, which passes `self.namespace` since phase 4, so a job notification is
now offered to that agent's handlers and no other's.

Tests: `tests/unit/agents/app_builder/test_build_namespaces.py`, 16 cases against real
components -- one client per consuming agent, one at the root for a single-agent application, none
for the root when it holds nothing, none for an agent that neither consumes nor publishes, and a
client-without-endpoint for a publish-only agent; publishing opted into per agent; one endpoint
per consuming agent, one at the root for a single-agent application, none without handlers, and
each endpoint subscribing only its own topics; one publishing service per agent with a client and
none for an agent without one; `hosted_namespaces` ordering; and the publish-opt-in error naming
the agent.

Four existing `build()` tests were updated: the mock config gained
`for_namespace.return_value = config` (the pattern `mock_config` already used), seven
`assert_called_once_with()` assertions became `assert_called_once_with(namespace="")` -- the same
call, now explicit -- `_eventing_component is None` became `_eventing_components == []`, and one
`get_event_handler` stub lambda took the namespace argument it is now passed. None of these is a
behaviour change; each is an assertion on a call shape.

### Phase 6, part 2 -- an agent's HTTP surface lives under its own prefix, and grouped Dapr is refused

A group applies the same registration once per agent, so two agents declare the *same* paths.
FastAPI serves the first match, so without a prefix one agent's requests are answered by another
agent's code -- and its Dapr deliveries by another agent's handlers. Nothing about that is visible
from a response.

**`RestApiBase.route_prefix`** is the single definition of where a component's routes go:

```python
    @property
    def route_prefix(self) -> str:
        return f"/api/{self.namespace}" if self.namespace else ""
```

It is a property on the component rather than a rule inside `AppBuilder` because **two places
have to agree on it**: the builder, which mounts the router, and `DaprEventing.subscribe`, which
tells the sidecar where to post. If those disagreed the sidecar would post to a path FastAPI does
not serve and every delivery would 404, with the application otherwise healthy.

**`AppBuilder._mount` applies it, and rewrites the tags:**

```python
        prefix = component.route_prefix or root_prefix
        if component.namespace:
            for route in component.router.routes:
                if isinstance(route, APIRoute) and route.tags:
                    route.tags = [f"{component.namespace}.{tag}" for tag in route.tags]
        app.include_router(component.router, prefix=prefix)
```

`root_prefix` is what a *root* component keeps, and it is not the same for every kind: a REST API
has always been mounted under `/api`, a transport endpoint at the top level because its paths are
a contract with a sidecar. A namespaced component ignores it and takes `route_prefix`, so both
kinds end up under one prefix per agent -- `/api/orders/orders` for the REST API and
`/api/orders/events/{topic}` for deliveries, which matches the `/api/order/orders/{id}` shape
spec sec. 11 uses.

The tags are **rewritten, not appended to**. `include_router(tags=...)` appends, which would put
each operation in two Swagger groups -- once under the agent and once under the bare resource
name -- so the rewrite happens on the routes. `isinstance(route, APIRoute)` rather than a
`getattr`: a Starlette `BaseRoute` has no tags, and only the decorator-produced routes do.
Mutating them is safe because a router belongs to exactly one component and `build()` runs once
per process (`Component.configure` refuses a second call).

**Grouped Dapr is refused at build time, and this is the part worth arguing.** *(Superseded by
part 4 below, which routes and fans out in the process instead. The reasoning is kept because it
is why the endpoint had to become singular.)* Prefixing fixed
delivery, but discovery cannot be prefixed: the sidecar fetches `GET /dapr/subscribe` from one
path, fixed by Dapr's protocol. With each agent's document behind its own prefix the sidecar finds
*no* document, subscribes to nothing, and the pod reports itself healthy while consuming nothing
-- the exact silent failure this feature exists to prevent. So:

```python
        if event_bus_type != "dapr" or len(self._eventing_components) <= 1:
            return
        ...
        raise ValueError(
            f"{len(self._eventing_components)} agents ({agents}) consume events and 'event_bus' is 'dapr', ..."
        )
```

The check is on the resolved `event_bus_type` rather than on the endpoint types, because one
transport serves the whole process and the type is what is already known here -- `isinstance`
against a module-level name would also break under the test patching that mocks these classes.

NATS is unaffected: it has no discovery endpoint, because the client subscribes directly, per
agent. **A single-agent Dapr application is unaffected** -- one endpoint, no prefix, byte-identical
document.

Fixing grouped Dapr properly means one process-wide discovery endpoint returning the union of
every agent's subscriptions, each entry naming that agent's own delivery route. That is a change
to the sidecar-facing contract rather than an internal detail, so it is **not** done here and is
listed under *Open points*. Refusing loudly is the interim, because the alternative is a pod that
looks healthy and consumes nothing.

Tests: `tests/unit/agents/app_builder/test_route_namespacing.py`, 18 cases, asserting through
`app.openapi()["paths"]` rather than `app.routes` -- FastAPI stores an included router as one
opaque entry rather than flattening its routes, so `app.routes` does not contain the paths under
test while the OpenAPI document is exactly what is served. Covered: the prefix for a root and a
namespaced component; a single-agent application's paths not moving; an agent's route carrying its
namespace; two agents declaring one route not colliding; tags prefixed, the bare tag replaced
rather than added to, two agents' tags not merging, and a root component's tags untouched; grouped
Dapr refused with both agents named, one agent on Dapr fine, two on NATS fine; the root delivery
path unchanged; an agent's delivery path moved; two agents on NATS getting their own; and the
subscription document naming the mounted path for an agent and the unchanged path for the root.

### Phase 6, part 3 -- every cache is manageable and every cache is probed

Phase 3 part 2 let a process hold several named caches. Two things still only knew about the
default one, and both were listed as phase 6's work.

**`CacheManagementApi` takes an optional `?name=` on every endpoint:**

```python
    async def get_cache_stats(self, name: str = DEFAULT_CACHE_NAME) -> CacheStatsResponse:
        stats = self._cache(name).get_stats()
```

One router for the process rather than one per cache, and that is a correctness point rather
than tidiness: caches can be registered *after* startup (`registry.add_cache` exists for that),
routes cannot, so anything keyed on the set of caches at build time would serve a stale list.
Resolving the name per request has no such window. A request that names nothing reaches the
default cache, so every existing call is unchanged.

**`_cache(name)` answers the two failures differently, and the distinction is the point:**

```python
        if not self.registry.get_all_caches():
            raise HTTPException(status_code=503, detail="Cache service not available")
        try:
            return self.registry.get_cache(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
```

**503** when no cache is registered at all: the application was built without one, it is not the
caller's doing, and it may resolve without a redeploy -- which is what 503 says, and it is what
this endpoint has always answered. **404** when caches exist but none has that name: that is a
bad request for a resource that is not there, and answering 503 would invite a retry that can
never succeed. The registered names go in the 404 body, because a caller who mistypes a name has
no other way to discover the right one -- there is no endpoint that lists them.

The eviction response gained a `"cache"` field naming which cache was cleared. With one cache the
answer was implicit; with several, a response that does not say what it cleared is not usable.

**Readiness probes every cache, not just the default:**

```python
        for cache_name, cache in registry.get_all_caches().items():
            entry = "cache" if cache_name == DEFAULT_CACHE_NAME else f"cache:{cache_name}"
            health_providers[entry] = CacheHealthChecker(cache)
```

This was a real gap rather than a missing feature. `CacheHealthChecker` pings Redis and flips
readiness when it cannot be reached; keyed on the default name, a project whose `sessions` cache
was a Redis instance had that instance unprobed -- so a Redis outage there took the pod out of
nothing, and the agent silently served cache misses. Worse, a project that registered *only* a
named cache had no cache health check at all, because the old gate was `registry.has_cache()`,
which asks about the default.

The default keeps the entry name `cache` it has always had, so an existing `/readiness` payload
does not change; a named cache appears as `cache:<name>`.

Tests: `tests/unit/agents/io/api/utilities/test_cache.py` rewritten onto the new registry calls
and grown to 20 cases -- the three endpoints reading and clearing a named cache, the default used
when no name is given, the response naming the cache it cleared, 503 with no cache registered,
404 for an unknown name on all three endpoints, and the 404 body listing the registered names.
Four cases added to `test_named_caches.py` for the readiness wiring: the default keeping the
`cache` entry name, a named cache getting its own, a *named-only* application still reaching
readiness, and each entry probing its own cache object.

Also corrected here: part 2's entry said 17 test cases where the file has 18.

### Phase 6, part 4 -- grouped Dapr works: one endpoint, routed and fanned out in the process

Part 2 refused a group of consuming agents on Dapr, because discovery cannot be prefixed per
agent. The user's answer was the right one and better than the refusal: **do the routing in the
process.** Keep the one endpoint the sidecar's protocol demands, pick the agents from the event,
and fan out -- since several agents may legitimately want the same event. Part 2's guard is
removed.

**There is one Dapr endpoint, at the root, and that is now structural:**

```python
    def __init__(self) -> None:
        super().__init__(should_register=False)
```

`DaprEventing` takes **no namespace at all**, unlike every other transport component. That is not
a simplification -- it is what keeps `_topics_by_agent` correct. That method reads *every* handler
in the process, which it can only do because `self.registry` is the application's registry rather
than one agent's view of it; a namespaced instance would silently see one agent's handlers and
route only that agent's topics. Making the constructor refuse a namespace means the mistake cannot
be made, and `route_prefix` is then always `""`, so the two fixed paths never move.

**The routing table is read from the handlers:**

```python
        by_agent: dict[str, dict[str, None]] = {}
        for handler in self.registry.get_event_handler():
            for topic in handler.get_subscribed_topics():
                if topic:
                    by_agent.setdefault(namespace_of(handler), {})[topic] = None
```

An agent that declared no topic does not appear, because it has nothing to subscribe and nothing
to be delivered.

**The document is the union; the delivery is the fan-out.** Those are two different readings of
the same table, and the asymmetry is the whole design:

- `_declared_topics` flattens it, deduplicated, because the sidecar delivers a topic to the
  application **once** however many agents want it -- so it is told once.
- `_agents_for(topic)` inverts it, returning every agent that declared the topic. Fanning that
  single delivery out is the application's job, not the sidecar's.

```python
        declared = tuple(namespace for namespace, topics in by_agent.items() if topic in topics)
        if declared:
            return declared
        with_handlers = tuple(dict.fromkeys(namespace_of(handler) for handler in self.registry.get_event_handler()))
        return with_handlers or (ROOT_NAMESPACE,)
```

The fallback is the same rule `DispatchIndex.candidates` applies one level down: **an absent
declaration cannot narrow anything to nothing.** A topic nobody declared goes to every agent that
has handlers, and each agent's `can_handle_event` decides. That is what a topic arriving from
outside the application needs -- `dapr_declarative_subscriptions` makes the document empty, so no
handler need declare anything and the framework never sees the topic list, yet the sidecar still
delivers. Routing such a delivery nowhere would silence the application, and an unhandled event
acknowledges (spec sec. 7.2), so the events would be consumed and discarded. For a single-agent
application both branches are the root, so nothing changes there.

**`publish` dispatches once per agent and does not let a failure stop the others:**

```python
        for namespace in agents:
            try:
                await self._process_cloud_event(cloud_event, {"dapr_topic": topic}, topic, namespace=namespace)
                dispositions.append(DeliveryDisposition.ACK)
            except Exception as exc:
                disposition = disposition_for(exc)
                dispositions.append(disposition)
                ...
```

Letting the exception out of the loop would let one agent silently cancel a neighbour's work. Each
failure is logged with its own agent named, so a fan-out failure stays attributable (C7).

**The single acknowledgement is `combined_disposition`, new in `models/errors.py`** beside the
disposition table it extends, since it is a spec sec. 7.2 concern rather than a Dapr detail:

```python
    outcomes = set(dispositions)
    if DeliveryDisposition.NAK in outcomes:
        return DeliveryDisposition.NAK
    if DeliveryDisposition.ACK in outcomes or not outcomes:
        return DeliveryDisposition.ACK
    return DeliveryDisposition.TERM
```

Each step is a decision, argued in its docstring. **Any NAK wins**, because one agent asked for
the delivery again and the only way to give it one is to ask for the whole message again.
**Otherwise ACK beats TERM**, because a TERM from one agent means *that* agent found the message
undeliverable -- a finished outcome -- and if another agent handled it, the message was handled;
answering TERM would report a successful delivery as dropped. **All TERM is TERM.** Empty is ACK:
nothing was dispatched, so nothing failed.

**The cost, stated because it has no NATS equivalent:** there is one delivery, so one
acknowledgement, so **a retry asked for by one agent redelivers to every agent in the group**.
A grouped Dapr deployment therefore wants `idempotency_enabled`, or handlers that tolerate a
repeat. Under NATS each agent has its own consumer and its own ack, and no such coupling exists.
This is in the class docstring as well as here, because it is the thing an operator has to know.

**Plumbing:** `_process_cloud_event` and `_dispatch_cloud_event` took an optional `namespace`,
defaulting to the endpoint's own -- every caller but this one. The unhandled and duplicate
counters now carry the agent the dispatch was *for* rather than the endpoint's namespace, which
for the fan-out is the difference between attributing an event to the agent that declined it and
attributing every event in the process to the root.

**`AppBuilder._wire_dapr_endpoint`** replaces `_refuse_grouped_dapr`: the Dapr branch of
`_wire_transport` now creates only the per-agent client, and one root endpoint is created after
the loop if anything in the process consumes. NATS endpoints stay per agent, because there the
broker routes -- one consumer per `(namespace, topic)` -- and nothing needs to be done in
process.

Tests: `tests/unit/agents/io/api/eventing/test_dapr_fanout.py`, 24 cases against real handlers,
config and chains -- the routing table keyed per agent and an agent that declared nothing absent
from it; the document as the deduplicated union with every route at the fixed path; `_agents_for`
resolving one declaring agent, two declaring agents, an undeclared topic to every agent with
handlers, and a single-agent application to the root; the fan-out reaching both declaring agents,
skipping a non-declaring one, dispatching once for a single-agent application, and continuing past
one agent's failure; all six acknowledgement combinations; each agent's client receiving its own
topics and being kept per agent; and the constructor refusing a namespace.

Updated: `test_route_namespacing.py` lost `TestGroupedDaprIsRefused` and gained the Dapr endpoint
staying at the root; `test_eventing_namespaces.py` is now NATS-only, since Dapr's per-agent
subscription moved to the fan-out file; `test_dapr.py` moved from `_client` to `_clients` and its
mock handlers gained a real `namespace` attribute, which `namespace_of` needs; and one
`assert_called_once_with(namespace="")` became `assert_called_once_with()`.

### Phase 7 -- a handler says which agent runtime should serve an event

`EventHandlerBase`'s own usage docstring has shown `get_runtime_name` since before any of this
work; the method did not exist. A project that overrode it got a method nothing ever called.
Alongside it, `process_event` has taken a `runtime_name` argument that the spec's compatibility
table records as "only logged". This closes both.

**The hook, on `EventHandlerBase`:**

```python
    def get_runtime_name(self, event: GenericCloudEvent, context: dict[str, Any]) -> str | None:
        return None
```

Per *event* rather than per handler, because the choice can depend on the payload -- one handler
routing to a fast model or a thorough one on the same event type is the case it exists for.

**The resolution happens in the chain, between selection and handling, and that is a departure
from the plan.** The plan puts it in `EventProcessingService` "after the chain selects a
handler". By then the handler has already run: the chain selects *and* runs in one pass, so a
runtime resolved afterwards is a value nothing can act on. Inside the loop there is exactly one
moment where the winner is known and the answer is still useful:

```python
                if await handler.can_handle(event, context):
                    logger.info("Handler '%s' handling event '%s'", handler.name, event.type)
                    self._bind_runtime(handler, event, context)
                    result = await handler.handle(event, context)
```

So the runtime is *bound into the context the handler is about to be given*, under
`RUNTIME_CONTEXT_KEY` (`"runtime"`) and `RUNTIME_NAME_CONTEXT_KEY` (`"runtime_name"`). A handler
that wants a particular runtime reads it from the context rather than looking it up -- and in a
grouped process it gets its own agent's runtime with no namespace anywhere in handler code, which
is the constraint the whole feature is under. The fallthrough is unaffected: a candidate whose
`handle` returns `None` passes on, and the next candidate gets its own binding.

**Three sources, most explicit first:**

```python
        declared = handler.get_runtime_name(event, context) or context.get(RUNTIME_NAME_CONTEXT_KEY)
        if declared:
            context[RUNTIME_NAME_CONTEXT_KEY] = declared
            context[RUNTIME_CONTEXT_KEY] = self._runtime_named(str(declared), handler)
            return

        names = self.registry.get_agents(namespace=self.namespace)
        if len(names) == 1:
            context[RUNTIME_NAME_CONTEXT_KEY] = names[0]
            context[RUNTIME_CONTEXT_KEY] = self.registry.get_agent(names[0], self.namespace)
            return
```

The handler's own answer, then the caller's `runtime_name`, then the single runtime in this
handler's namespace. `process_event` now seeds its argument into the context:

```python
        if runtime_name:
            context[RUNTIME_NAME_CONTEXT_KEY] = runtime_name
```

Only when asked for, so a caller that passes nothing leaves the key *absent* rather than `None` --
the difference between "no preference" and "explicitly no runtime". That is what makes a parameter
which has only ever been logged mean something, while keeping the handler's own answer above it.

The namespace is named explicitly in both registry calls, for the reason it is named in
`_handlers`: an omitted namespace on the root registry means every namespace, so the single-runtime
count would include a neighbour's agent and "exactly one" would be wrong in a group. There is a
test for two agents each owning a `planner`, where each chain binds its own.

**The plan's ambiguity error is not implemented, and this is the substantive departure.** The plan
says "`None` + multiple agents + no name declared -> raise a descriptive error". That would break
applications that work today: two agents plus handlers that resolve their own runtime by name is a
shape this framework already supports -- it is what the scaffolder generates, `self.registry
.get_agent('<runtime_name>')` in a service's `on_startup` -- and those applications rely on the
framework resolving nothing. Raising would fail every delivery in them. So nothing is bound, and
the ambiguity is reported once per handler at WARNING, naming the candidates and the override.
Once, because the condition is a property of the code rather than of the event: the same handler
in the same namespace is ambiguous for every event it will ever see, and a per-delivery warning
would bury the one line that matters. This needs a spec amendment; it is under *Open points*.

**What *does* raise is a declaration the framework cannot honour:**

```python
            raise ValueError(
                f"Handler '{handler.name}' asked for agent runtime '{name}', which is not registered in namespace "
                f"'{self.namespace or ROOT_LABEL}' or at the root (registered here: {registered}). Either register it, "
                "or return a name that exists from get_runtime_name()."
            )
```

The same reading as `event_publishing_enabled` without a transport: an explicit statement the
framework cannot satisfy is a failure, not something to fall back from silently.

**Found while writing the tests, and worth recording:** constructing a component *directly* with
an explicit `name=` does not qualify it with the namespace -- only `AppBuilder._register` does
that (phase 3 part 1). So two `AgentRuntime(name="planner")` instances in two namespace scopes
still collide on the one registry key. Everything the builder creates is safe; a test or a project
that constructs a component by hand inside a `namespace_scope` is not. The test helper qualifies
the name itself and says why. Not fixed here -- the fix would be `Component.__init__` qualifying an
explicit name, which changes naming for every component in the framework and deserves its own step.

Tests: `tests/unit/agents/handler/test_runtime_binding.py`, 18 cases against real
`AgentRuntime`, `Config` and chains -- a declared runtime bound and bound *before* the handler
runs; the choice varying with the payload; the handler winning over the caller and the caller
winning over the fallback; `process_event` seeding its argument and leaving the key absent when
it has none; one runtime bound with no declaration, none bound when there is no runtime at all,
and each agent binding its own in a group; the ambiguous case binding nothing, reporting once
rather than per delivery; an unknown declared name raising with the handler, the namespace and the
registered names in the message; and the default hook returning `None`.

**Verified not vacuous:** with the `_bind_runtime` call removed, 14 of the 18 fail -- the four
that survive are the ones asserting that *nothing* is bound.

### An ambiguous name fails at startup, wherever it comes from

Raised by the user against phase 7's open point, and the reason given is the right frame for it:
a registry name is what appears in every log line, span and health entry, so **two components
that share one -- or one whose name does not say which agent it belongs to -- cannot be told
apart when someone is reading the logs.** That has to fail while the process is starting, not be
disambiguated silently or, worse, resolved by dropping one of them.

Four paths could produce an ambiguous name. All four are closed.

**1. An explicit `name=` reached `Component` verbatim.** The derived name was qualified with the
namespace; an explicit one was not:

```python
-        self._name = name or qualified_component_name(self._namespace, camel_to_snake(self.__class__.__name__))
+        self._name = qualified_component_name(self._namespace, name or camel_to_snake(self.__class__.__name__))
```

So `AgentRuntime(name="planner")` built inside `namespace_scope("orders")` registered as
`planner`. The log line said `planner` and nothing about which agent's, and a second agent's
`planner` collided on the key. `AppBuilder._register` had been compensating by qualifying after
construction; it now assigns the bare name and lets the setter do it, so the rule lives in one
place instead of two.

**2. `Component.name`'s setter took the new name verbatim** -- the same hole, reachable by any
component doing `self.name = "..."`. It qualifies now.

**3. `Registry.update_component_name` silently dropped whatever held the target name.** It was:

```python
        self._components[new_name] = self._components.pop(old_name)
```

Renaming one component onto another's name **removed the other from the registry**, and the only
symptom was a collaborator that could no longer be found -- no error, no log. It now refuses,
naming what is there; renaming to the name a component already has is a no-op rather than a
failure, which is what makes the qualifying setter safe to call twice.

**4. `AppBuilder.with_namespace` deduplicated a repeated agent name.** Declaring `orders` twice
quietly merged two agents' components into one namespace:

```python
        if namespace in self._namespaces:
            raise ValueError(
                f"Namespace '{namespace}' is already hosted by this process, so it cannot be declared again. Two "
                "agents cannot share a name: the name is what identifies an agent in every log line, span, queue "
                "group, durable and cache partition, ..."
            )
```

The agent name is the strongest case of the user's point: it reaches the queue group, the
JetStream durable and the cache partition as well as the logs, so two agents under one name are
indistinguishable to the broker too. The message names the legitimate case it might be mistaken
for -- one agent assembled from several parts -- and says to compose those into a single
`AgentRegistration` instead.

**`qualified_component_name` is deliberately *not* idempotent**, and finding out why was the one
surprise here. Skipping the prefix when a name already appears to carry it looks like a safeguard
against `orders_orders_db`; it is worse than the problem. A base name can legitimately begin with
the namespace -- `BillingHandler` in namespace `billing` derives `billing_handler` -- and such a
component would then register *unqualified*, which is exactly the ambiguity being removed. It was
implemented that way first and a test caught it. "Already prefixed" is not decidable from the
string, so it is not guessed; the docstring says so, and there is a test for the
`BillingHandler`-in-`billing` case. The cost is that a caller who qualifies a name itself gets it
qualified twice -- redundant, still unambiguous, and no framework code does it.

**The duplicate-name error now says what to do.** `add_component`'s message was `Component with
name X already exists`, which in a group does not say whose or why:

```python
                f"Component name '{name}' is already taken by a {existing}, so {type(component).__name__} in namespace "
                f"'{agent}' cannot register under it. Registry names have to be unique across the whole process: they "
                "are what identifies a component in logs, spans and health entries, and two components sharing one "
                "name cannot be told apart afterwards. A name is qualified with its namespace automatically, so this "
                "is either two components of one class in one agent, or two explicit names that collide -- pass a "
                "distinct 'name=' to one of them."
```

Tests: `tests/unit/agents/component/test_name_uniqueness.py`, 16 cases -- a directly constructed
component qualified, two agents each holding a `planner`, the root keeping the bare name, a
rename qualified and a root rename unchanged; the `BillingHandler`-in-`billing` case and the
qualifier being a plain prefix; two components of one class in one agent colliding, two explicit
names colliding, the message naming the agent and the fix, and a root component not colliding
with an agent's; renaming onto a taken name refused with the other component still registered
afterwards, renaming to the same name and to a component's own qualified name both no-ops, and
renaming from an unregistered name still raising. `test_namespace_builder.py`'s dedupe test became
two refusal tests.

### One name per agent: the name given in code, with `app_name` as the fallback

Raised by the user, whose premise was worth checking first: the namespace is **not** derived from
`app_name`. It never was -- an agent's name comes from `with_namespace("orders")` in code, and
config supplies nothing. But the instinct behind the question was right, because config was
supplying a *second* name for the same agent, and two of the places that read it were wrong.

The rule now, stated once: **the name given in code is the agent's identity; `app_name` is used
only when no name was given, and is otherwise a display string for the process.**

**1. An agent no longer has to restate its name in config.** `Config(agent_scope=...)` carried
`Validator(f"{agent_scope}.app_name", must_exist=True)`, so every agent in a group had to declare
an `app_name` of its own -- a second name, free to disagree with the first. The same agent could
be `orders` in the registry, the queue group, the durable and the cache partition, and
`Order Processing` in a dashboard. The validator is gone. `app_name` stays a root key for the
OpenAPI title, `/info` and `/status/build`, and an agent may still set one *for display* without
it touching identity.

**2. Telemetry identity was the display name, which breaks C2.** `otel_service_name` defaulted to
`app_name`, so an agent's `service.name` was whatever `app_name` said:

```python
    def _resolve_service_name(self) -> str:
        if self._agent_scope:
            scoped = self._settings.get(f"{self._agent_scope}.otel_service_name")
            return str(scoped) if scoped else self._agent_scope
        return str(self.get("otel_service_name", self.get("app_name", "agent-service")))
```

A scoped view answers with its own `otel_service_name` if the agent set one, and otherwise with
the **namespace**. Note what it deliberately does *not* do: fall back to the root's
`otel_service_name`. That is the one place a scoped read must not, because inheriting it would
give every agent in a group the same `service.name` -- and then regrouping moves work between
agents that no dashboard can tell apart, which is the whole of what C2 forbids. The root view
keeps the old chain exactly, so a single-agent application's dashboards do not move.

**3. A namespaced scheduler derived its tick subject from `app_name`.** This was a live defect
left behind by a placeholder:

```python
-        # ROOT_NAMESPACE is still "" for every component; phase 2 is what gives this a value.
-        identity = ROOT_NAMESPACE or str(self.config.get("app_name", "") or "").strip()
+        identity = self.namespace or str(self.config.get("app_name", "") or "").strip()
```

`ROOT_NAMESPACE` is the module constant `""`, so the expression was *always* `app_name`. The
comment says phase 2 would give it a value -- phase 2 landed, `self.namespace` has one, and
nothing came back to this line. The consequence: two agents in a group each with a `nightly`
scheduler derived the same tick subject and would have consumed each other's ticks, and moving an
agent between groups could change the subject its external `CronJob` publishes to, which is
exactly what C1 forbids. The `source` string on the next line had the same inversion, so the
error message named the wrong key. Both fixed, with two regression tests that fail against the old
expression.

Everything else that reads `app_name` was already right and is untouched: the NATS queue group
(`if self.namespace: return self.namespace`, then `nats_queue_group`, then `app_name`), and the
display readers.

**Which of these are breaking, precisely.** The `otel_service_name` change is, and it is listed as
*Breaking change 2* under *Compatibility*: `Config(agent_scope=...)` is not new -- it landed in
April and is on `develop` -- so a repo already using it sees its `service.name` change. The
dropped validator is a loosening: configuration that was valid stays valid. The scheduler subject
is **not** breaking for anything deployed, because a scheduler can only have a namespace if it was
built inside a `namespace_scope`, which is branch-new; the *Compatibility* bullet says so rather
than claiming a break that cannot happen.

Tests: `tests/unit/agents/config/test_agent_identity.py`, 8 cases -- an agent's service name being
its own name, an agent overriding it for itself, the root's override *not* leaking into an agent,
a single-agent application still reading `app_name`, an explicit root override still winning at
the root, the default when there is neither, and `app_name` staying readable and settable for
display without touching identity. Two cases added to `test_scheduler.py` for the namespaced tick
subject, and `test_agent_scope.py`'s "missing scoped app_name raises" became "an agent does not
have to restate its name".

**Not touched, deliberately:** `black --check` still fails on `config/config.py`, and did at HEAD too -- it is one of the files `CLAUDE.local.md` documents as
disputed between `black` and `ruff format`. `black` reformatted a pre-existing ternary there when
run over the changed files; that reformat was reverted, because accepting it would have started
the ping-pong the two formatters play over that file.

### Phase 8 -- the group becomes a running process

Everything before this made a group *possible*; nothing made one *start*. This is the phase that
turns a deployment decision into a process: which agents run here arrives at container start,
and the code that reads it is the only code allowed to.

Three commits, split along the one line the plan is emphatic about -- **resolution versus
wiring**. Environment reads, file reads and `sys.exit` stay out of `AppBuilder`, so it remains a
pure function of its call sequence and a test can state an exact composition without controlling
the environment or the filesystem.

#### `GroupConfig` and its resolution (`d00ca03`)

Two files, and their different lifetimes are the reason there are two rather than one:

- **`agents.toml`** says which agents this *image* contains and where their declarations live.
  It changes only when an agent is added or removed -- a rebuild anyway -- so it is baked in.
- **`deployment-groups.yaml`** says which of them *this process* runs. Never baked in, since one
  image serves every group, so it arrives as a mount or is replaced entirely by environment
  variables.

`GroupConfig.resolve` is the only member that reads either, plus the environment:

```python
        declared = cls._read_group_file(env, root)
        name, agent_names, critical_names, cache_names = cls._apply_env_overrides(env, declared)
        ...
        agent_map = cls._read_agent_map(env, root)
        agents = cls._resolve_agents(agent_names, critical_names, agent_map, name)
```

**Environment overrides the file key by key** (spec sec. 5.1), so a Deployment changes the agent
list without restating the group's name or its caches, and each resolved value is logged with the
source it came from -- "which agents did this pod actually start" being the first question asked
of a group that misbehaves.

One rule the spec does not state and the tests forced out: **when `BLUEPRINT_AGENTS` supplies the
group and `BLUEPRINT_GROUP` names none, the file is not read at all.** That is the `docker run`
and CI shape from sec. 5.1, and reading the file anyway made an unrelated multi-group file in the
image *ambiguous* -- for nothing, because with no group named no slice of it applies and the only
value it would have contributed is already overridden.

**Every way of getting a group wrong is a startup failure**, because the alternative is a pod
that passes its probes with a queue nobody is consuming: an agent the image does not contain, an
agent named twice, a name that cannot be a namespace, an unknown group, a malformed or
`groups`-less file, a missing or malformed agent map. Each message names what it found and what it
expected. `critical` defaults to `True` for the reason sec. 9.1 gives -- a group short one
consumer is worse than no pod -- and a *non*-critical agent missing from the map is skipped with
an ERROR instead, since that flag is the deployment saying it would rather run the rest.

Two details worth their lines. `AgentSpec.name` is put through `validate_namespace`, because it
*becomes* a namespace: rejecting it here names the group file, while letting it through would
surface as a validation error from inside some component's constructor. And PyYAML is imported
inside the parse rather than at module scope -- it is not a declared dependency of this package,
it arrives with `uvicorn[standard]`, so a module-level import would break importing *anything*
from the package in an installation that trimmed it. See *Open points*.

#### `with_group` and `from_group` (`71dfbb1`)

```python
        for spec in group.agents:
            registration = self._load_registration(spec)
            if registration is None:
                continue
            self.with_namespace(spec.name, registration=registration)

        for cache_name in group.cache_names:
            self.with_cache(name=cache_name)
```

The caches are the group's rather than any agent's, because a cache is process-wide (spec
sec. 8) -- so phase 3 part 2's `with_cache(name=...)` is what the group's `cache_names` feed.

Importing an agent's module is the one thing here that reaches outside, and it is deliberately on
this side of the resolution/wiring line: it is driven entirely by the `module` strings the group
carries, so a test points them at test modules and controls neither environment nor filesystem to
do it. Imports happen **per group**, so cold start is proportional to the agents this process
hosts rather than to the agents the image contains.

`_load_registration` catches **every** exception from the import, not `ImportError` alone:
importing a module runs it, and an agent whose declaration raises at import is exactly as
unloadable as one whose module is absent. It also refuses an attribute that is not an
`AgentRegistration`, and a `module` string that is not `package.module:attribute` -- both of which
would otherwise fail later and further away.

A critical agent that cannot be loaded raises `GroupConfigError`; a non-critical one is skipped
with an ERROR and the rest of the group still starts. The flag is read *before* the agent is
wired rather than after an exception, because there is no partial build to unwind: one process,
one `build()`.

#### The entry point (`029f287`)

`python -m blueprint.agents.entrypoint`, and it exists to hold the three things `AppBuilder` must
not: reading the environment, reading files, and exiting.

```python
def build(*, environ: dict[str, str] | None = None) -> tuple[FastAPI, Config]:
    config = Config(settings_files=DEFAULT_SETTINGS_FILES)
    group = GroupConfig.resolve(config, environ=environ)
    app = AppBuilder(config).with_group(group).build()
    return app, config
```

Split from `main` so the whole startup path is testable without a server and without
`sys.exit`: everything that can fail happens in `build`, and `main` only decides what to do about
it. `main` returns a status rather than exiting, so a test asserts on the status; the
`__main__` guard is what turns it into an exit.

**Why it catches rather than lets the exception out.** A group that cannot be resolved must stop
the process *before the port is bound* (spec sec. 9.1), so Kubernetes crash-loops with a readable
message instead of reporting a healthy replica that is silently short a consumer. An uncaught
exception also exits non-zero, but buries the one line an operator needs under a traceback of
framework internals. The reason is `print`ed to stderr *as well as* logged, because logging is
configured by `AppBuilder` -- which has not run yet when resolution fails.

A project keeps its own `main.py` if it wants: a standalone deployment is untouched, and
`uvicorn src.main:app` works exactly as before.

#### Not in this phase, and why

- **The settings-fragment merge.** The plan lists it here; the changelog's *Open points* has
  carried it since config rework step 3a with **two unanswered questions** -- whether a fragment
  declaring `envvar_prefix` is rejected, and whether a fragment may override a shared
  infrastructure key at all. Both are decisions rather than implementations, and guessing either
  produces a merge that silently drops or silently overrides configuration. Still open.
- **`on_startup` raising** -- the third row of sec. 9.1's failure table. It says "mark namespace
  down, pause consumers (C4), continue", which is phase 9's per-namespace degradation machinery,
  not something to improvise here.
- **`deployment-groups.yaml` and `agents.toml` are not generated.** Phase 8 *reads* them; the
  scaffolder writing them belongs with the manifest generation that is already parked.

Tests: `tests/unit/agents/test_group_config.py` (33 cases), `test_with_group.py` (24) and
`test_entrypoint.py` (12) -- 69 in total. The group file and the environment as sources and in
combination, precedence and its logging, criticality from both sources, every validation failure,
the value object's freezing; one namespace per agent with order preserved, the group's caches,
every declaration-loading failure for critical and non-critical agents, and that `with_group`
ignores the environment even when it is set; and the entry point building from either source,
serving what it built, and returning non-zero with the reason on stderr without binding a port.

### `build()` did not change, and one `main.py` does serve both shapes

Both raised by the user against phase 8, and the first was a fair misreading of a name I chose
badly.

**`AppBuilder.build()` still returns a `FastAPI`.** Nothing about it changed in phase 8, and no
existing `main.py` needs editing. The function that returns a tuple was `entrypoint.build()` -- a
*different* function, in a module nothing imported before this phase. But a second `build` in the
same package returning a different shape is exactly the trap it looks like, so it is now
`entrypoint.build_group_app()`, with the reason in its docstring and a test asserting that
`entrypoint.build` does not exist. The lesson is worth keeping: `build` is spoken for in this
package.

**One `main.py` for both shapes is not merely possible, it is what spec sec. 11 requires** -- and
it already works. The single declaration the spec asks for is the whole file:

```python
registration = (
    AgentRegistration()
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_rest_api(OrderApi)
)
```

No `AppBuilder`, no `Config`, no `run_app`, no `if __name__`, no namespace, no group. The same
object then serves three deployments, which `TestOneDeclarationServesBothDeploymentShapes` now
pins down rather than asserting:

| Deployment | How | What runs |
|---|---|---|
| Standalone, as today | `AppBuilder(config).with_registration(registration).build()`, `uvicorn src.main:app` | root namespace |
| Alone, as a group of one | `BLUEPRINT_AGENTS=order python -m blueprint.agents.entrypoint` | namespace `order` |
| Beside other agents | `BLUEPRINT_AGENTS=order,billing ...` | namespaces `order`, `billing` |

The dual-branch `main.py` the plan once described -- the component list duplicated under
`if __name__ == "__main__"` and `else:` -- is what the spec forbids, and nothing in the
implementation needs it: `agents.toml` points at `main:registration` like any other module, and a
group of one is an ordinary group.

**The one consequence to know about, and it is deliberate.** A group of one is *not* identical to
standalone, because it uses the agent's real name: components become `order_order_service` rather
than `order_service`, routes move from `/api/...` to `/api/order/...`, and the queue group becomes
`order` rather than `app_name`. Spec sec. 11 chooses this on purpose -- "a dev mode that ran at
`namespace=""` would give every developer local URLs and integration tests that differ from
production" -- so local and CI match the deployment instead of diverging from it. Migrating an
existing agent from standalone to a group of one therefore moves its routes and its consumer
identity, which is a migration with consequences rather than a rename; phase 10 is where that gets
written up for a project to follow.

### The builder surface: one class, and the group's rules in the class that imposes them

**No code changed. Two proposals written, and the spec and plan amended to match.** Recorded here
because the decisions are the reviewable artefact, and because the next phase is their
implementation.

`docs/plans/2026-09-10-builder-unification.md` -- **phase 8b**, decided, not written.
`docs/plans/2026-09-10-config-validation-unification.md` -- deliberately **not** part of this
feature.

**The problem, restated correctly.** Adding one `with_*` method today means editing four places:
`AppBuilder`, `AgentRegistration`, `NamespaceBuilder`, and `AgentRegistration.apply`'s `appliers`
dict. Three of those fail *silently* -- the capability is simply absent from that surface -- and
nothing tells the next developer the four exist. The duplication looked like a style problem and
is not: `AppBuilder.with_handler(H)` **constructs `H` immediately**, and a component constructed
before a namespace exists belongs to the root for ever, so a second class had to exist to defer
construction until a namespace was in force. `AgentRegistration` is that class, `NamespaceBuilder`
is its block-form sugar, and `appliers` is the bridge. So the fix is not to share the methods but
to remove the reason they diverged: an `AppBuilder` that **records** instead of constructing
serves both shapes, and the other three have no purpose left. Four sites become one.

**Collection is its own class.** An intermediate design put an `absorb(builder, namespace=...)`
method on `AppBuilder`; the user's objection retired it -- an `AppBuilder` does not know it is
being collected, because the collection happens elsewhere. So `AgentGroup` (new class, new module)
takes named builders and one configuration and drives one wiring pass, `AppBuilder` keeps exactly
one job, and `with_group` / `from_group` move off `AppBuilder` too. The refusals move with them,
which is the better half of the change: the group's restrictions belong to the thing imposing
them, so **standalone stays permissive and the collector enforces**. That is also the rule stated
plainly -- standalone allows more; to join a group you accept the group's constraints.

**Decisions, D1-D7 in the proposal:**

- **Standalone knows nothing about namespaces.** `build()` wires at the root, and the agent's name
  lives only in the group configuration. Consequence, stated rather than hidden: a standalone agent
  moved into a group changes its queue group and durable once, on the first grouped deploy.
- **Refusals at assembly, each named:** instances (their namespace and registry key were fixed
  before the group existed), `AppBuilder(config)` (one process, one settings tree, one port), a
  builder already built. Nothing loses a capability -- the factory form recovers the instance case.
  No deprecation warnings: sec. 10 makes the standalone shape supported indefinitely, so warning
  about it every startup would be crying wolf.
- **A cache is private to the agent that declared it.** Names qualified per namespace, no root
  fallback, no shared-cache opt-in. This finally implements what spec sec. 8 always said and only
  half of which was built. It **deletes** `GroupConfig.cache_names` and `AgentScopedCache`:
  separate stores make the isolation structural, so the prefixing lens has nothing left to prevent.
- **A health checker's key carries its agent.** Two agents calling
  `with_health_checker("db", ...)` currently collide in a dict and one disappears silently.
  `(namespace, name)` is stored as data, the prefix is its rendering -- phase 9's
  `readiness_policy = "critical"` has to attribute a failing checker to an agent, and recovering
  that by splitting a string breaks the moment a name contains the separator.
- **Group settings are defaults, and only defaults**; each agent's own `settings.toml` merges under
  that agent's scope. So an agent may set any key for itself and can never change what another
  agent or the process sees -- which closes the fragment-merge open point below rather than
  answering it.
- **`AgentBuilder` records too**, and this fixes a live defect rather than only changing a shape.
  `AgentBuilder.__init__` requires a `Config`, and `Component._shared_config` deliberately has no
  public read path -- so the factory form phase 8 documents,
  `lambda: AgentBuilder(config, runtime_name="orders").build()`, **cannot be written at all** in a
  declaration-only `main.py`. Passing the unbuilt builder to `with_agent` and calling
  `agent.build(config.for_namespace(ns))` at wiring time removes the lambda and a second latent bug
  with it: a lambda closes over whichever configuration was in scope where it was written, which in
  a group is the wrong one.

**Two behavioural changes worth knowing.** `configure_logging()` moves from `__init__` into
`build()` -- with nothing constructed before `build()`, that is where it belongs. And registration
order keeps its meaning, but an instance recorded *after* a class registers *before* it, which can
flip equal-priority tie-breaking; `build()` knows both the recorded order and which entries were
instances, so it raises on that combination instead of silently reordering.

**Checked against the four Builder anti-patterns**, which was the user's question. Collect-then-wire
is the pattern, not an abuse of it; what exists today is the smell. (1) Side effects during
accumulation -- removed. (2) A silently single-use builder -- `build()` calls
`Component.configure`, which refuses a second call and surfaces as someone else's error; it gets
its own message. (3) Requiring the product's context in the constructor -- `config` moves to
`build()`. (4) Replay drift -- mitigated by storing the *method name* and resolving it with
`getattr`, plus a test asserting the declaration surface and the replay agree.

**Deferred, and not to be touched during 8b:** configuration validation. Four mechanisms disagree
about what a missing key means, and two findings are worth recording because they are not visible
from reading the code:

- **The three root validators cannot fail.** `must_exist=True` together with `default=` never
  fires -- Dynaconf injects the default. Verified against the installed version:
  `Validator("app_name", must_exist=True, default="agent_blueprint")` yields
  `'agent_blueprint'`; drop the default and the same declaration raises. So the only condition
  among the three that can actually fail is `is_type_of=int` on `app_port`, and an application with
  no `settings.toml` starts and calls itself `agent_blueprint`. The defaults are defensible; the
  code *claiming* `must_exist=True` is not, because the next genuinely required key gets copied
  from it.
- **The actuator's configuration branches are dead.** `Config.validate()` runs inside
  `__init__` and raises, so a `Config` that exists has always passed and `_validation_errors` is
  always empty -- making `actuator_api.py:95` (readiness 503 carrying the reasons) and `:149`
  (liveness warning) unreachable. The readiness probe was written for a behaviour the process does
  not have.

**Amended in the spec:** sec. 2 (Registration -> Declaration), 4.1 (`AgentGroup`, no cache list),
4.2 (deferred wiring normative, the refusal table, config resolution order, order semantics), 4.3
(the ContextVar's owner), 5.3 (defaults-only group settings; process-scope keys raise), 8 (caches
declared-only), 9 (startup sequence), 10 (three new compatibility rows), 11 (`main.py` and the
optional `create_app`).

**Amended in the plan:** phase 8b added between 8 and 9 with an eight-step breakdown, and it is
before 9 deliberately because 9 needs D4's attribution data; phases 0 and 3 carry superseded
banners rather than being deleted, because their ContextVar and `with_cache`-signature reasoning
still stands; the migration path corrected from two file changes to **three** (`agents.toml` was
missing) and its `main.py` rewritten; the dual-branch migration recipe under *File change summary*
removed, since it contradicted the rejection stated 600 lines above it; `python -m
blueprint.agents.orchestrator` corrected to `entrypoint`; the *not a separate orchestrator*
argument reconciled with `AgentGroup`; cache and executor sharing rows corrected; testing
expectations extended.

### Phase 8b, step 1 -- `AppBuilder` records, and `build()` is the only thing that builds

**`Declaration` (`app_builder.py`), the five `with_*` and `with_cache` store instead of
constructing, `build(config=None)` replays them.** This is the change the whole unification rests
on: `with_handler(H)` used to construct `H` on the spot, so a component declared before any
namespace existed belonged to the root for ever -- which is the only reason `AgentRegistration`
had to exist as a second class. It no longer does.

- **`Declaration`** is a frozen value object holding `kind`, `target`, `name`, `namespace` and
  `kwargs`. `target` is a class, a zero-argument factory, an already-built component, or `None`
  for a cache. `is_built` reports whether `target` is already a `Component`, which is what the
  order check below reads.
- **`_record(kind, target, namespace, kwargs, *, name, method)`** replaces `_register`. It
  resolves the namespace **at the call**, not at construction -- `namespace or
  current_namespace()` -- because the caller's scope is what carries it and by the time the
  replay runs no scope is in force. Two checks stay at record time, both answerable there and
  both better reported at the offending line: `validate_namespace(namespace)`, and the
  already-built-instance-for-another-namespace refusal (unchanged wording, moved from
  `_register`).
- **`_construct(declaration)`** is the other half of the old `_register`: it enters
  `_construction_scope(declaration.namespace)` and calls `declaration.target(**kwargs)`, or
  adopts the instance, then assigns the explicit name. A class and a factory are now handled by
  the same branch, because a class *is* a zero-argument factory once its keyword arguments are
  applied -- which is what lets `lambda: AgentBuilder(...).build()` be deferred exactly as far as
  a class is.
- **`declarations`** is a public read-only snapshot, for the collector in step 3 and for a test
  that wants to assert what a `main.py` declares without building any of it.
- **`_construct_declarations()`** replays in call order, then creates the caches. Caches last on
  purpose: a cache backend is itself a `Component`, so building one mid-pass would interleave it
  into the registry's insertion order and shift every component declared after it.

**`build(config=None)`** gained three things. It refuses a second call with its own message
rather than surfacing `Component.configure`'s "already set" from three frames down. It settles
the configuration -- given to `__init__`, given here, or, when neither, loaded from
`DEFAULT_SETTINGS_FILES`, which is what makes the migrated `AppBuilder().build()` shape work.
And it injects the configuration **before** constructing anything, which is strictly more correct
than the old order: every component now exists in a process that already has its configuration.

**`_check_declaration_order`** is the one new refusal. An instance is constructed by the caller
at its own source line and is therefore in the registry *before* `build()` runs, while a class is
constructed during the replay -- so an instance recorded after a class registers before it.
That is not cosmetic: `DispatchIndex.build` resolves handler priority ties by registration order.
The check runs **after** construction, deliberately, because a class's priority is a property of
the object and reading it off the class would mean parsing a default argument and being wrong
about every handler that computes one; the application is not returned when it raises, so the
components already in the registry go nowhere. It fires only for handlers, only within one
namespace, and only at equal priority -- the only case where the order decides anything.

**`configure_logging()` moves, but not all the way to `build()`.** The plan says `build()`; that
is right for a declaration-only `main.py` and wrong for the shape the scaffolder still generates,
where `with_service(OrderService())` constructs at its source line and the builder's own
`with_namespace` / `with_cache` calls log as they go. So the call lives in one place,
`_use_config`, which runs from `__init__` when a configuration is given there and from `build()`
when it is not. An existing `AppBuilder(config)` chain therefore logs exactly as it did.

**Smaller changes that this needed:**

- `EventHandlerBase.priority` -- a public property over `_priority`. The ordering rule is
  enforced from outside the class, and `__lt__` answers the sorting question, not that one.
- `CacheBackendFactory._validate_name` -> `validate_name`. `with_cache` calls it at record time,
  because a cache name becomes a directory segment and a Redis key prefix: it crosses the process
  boundary, so it is validated where it is written. The factory still validates when it creates
  the backend -- it owns the rule, and nothing reaches it only through the builder.
- `DEFAULT_SETTINGS_FILES` moved from `entrypoint.py` to `config/config.py` and is exported from
  the `config` package. Two callers now need the same answer: the container entry point, and
  `build()` when the application handed it no configuration.
- `AgentRegistration.apply` hands a factory to the builder instead of calling it. A factory used
  to be invoked at apply time -- producing an instance that landed in the registry before every
  class of the same agent -- and now defers as far as a class does.
- The registry-creation fallback considered for `build()` was **not** added: `AppBuilder.__init__`
  constructs a `TelemetryManager`, which is a `Component`, so the shared registry always exists by
  the time `build()` runs. Verified rather than assumed.

**Behavioural change, stated for the migration guide:** nothing is in the registry until
`build()`, so code that looks a component up between `with_*` calls breaks. The framework's own
convention already forbids it -- collaborators are resolved in `on_startup` -- so the fix is the
documented pattern.

**Tests.** New `tests/unit/agents/app_builder/test_deferred_wiring.py` (32 cases): nothing is
constructed or registered before `build()`, what a declaration records, the order refusal and the
three cases it must *not* fire on, where the configuration may be handed over, the single-use
guard, and an application that declares nothing. The existing suites that asserted on the registry
straight after a `with_*` call now say when construction happens, through a `realize()` helper in
`conftest.py` that runs `build()`'s own replay pass without the actuator, root API and FastAPI
application that would drown the assertion. 1962 unit tests pass, 34 more than before this step.

---

### Phase 8b gains a step 9: the rules this overhaul establishes, written where they will be read

**No code changed. A step was added to the plan, and a documentation audit was run to decide where
it lands.** Recorded here because the audit's findings are the reviewable artefact and because they
changed the answer.

**The question.** This overhaul settles principles -- collect then wire, the namespace is ambient,
a name that leaves the process is validated and never repaired -- that a later feature can violate
without anyone noticing. They exist today only in this changelog, which is now over 4600 lines and
which nobody will read end to end. So: write them down as rules, and put a test behind the ones a
test can hold. Placed **last** in phase 8b, because a rule can only describe something that exists.

**The finding that decided the location.** `CLAUDE.md:5` has always said *"See `AGENTS.md` for
architecture, component patterns, and testing conventions shared across all AI assistants."*
**`AGENTS.md` has never existed.** `git log --all --diff-filter=A -- AGENTS.md` returns nothing --
it was not written and later deleted, it was cited into existence. Worse,
`docs/plans/2026-06-10-sessions-job-handler.md:122` quotes what it *states* about versioning, so a
claim has already been sourced to a document that is not there.

That inverted the recommendation. A new `docs/concepts/design-rules.md` would have added a file and
left the dead pointer beside a live one; writing `AGENTS.md` turns a reference that resolves nowhere
into one that resolves, at no net cost in files.

**The rest of the audit**, over all 61 tracked markdown files. Two real problems, both duplication
rather than absence:

- **`docs/superpowers/`** holds `plans/` and `specs/` mirroring `docs/plans` and `docs/specs` --
  3 files, 2079 lines -- and **nothing in the repository links to any of them.** A second,
  abandoned home for the same two document types.
- **Four cache documents totalling 968 lines:** `docs/concepts/caching.md` (347),
  `docs/concepts/cache-system-overview.md` (232), `docs/concepts/cache-architecture.md` (181),
  `docs/guides/caching-getting-started.md` (208). `docs/README.md` links one of the four.

Two further references resolve nowhere and are legitimate: `docs/guides/multi-agent-setup.md` is a
phase 10 deliverable, and `agent_group.py` is phase 8b step 3. One is not:
`docs/development-workflow.md`, cited by this plan's own file summary and never written. Everything
else that a naive sweep flags -- `nats.py`, `config.py`, `settings.toml` -- is this repository's
bare-filename shorthand, which is convention rather than rot; the audit script resolves those
against `src/blueprint/agents/` before reporting.

**What step 9 will do**, in three commits: write `AGENTS.md`; add
`tests/unit/agents/test_design_rules.py` with one guard per mechanically checkable rule -- including
a reference-resolution guard, which is the check that would have caught `AGENTS.md` and is what
makes the rest durable; and clean up the duplication above. Step 8's surfaces-agree test moves into
that file rather than being written twice.

**The user's instruction, recorded because it widened the step:** `AGENTS.md` alone is not enough --
everything else has to be coherent too. Hence part 3, which is documentation debt this feature did
not create.

---

### Phase 8b, step 2 -- `AgentBuilder` records too, and is built against its own agent's configuration

**This fixes a live defect, not only a shape.** `AgentBuilder.__init__` required a `Config`, and
`Component._shared_config` deliberately has no public read path (config rework step 2b). So in a
`main.py` that only declares -- which is every grouped agent -- there was no configuration in
scope to pass, and the factory form phase 8 documents,
`lambda: AgentBuilder(config, runtime_name="orders").build()`, **could not be written at all**.
`AgentBuilder` was unusable in exactly the deployment shape this feature exists for.

**`agent/agent_builder.py`**

- **`__init__(config: Config | None = None, ...)`.** `config` stays the first positional
  parameter, so `AgentBuilder(config, runtime_name="x")` is untouched; it is now optional, which
  is what makes an unbuilt builder declarable.
- **`with_model_from_config` records.** It used to call `self._config.get_ai_config(...)` on the
  spot, apply the `model_name` override and raise all three of its refusals. Now it sets
  `_model_from_config` and `_model_name_override` and returns. The reading moved to a new
  `_resolve_ai_config`, called from `build()`, which carries the same three refusals with the
  same messages, naming the same runtime.
- **`build(config: Config | None = None, **kwargs)`.** The single-use guard moved to the top,
  ahead of the "model must be configured" check it used to follow -- with `_ai_config` now
  resolved *inside* `build`, the old first check tested a field that is `None` on every call, so
  the two had to be reordered and the model check rewritten to ask whether
  `with_model_from_config()` was called rather than whether it left a result. Then
  `_resolve_config`, `_resolve_ai_config`, and the AI client, prompt and metrics as before, all
  reading the resolved configuration rather than `self._config` directly.
- **`_resolve_config` -- and its precedence is the opposite of `AppBuilder`'s, deliberately.**
  `build(config)` **wins** over `AgentBuilder(config)`. An `AppBuilder` is the application, so
  nothing above it knows better and two configurations mean the author is confused -- step 1 made
  that a refusal. An `AgentBuilder` sits *inside* an application, and what the application passes
  is the view scoped to this agent's namespace (C5), which is the whole point of D6. A
  constructor argument is a convenience for the standalone chain, so it yields. When the two
  differ the choice is logged at DEBUG. At the root `for_namespace("")` returns the loader
  itself, so for a single-agent application they are the same object and nothing is chosen.
- **`_require_config`** raises when neither was given, naming both places one can be passed.
  Not defaulted to `DEFAULT_SETTINGS_FILES` the way `AppBuilder.build()` is: an `AgentBuilder`
  always sits inside an application that already has a configuration, so a missing one is a
  wiring mistake rather than a case to guess a settings file for.
- **`runtime_name`** is now a public property. The application names the agent in its logs and
  its failures before the agent exists.
- `get_model_settings()` reads through `_require_config()`, so it is unchanged for anyone who
  constructed with a configuration and raises a named error for anyone who did not.

**`app_builder.py`**

- **`with_agent` accepts an unbuilt `AgentBuilder`** -- a class, an unbuilt builder, a factory,
  or an instance (D6). `_record` had to learn it, because an `AgentBuilder` is neither a
  `Component` nor callable and would have been refused by the `not callable(target)` branch. It
  is accepted for `kind == "agent"` only; passed to any other `with_*` it is refused with a
  message saying where it belongs.
- **`_construct(declaration, config)`** gained the configuration and a third branch:

      elif isinstance(declaration.target, AgentBuilder):
          with _construction_scope(declaration.namespace):
              instance = declaration.target.build(config.for_namespace(declaration.namespace), **declaration.kwargs)

  That one line is D6: the model, prompt and metrics of a grouped agent are read from its own
  configuration section rather than from the root or from a neighbour's. `_construct_declarations`
  takes the configuration and passes it through; `build()` hands it the one it resolved.
- `AgentRegistration.with_agent` and `_add` learned the same, and the docstring's `lambda`
  example is replaced by the builder form. The factory form still works and is still the escape
  hatch for anything a plain call cannot express -- but it is no longer what the documentation
  recommends, because a lambda closes over whichever configuration was in scope where it was
  written, which in a group is another agent's.
- Importing `AgentBuilder` into `app_builder.py` introduces no cycle: `agent_builder.py` imports
  the config package, the AI clients and `AgentRuntime`, and none of them import the builder.
  Verified by import, not by reading.

**Behavioural change:** the three model refusals move from `with_model_from_config()` to
`build()`. An application that misconfigures its model now learns at build time rather than at
declaration time. Nothing else about them changed -- same conditions, same messages, same runtime
named.

**Tests.** `tests/unit/agents/agent/test_agent_builder.py` gains `TestTheModelRefusalsMovedToBuild`
(the three refusals, plus one asserting the message still names the runtime) and
`TestWhereTheConfigurationComesFrom` (constructible without a config; `build(config)` supplies
one; neither is refused with a message naming both places; `build`'s wins over the constructor's;
`get_model_settings` without one is refused; `runtime_name` readable before building), and
`TestWithModelFromConfig` now pins that it reads no configuration at all.
`test_deferred_wiring.py` gains `TestAnUnbuiltAgentBuilder`: recorded rather than refused, not
built by the `with_` call, handed the namespace-scoped view, handed the loader itself at the root,
constructor arguments forwarded to `build`, and refused by the other `with_*` methods. The
`realize()` helper passes the builder's configuration through the replay. 1979 unit tests pass,
17 more than before this step.

---

### Phase 8b, step 3 -- `AgentGroup`: named declarations in, one application out

**New module `agent_group.py`.** Collection is its own unit, in a class `AppBuilder` has never
heard of. That is the correction that killed the earlier `absorb(builder)` design: an
`AppBuilder` records what *one* agent is made of and never learns it can be collected, so every
rule that exists only because agents share a process lives in the new file rather than being
scattered into the builder, where it would punish the single-agent case for a situation it is
not in.

**`AgentGroup(name, agents, *, cache_names=())`** takes a `Mapping[str, AppBuilder]` -- a mapping
rather than a list because two agents cannot share a name, and a mapping says so structurally
instead of needing a check. Each key is validated as a namespace and the root is refused.
`cache_names` is D3's casualty and is marked as such; it is what `GroupConfig` still carries.

**Three things happen there and nowhere else:**

- **`resolve(config, *, environ=None)`** -- the only I/O: `GroupConfig.resolve` reads the
  environment and the group file. It is `AppBuilder.from_group` moved and renamed.
- **`from_config(group)`** -- imports each agent's module and reads the named attribute, which
  must now be an **`AppBuilder`**, not an `AgentRegistration`. `_load_declaration` and
  `_skip_or_raise` moved across with the critical/non-critical rule intact: a critical agent
  that cannot be loaded raises, a non-critical one is skipped with an ERROR. Reads no
  environment and no files, so a test states an exact composition literally.
- **`assemble(config)`** -- one root `AppBuilder`, one `build()`, one `FastAPI`:

      for namespace, builder in self._agents.items():
          root.host_agent(namespace)
          with namespace_scope(namespace):
              for declaration in builder.declarations:
                  declaration.replay(root)

  The namespace is never passed as an argument. The collector opens a `namespace_scope` and
  `_record` reads it from there -- the same ambient mechanism a component uses, and the reason
  step 4 can delete the `namespace=` keyword without the group losing anything.

**`Declaration.replay(builder)`** is how a recorded call moves onto another builder:

      arguments = () if self.target is None else (self.target,)
      getattr(builder, f"with_{self.kind}")(*arguments, name=self.name, **self.kwargs)

Resolved by name with `getattr` rather than through a table, which is the fourth Builder
anti-pattern -- replay drift -- mitigated as the proposal specified: a table is a second place
to edit, and a missing method fails just as loudly as a `KeyError` while needing no maintenance.
One branch above it handles `with_health_checker(name, checker)`, whose name is positional where
every other `with_*` takes it as a keyword; the irregularity is cheaper in one commented branch
than as a breaking change to published API.

**The refusals** (spec sec. 4.2), all in `_refuse_what_a_group_cannot_honour`, all run before
anything is replayed so a bad group leaves no half-populated registry:

| Refused | Because |
|---|---|
| the builder has already been built | its components exist and belong to the root, and `build()` injects the configuration process-wide, which happens once |
| `AppBuilder(config)` | one process has one settings tree, one logging configuration and one port, and the group supplies all three |
| a declaration holding an instance | it was constructed at that line, before the group existed, so its namespace and registry key are already the root's |

**Order matters and is documented in the code:** the already-built check runs *first*, because
`build()` adopts whatever configuration it resolved, so a built builder always reports one too --
check the configuration first and its message is the only one anybody ever sees. Found by a test
that asserted the wrong message.

**`app_builder.py`**

- **`host_agent(namespace)`** -- extracted from `with_namespace`, which now calls it. Not a
  `with_*`: it declares no component, it states a fact about the process. `build()` needs that
  fact because two of the things it does are per agent rather than per component -- it wires one
  transport per hosted agent, and asks each agent's configuration whether that agent publishes.
  Neither can be derived from the declarations, because an agent may declare nothing and still
  have opted into publishing. The builder is *told*; it never learns another builder exists.
- **`has_config` and `is_built`** -- two public booleans, which is what the collector reads.
  Booleans rather than the objects: handing out the configuration would hand out the *unscoped*
  loader, and config rework step 2b removed every path to that.
- **`with_health_checker` records** a `Declaration` with `kind="health_checker"` instead of
  stashing into a lazily-created `_custom_health_checkers` attribute behind a `hasattr` check.
  This is what stops a group silently dropping an agent's readiness checks, and it hands step 6
  the `(namespace, name)` pair it needs as data. The key is still the bare name, so a readiness
  payload is unchanged and two agents declaring `"db"` still collide -- that is step 6's fix.
  Calling it *after* `build()` still adds straight to the live `ActuatorApi`, because by then
  the declarations have been replayed and recording would do nothing.
- `_UNCONSTRUCTED_KINDS` names the two kinds the replay pass does not construct: a cache is
  created by `CacheBackendFactory`, and a health checker is not a `Component` at all.
- **Deleted:** `from_group`, `with_group`, `_load_registration`, `_skip_or_raise` -- 126 lines,
  and with them the `importlib` and `group_config` imports. `AppBuilder` no longer references
  `GroupConfig` in any form.

**`entrypoint.py`** now reads:

      config = Config(settings_files=DEFAULT_SETTINGS_FILES)
      app = AgentGroup.resolve(config, environ=environ).assemble(config)

so the module holds the one thing neither `AppBuilder` nor `assemble` may do: exit the process.
Its header said it held "the three things `AppBuilder` must not: reading the environment, reading
files, and exiting the process"; two of those now belong to `AgentGroup.resolve`, and the
docstring says so.

`AgentGroup` is exported from `blueprint.agents`.

**Tests.** `test_with_group.py` becomes `tests/unit/agents/test_agent_group.py`, rewritten
against the new surface: one namespace per agent, a group of one, one declaration serving two
agents, a declaration not consumed by being assembled, an empty group, name validation, all
three refusals with the messages that name the agent and the fix, a factory accepted where an
instance is refused, nothing assembled when a refusal fires, the group's caches and an agent's
own cache, a health checker carried over, loading and the critical flag, no I/O in `from_config`,
`resolve`, and a case asserting `AppBuilder` has neither `with_group` nor `from_group`.
`test_entrypoint.py`'s declaration is now an unbuilt `AppBuilder`, and its standalone case builds
a separate one -- a builder builds once, and only that file runs both shapes in one process.
1994 unit tests pass, 15 more than before this step.

---

### Phase 8b, step 4 -- four declaration surfaces become one

**Deleted: `RegisteredComponent`, `AgentRegistration`, `NamespaceBuilder`,
`AppBuilder.with_registration`, `AppBuilder.with_namespace` and its two `@overload`s, and the
`namespace=` keyword on all five `with_*`.** `app_builder.py` goes from 1566 lines to 1236.
`AgentRegistration.apply` and its `appliers` dict go with the class.

This is the payoff the phase was for. Adding one `with_*` method meant editing four places --
`AppBuilder`, `AgentRegistration`, `NamespaceBuilder`, and `apply`'s `appliers` dict -- and
three of those failed *silently*, the capability simply absent from that surface. There is now
one place. The other three existed only to defer construction until a namespace was in force,
and step 1 removed that reason.

**What replaced each of them**

| Deleted | Now |
|---|---|
| `AgentRegistration` | an unbuilt `AppBuilder` -- used without `build()`, it *is* the declaration |
| `NamespaceBuilder` + `with_namespace` | `AgentGroup`, which takes named builders |
| `AgentRegistration.apply` + `appliers` | `Declaration.replay`, resolving the method with `getattr` |
| `namespace=` on the five `with_*` | the ambient scope the group opens |

**`_record` lost its namespace parameter**, and that is the point rather than a tidy-up:

      namespace = current_namespace()

A declaration takes the namespace in force *where it is written* -- the root for a standalone
application, the agent's own for a declaration a group is replaying inside `namespace_scope`.
So nothing a developer writes names a namespace, and the same file serves both deployment
shapes unchanged.

**A removed keyword that would have kept working is refused.** `namespace` is not an error to
Python once the parameter is gone -- it falls into `**kwargs` and is forwarded to the
component's constructor, and `ServiceBase` accepts one. So `with_service(OrderService,
namespace="orders")` would have gone on placing the component in `orders`, by an entirely
different mechanism, until the first component with its own `__init__` failed at build time
instead. `_record` therefore refuses the keyword by name and says what it would otherwise do.
Found by writing the test that asserts the keyword is gone and watching it not raise.

**Smaller changes:**

- The five `with_*` type hints gained `| Callable[[], T]`. Factories were always accepted and
  were only ever in `AgentRegistration`'s signatures; with that class gone, `AppBuilder`'s
  signatures have to say what it takes.
- The instance-namespace refusal is still there and still reachable -- ``with_service(instance)``
  with a scope open -- but its message no longer suggests a `namespace=` argument as the fix.
- `blueprint.agents` no longer exports `AgentRegistration` or `NamespaceBuilder`.
- `AgentSpec.module`'s docstring says `AppBuilder` rather than `AgentRegistration`; it is what
  step 3 made true and this is where it is written down.

**Tests.** `test_agent_registration.py` deleted -- its subject no longer exists.
`test_namespace_builder.py` becomes `test_namespace_placement.py`, keeping every case whose
subject survives the API change: the ambient scope qualifies the registry name, reaches the
component, is never forwarded to its constructor, and is captured at the call rather than at
construction; explicit names are qualified; an already-built instance is refused for another
namespace; `host_agent` records the composition and refuses a duplicate, the root and an illegal
name; a scoped declaration is not a hosted agent. It gains `TestTheDeletedSurfaces`, four cases
pinning that the other three surfaces stay deleted and unexported.

`test_build_namespaces.py` and `test_route_namespacing.py` were written against
`with_namespace(...)`. The route tests now use `AgentGroup(...).assemble(config)` directly,
because they assert on the application. The transport tests need the *root builder* -- the
endpoints they assert on register nowhere, and `assemble()` returns the application and keeps
its builder private -- so they use a local `hosting()` helper that runs `assemble`'s loop
through the same public `Declaration.replay`, with a docstring pointing at `test_agent_group.py`
for the group's own behaviour.

`tests/unit/agents/app_builder/TESTS.md` updated: it documented two files that no longer exist
and a `with_health_checker` that no longer works that way.

1963 unit tests pass, zero failures. The count is 31 *lower* than after step 3, and that is the
deletion showing up rather than coverage lost: the cases for two classes that no longer exist
went with them.

---

---

## Compatibility

**Two breaking changes have landed.** The second one only affects a project that already uses
`Config(agent_scope=...)`; the scheduler change discussed further down is deliberately *not* on
this list, and why is stated with it.

**Breaking change 1: `scheduler_mode` is required.** A project that registers a
scheduler and does not set it fails at `build()` with an error naming both values and what each
one costs. Nothing changes behaviour silently: the alternative -- defaulting the key -- would
either keep firing a timer per replica (#73) or stop ticking a service that has no broker, and
neither is safe to inherit. The reasoning, including the counter-argument, is under *P5* above; it
is a deliberate departure from spec sec. 7.5 and needs a spec amendment.

**Breaking change 2: a scoped `Config`'s telemetry `service.name` is now the agent's name.**
This affects a project that constructs `Config(agent_scope="foo")` -- which is not new, it has
been available since April and is on `develop`, so this is a change to shipped behaviour rather
than to something only this branch can reach.

| | Was | Is |
|---|---|---|
| `otel_service_name` for a scoped view | `<scope>.otel_service_name`, else root `otel_service_name`, else `<scope>.app_name`, else root `app_name` | `<scope>.otel_service_name`, else the scope name |

So a repo with `foo.app_name = "Foo Service"` and no `foo.otel_service_name` sees its
`service.name` change from `Foo Service` to `foo`, and one relying on a *root*
`otel_service_name` while using a scope sees it change to the scope name as well. The root path is
untouched, so a project that passes no `agent_scope` -- every single-agent application -- is
unaffected.

**Migration** is one line if the old name matters: set `<scope>.otel_service_name` to whatever the
dashboards already key on. Keeping the old chain was the alternative and is what C2 forbids: it
lets every agent in a group report one `service.name`, and then regrouping moves work between
agents no dashboard can tell apart. The point of the change is that the agent's name is the one
identity it has.

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

**A spaced `app_name` now fails an event-mode scheduler's startup instead of being rewritten.**
This is the one behaviour change here that can affect an existing project: `app_name = "Health
Monitor"` with `scheduler_mode = "event"` used to derive the tick subject
`Health_Monitor.scheduler.<name>` and now raises at startup, naming the key, the value and that
subject. The rewrite was never safe -- the `CronJob` publishing the tick is written against the
subject by someone who cannot see the rewrite, so the failure it produced was a tick that never
arrived and no log line anywhere explaining it. Migration is either renaming `app_name` to a
subject-safe value or passing `topic=` explicitly. A wildcard in `app_name` or `nats_queue_group`
likewise now fails, where before it reached the broker as a queue name and seeded a wildcard
dead-letter subject.

**The namespace alphabet is a constraint on code that does not exist yet.** Nothing constructs a
namespaced client today, so no name in any deployment is affected; a namespace must now be `""` or
`[a-z][a-z0-9_]*`, which is enforced before the first namespaced agent can be declared. Doing it
now is free -- after the first namespaced deployment, changing the alphabet would rename durables,
and renaming a durable is a consumer migration (spec sec. 7.7).

Everything else remains non-breaking. Specifically:

- `Component.__init__`, `ClientBase.__init__` and `ServiceBase.__init__` gained an optional
  `name` parameter, and `IOClientBase.__init__`, `NATSClient.__init__`, `DaprClient.__init__` and
  `EventPublishingService.__init__` an optional `namespace`. All default to the previous
  behaviour, and the root namespace keeps every existing registry name, so no existing
  construction site or lookup changes.
- `NATSClient._durable_for` became an instance method (it reads the namespace). It is private;
  the public `nats_durable_name` behaviour is unchanged for the root namespace.
- `EventPublishingService.on_startup` now raises a different message when no transport client is
  registered -- it names the namespace it looked in. It raised before too, so this is wording.
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
- **Phase 8 is entirely additive.** A standalone `main.py` deployment is untouched: nothing
  reads `deployment-groups.yaml` or `agents.toml` unless `python -m blueprint.agents.entrypoint`
  or `GroupConfig.resolve` is called, and `uvicorn src.main:app` behaves exactly as before.
- **New environment variables, all optional**: `BLUEPRINT_GROUP_CONFIG`, `BLUEPRINT_GROUP`,
  `BLUEPRINT_AGENTS`, `BLUEPRINT_CRITICAL_AGENTS`, `BLUEPRINT_AGENT_MAP`. They are read only by
  the group resolution, never by `Config`, so they cannot collide with a project's settings.
- **`pyyaml>=6.0` is a new declared dependency.** Asked for and approved; it is what reads the
  group file. Already present in every environment through `uvicorn[standard]`, so declaring it
  changes no installed set -- it stops the group file depending on a *transitive* dependency,
  which is the thing that breaks on an unrelated upgrade.
- **`<agent>.app_name` is no longer required.** A scoped `Config` used to refuse to load without
  it. Setting one is still allowed and still read, but only for display.
- **An agent's `otel_service_name` now defaults to its own name rather than to `app_name`, and no
  longer inherits a root-level `otel_service_name`.** A single-agent application is unchanged:
  explicit `otel_service_name`, then `app_name`, then the default. A grouped agent's
  `service.name` becomes its agent name unless it sets its own -- which is the point (C2), and
  which does change what a dashboard sees for a project that had been relying on the root value
  while using namespaces.
- **A namespaced scheduler's derived tick subject changes from `<app_name>.scheduler.<name>` to
  `<agent>.scheduler.<name>` -- and this is deliberately *not* counted as a breaking change.**
  A scheduler's namespace is only non-empty when it was constructed inside a `namespace_scope`,
  which exists only on this branch: `SchedulerBase.__init__` never took a namespace, and
  `Component`'s namespace parameter arrived with P6. So no deployed scheduler can have one, and
  no `CronJob` in the field publishes to a namespaced subject. A root scheduler -- every one that
  exists -- derives exactly what it derived before.

  It *is* a change for anyone who adopted this branch mid-flight and gave a scheduler a
  namespace: their tick subject moves, and the publisher has to move with it. The startup log
  names the subject in both modes, which is where to read the new value. Note also that
  `Config(agent_scope=...)` alone does **not** give a scheduler a namespace -- a scoped config and
  a component's namespace are different things before this branch -- so a project using
  `agent_scope` today is unaffected by this one.
- **An explicit `name=` is now namespace-qualified, wherever it is set.** At the root -- every
  single-agent application -- `qualified_component_name("", name)` is `name`, so nothing changes.
  Inside a namespace, a component constructed directly with `name="planner"` registers as
  `orders_planner` where it used to register as `planner`. The builder path already behaved this
  way.
- **`Registry.update_component_name` refuses a name that is taken** instead of overwriting the
  entry. Anything relying on the overwrite was losing a component silently.
- **`AppBuilder.with_namespace` refuses an agent name it already hosts** instead of merging into
  it. To assemble one agent from several parts, compose them into one `AgentRegistration`.
- **`EventHandlerBase.get_runtime_name(event, context)` is new and defaults to `None`.** It was
  already in the class's usage docstring, so a project may have written one; it is now actually
  called. Returning `None` keeps today's behaviour.
- **The processing context gains `runtime` and `runtime_name` keys when a runtime can be chosen.**
  A single-agent application with one `AgentRuntime` now finds them populated where it did not
  before -- additive, and nothing in the framework reads them. With several runtimes and no
  declaration neither key is set, and a WARNING names the candidates once per handler.
- **`process_event`'s `runtime_name` argument is no longer only logged.** It seeds the context as
  the caller's choice, below the handler's own `get_runtime_name` and above the single-runtime
  fallback. A caller that passes nothing is unaffected.
- **`DaprEventing()` takes no namespace, and `DaprEventing._client` is now `_clients`, a dict
  keyed by namespace.** There is one endpoint per process, at the root. A single-agent
  application's document, delivery path and acknowledgement are all unchanged.
- **A group of consuming agents on Dapr now works** (it was refused in phase 6 part 2). One
  delivery is fanned out to every agent that declared the topic, and the one acknowledgement is
  their combination -- so **a retry asked for by one agent redelivers to all of them.** Set
  `idempotency_enabled` for grouped Dapr, or keep handlers repeat-tolerant. NATS is unaffected.
- **`_process_cloud_event` and `_dispatch_cloud_event` gained a trailing optional `namespace`.**
  Both are protected; the default is the endpoint's own namespace, which is what every caller
  except the Dapr fan-out passes.
- **The `/cache/*` endpoints take an optional `?name=`, defaulting to `default`.** Every existing
  call is unchanged. New answer: an unknown name is `404` rather than `503`, and `POST
  /cache/evict` now includes a `"cache"` field in its response body.
- **`/readiness` gains one entry per named cache, as `cache:<name>`.** The default cache keeps
  the entry name `cache`, so an existing payload is unchanged. A project that registered only a
  named cache previously had no cache health check at all.
- **A namespaced component's routes move to `/api/<agent>/...`, and its tags gain an
  `<agent>.` prefix.** Nothing moves for an application that declares no namespace: a root REST
  API stays under `/api`, and a root transport endpoint stays at `/events/{topic}` and
  `/dapr/subscribe`.
- **`RestApiBase.route_prefix` is new**, and public, because `DaprEventing.subscribe` has to
  render the same prefix the builder mounts.
- **A group of two or more consuming agents on `event_bus = "dapr"` now fails at `build()`.**
  The sidecar fetches the subscription document from one fixed path, so per-agent documents
  would leave it subscribed to nothing. Single-agent Dapr is unchanged; NATS hosts groups
  normally. Listed under *Open points*.
- **`AppBuilder._eventing_component` is now `_eventing_components`, a list.** Underscore-private,
  but anything introspecting it breaks. It holds exactly one element for every application that
  declares no namespace.
- **`event_publishing_enabled` is now read per agent**, through that agent's configuration view.
  A root-level key still applies to a single-agent application unchanged; in a group an agent can
  set its own, and `<agent>.event_publishing_enabled` wins over the shared value.
- **`SessionsApiClient`, `SessionKeyProvider` and `SessionsBus` gained a leading optional
  `namespace`.** All three are framework-constructed from `build()`, so the leading position
  affects nobody.
- **Phase 5 is not a consumer migration, and expects neither a replay nor a gap.** The plan
  requires this to be stated, because renaming a durable or changing a filter set is broker-side
  state and a recreated consumer resumes by its delivery policy. Neither happens here: the
  namespace-qualified durable landed with P6 and is dormant until a namespace exists (the root
  keeps `<topic>-durable`), and phase 5 changes no filter set -- one durable per
  `(namespace, topic)` filtering one subject was already the shape, so declaring a topic adds a
  consumer instead of reconfiguring one. The first deployment that *is* a migration is the first
  one that declares a namespace, and it creates new consumers rather than renaming existing ones.
- **`RestApiBase.__init__` gained a keyword-only `namespace`**, forwarded to `Component`.
  Defaults to the root, and every subclass in the repo already passes `should_register` by
  keyword, so no existing call changes.
- **`NatsEventing.__init__` and `DaprEventing.__init__` gained a leading optional `namespace`.**
  Both are framework-constructed and unregistered, so the leading position affects nobody.
- **The `blueprint.events.unhandled` and `blueprint.events.duplicate` counters now carry the
  endpoint's real namespace** instead of a hardcoded root. A single-agent application still
  reports `namespace=""`, so no existing dashboard sees a new label value.
- **`EventHandlerBase.get_handled_event_types()` is new and defaults to `[]`**, which means
  "offer me every event" -- the behaviour every handler has today. Overriding it narrows only
  which events that handler is *asked* about; `can_handle_event` still decides. Declarations are
  matched by equality: a pattern such as `order.*` is refused at startup rather than silently
  matching nothing.
- **`SessionsJobHandler` now declares its event type**, derived from the `JOB_TYPE` its
  subclasses already set. Selection is unchanged -- the declaration and `can_handle_event` read
  one property -- so a subclass sees no difference beyond not being asked about other job types.
- **`HandlerChain.__init__` gained a leading optional `namespace`, and `process_event` /
  `process_rest_request` a trailing keyword-only one.** All default to the root. `HandlerChain`
  is constructed by the framework only -- it is `should_register=False` and nothing looks it up --
  so the leading position is safe; the two service methods took keyword-only because their
  positional tails are used by callers.
- **`HandlerChain._dispatch` now asks for its own namespace's handlers instead of every
  namespace's.** For a single-agent application these are the same set: every handler is at the
  root. In a grouped process it is the difference between dispatching to one agent and to all of
  them.
- **`CloudEventProcessorMixin` requires a `namespace` attribute as well as `registry`.** Both come
  from `Component`, which every class it is mixed into already subclasses.
- **`AppBuilder.with_cache` gained a keyword-only `name`, and the three positional forms are
  unchanged.** `with_cache()`, `with_cache(False)` and `with_cache(True, False)` mean what they
  always meant, which is why `name` had to come last and be keyword-only (spec sec. 4.2). The
  default cache keeps its registry key `disk_cache_service`, its configured `cache.cache_dir` and
  its Redis key prefix, so no existing cache data moves.
- **`DiskCacheService.__init__` and `RedisCacheService.__init__` gained a trailing optional
  `component_name`, and `CacheBackendFactory.create` a trailing optional `name`.** Additive and
  defaulted; existing positional calls are unaffected. `create` derives the component name from
  the cache name, so callers pass one name rather than two that have to agree.
- **`AppBuilder.with_*` gained a keyword-only `namespace`, and an explicit `name=` is now qualified
  with the namespace the component was built in.** At the root -- every single-agent application --
  `qualified_component_name("", name)` is `name`, so nothing changes. In a namespace the key becomes
  `<namespace>_<name>`, which is what makes one registration applicable to two agents at all.
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

- **Phase 7's ambiguity error needs a spec amendment.** The plan asks `process_event` to raise
  when a handler declares no runtime and several are registered. It is implemented as a
  once-per-handler WARNING with nothing bound, because raising would fail every delivery in an
  application that has two agents and handlers resolving their own runtime by name -- the shape
  the scaffolder generates. The spec's compatibility table already calls phase 7 "purely
  additive", which the raise would contradict; the plan bullet is what should change.
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
- ~~**The settings-fragment merge has two unanswered questions, both raised by step 3a.**~~
  **Answered 2026-09-10 (D5), and by dissolving the questions rather than deciding them.** A
  group's settings supply *defaults only*, and each agent's own `settings.toml` merges under that
  agent's scope -- so a fragment and a root key never occupy the same slot and there is no
  collision to report or refuse. The second sub-question therefore has no subject, and the first is
  generalised: process-scope keys in a fragment (`app_port`, `event_bus`, `envvar_prefix`,
  `nats_stream_name`) **raise**, from an explicit list, because scoped they are read by nothing and
  reported by nothing. Implementation is phase 8b step 7. The original text follows, because the
  probe in it is still the evidence that nothing merges fragments yet.

  Spec
  sec. 5.3 requires each agent to keep writing plain top-level keys in its own `settings.toml` and
  the build to merge each fragment under that agent's scope, reporting collisions with a root key.
  Confirmed by probe that nothing does this yet: handing two fragments to
  `Config(settings_files=[...])` merges them *flat*, so the last file silently wins -- two
  fragments each declaring `model_name` at root end with `for_namespace("orders")` returning
  billing's value. What the merge must decide, and the spec does not say:
  - **A fragment declaring `envvar_prefix` must be rejected, not merged.** The prefix is
    process-wide -- one group, one prefix -- and it is now a *top-level* key, which is exactly the
    shape a fragment consists of. `_reject_sectioned_envvar_prefix` does not catch this: it looks
    for the key nested inside a section, and a fragment's is at the top level where it looks
    legitimate. Merged and scoped it would be silently inert; merged at root, whichever agent
    happens to load last would decide how the whole group reads its environment.
  - **Whether a fragment may override a shared infrastructure key at all.** Sec. 5.3 says a
    collision between a fragment and a root key MUST be *reported*; it does not say whether it is
    then refused. The two readings differ in practice: an agent overriding `model_name` is the
    point of scoping, while an agent overriding `nats_url` or `app_port` breaks the group it is
    hosted in -- and `app_port` is already root-only (config rework step 1), so at least one key
    has to be refused rather than reported. The likely answer is a small set of group-owned keys
    that a fragment may not carry, with everything else scoped.
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
- ~~**Cache names are not namespace-scoped**~~ -- **done**, by prefixing the partition
  (`AgentScopedCache`). The deployment constraint decided it: a backend per agent per name would
  multiply the writable paths a group needs and split one `emptyDir`'s budget N ways. Two things
  it leaves open. The lens is per *registry view*, so framework code that reaches
  `Component.shared_registry` directly still gets the shared store -- correct today, and worth
  re-checking whenever a framework component starts caching on an agent's behalf. And nothing
  migrates keys written before the prefix existed: an application upgrading with a persistent
  redis cache sees its old entries as absent, which is a cold cache rather than an error, but
  should be said in the migration guide (phase 10).
- **The examples are not migrated, by decision (2026-09-08).** Note that phase 8b changes what
  blocks them: `AgentRegistration` is deleted, and passing instances (`with_rest_api(MonitorApi())`)
  stays legal standalone -- it is refused only when a builder is collected into a group. So the
  examples keep working untouched, and converting them is only needed if they are to be *grouped*.
  Asked
  whether to convert one project's `main.py` as proof, the user chose not to touch the examples
  part-way through the changes, and to revisit them when the integration tests are written --
  where two real example projects grouped into one process would be a better test of C1 and C5
  than a fixture written for the purpose. So the "only `main.py` differs" claim currently lives
  in `test_agent_registration.py` rather than in the tree, and the examples keep passing
  instances (`with_rest_api(MonitorApi())`), which `AgentRegistration` refuses -- converting them
  is part of that later work, not a prerequisite for it.
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
