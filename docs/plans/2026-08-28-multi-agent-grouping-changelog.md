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

Documentation and process:

- Deployment guide now warns that multi-replica is unsafe, and its examples default to one replica
  (`2d80b63`)
- New config keys documented: `event_client_drain_timeout`, `dapr_pubsub_name`,
  `dapr_declarative_subscriptions`
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

The spec's one deliberate future break is `with_cache`'s `name` parameter (sec. 10.1), which must
stay keyword-only and last, or an existing `with_cache(False)` would silently become a cache named
`False`.

---

## Open points

- **P2-P6 remain**, starting with P2 (the acknowledgement contract in code).
- **JetStream competing consumers are still open**, carried into P3: the shared durable needs a
  deliver group set through `ConsumerConfig`/`subscribe_bind`, alongside `ack_wait` and
  `max_ack_pending`. Core NATS -- the default path -- is fixed by P1.
- **Local NATS and Dapr integration environment.** Everything above is covered by unit tests with
  mocked transports. Once the feature is implemented, stand both brokers up locally (compose file
  plus a CI job) and cover the behaviour that only a real broker exhibits: queue-group distribution
  across replicas, ack/nak/term and redelivery after `ack_wait`, JetStream durable survival across
  reconnect, the shutdown drain acknowledging in-flight work, `filter_subjects` behaviour on a
  durable that already exists, and the Dapr sidecar actually fetching the discovery document and
  delivering to `/events/{topic}`. Depends on the unit/integration split in #80 being settled first,
  since `tests/integration/` is currently not run by CI at all. Add to that list: **what a queue
  group does when one agent's subjects overlap** -- a wildcard plus a literal it covers, both in the
  same group, both matching one message. `nats-server` is expected to merge subscriptions by queue
  name across matching nodes and deliver once (to either callback, non-deterministically), which
  would also end the double dispatch such a pair caused before P1. If it does not merge, the agent
  receives the event twice and P2 acks both copies as ordinary work, so the answer changes what P2
  has to handle.
- **The two design questions in spec sec. 13** that change the shape rather than the parameters: 20
  or 100 agents, and whether the 4 GB host budget is real.
- **#80** -- the failing example tests and the unenforced test split.
