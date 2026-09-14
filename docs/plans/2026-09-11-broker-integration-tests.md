# Broker integration tests

| | |
|---|---|
| **Status** | Step 0 landed. Steps 1-3 next. |
| **Why** | Everything the multi-agent work claims about delivery is unit-tested against **mocked transports**. Nobody has watched any of it happen against a real broker. |
| **Scope** | NATS. Dapr needs a sidecar rather than a broker and is a chore below. |
| **Depends on** | #80, the unit/integration split -- settled in step 0, because `tests/integration/` was not run by CI and sat at 29 failures. |
| **Related** | `docs/plans/2026-08-28-multi-agent-grouping-changelog.md`, whose *Open points* names what only a real broker can settle. |

This document is both the plan and its running record, the way the grouping plan and its changelog
are. It is **not** a phase of that plan: the grouping feature is complete and pushed. This is the
list of things that feature asserts and nobody has yet verified.

## The constraint that shapes how this is written

There is no Docker on the machine this is authored on. The tests are written here and **run by the
developer**, who pastes failures back. That makes every step smaller than it would otherwise be and
makes the harness's first job to fail loudly and readably when the broker is absent.

The second constraint follows from it: **a broker test must skip, not fail, when the broker is not
there.** An offline run of the whole suite stays green, and `-m integration` is how you ask for the
tests that need something running.

## Plan

- **Step 0 -- the unit/integration split (#80).** Landed. See below.
- **Step 1 -- the harness.** A `docker-compose.yml` standing up NATS with JetStream, and the
  fixtures: a connection that skips the test when the server is unreachable, a stream created and
  torn down per test, and an application built against the real URL.
- **Step 2 -- the path, end to end.** A real `AppBuilder` application on real NATS: publish a
  CloudEvent, the handler runs, its `HandlerResult` is published to the outbound subject, and the
  inbound message is acknowledged exactly once. This is the test the whole exercise is for.
- **Step 3 -- the acknowledgement lifecycle.** Against the real broker, not a mock of it: a
  retryable failure naks and is redelivered after `nats_ack_wait`; a `CriticalHandlerError` terms
  and is dead-lettered without redelivery; an event no handler matches is **acked**, not naked; a
  payload that fails CloudEvent parsing terms without dispatching; and `nats_max_deliver`
  exhaustion dead-letters.

## Chores

Recorded rather than built, so they are not rediscovered. Each is something only a real broker or a
real cluster can answer.

### Broker behaviour still unwatched

- **Queue-group distribution across replicas.** Two application instances sharing one queue group:
  one delivery per message, not two. This is the claim that makes `replicaCount > 1` safe, and it
  is the one P1 rests on.
- **A durable surviving reconnect.** Kill the connection mid-stream and assert nothing is
  redelivered that was already acked, and everything unacked is.
- **The shutdown drain.** In-flight handlers finish and their acknowledgements arrive *before* the
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

- **C1 by observation.** Two agents in one `AgentGroup` on one NATS: each sees only its own topics,
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
