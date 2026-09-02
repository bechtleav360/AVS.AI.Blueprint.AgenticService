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
  spec/plan convention (`a889f2b`)
- **Acknowledgement contract**: a normal return acks, a raised exception does not; `NO_HANDLER_FOUND`
  acks (`c3d83c8`)
- **Selection and fan-out rules** (spec sec. 7.7), including the two rules that keep a dispatch
  index and broker-side filters non-breaking (`ebcd78d`)
- Acceptance criteria for both of the above (`7491e00`)

Code:

- **P0 -- transport lifecycle**: managed whole-map `subscribe()`, background retry, reconnect
  re-subscription, `subscriptions_ready` readiness gating (`1ffc364`)
- **P0 -- shutdown drain**: in-flight handlers finish before the connection closes (`7bd627f`)
- **P0 -- message boundary**: an undecodable payload is distinguished from a failed dispatch
  (`2a7460f`)
- **Dapr subscription discovery fixed** -- declared topics now actually subscribe; `GET
  /dapr/subscribe` no longer answers 422 (#81, `b2f12dc`)

Documentation and process:

- Deployment guide now warns that multi-replica is unsafe, and its examples default to one replica
  (`459fd53`)
- New config keys documented: `event_client_drain_timeout`, `dapr_pubsub_name`,
  `dapr_declarative_subscriptions`
- Feature working rules in `CLAUDE.md`: one reviewable change at a time (`f6ef96e`), and a
  walkthrough whenever real code is written (`62dffd0`)

Issues opened along the way:

- **#80** -- 28 failing example tests assert on removed examples; the unit/integration split is
  unenforced
- **#81** -- Dapr declared topics never subscribe (fixed here)

**Breaking changes: none so far.** See *Compatibility* at the end.

---

## Changes in detail

### Spec and plan extracted into the repo's conventions (`a889f2b`)

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

### Acknowledgement contract (`c3d83c8`)

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

### Selection and fan-out (`ebcd78d`)

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

### Acceptance criteria for the above (`7491e00`)

Five criteria added to spec sec. 12, covering the ack contract, cross-transport parity, the
undeclared-handler rule, filter derivation, and the two observability counters.

**Motivation.** Sections 7.2 and 7.7 were normative but had no entry in the acceptance criteria, so
"done" did not include them.

### P0 -- transport lifecycle (`1ffc364`)

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

### P0 -- shutdown drain (`7bd627f`)

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

### P0 -- message boundary (`2a7460f`)

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

### Dapr subscription discovery (#81, `b2f12dc`)

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

### Deployment guide corrected (`459fd53`)

The guide recommended `replicaCount: 2`, an HPA, and `--set replicaCount=3` as ordinary scaling. It
now opens with a warning naming the three defects that make multi-replica incorrect rather than
merely inefficient, its examples default to one replica, and the HPA section says to leave
autoscaling off for now. Also dropped the spec's ADR-derived `Status: draft` row, since `draft`
belongs to ADR vocabulary while this repo uses Status as a revision marker.

**Motivation.** This is the only piece of *existing, shipped* documentation that could cause harm
before any code changes: following it doubles every side effect and every inference bill, and
duplicates every cron tick.

### Working rules for this feature (`f6ef96e`, `62dffd0`)

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
- The Dapr subscription document is empty for every project that exists today, since
  `get_subscribed_topics()` is overridden nowhere -- so no deployment can start double-subscribing.
- New config keys all default to current behaviour.

The spec's one deliberate future break is `with_cache`'s `name` parameter (sec. 10.1), which must
stay keyword-only and last, or an existing `with_cache(False)` would silently become a cache named
`False`.

---

## Open points

- **P1-P6 remain**, starting with P1 (queue groups) and P2 (the acknowledgement contract in code).
- **Local NATS and Dapr integration environment.** Everything above is covered by unit tests with
  mocked transports. Once the feature is implemented, stand both brokers up locally (compose file
  plus a CI job) and cover the behaviour that only a real broker exhibits: queue-group distribution
  across replicas, ack/nak/term and redelivery after `ack_wait`, JetStream durable survival across
  reconnect, the shutdown drain acknowledging in-flight work, `filter_subjects` behaviour on a
  durable that already exists, and the Dapr sidecar actually fetching the discovery document and
  delivering to `/events/{topic}`. Depends on the unit/integration split in #80 being settled first,
  since `tests/integration/` is currently not run by CI at all.
- **The two design questions in spec sec. 13** that change the shape rather than the parameters: 20
  or 100 agents, and whether the 4 GB host budget is real.
- **#80** -- the failing example tests and the unenforced test split.
