# Broker integration tests

| | |
|---|---|
| **Status** | Steps 0-3 verified against a real broker, plus chores 1-3. |
| **Why** | Everything the multi-agent work claims about delivery was unit-tested against **mocked transports** and had never been watched against a real broker. Steps 0-3 and chores 1-3 now have been; the rest of *Chores* has not. |
| **Scope** | NATS. Dapr needs a sidecar rather than a broker and is a chore below. |
| **Depends on** | #80, the unit/integration split -- settled in step 0, because `tests/integration/` was not run by CI and sat at 29 failures. |
| **Related** | `docs/plans/2026-08-28-multi-agent-grouping-changelog.md`, whose *Open points* names what only a real broker can settle. |

This document is both the plan and its running record, the way the grouping plan and its changelog
are. It is **not** a phase of that plan: the grouping feature is complete and pushed. This is the
list of things that feature asserts and nobody has yet verified.

## The constraint that shapes how this is written

Docker is on this machine, but **only the developer can reach it**. The tests are written here and
**run by the developer**, who pastes failures back. That makes every step smaller than it would
otherwise be, and makes the harness's first job to fail loudly and readably when the broker is
absent -- every round trip costs a message, so a test that fails obscurely costs two.

The second constraint follows from it: **a broker test must skip, not fail, when the broker is not
there.** An offline run of the whole suite stays green, and `-m integration` is how you ask for the
tests that need something running. This is not a formality: writing it the obvious way produced a
suite that *hung* offline rather than skipping, which is recorded in step 1 below.

## Plan

- **Step 0 -- the unit/integration split (#80).** Landed. See below.
- **Step 1 -- the harness.** Landed and green against NATS. See below.
- **Step 2 -- the path, end to end.** Landed and green. See below.
- **Step 3 -- the acknowledgement lifecycle.** Landed and green. See below.

## Chores

Recorded rather than built, so they are not rediscovered. Each is something only a real broker or a
real cluster can answer.

### Broker behaviour still unwatched

- ~~**Queue-group distribution across replicas.**~~ **Done.** Two application instances sharing one queue group:
  one delivery per message, not two. This is the claim that makes `replicaCount > 1` safe, and it
  is the one P1 rests on.
- **A durable surviving reconnect.** Kill the connection mid-stream and assert nothing is
  redelivered that was already acked, and everything unacked is.
- ~~**The shutdown drain.**~~ **Done.** In-flight handlers finish and their acknowledgements arrive *before* the
  connection closes -- the ordering P0 fixed, and the one that makes duplicates certain on every
  deploy when it is wrong.
- **Overlapping subjects in one queue group.** A wildcard and a literal it covers, both subscribed
  by one agent, one message matching both. `nats-server` is expected to merge the subscriptions and
  deliver once; if it does not, the agent sees the event twice and P2 acks both copies as ordinary
  work, which changes what P2 has to handle.
- **`filter_subjects` on a durable that already exists**, and what the server does with an
  `add_consumer` whose configuration differs from the durable already there.
- **Whether `msg.metadata.num_delivered` lines up with `max_deliver`** the way the dead-letter
  trigger assumes.

### Grouping, against a real broker

- ~~**C1 by observation.**~~ **Done.** Two agents in one `AgentGroup` on one NATS: each sees only its own topics,
  and the durable and queue-group names are byte-identical to the same agent deployed alone. The
  unit tests assert the names; this would assert the consequence.
- **The scheduler tick claim across real processes.** Three replicas in separate processes sharing
  one `DiskCacheService` directory -- whether `diskcache-rs` file locking actually makes `add`
  atomic across processes -- and Redis `SET NX` under real contention.
- **A `CronJob` tick delivered to exactly one replica** through the queue group, and what a
  `CronJob` restart or a missed `startingDeadlineSeconds` actually produces.

### Infrastructure

- **A CI job.** NATS as a GitHub Actions service container, running `-m integration`. Until it
  exists these tests are local-only, which is a smaller version of the problem #80 describes.
- **Dapr.** Needs the sidecar, not just a broker: the discovery document actually fetched, and
  deliveries arriving at `/events/{topic}`. Roughly doubles the harness, and is why it is not in
  the plan above.
- **Redis under contention**, for the dedup `exists`-then-`set` window and the tick claim.

### Found on the way, not fixed

- **`examples/webhook_relay` cannot start against a real NATS.** It sets `event_bus = "nats"` and
  `app_name = "Webhook Relay"`; `app_name` is the root namespace's queue group since P1, and
  `validate_subject_segment` rejects whitespace -- so `_resolve_queue_group` raises at subscribe
  time. Confirmed by calling the validator directly. Four other examples carry a spaced `app_name`
  and are latent rather than broken, because they use Dapr or no bus at all. The examples are
  deliberately untouched by this work; this is exactly the kind of thing step 2's harness would
  catch if it were pointed at them.

---

## Changelog

### Chores 1-3 -- grouping observed, replicas, and the shutdown drain

Three of the *Chores* below, done as tests rather than left as notes.

#### C1 by observation (`test_grouped_agents.py`)

Two agents in one process on one broker and one stream. The unit tests assert the *names* the
framework derives; these assert the consequence:

- an event on one agent's topic reaches that agent and not its neighbour, with both subscribed at
  the same time -- and in both directions at once, so the test cannot pass by one agent being idle;
- the queue group is the **agent's name**, not the group's: `AgentGroup("integration", ...)` is the
  deployment, and nothing broker-side carries it, or moving an agent to another group would move
  its queue group with it;
- two agents subscribing to **the same subject** get a durable each, and both receive the event.
  Sharing a durable would make them one consumer splitting the messages, so each agent would see
  half its own events -- the failure P1 and P6 exist to prevent;
- the same agent, hosted alone and hosted beside a neighbour, presents byte-identical names. If
  they differed, regrouping would strand an agent's backlog on a consumer nothing binds to any
  more: a migration rather than a deployment change.

#### Replicas and the shutdown drain (`test_delivery_once.py`)

The second replica is a raw nats-py subscription bound to **the names the framework derived** --
its deliver subject, its queue group -- rather than a second interpreter. That is the sharper
test: a real replica is identical to the first, so what makes distribution work is that both bind
the *same* names. Six messages, two binders, six deliveries in total rather than twelve.

The drain is three tests, because "it works" is three claims: an in-flight handler **finishes**
when shutdown begins; its acknowledgement **reaches the broker before the connection closes**
(`num_ack_pending == 0`, read after the lifespan has ended); and a second process started on the
same durable is **not** given the message again. Any one of them false makes a rolling deploy
produce duplicates.

#### A false alarm, found by the harness itself

Every run logged:

```
ERROR JetStream stream '...' does not carry subject(s) [...] and could not be updated
      (subject "it....>" overlaps with "it....orders.created");
      consumers filtering those subjects will fail to bind
```

and the consumers bound perfectly well. `_provision_stream` computed the subjects to add with a
**set difference**, so a stream an operator provisioned as `orders.>` looked as though it were
missing every literal underneath it. The client asked the server to add them, the server refused
the overlap, and the client then predicted a failure that does not happen -- on every connect, to
any deployment whose stream uses a wildcard.

New `subject_is_covered_by` in `io_client_base.py` does the NATS match instead (`*` is one token,
`>` is one or more and only last), and `missing` is computed with it. Nine parametrised cases pin
the matcher, including the two easy ones to get wrong: `orders` is **not** covered by `orders.>`,
and `orders.created.eu` is not covered by `orders.*`.

#### One fixture bug, worth recording because it looked like a framework hang

`nats_app` and `nats_group` reset the process-global registry so a test can start a second
process. Put *inside* the lifespan, that cleared the components while shutdown was still running
-- and a shutdown draining an in-flight handler then never returned. It read as the framework
hanging; a standalone probe showed the real drain completing in 1.5s. The reset is now in a
`finally` around the whole `async with`.

### Step 3 -- the acknowledgement lifecycle

`tests/integration/test_acknowledgement_lifecycle.py`. Spec sec. 7.2 fixes one outcome table for
every transport; the unit tests assert the framework *decides* the right disposition, and these
assert the broker then *does* it. Five groups, one per row of the table:

- a `RetryableHandlerError` naks and the same event id reaches the handler again after
  `nats_ack_wait`, with `num_redelivered` confirming it from the broker's side;
- `CriticalHandlerError` and `InvalidEventError` term -- delivered once, and still once after the
  ack-wait window has passed, which is the only way to tell a term from a slow nak;
- an event **no handler matches is acknowledged**, not naked. Finding no work in an event is a
  normal outcome, and naking it would put a message nobody wants back on the queue for ever;
- a payload that is not a CloudEvent is termed **without being dispatched**, and dead-lettered
  with its bytes unchanged -- there is no event id for the header, because nothing parsed;
- `nats_max_deliver` exhaustion stops the handler being called and dead-letters with
  `deliveries-exhausted` rather than `terminal-failure`, because a broken handler and a rejected
  event are different operational problems.

`nats_ack_wait` is 2s in `integration_config`, which is what makes the redelivery assertions
affordable; the two "it did *not* come back" tests each wait two windows.

**Green on the first run against a broker**, having been written entirely from the client's
source with no broker available. All five rows of the disposition table hold as specified.

### Step 2 -- the path, end to end

`tests/integration/test_event_path.py`. Four claims, each read off the **server** rather than off
the framework's account of itself: the handler receives what was published; its `HandlerResult`
reaches the subject `event_publishing.topic_mapping` names, as a new CloudEvent with its own id
and `app_name` as its source; the inbound message is acknowledged, with `num_ack_pending == 0` and
the ack floor advanced; and **it is not redelivered once `nats_ack_wait` has passed**.

That last one is the test a mock cannot write. An unacknowledged JetStream message comes back
after `ack_wait` -- 2 seconds here -- so waiting the window out and finding the handler called once
is the acknowledgement working. `num_ack_pending == 0` alone would pass against a consumer that
had acked and then been redelivered for some other reason, so both are asserted.

The test watches the outbound subject over **Core NATS**, not with a JetStream consumer of its
own: a durable would be broker-side state to tear down, and would bind to the same stream the
application's consumer is on.

#### The framework's stream did not cover the subjects it publishes to -- now fixed

The finding, and it is a live defect rather than a test-shaping detail. `_stream_subjects` returns
the subscribed topics, their `.>` forms, and the dead-letter subject. **A subject a handler result
is published *to* is not among them.** Probed against the broker, with the framework left to
provision its own stream:

```
stream subjects: ['blueprint-it.dead-letter', 'itdfbb736c0a.in', 'itdfbb736c0a.in.>']
outbound covered: False
ERROR   Failed to publish event to topic 'itdfbb736c0a.out': nats: timeout
WARNING Failed to publish handler event: nats: timeout
```

Three consequences, in order of how long they would take to find:

- **The publish stalls.** `js.publish` waits for a stream acknowledgement that no stream will
  send, so every outbound event costs the JetStream publish timeout before it gives up.
- **The event is not persisted.** A Core NATS subscriber *does* see it -- a JetStream publish
  still puts the message on the subject -- so a live listener looks fine while a downstream
  JetStream consumer receives nothing, which is the worst version of this to debug.
- **The failure is a WARNING.** `EventPublishingService.publish_handler_event` catches every
  exception and logs; the handler has already returned, so its inbound message is acked and the
  result is simply gone.

Was stated as `test_the_outbound_subject_is_covered_too`, `xfail(strict=True)`. **Closed**: the
client now declares its publishable subjects and the stream carries them -- see the grouping
changelog's *Publishing is its own decision, and its subjects are declared*. The marker is gone
and the test is an ordinary one. The rest of step 2 still requests the `jetstream` fixture, which
is what a deployment with an operator-provisioned stream looks like.

#### The harness had a collision of its own

Every test used one `app_name`, so every test's client derived the same queue group and therefore
the same default dead-letter subject, `blueprint-it.dead-letter` -- which the client puts into the
stream it provisions. Two tests' streams then claim one subject and the second is refused:

```
BadRequestError: code=400 err_code=10065 description='subjects overlap with an existing stream'
```

Found by leaving a stream behind when a probe crashed and starting the next one. `nats_queue_group`
is now per test, so the dead-letter subject falls inside that test's own prefix. `nats_ack_wait`
dropped from 5s to 2s at the same time, so a test that waits the redelivery window out costs three
seconds rather than six.

### Step 1 -- the harness

Four files: `tests/integration/docker-compose.yml`, the fixtures in `conftest.py`, `helpers.py`,
and `test_harness.py`, which tests the harness itself before anything is tested with it.

**The services.** NATS with JetStream and Redis, both published on localhost because the tests run
on the host:

```yaml
command: ["--jetstream", "--store_dir=/tmp/nats", "--http_port=8222"]
```

`--jetstream` is not optional: without it the server accepts the connection and refuses the stream,
every subscription falls back to Core NATS, and steps 2 and 3 would be asserting redelivery and
`max_deliver` against a transport that has neither. **No volumes, deliberately** -- JetStream state
lives in the container and dies with it, so `down` then `up -d` is a clean broker. A durable
remembers its filter subject and its delivery count, so a leftover one can make a redelivery test
pass against last week's consumer.

**Isolation per test.** `subject_prefix` is a fresh `it<uuid>` per test and every subject goes
under it; `jetstream_stream` yields `IT_<PREFIX>` and **deletes the stream afterwards** -- which
deletes its consumers with it. The fixture deliberately does *not* create the stream: the framework
creates its own in `_ensure_stream`, and a test of that behaviour has to watch it happen.

**The application fixture waits for the subscriptions.** `NATSClient.subscribe()` returns
immediately and connects in a background retry task, so at the moment the lifespan returns the
agent is typically not yet on its topics. A test that published there would be asserting on a
race -- JetStream would hold the message and it would usually pass, Core NATS would drop it and it
would usually fail, and neither outcome would be about the thing under test. So `nats_app` enters
the lifespan directly (not through `TestClient`, which would run it on a second event loop in a
background thread) and then blocks on `subscriptions_ready`.

**The offline path had to be fixed before it worked at all, and this is the useful finding.** The
obvious probe -- `nats.connect(...)`, catch, skip -- **hangs**. Two behaviours combine:
`localhost` resolves to `::1` first on Windows, an unreachable IPv6 port drops the SYN rather than
refusing it (`netstat` shows the connection sitting in `SYN_SENT`), so the attempt stalls for the
whole `connect_timeout`; and nats-py then retries the initial connect **indefinitely**, because
`max_reconnect_attempts` governs re-connection and not the first one. An offline `pytest
tests/integration` sat there until it was killed. The probe is now a bare TCP `open_connection`
under `asyncio.wait_for` -- no protocol handshake, no retry loop, a deadline the fixture owns --
and the default URL is `nats://127.0.0.1:4222` rather than `localhost`. `nats_connection` also
passes `allow_reconnect=False`, so a broker that disappears mid-run fails the test that noticed
instead of parking it in the reconnect loop.

Offline, the whole directory now skips in about a second, and every skip names the command:

```
SKIPPED [1] tests/integration/test_harness.py:59: No NATS server at nats://127.0.0.1:4222.
           Start one with: docker compose -f tests/integration/docker-compose.yml up -d
```

**What `test_harness.py` asserts.** The broker (a Core NATS round trip, and that JetStream is
enabled); the isolation (a stream is this test's own, and no `IT_` stream from an earlier test
survived its teardown); and the application -- it connects and reaches `subscriptions_ready`, its
client reports healthy, its queue group is the agent's identity, the framework creates the stream
it was told to use and covers the subscribed subject, and an event published from outside the
process reaches a handler inside it with no handler left in flight. That last one is step 2 minus
the acknowledgement and the outbound result, and it is here so that a step-2 failure reads as being
about those rather than about whether anything arrives at all.

Also fixed in passing: `test_shared_redis_cache.py` pointed at a `docker run` command instead of
the compose file, and its skip message carried a non-ASCII em-dash that rendered as a replacement
character in the terminal.

**Verified.** `nats:2.10-alpine` accepted the compose file, and all ten harness tests passed on
the first run against it -- including the three that were most likely to be wrong, since they were
written from the client's source rather than from a run: JetStream's reported subject list matching
what the stream was created with, `_ensure_stream` creating the stream and covering the subscribed
subject, and an event published from outside the process reaching a handler inside it. The whole
directory runs in **29 seconds**.

#### The one failure was a pre-existing test, and not about Redis

`test_shared_redis_cache.py::test_two_processes_share_cache` failed the moment Redis was actually
running -- it had skipped for its whole life, so its first real run was this one:

```
subprocess.TimeoutExpired: Command '[...python.exe, -c, "...RedisCacheService..."]'
                           timed out after 10 seconds
```

The subprocess spends its budget **importing the framework**, not talking to Redis: measured at
**11.5s cold** for `from blueprint.agents.services.infrastructure.redis_cache_service import
RedisCacheService`, which pydantic-ai dominates. Ten seconds was below the floor. Three fixes in
`_run_reader`:

- `IMPORT_BUDGET_SECONDS = 60`, named for what it actually pays for, with the measurement recorded
  next to it.
- `TimeoutExpired` becomes an `AssertionError` that says it is an import-speed problem. The failure
  was a `subprocess.py` traceback pointing at nothing in this repository.
- **A non-zero exit carrying stderr now fails with that stderr.** The child exits 1 for a genuine
  cache miss, and every other error was being swallowed into the same `return None` -- so a broken
  reader was indistinguishable from an empty cache, and reported as `read None, expected {...}`.

It is the same lesson as the 29th failure in step 0: a test that has only ever skipped is a test
whose first real run is a first draft.

### Step 0 -- the unit/integration split, settled (#80)

**The prerequisite, and the reason it is one.** `tests/integration/` was **not run by CI at all**
(`ci.yml` and `publish.yml` both run `tests/unit`), so a broker test added there would have been
invisible; and the directory sat at **29 failures**, so a new red line in it would have meant
nothing. Neither is a thing to build on.

The split was enforced three ways at once and agreed with itself in none of them: CI selected by
**directory**, the `integration` marker was applied **by hand** to three tests out of roughly sixty,
and everything else in `tests/integration/` was unmarked -- so `pytest -m "not integration"`
deselected three tests and then failed 28. Two tests in there carried comments explaining that they
were deliberately *not* marked because they were offline, which is a contributor documenting the
confusion in place rather than fixing the category.

**One rule now: a test in `tests/integration/` requires an external service.** New
`tests/integration/conftest.py` applies the marker by location:

```python
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if INTEGRATION_ROOT in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.integration)
```

Directory and marker can no longer drift apart, and nobody has to remember a decorator. The half
that cannot be enforced -- that a test needing nothing does not belong there -- is stated in the
module docstring and in `AGENTS.md`, and the two tests that were in the wrong place were **moved
out rather than marked**.

#### What moved, and what was deleted

`tests/integration/examples/test_examples.py` asserted on seven example projects, **four of which
were deleted from `examples/` over a year ago**. It imports only `pytest`, `pathlib` and `tomllib`:
it never starts a process or opens a socket, so it is a repository-consistency check that had been
filed as an integration test and therefore never run. Rewritten as
`tests/unit/examples/test_example_structure.py`, where CI runs it.

**The list is derived from the directory now, never hardcoded** -- that is the whole lesson of #80.
The two directories that are not projects are listed with the reason, in the `KNOWN_GAPS` style this
repository already uses, and a case asserts each listed one is *still* not a project so the
allowlist cannot outlive its entries:

- `shared_cache_demo` -- standalone demo scripts plus a README, illustrating the cache API. No
  declaration and no settings, because it is not an application.
- `customer_support_qa` -- a skeleton left by an earlier refactor: `src/api`, `src/handlers`,
  `src/models` and `src/services`, but no `main.py`, no `settings.toml` and no `README.md`.

Per project it checks what a reader needs before they can run it: a `main.py` (at the root or under
`src/`, both shapes are in use), a `settings.toml` that parses and names the application, and a
`README.md`. The five real projects pass.

Two 1-line files were deleted rather than carried: `tests/integration/test_blueprint_integration.py`
and `tests/integration/examples/test_example_startup.py`, both reading
`# Tests removed -- to be recreated after architecture refactor`. The refactor happened.

Two genuinely offline tests moved into `tests/unit/`, where their own comments said they belonged:

- `test_sessions_startup_resilience.py` -> `tests/unit/agents/io/api/eventing/`. It binds and
  releases a loopback port to guarantee ECONNREFUSED, which is offline by construction.
- `test_scheduler_event_mode.py` -> `tests/unit/agents/io/api/scheduling/`.

`test_shared_redis_cache.py` stays: it genuinely needs Redis, and skips cleanly without it.

#### The 29th failure was a phase 9 regression nobody had recorded

The changelog carried "the 28 pre-existing failures in `tests/integration/examples/`". There were
**29**, and the extra one was not in `examples/`:
`test_scheduler_event_mode.py::test_event_mode_tick_arrives_as_an_event` answered `RETRY` where it
asserted `SUCCESS`.

The chain: the test builds a Dapr application; the Dapr client's health check probes
`localhost:3500` for a sidecar that is not there; the check fails; phase 9's namespace supervisor
degrades the root agent and **pauses its transports** (C4); and the paused fan-out declines the
tick. Every link is working as designed -- and the test's own docstring, "nothing here reaches the
network", had quietly become false when phase 9 gave that health check a consequence.

Worse than failing: it was **environment-dependent**. The result turned on whether anything happened
to be listening on port 3500, so it would have passed for a developer with a sidecar running.

Fixed in the test, with the framework's own switch rather than a patch:

```toml
health_check_dapr = false
```

The delivery path needs no sidecar; only the health check reaches for one. Turning that probe off
is what makes the test offline again, and deterministic. A new rule in `AGENTS.md` states the
general form: *a test that reaches for a service it does not need is not offline, it is lucky.*

#### Result

| | Before | After |
|---|---|---|
| `pytest tests/ -m "not integration"` | 28 failed, 990 passed | **passes**, 2924 collected |
| `pytest tests/` | 29 failed | **passes** (3 Redis tests skip) |
| `tests/integration/` contents | 6 files, 2 of them 1-line stubs, 1 asserting on deleted examples | 1 file, which needs Redis |

`CLAUDE.md`'s test commands were corrected -- it documented
`uv run pytest tests/ -m "not integration"` as "skip integration tests", which was not what that
command did -- and `AGENTS.md` gained the two rules above.

**Not done here, deliberately:** no CI job runs `-m integration`. That belongs with the harness
that gives it something to run, and is listed under *Chores* below.
