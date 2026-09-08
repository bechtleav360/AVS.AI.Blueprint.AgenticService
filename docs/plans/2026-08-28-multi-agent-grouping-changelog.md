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

- **Two spec amendments are outstanding for `with_namespace` (phase 3 part 1).** Spec sec. 4.2
  types the return as `AppBuilder | NamespaceBuilder` and lists a `config: Config | None`
  parameter. The union is honoured at runtime but resolved by `@overload` so no caller narrows it;
  the `config` parameter is **not** accepted, because config rework step 2 left it with no reader
  -- `Component.config` derives each component's view from the one loaded tree. The spec should
  say so rather than describing a parameter the implementation refuses. Reasoning in the phase 3
  part 1 entry above.

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
- **The settings-fragment merge has two unanswered questions, both raised by step 3a.** Spec
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
- **The examples are not migrated to `AgentRegistration`, by decision (2026-09-08).** Asked
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
