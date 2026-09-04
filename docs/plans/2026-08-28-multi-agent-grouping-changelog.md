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

Documentation and process:

- Deployment guide now warns that multi-replica is unsafe, and its examples default to one replica
  (`2d80b63`)
- New config keys documented: `event_client_drain_timeout`, `dapr_pubsub_name`,
  `dapr_declarative_subscriptions`, `idempotency_enabled`, `idempotency_ttl`
- Feature working rules in `CLAUDE.md`: one reviewable change at a time (`4cf2d51`), and a
  walkthrough whenever real code is written (`7735251`)

Issues opened along the way:

- **#80** -- 28 failing example tests assert on removed examples; the unit/integration split is
  unenforced
- **#81** -- Dapr declared topics never subscribe (fixed here)

**Breaking changes: none so far.** See *Compatibility* at the end.

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

### P4 -- opt-in deduplication, and the decision forced on the author

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

No breaking change has landed. Specifically:

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

The spec's one deliberate future break is `with_cache`'s `name` parameter (sec. 10.1), which must
stay keyword-only and last, or an existing `with_cache(False)` would silently become a cache named
`False`.

---

## Open points

- **P5-P6 remain**, starting with P5 (cron as an event source, #73). P0-P4 have all landed.
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
- **Nothing bounds the dedup cache.** Every dispatched event writes one entry for `idempotency_ttl`
  seconds. `DiskCacheService` expires lazily -- an entry is removed when it is next read, so
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
  has to handle.
- **The two design questions in spec sec. 13** that change the shape rather than the parameters: 20
  or 100 agents, and whether the 4 GB host budget is real.
- **#80** -- the failing example tests and the unenforced test split.
