# Changelog
## [Unreleased]

### Fixed

- **Event deduplication claims atomically.** The handler chain checked for the marker with
  `exists()` and then wrote it with `set()`, so two replicas handed the same event at the same moment
  both passed the check and both dispatched. It now uses the cache's atomic `claim()`, which already
  existed for the scheduler's tick claim.
- **A handler result that fails to publish fails the delivery.** `publish_handler_event` caught
  every exception and logged a WARNING, so the inbound event was acknowledged and the handler's
  output was lost. The failure now naks the event -- the handler runs again on redelivery -- and the
  dedup marker is released so the redelivery is not skipped. Result events get a deterministic id
  (UUIDv5 over agent, source event, type and position) instead of a random one, so a republished
  result keeps its id and consumers can deduplicate it.
- **An agent latched down at startup is shown as down in `/health/ready`.** The latch paused the
  agent and set its gauge to 0, but readiness was computed from health checks alone, so the probe
  and the payload reported it `UP` with nothing failing. The payload now shows it `DOWN` with a
  `reason`, and the readiness policy counts it. The poll also no longer skips everything when no
  health check is registered, which had left both the verdict and resumption unevaluated.
- **An agent latched down at startup recovers without a restart.** Its failed components are
  retried every `startup_retry_interval_seconds` (default 30), in start order; when all have
  started the latch is released and health checks decide. It never ends the process. `on_startup`
  must therefore be safe to call again after it raised.
- **A non-critical agent marked down at startup no longer consumes events anyway.** When its
  client failed `on_startup`, the agent was paused before its eventing endpoint subscribed, and the
  subscribe path ignored the pause -- so the latched-down agent connected and took events it could
  not process. A paused client now registers its topics and waits; it connects and subscribes only
  if the agent is released.
- **Credentials inside `nats_url` no longer reach the log or `/health`.** The connect log line
  printed the URL verbatim, and the NATS health message printed the parsed URL including
  `user:password@`. Both now show `***@host:port`.
- **An environment override of a key an agent's own `settings.toml` also sets now wins in a group.**
  `DYNACONF_<AGENT>__KEY` was compared against the agent file's keys case-sensitively -- Dynaconf
  upper-cases what it loads, the file keeps lower case -- so the override was never seen: a list
  was concatenated with the file's, a scalar was replaced by the file's value, and the key was
  reported as merged. Keys are now matched case-insensitively, at every nesting level.
- **Both scaffolded `Dockerfile`s declared a `HEALTHCHECK` against a route that does not exist.**
  `curl -f http://localhost:8000/health` -- but `ActuatorApi` serves `/health/live` and
  `/health/ready`, and nothing at `/health`. `curl -f` fails on the 404, so every container built
  from a scaffold reported `unhealthy` for its whole life: compose's `depends_on:
  service_healthy` never released, and anything reading Docker's health state saw a permanently
  failing container that was in fact serving traffic. Both now probe `/health/live`, which is what
  the deployment guide has always shown. A generated-project test holds the path.

- **`asbs validate --group` contradicted the runtime about where an agent's `root` points.** The
  runtime resolves every `root` against the **image root** -- the directory the process runs in --
  and `BLUEPRINT_AGENT_MAP` may put the map anywhere, so a repository keeping `deploy/agents.toml`
  with its agents at the top runs correctly. The validator resolved each `root` against whichever
  directory the map sat in, so it reported that layout as `... is not a directory` under the
  verdict "would stop this image starting" -- a false statement about a working image, whose
  correct reading is to break a layout that worked. The two coincide only where the map is at the
  image root, which is what `asbs setup --group` writes, so no test caught it. The command now
  takes the directory argument as the image root and `--agent-map PATH` (or `BLUEPRINT_AGENT_MAP`)
  as where the map is; a relative path resolves against the image root, as at runtime. The error
  for an absent map names the flag. Present since `root` became required in 0.9.0a4.
- **An agent settings file that scoped keys under the agent's own name merged into nothing.**
  `[default.<agent>]` in that agent's own `settings.toml` nested to `<agent>.<agent>.*` once the
  file was merged under the agent's namespace, so every key in it was unreachable -- and the
  failure surfaced far from the cause, as `No model name for runtime agent '<agent>_agent'
  configured`, naming the agent rather than the file. Found migrating a real project. It is now
  refused at merge, naming the section and the fix, and `asbs validate --group` reports it without
  starting anything. Plain `[default]` serves both shapes: standalone resolves it because a scoped
  lookup falls back to the root key.
- **A grouped agent's own `settings.toml` was never read.** The group looked for it beside the
  *declaration module* -- inside `src/` -- while every scaffolded project writes it beside `src/`,
  so the file existed, looked right, and was never opened. Nothing failed: the agent ran on the
  group's defaults and said so nowhere. It is now read from the directory the agent map states.
- **Prompts resolved against the process working directory.** One directory for a whole group, so
  it was right for at most one agent; the others found nothing, or found a neighbour's prompt of
  the same name. Each agent's configuration view now reports its own directory as the package
  root, so `<agent>/src/prompts` resolves exactly as it does standalone.
- **A scaffolded agent no longer ships process-wide keys.** `log_level` and `log_format` were
  written into every agent's `settings.toml`, so every group one joined dropped them with a
  warning about a file the scaffolder itself wrote. They are now commented out, with the reason.

### Added

- **Handlers see the subject a NATS message was delivered on**, as `context["nats_subject"]`
  (`NATS_SUBJECT_CONTEXT_KEY`), beside `nats_topic`, which is the subscription and may be a
  wildcard. It comes from the broker, not the event, so a tenant can be derived from the subject the
  broker checked rather than from the publisher-controlled `tenantid`.
- **NATS credentials from their own keys.** `nats_user`/`nats_password`, `nats_token`,
  `nats_creds_file` and `nats_nkey_seed` are passed to the connection, so an account under
  tenant-scoped auth no longer has to put its credentials inside `nats_url`. At most one method may
  be configured; a half-set login, a creds file that is not there, or two methods at once fail
  startup. `nats_inbox_prefix` replaces `_INBOX` for accounts not permitted `_INBOX.>`. All are read
  per agent, so each agent of a group can have its own account. The dependency on `nats-py` is now
  `nats-py[nkeys]`, which creds files and nkey seeds need.
- **A `blueprint-migration` Claude Code skill**, installed by `asbs claude`: moving an existing
  single-agent project into a group -- the files it touches, the mistakes that break it, and how
  `asbs validate --group` checks it. The migration guide was previously reachable only from inside
  `blueprint-multi-agent`. `asbs claude` now lists the skills and agents it installed by reading
  them from the package, rather than from a hand-kept list that would have left any new skill
  unannounced.
- **A standalone agent declares nothing group-related.** `asbs setup` writes a `create_app()`
  factory beside the declaration, and the generated Dockerfile serves it with
  `uvicorn src.main:create_app --factory` -- no agent map, no group, no namespace. A group of one
  is still a group, and requiring an agent to declare itself one in order to run alone is what put
  the group's own file inside the agent. The same directory is still hosted by a group image
  without changing a line; its components simply gain that agent's namespace, and with it the
  `/api/<agent>` route prefix.
- **`.dockerignore`**, written by both `asbs setup` and `asbs setup --group`. Not tidy-up: the
  group image copies the whole `agents/` tree, because which agents a process runs is decided at
  startup rather than at build time -- and Docker's build context is the filesystem, not the
  repository, so `**/.secrets.toml` being in `.gitignore` did nothing to keep real keys out of a
  layer.
- **`asbs setup --group` writes a `pyproject.toml`** as well. The group Dockerfile's builder stage
  installs from one, so without it the image could not be built.
- **The declaration rules apply to `create_app` too.** A component registered as an already-built
  instance is refused when a *host* builds a declaration -- `create_app()` or a group -- because an
  agent that works standalone only because nobody checked is an agent that fails the day it joins a
  group. The older shape, `AppBuilder(config)` built in place, stays permissive and keeps working.
- **`root` in the agent map**, required per agent, relative to the directory `agents.toml` is in.
  Stated rather than derived: a root guessed from where a declaration happens to sit is right for
  one layout and silently wrong for every other, and nesting an agent at any depth now costs
  nothing. A missing `root`, one that escapes the image, one that is not a directory, and two
  agents sharing one are each refused at startup, naming the agent.
- **Misplaced files are refused, not ignored** (`blueprint.agents.layout`). One table of artefacts
  with a single legal location, enforced at group assembly and reported by `asbs validate
  --group`: `settings.toml` and `.secrets.toml` beside `src/`, `agents.toml` at the image root.
  `Dockerfile` is deliberately absent from it -- an agent may own one while living in a group
  repository. Adding an artefact is one tuple.
- **`asbs setup --group`** writes the image's files -- an empty agent map, the process settings
  and a group Dockerfile -- and creates no agent.
- **`asbs validate --group`** validates an image: every `root`, each agent's layout, misplaced
  files, process-wide keys left in an agent, and which `settings.toml` each agent actually reads.
- **`asbs dev --name`**, and `asbs dev` no longer needs an `agents.toml` in an agent's directory.
  It writes the one-agent map outside the project for that run.

### Breaking

- **`nats_use_jetstream = true` is enforced against the server; there is no fallback to Core
  NATS.** The server is asked for the account's JetStream information on connecting. If it does not
  offer JetStream, the agent fails: at startup through the startup failure policy, later (broker
  unreachable at startup) by shutting the process down for the root or a critical agent and marking
  a non-critical one down. The previous fallback rarely triggered, and when it did it dropped
  durable consumers and acknowledgements without anyone deciding it.
- **`ClientBase.subscribe()` callbacks take the delivery subject.** The contract is now
  `DeliveryCallback = Callable[[CloudEvent, str], Awaitable[None]]` (in `clients/client_base.py`):
  the event, then the subject it arrived on. Only code that calls `NATSClient.subscribe()` directly,
  or implements `ClientBase`, is affected -- handlers are not. A one-argument callback now fails
  with a `TypeError` on the first message.
- **`nats_url` has no default outside development.** With `event_bus = "nats"` and no `nats_url`,
  a process whose `app_environment` is anything but `"development"` now fails startup naming the
  key -- a standalone or critical agent before the port is bound, a non-critical agent of a group
  by being marked down. It used to connect to `nats://localhost:4222`, which in a pod reaches
  nothing and retried forever while the pod reported healthy. Development keeps the localhost
  fallback, with a WARNING. A broker in the same pod needs `nats_url` set explicitly.
- **A process in development mode logs a WARNING at startup** that it is not suitable for
  production. `app_environment` defaults to `"development"`, so a deployment that sets nothing now
  says so in its own log.
- **`root` is required in `agents.toml`.** Every existing entry needs one line added; a map
  without it refuses to start rather than guessing. For an image that copied one agent to `/app`,
  that is `root = "."`.
- **The standalone image no longer runs the group entry point.** It serves
  `src.main:create_app` directly. An existing project keeps working: `uvicorn src.main:app` is
  still served for a pre-split `main.py`, and a project that wants the old command can keep it.
- **`agents.toml` inside an agent is refused unconditionally**, with no exception for an agent
  mapped at the image root. That shape only existed to let a standalone agent be a group of one,
  which it no longer has to be.
- **`asbs setup` no longer writes `agents.toml` into an agent.** The map says which agents an
  *image* contains, which is a packaging decision -- an agent carrying one is an agent that knows
  whether it is running alone. The single-agent `Dockerfile` writes a one-agent map into its own
  image instead. Existing projects keep working; delete the file when the agent joins a group,
  where it is refused.
- **The `src/<agent>/main.py` group layout is retired.** An agent is now the same directory alone
  or in a group -- `<agent>/settings.toml` beside `<agent>/src/` -- which is what lets it move
  between repositories untouched. Multi-agent grouping has only ever shipped in 0.9.0 alphas, so
  nothing stable depended on the old shape.
- **`AgentMapPartGenerator` is gone.** It generated a file that is no longer written; its
  `agent_namespace` helper moved to `PartGeneratorBase`.

### Added

- **The documentation ships inside the package.** The user-facing guides moved from the repository
  root to `src/blueprint/agent_generator/docs/` and are now installed with the wheel, so a
  developer or an AI assistant working in a consuming project can read them with no network access.
  Previously `README.md` became the wheel's `METADATA` while the 21 documentation pages it links to
  stayed behind in the repository, and every one of those links resolved to nothing once installed.
- **`asbs docs`** locates the packaged documentation: `asbs docs` lists every page, `asbs docs
  <topic>` prints the path to one, `asbs docs <topic> --cat` prints its contents, and `--root`
  prints the directory. A bare page name is accepted when it is unambiguous.
- **Seven Claude Code skills**, installed by `asbs claude` alongside the two that already existed:
  `blueprint-cli`, `blueprint-config`, `blueprint-events`, `blueprint-multi-agent`,
  `blueprint-testing`, `blueprint-deployment` and `blueprint-troubleshooting`. Each carries the
  rules that are expensive to get wrong and points at the packaged page for the rest, rather than
  restating it -- the docs stay the single source of truth.
- **`LICENSE`** (MIT). The repository claimed MIT in its classifiers and linked a `LICENSE` file
  that did not exist; the license is now declared as an SPDX expression and ships in the wheel.

### Changed

- **`docs/guides/cli-reference.md` is an index**, with one page per command under `guides/cli/`
  (`setup`, `create`, `validate`, `dev`, `claude`, plus `naming` and `auto-registration`). It was a
  single 1,023-line page, which meant reading about one flag cost the whole file.
- **Migrating an existing agent into a group is its own page**,
  `guides/multi-agent-migration.md`, split out of `guides/multi-agent-setup.md`.
- **`README.md` links are absolute.** Relative links do not resolve on the PyPI project page or in
  the installed `METADATA`. The CI badge pointed at an unrelated repository.

### Fixed

- **`pytest` and `pytest-asyncio` are no longer runtime dependencies.** They were listed in
  `[project.dependencies]`, so every consumer installed the test suite's tooling in production.
  They remain in the `ci` extra.
- **`SessionKeyProvider`'s `"job"` source now sends `agent_id` as the `X-Agent-Id` header, not a query parameter** (#94). Since #76/#78 (0.7.0), `_get_from_job` sent `agent_id` via `params={"agent_id": ...}` on `GET /internal/jobs/{job_id}/session-key`, but the server (service-sessions#194/#203) reads it from `X-Agent-Id` specifically — deliberately, to keep it out of access logs (service-sessions#198). Every call to this endpoint therefore got `422 Unprocessable Content` ("X-Agent-Id header required"), and every job dispatched to a `session_key_source="job"` consumer silently never progressed past `pending` — root-caused investigating bechtleav360/avs.ai.project.vera#177. No behavior change for `env`/`config`/`vault`/`remote` sources.
- **`SessionsBus._process_job_notification` no longer silently drops a non-403 `HTTPStatusError` (or a failed 403-retry) as an unretrieved asyncio task exception** (#94 follow-up). Both paths used a bare `raise`/re-raise inside a sibling `except` clause, which propagates straight out of the try/except instead of reaching the catch-all `except Exception` below it — invisible because job processing only ever runs as a fire-and-forget task. This was the actual mechanism behind #94's "job silently never progresses past `pending`" symptom, and it applied to any wire-contract drift, not only the one #94 diagnosed. Classification is now a single shared helper (`_is_retryable_http_status`), applied identically on the main dispatch path **and** the 403-retry path:
  - **Non-retryable terminal 4xx** (e.g. 404 unknown/expired job, 409, 422 contract drift) is now logged and, **when a session key was already obtained earlier in the same pass**, cancels the job via `_cancel_invalid_job`; a failed 403-retry cancels the same way.
  - **Retryable** upstream fault (5xx, 408, 429 — a service-sessions deploy/restart, LB blip, or rate limit — or 401, a missing/invalid `X-Api-Key` that's systemic across every job this agent handles rather than specific to this one, and that a cancel attempt would itself hit again) is instead logged and left `pending` for redelivery to retry, exactly like `RetryableHandlerError` — canceling on a transient blip would turn every upstream deploy into permanent job loss, strictly worse than #94's original symptom.
  - **No session key available at all for a terminal error** — #94's own originating case, a failure inside the key fetch itself — the job cannot be cancelled either (service-sessions' `cancel_job` route requires a real `X-Session-Key` unconditionally); that case is now escalated at `critical` instead of disappearing at the same log level as a routine cancel failure, but it does still remain `pending` — a redundant re-fetch was removed, not the underlying inability to authenticate a cancel without a key.

  A review round found the retry path had its own `except Exception` that unconditionally cancelled, including on a retryable failure hit during the retry itself, reintroducing the exact permanent-job-loss risk the classification exists to prevent, just one path over.
- **`_cancel_invalid_job`'s log line no longer reads as "already cancelled" before the cancellation has even been attempted** (#94 follow-up, review nit). It logged `"Invalid job %s: %s. Cancelling."` unconditionally, before checking whether a session key could even be obtained; when that check failed, a `critical` line immediately followed explaining the job could *not* be cancelled — a skimmed incident read of just the first line could wrongly conclude the job was already handled. Reworded to `"...Attempting cancellation."`, accurate regardless of whether the attempt that follows succeeds.
- **`SessionKeyClaimConflictError` (a `"job"` source 409 — another agent instance already claimed this job) is now classified explicitly instead of falling into `_process_job_notification`'s generic catch-all** (#94 follow-up, review finding). The exception's own docstring already documented the intended handling ("a caller catching this specifically can log 'another agent instance already claimed this job' instead of treating it identically to 'the key is simply gone'"), but no `except` clause implemented it — an expected multi-consumer race was logged at `logger.exception` with a full traceback, indistinguishable from a real bug. Now logged at `warning`, with no cancel attempt (there's nothing to cancel; the job belongs to the other instance now).

### Added
- **`AppBuilder.build()` now sources `docs_url`/`redoc_url`/`openapi_url` from config** (#191, defaults unchanged: `/docs`, `/redoc`, `/openapi.json`). Previously these were hardcoded at `FastAPI()` construction, so a consumer could not disable the built-in `/docs` route without mutating `app.router.routes` after the fact — fragile because it depends on FastAPI's internal route-registration shape (bechtleav360/avs.ai.idac.service-sessions#191). Set `docs_url = "@none"` (Dynaconf's `None` cast) in `settings.toml` to opt out before the route is ever registered. Set at the root of `settings.toml`, not under an `agent_scope` block (`Config._scoped_get()` falls back to the root value when a scoped lookup is `None`). Note FastAPI only registers `docs_url`/`redoc_url` when `openapi_url` is also set, so disabling `openapi_url` disables all three.

## [0.9.0] - 2026-09-14

**Multi-agent grouping.** How many agents share a process becomes a *deployment* parameter rather
than an architectural commitment. An agent's code is identical whether it runs alone or beside
nineteen others; only what starts the process differs. A standalone agent is unaffected by almost
all of this — see **Breaking** for the exceptions, which are listed in the order you are likely to
hit them.

Full migration path, including the one decision to get right before the first deploy:
[`guides/multi-agent-setup.md`](src/blueprint/agent_generator/docs/guides/multi-agent-setup.md). The normative spec is
`docs/specs/2026-08-28-multi-agent-grouping.md`.

### Added

- **Agent grouping.** `agents.toml` names the agents an image contains and the module each
  declaration lives in; `BLUEPRINT_AGENTS`, or `BLUEPRINT_GROUP` plus a mounted
  `BLUEPRINT_GROUP_CONFIG` file, decides which of them a given process runs;
  `python -m blueprint.agents.entrypoint` resolves, builds and serves them. Each hosted agent owns
  its handlers, agent runtime, REST routes (`/api/<agent>`), AI client, thread pool, caches and
  broker connection; the port, the health endpoint and the process are shared.
  `BLUEPRINT_CRITICAL_AGENTS` says which agents failing should fail the process.
- **Agents in one process are isolated, and the barrier is enforced rather than conventional.** An
  agent resolves its own components, caches and configuration plus the root's shared ones. Reaching
  a neighbour by its registry key, by an explicit `namespace=` on a view, by a dotted configuration
  key, or by sharing one declaration's mutable argument between two agents is refused or reported
  absent. `Config.settings` remains the documented escape hatch and logs a WARNING naming the agent.
- **An agent's identity is stable across regrouping** (spec C1): its NATS queue group, JetStream
  durable, cache partition, OpenTelemetry `service.name`, registry prefix and REST prefix all derive
  from the agent's own name and never from the group or the pod.
- **Per-agent observability.** `service.name` per agent, `blueprint_namespace_up{agent}`, a
  readiness entry and health checks attributed per agent, `blueprint.scheduler.tick_age_seconds`,
  `blueprint.events.dead_lettered`, `blueprint.events.unhandled` and `blueprint.events.duplicate`.
- **`CacheService.claim`** — set-if-absent, atomic on both backends (`add` on disk, `SET NX EX` on
  Redis). This is the compare-and-set primitive the deduplication work flagged as missing.
- **Named caches.** `with_cache(name=...)`, `/cache/*` endpoints take `?name=`, and `/readiness`
  gains a `cache:<name>` entry per named cache.
- **Opt-in event deduplication** — `idempotency_enabled` and a required `idempotency_ttl`. Off by
  default; a failed dispatch releases its claim so the nak's redelivery still runs.
- **`nats_publish_mode`** (`"core"` / `"jetstream"`) separates publishing from durable consumption,
  with `nats_publish_subjects` for subjects not already in `event_publishing.topic_mapping`. Unset,
  it follows `nats_use_jetstream`, so nothing existing changes.
- **`run_app`**, so a project can serve itself from its own settings.
- **Scaffolding**: `asbs setup` now writes `agents.toml`, a `pyproject.toml` and two tests, so
  `asbs setup` → `pytest` → `asbs validate` closes; `asbs validate` reports what a project has not
  said about grouping and about idempotency; the CLI no longer crashes on a Windows console.
- New config keys: `event_client_drain_timeout`, `dapr_pubsub_name`,
  `dapr_declarative_subscriptions`, `idempotency_enabled`, `idempotency_ttl`, `scheduler_mode`,
  `event_publishing_enabled`, `nats_publish_mode`, `nats_publish_subjects`. All default to current
  behaviour except `scheduler_mode`, which is required — see below.
- `pyyaml>=6.0` is now a declared dependency (it reads the group file). Already present in every
  environment via `uvicorn[standard]`, so no installed set changes.

### Breaking

1. **`scheduler_mode` is required.** A project that registers a scheduler and does not set it fails
   at `build()`, with an error naming both values and what each costs. `"in_process"` reproduces
   today's behaviour exactly and is the no-op migration; `"event"` is the one that fixes #73.
   Defaulting the key would either keep firing a timer per replica or silently stop ticking a
   service with no broker, and neither is safe to inherit.
2. **A subject-unsafe `app_name` or `nats_queue_group` now fails at startup** instead of being
   rewritten or reaching the broker. `app_name = "Health Monitor"` with an event-mode scheduler used
   to derive `Health_Monitor.scheduler.<name>`; the rewrite was invisible to whoever wrote the
   `CronJob`, so the symptom was a tick that never arrived. Rename to a subject-safe value, or pass
   `topic=` explicitly.
3. **A scoped `Config`'s dotted key no longer resolves against the whole tree.** `_scoped_get` used
   to fall back from `<scope>.<key>` to the raw key, and since an agent's section is
   `[default.<agent>]`, that let one agent read another's settings. The fallback is now an allowlist
   of the four prefixes the framework itself owns (`cache`, `event_publishing`, `runtimes`,
   `runtime`). A project reading its *own custom* nested key through a scoped view now gets an error
   naming the rule; flat keys and `Config.settings` are unaffected.
4. **A registry view that names another agent is refused.** `get_component(..., namespace="other")`
   and `get_cache(..., namespace="other")` raise on a scoped view. Every in-framework caller passes
   its own namespace or holds the application registry, so nothing internal is affected.
5. **A scoped `Config`'s telemetry `service.name` is the agent's name.** Affects a project using
   `Config(agent_scope=...)`, which has shipped since April. A repo with `foo.app_name = "Foo
   Service"` and no `foo.otel_service_name` sees `service.name` change from `Foo Service` to `foo`.
   Migration is one line: set `<scope>.otel_service_name` to whatever the dashboards key on. A
   project that passes no `agent_scope` is unaffected.
6. **Cache keys moved, twice.** A cache is now private to the agent that declared it, keyed on
   `(namespace, name)` with its own subdirectory and Redis prefix. An application upgrading with a
   persistent Redis cache or a mounted disk cache sees its old entries as **absent** — a cold cache,
   not an error. A group still needs exactly one writable mount, since an agent's store is a
   subdirectory of `cache.cache_dir`. If any cache entry is load-bearing rather than an
   optimisation, migrate it deliberately.
7. **Four declaration surfaces are deleted**: `AgentRegistration`, `RegisteredComponent`,
   `NamespaceBuilder`, and `AppBuilder.with_namespace` / `with_registration`. `AppBuilder` is the one
   declaration surface; `AgentGroup` collects named declarations into a process. Passing an
   already-built component instance (`with_service(MyService())`) still works for a single standalone
   agent and is refused in a group — pass the class, or a zero-argument factory.
8. **`ClientBase.subscribe` changed from `(topic, callback)` to `(topic_callbacks)`**, and
   `EventHandlingBase.subscribe` and `POST /nats/subscribe/{topic}` are removed. This affects
   third-party transport implementations; both in-repo clients are updated.
9. **On grouped Dapr, one delivery is fanned out in-process to every agent that declared the
   topic, and the single acknowledgement the sidecar receives is their combination** — so a retry
   asked for by one agent redelivers to all of them. The sidecar fetches the subscription document
   from one fixed path, which is why there is one endpoint at the root that routes rather than one
   document per agent. Set `idempotency_enabled` for grouped Dapr, or keep handlers
   repeat-tolerant. Single-agent Dapr and NATS are both unaffected.
10. **`Registry.update_component_name` refuses a name that is already taken** instead of overwriting
    it. Anything relying on the overwrite was losing a component silently.
11. **`asbs setup` now scaffolds `.secrets.toml`**, the name `DEFAULT_SETTINGS_FILES` actually loads;
    it used to write `secrets.toml`, which nothing read. This is a change to the *scaffolder* only —
    the framework's file list is untouched, so no existing deployment changes. `asbs validate`
    reports an undotted file as the rename it needs. An already-scaffolded project should rename its
    file.
12. **`Component.shared_config` is now private (`Component._shared_config`)**, with
    `Component.reset_shared_state()` as the one supported way to clear it. The old attribute was
    public and writable but read by nothing outside `_ComponentMeta`, so hiding it looked like
    code-only cleanup. It is not: a test suite that rebuilds its `AppBuilder` app once per test case
    and resets state between cases with the old `Component.shared_config = None` now silently
    no-ops, since the real state lives on `_shared_config` — `Component.configure()`'s "already set"
    guard then trips starting from the second test in the run, with an error that does not name this
    rename. **Any project resetting shared state between test cases must switch to
    `Component.reset_shared_state()`** in its fixtures; this also clears `shared_registry`, which
    stays public and is otherwise unaffected. A project that never resets shared state between
    builds is unaffected.

### Fixed

- **⚠️ The environment a project selects is now actually the one that loads** (#89). `Config`
  passed the resolved `app_environment` to Dynaconf as `current_env=`, which is a *derived*
  property reporting the active environment, not the parameter that selects one. That parameter
  is `env=`. The resolved environment was therefore never applied: a deployment could log
  `Loading configuration properties for environment: production` and read every value from the
  default section, with nothing anywhere disagreeing. Verified against dynaconf 3.3.5 — with two
  sections that differ, `current_env=` returns the default's value and `env=` returns
  production's.

  **This is a behavioural change, and it is not opt-in.** A project that declares a non-default
  `app_environment` *and* has a matching `[<environment>]` section has been silently running the
  default section; on upgrade it starts getting the section it always asked for. If that section
  is stale — written once, never exercised, never corrected because it never took effect — the
  values in it go live on upgrade. **Check your non-default sections before upgrading.** A
  project with no `app_environment`, or with no section for it, is unaffected.

  Note `app_environment` is read by the first configuration pass, which loads with
  `environments=False` and so sees **top-level keys only** — the same shape `envvar_prefix`
  requires. Declared inside a section it is invisible to that pass and selects nothing, before
  this fix or after; set it at the top level of `settings.toml`, or as `<PREFIX>_APP_ENVIRONMENT`
  in the environment. Pinned by `TestTheResolvedEnvironmentIsTheOneLoaded`, whose cases fail
  against the old keyword.
- **`/status/env` no longer returns credentials in clear** (#91). Config masking matched whole keys
  only, so anything with a prefix or suffix around the secret word came back readable. Present since
  `4e6421b`, unrelated to grouping. An agent-scoped actuator also now reports its own scope rather
  than the whole tree.
- **Dapr declared topics actually subscribe** (#81). `GET /dapr/subscribe` served nothing usable and
  answered 422 to the sidecar. A project that overrides `get_subscribed_topics()` will see Dapr
  behaviour change by design — declared topics went from subscribing to nothing to subscribing.
- **Resilient broker startup and subscription readiness** (#28). Connection and subscription setup
  run asynchronously with background retry, `/health/live` succeeds while retrying,
  `/health/ready` stays unhealthy until subscriptions are established, and NATS and Dapr behave
  consistently. Configurable via `event_client_max_retries` and `event_client_retry_delay`.
- **Schedulers no longer fire duplicate cron ticks under multiple replicas or workers** (#73).
  `scheduler_mode = "event"` delivers the tick as an ordinary event, so the queue group picks one
  replica; `"in_process"` claims each tick in the shared cache so one replica runs it.
- **Schedulers no longer start twice** (#43), on both causes: a second `build()` pass no longer
  starts a second timer, and `SchedulerBase` sitting in the REST-API lifespan loop as well as the
  scheduler loop no longer creates two `AsyncIOScheduler` instances per scheduler. The manual
  trigger route is now registered before `include_router` copies it, so it is actually served.
- **`AgentBuilder` no longer needs a `Config` at construction and builds no model during `__init__`**
  (#4). The AI client and model are resolved in `build()`, against the agent's own configuration view.
- **The unit/integration test split is enforced** (#80). `tests/integration/` was not run by CI and
  sat at 28 failures asserting on examples that had been removed.
- **A handler's published result is no longer silently lost under JetStream.** The client declared
  no publishable subjects, so `js.publish` waited for an acknowledgement no stream would send, timed
  out, and was swallowed as a WARNING while a Core NATS listener still saw the message. Found
  against a real broker.
- **`AgentRuntime` is constructed with its name and registered like every other component.** It
  registered itself under the bare name, so two agents in a group sharing a runtime name collided on
  one registry key. This also made a freshly scaffolded project fail to start with
  `TypeError: AgentRuntime.__init__() missing 1 required positional argument: 'name'`.
- **A scaffolded project starts, tests and validates.** Its settings file wrote `[default.logging]`
  and `[default.observability]` tables the framework never reads; `asbs create agent` wrote
  `[default.runtimes.<agent>.models]` where the framework reads `model_settings`; `asbs create` wrote
  absolute imports into files using relative ones; `asbs create handler` could die mid-command on a
  Windows console leaving the project half-edited; and `asbs setup` printed
  `pip install -e .` without writing a `pyproject.toml`.
- **`token_metrics_enabled` is actually read.** `get_observability_config()` never passed it, so the
  per-call token and latency metrics stayed on however the key was set.
- **`GET /cache/stats` no longer returns 500**, and the four overlapping cache documents are one,
  rewritten against the code.
- **Five bundled examples declared an `app_name` the broker refuses**; `webhook_relay` was broken
  outright. All renamed, and a test now holds every example's `app_name` to the subject alphabet.
- Events that match no handler are counted rather than flagged, acknowledged rather than redelivered
  to `max_deliver`; a critical error drops on Dapr and terms on NATS; an unparseable body drops
  instead of answering 422; in-flight handlers drain before the connection closes; JetStream
  consumers share load via a deliver group; and what the framework gives up on is republished to
  `<queue group>.dead-letter` before being termed.

### Known issues

- Generating the `CronJob` for `scheduler_mode = "event"` is deliberately deferred, so the publisher
  must be written by hand.
- No CI gate enforces that an environment's group declaration covers the in-image agent map;
  `asbs validate` reports it locally.
- The memory number this feature exists to produce — marginal RSS per additional hosted agent — has
  not been measured (#32, #35, #36).
- **#75** (supervisord multi-agent-per-host vs. Kubernetes per-agent Pod) is materially answered by
  the spec: grouping makes the choice a deployment parameter and Kubernetes runs one Deployment per
  group. The ADR the issue asks for is still outstanding.
- Dead letters accumulate on `<queue group>.dead-letter` with no consumer; draining it is an
  operational task the framework does not perform.
- `size` in the cache statistics counts TTL metadata entries, so a cache holding two values reports
  `4`. Documented as-is rather than changed, because a reported metric is somebody's dashboard.

## [0.8.0] - 2026-09-07

### Added
- **`Config.get_sessions_config()` typed accessor for the `[sessions_service]` block** (#87). `Config` already exposed a typed getter for every other config block (`get_ai_config`, `get_cache_config`, `get_observability_config`, `get_event_publishing_config`, `get_prompt_config`, `get_nats_subscription_config`) — sessions was the one gap, even though `SessionsServiceConfig` already shipped. The new getter reads and validates the block against `SessionsServiceConfig`, so downstream agents running in `event_bus = "sessions"` mode can retire the local wrappers they hand-rolled to read the raw `sessions_service` sub-dict (which duplicated the framework's field/default contract and drifted from upstream defaults). Behaviour on an **absent** block is `None` (not an error) — REST-only agents never configure sessions, so absence graceful-degrades rather than raising; a **present but invalid** block (e.g. missing a required `base_url` / `api_key` / `agent_id`) fails fast as a `ConfigError`. Validation errors report field/type only — never the offending input value — so a mistyped `api_key` cannot leak a secret into logs or the error message. Unblocks bechtleav360/avs.ai.idac.agents-document-classifier#44.

## [0.7.0] - 2026-09-04

### Added
- **`SessionsJobHandler` can now mark a job `FAILED`** (#72). `SessionsApiClient` gains `fail_job(session_id, job_id, session_key, error)`, posting a `JobError`-shaped `{"message", "code"}` to the svc-sessions `/fail` endpoint (running→failed, live since 2026-06-24) — the write-side counterpart to the already-generic read side. A new overridable hook `SessionsJobHandler.failure_of(result) -> JobError | None` lets a handler whose `process()` returns a failure *without raising* route that result to `fail_job` instead of `complete_job`; it defaults to `None` (complete), so existing consumers are unchanged until they override it. This unblocks `document-analyser`, whose `AnalyseBatchHandler` computes an internal "failed" outcome and returns it normally (bechtleav360/avs.ai.idac.agents-document-analyser#167, #169). Supersedes the `fail_job`-specific part of #41, whose "jmes-validator-only" premise never applied to `SessionsJobHandler` consumers. The error shape is a new `JobError` `TypedDict` (`blueprint.agents.models.sessions`), so a mistyped key is caught by mypy at the construction site rather than at runtime. The shared terminal-write retry knobs are now `TERMINAL_MAX_ATTEMPTS` / `TERMINAL_RETRY_BACKOFF_SECONDS` (they retry both `complete_job` and `fail_job`); the former `COMPLETE_*` names remain as read-only deprecated aliases (see the ⚠️ note under _Changed_).
- **`SessionKeyProvider` gains a `"job"` source** (#76). `env`/`config` only ever supported one static key for every session, which cannot work for consumers whose session keys are generated fresh per session and actually validated (encryption enforced) — the gap live-reproduced as `ValueError: Environment variable SESSION_KEY not set` immediately after a job dispatch (bechtleav360/avs.ai.project.pida#385). `source = "job"` fetches the key via `GET {session_key_remote_url}/internal/jobs/{job_id}/session-key?agent_id=<this agent's own id>` (bechtleav360/avs.ai.idac.service-sessions#194 Finding 2 / #196), threading a new optional `job_id` parameter through `get_session_key` from `SessionsBus`'s three call sites. A 409 (job already claimed by a different `agent_id`) raises the new `SessionKeyClaimConflictError`, distinct from the 404/`httpx.HTTPStatusError` case. `env`/`config`/`vault`/`remote` sources are unaffected.

### Changed
- **⚠️ BREAKING (behavioural, non-opt-in) — an unrecoverable exception from `process()` now marks the job `FAILED` instead of `COMPLETED`** (#72). Previously `ValueError` and any other non-retryable, non-`InvalidEventError` exception were routed to `complete_job` with an error-shaped result (`{"status": "failed", "error": ...}`), leaving the job's top-level status `COMPLETED`. They now route to `fail_job` (svc-sessions `FAILED`). This applies to **all** consumers on upgrade (unlike the opt-in `failure_of` hook), with **no consumer code change required to be affected**. Two consequences to check before upgrading: (1) svc-sessions spawns pipeline-downstream jobs only on `COMPLETED`, so a step that previously ran through despite an error now **halts its chain** instead of silently continuing on bad data; (2) a consumer that reads a failed job's `result` body sees only `error.message`/`error.code` for these cases (verified: no known consumer does — see PR #79). Deprecated retry knobs `COMPLETE_MAX_ATTEMPTS` / `COMPLETE_RETRY_BACKOFF_SECONDS` are now **read-only** aliases of `TERMINAL_MAX_ATTEMPTS` / `TERMINAL_RETRY_BACKOFF_SECONDS`; overriding the old names no longer changes retry behaviour — tune the `TERMINAL_*` names instead.

### Fixed
- **`SessionsJobHandler`: setting the deprecated `COMPLETE_MAX_ATTEMPTS` / `COMPLETE_RETRY_BACKOFF_SECONDS` class attributes on a subclass now raises `TypeError` at class-definition time** instead of silently shadowing the read-only alias property — a stale pre-0.7.0 override previously kept reading back its own value while `TERMINAL_*`-based retry logic ignored it entirely. Tune `TERMINAL_MAX_ATTEMPTS` / `TERMINAL_RETRY_BACKOFF_SECONDS` instead.
- **`SessionsJobHandler.failure_of()` raising an exception now maps through the same outcome table as a raise from `process()` itself** (e.g. fails the job via `fail_job`) instead of propagating out of `handle_event` uncaught, which previously left the job stuck `RUNNING` with no terminal write and no redelivery.

## [0.6.4] - 2026-07-29

### Fixed
- **`EventProcessingService` no longer constructed when no event handlers are registered** (#67). `AppBuilder.build()` created it unconditionally, even for pure-scheduler or pure-REST agents that never route through the handler chain. Now gated on `registry.get_event_handler()`, mirroring the existing `EventPublishingService` guard.
- **`@traced` no longer binds/stamps arguments on every call when tracing isn't recording** (#65). Checks `span.is_recording()` right after opening the span and skips `inspect.signature().bind()` + attribute extraction for no-op spans (no OTel provider/exporter configured). Span creation and error-status handling are unchanged.
- **`MetricsRecorder` no longer recreates OTel token/latency instruments on every LLM call** (#64). `record()` called `meter.create_counter`/`create_histogram` on every invocation instead of once; both instruments are now created lazily on first use and cached on the instance. Also documents the previously-undocumented `token_metrics_enabled` config key.

## [0.6.3] - 2026-07-08

### Fixed
- **`SessionsBus` now reconciles jobs missed while disconnected** (#57). SSE is a live-only push
  transport, so jobs created during a restart, redeploy, or stream gap were never delivered and
  stayed `pending` on the server (observed: 9 `analyse.batch` jobs created before a reconnect that
  were never picked up). On every (re)connect the bus now reconciles two ways: (1) a REST
  **catch-up** — lists pending jobs for its capabilities (`GET /jobs?status=pending`) and dispatches
  each through the normal job path (best-effort; de-duplicated by the handler's idempotency guards;
  a listing failure never disturbs the live stream), and (2) **`Last-Event-ID` resume** — tracks the
  last SSE event id and sends `last_event_id` on reconnect so a same-process stream gap replays from
  the server ring buffer. A cold start omits `last_event_id` (catch-up covers it). Distinct follow-on
  to #45. A job stranded in `running` by a crashed agent is recovered server-side
  (avs.ai.idac.service-sessions#127) and then redelivered by this catch-up.

## [0.6.2] - 2026-07-06

### Fixed
- **`SessionsBus` registers with the dispatch registry before opening the SSE stream** (#45).
  Sessions v0.4.0 gates `GET /jobs/stream/sse` on a prior `POST /agents/register`; the bus now
  registers (idempotent) before every connect attempt and re-registers on reconnect, fixing the
  403 loop that broke all deployed agents. A pre-v0.4.0 server (404 on register) is handled as
  "legacy, proceed without registration". The real status/body of an SSE rejection is now logged
  instead of an opaque `SSEError`.
- **Keepalive comment frames are no longer logged as `Unknown SSE event type: message`** (#44).

### Changed
- **`SessionsBus` unregisters and drains in-flight jobs on graceful shutdown.** It stops the stream,
  waits for in-flight jobs (bounded by `job_timeout_seconds`, cancelling stragglers), then calls
  `DELETE /agents/{agent_id}` so the agent leaves the registry immediately instead of lapsing at TTL.
- Job notifications are parsed into a typed `JobNotification` model at the SSE boundary.
- **Business REST routers no longer carry a blanket `rest` OpenAPI tag.** `_build_rest_endpoints` mounted every `with_rest_api` router with `include_router(..., tags=["rest"])`, which stamps a redundant `rest` tag onto *every* operation on top of its own per-operation tag — so the entire business API collapses into a single `rest` group in Swagger UI. Routers are now mounted without the blanket tag; operations group by their real resource tags (set via the `RestApiBase` decorators), and untagged routes fall under FastAPI's `default`. Presentation only — no route/path/schema change. Downstream services that relied on the `rest` grouping should tag their routes (most already do).

## [0.6.1] - 2026-06-10

### Added
- **`SessionsJobHandler`** (`blueprint.agents.handler`) — shared job-lifecycle base for
  sessions-service SSE handlers (#19). Subclasses set `JOB_TYPE`, `PAYLOAD_MODEL`,
  `RESULT_MODEL` and implement `process()`; the base wraps fetch → validate → start →
  process → complete with two-stage idempotency (an in-flight guard for concurrent
  duplicates plus a **terminal-only** seen-set populated only on complete/cancel) and a
  centralised error→status mapping (cancel / complete-with-error / left-eligible-for-
  redelivery). Post-start retryable/critical failures are not silently dropped, but are
  not yet fully resumable — svc-sessions rejects `RUNNING→RUNNING` (409), so true resume
  awaits a re-pend/lease capability there (avs.ai.idac.service-sessions#59).
  Additive and backwards compatible — `EventHandlerBase` is unchanged.

### Fixed
- **OpenAPI app metadata now comes from config** (#11). `AppBuilder.build()` no longer
  hardcodes `version="0.1.0"`; it reads `app_version` (fallback `"0.0.0"`) alongside
  `app_name` (fallback `"blueprint-service"`) and `app_description` (fallback `""`). The
  misleading framework-internal description fallback is removed. Set `app_version` in a
  service's `settings.toml` to surface the real version at `/docs`.
- **`asbs dev` now uses the launching interpreter** (#15). The dev server subprocess
  spawned `"python"` literally, which on Windows with uv-managed venvs could resolve to
  uv's base interpreter and fail with `No module named uvicorn`. It now uses
  `sys.executable`, so the reload server runs in the same venv as `asbs`.
- **Kebab-case component names produce valid identifiers** (#3). `camel_to_snake` now
  normalizes hyphens, so kebab-case names no longer generate invalid Python identifiers.

## [0.5.0] - 2026-03-05

### Architecture Refactoring - Component System Streamlining

**Planned from Plan.md - 3 features ready for implementation**

#### Feature 3: Streamlined Base Package (Foundation)
- **BREAKING**: Promote concrete default implementations into `Component` base class
  - `get_name()`, `get_registry()`, `get_config()` default implementations
  - `link_config()`, `link_component_registry()` no longer abstract
  - `on_startup()`, `on_shutdown()` default no-op implementations
- Remove redundant overrides from `EventHandler`, `BusinessService`, `RestApi`, `AgentRuntime`
- Delete `interfaces.py` - `ComponentInterface` Protocol is unused

#### Feature 1: FastAPI Annotation-Based Route Registration
- **BREAKING**: `RestApi` decorator-based route registration
  - `RestApi.__init__` creates `APIRouter` and auto-discovers decorated methods
  - Routes defined with `@self.router.get()`, `@self.router.post()`, etc.
  - Remove `_register_routes()` abstract method
  - Remove `payload_type` init parameter and `Generic[PayloadT]`
- Update all 4 REST API examples to use annotation pattern

#### Feature 2: Scheduler Base Class
- **NEW**: `Scheduler` base class in `blueprint.agents.base`
  - Extends `Component` with full registry and config access
  - Constructor: `__init__(self, crontab: str, name: str = "Scheduler")`
  - Abstract method: `tick(self) -> None` - called on each cron interval
  - Background asyncio task with `croniter` for schedule evaluation
  - Automatic lifecycle management (startup/shutdown)
- Add `AppBuilder.with_scheduler(scheduler: Scheduler)` method
- Integrate into lifespan manager for proper startup/shutdown

### Sessions Service Integration - Architecture Planning 📋

**Documented in plan_blueprint.md - Ready for implementation**

Comprehensive 6-phase architecture plan for consuming jobs from Sessions Service via SSE:

#### Planned Components
- **JobConsumerService**: SSE connection management and job-to-CloudEvent conversion
- **SessionsApiClient**: REST API client for job lifecycle operations
- **JobHandler**: Optional convenience base class for job processing
- **SessionKeyProvider**: Abstract session key retrieval from multiple sources



### Testing & Quality Assurance

#### Example Verification System
- **NEW**: Comprehensive integration tests for all 7 example applications
  - `tests/integration/examples/test_examples.py` - 36 structure/config tests
  - `tests/verify_examples.py` - Automated startup verification script
  - All 36 structure tests passing ✓
  - 5/7 examples start without API keys, 2/7 require credentials



## [0.3.XX] - Planned
- RestAPI Baseclass for all RestAPIs
- Component Class as Baseclass for all Components (Baseclasses)
- Implement some standard methods in Component
- Scheduler in communication layer (Alternative to Events and API)

## [0.3.11] - 2025-12-22

### Highlights
- Added a  two-agent **Customer Support Q&A** example app and documented the new workflow, configuration guide, and config validation script.
- `Config.get_ai_config()` now understands both `model_*` and legacy `ai_model_*` keys plus plural/singular runtime sections.
- Health check logging is quiet unless something fails (new filter, toned-down actuator + provider logs).

## [0.3.10] - 2025-11-27

- [ ] Make the status of the Handler Result an Enum
- [ ]  Improve logging for parallel event consumption. Configure the logging formatter to always print the current event ID
- [ ]  Add endpoint to receive logs identified either bei span id or event id


## [0.3.9] - 2025-11-27

### Fixed
- Hardened `AgentBuilder.build()` so it always resolves the configured system prompt (either explicit or runtime default) before constructing `AgentRuntime`, raising helpful `ValueError`s when configuration is missing or the prompt cannot be loaded. This prevents the prior `TypeError: 'NoneType' object is not iterable` during agent startup.
- Added regression coverage around the updated builder behavior to ensure `PromptLoader` results are passed through to the runtime constructor and that misconfiguration is surfaced immediately.

### Documentation
- Reframed the integration testing guide into a black-box testing prompt for LLM-driven test generation, making the expected Dapr/respx workflow explicit and avoiding instructions that mock internal classes.

## [0.3.8] - 2025-11-26

### Added
- DAPR events are now automatically unwrapped

### New Cache introduced
- **Persistent Caching Layer**: New `CacheService` and `DiskCacheService` for high-performance disk-based caching
- `AppBuilder.with_cache()` method to enable caching with fluent interface
- `ComponentRegistry.get_cache()`, `has_cache()` methods for cache management

#### Features
- **Order-independent key hashing**: `{"a":1,"b":2}` and `{"b":2,"a":1}` produce identical hashes
- **JSON string normalization**: JSON strings are automatically parsed and sorted for consistent hashing
- **Recursive JSON handling**: Nested JSON structures are properly normalized
- **Lazy TTL cleanup**: Expired entries are cleaned up only when accessed
- **Cache statistics**: `get_stats()` method for monitoring cache usage

#### Configuration
New cache settings in `settings.toml`:
```toml
[cache]
cache_dir = ".cache/blueprint"           # Cache directory path
size_limit = 1000000000                  # 1GB max size
eviction_policy = "least-recently-used"  # LRU eviction
default_ttl = 3600                       # 1 hour default TTL
```

#### Dependencies
- Added `diskcache-rs>=0.4.4` for high-performance persistent caching

## [0.3.4]- 2025-11-25

### Added
- New `/info` actuator endpoint exposing app name, version, and all dependency versions.
- `ServiceInfo` model (`src/blueprint/agents/models/status.py`) for structured `/info` responses.
- Actuator links (`/info`, `/status/env`, `/status/llm`, `/status/build`) in root `/` metadata.
- Supporting classes in component registry in addition to names
- Fetching an unregistered component now throws an exception
- Added get_config() to all base classes
- Simplied Prompt Loading, removed the need to give package root and config path to AgentBuilder

### New Feature: Dapr Retry Flow
We are strictly avoiding the DROP status for errors because Dapr deletes DROP messages immediately.

To ensure failed messages eventually reach the Dead Letter Queue (DLQ), we use the following flow:

- Application Error: Your code throws an exception (e.g., 500 Internal Error).
- Return RETRY: We catch this and tell Dapr to RETRY.
- Dapr Retries: Dapr will retry the message N times based on your configured Resiliency Policy.
- Move to DLQ: Once the max retries are exhausted, Dapr automatically moves the message to the configured Dead Letter Topic.



## [0.3.0] - 2025-11-24

### Changed
- **BREAKING:** Refactored `AppBuilder` constructor - now requires `Config` object instead of `settings_files` and `root_path` parameters
- **BREAKING:** Moved base classes to unified `blueprint.agents.base` module: `EventHandler`, `AgentRuntime`, `RestApi`, `BusinessService`
- Handler storage refactored from dict to list to support multiple handlers with identical names
- All components now use async `on_startup()` lifecycle hooks to retrieve dependencies from registry

### Added
- `AppBuilder.with_service()` method to register business services
- Async lifecycle management for all components via `on_startup()` and `on_shutdown()` hooks

### Removed
- `AgentRuntime` from `blueprint.agents.agent` module (moved to `blueprint.agents.base`)
- `EventHandler` from `blueprint.agents.handler` module (moved to `blueprint.agents.base`)
- `RestApi` from `blueprint.agents.api.rest` module (moved to `blueprint.agents.base`)
- `package_root` parameter from `AgentBuilder` - no longer needed with new prompt loading

### Fixed
- All integration and unit tests updated for new architecture
- FastAPI `TestClient` fixtures now properly manage lifespan to run startup hooks
- Example applications refactored to use new `AppBuilder(config=Config(...))` pattern

## [0.2.8] - 2025-11-24

### Added
- New `MetricsRecorder` and `MetricsExtractor` classes for modular metrics handling
- `with_metrics(enabled: bool = True)` builder method to toggle metrics logging
- `AgentRuntime.get_prompt(prompt_name)` method for lazy-loaded prompt retrieval with caching
- Complete prompt handling redesign with simplified API

### Changed
- **BREAKING:** Simplified `AgentBuilder` prompt API - replaced 4 methods with single `with_system_prompt(prompt: str | None = None)`
- Extracted metrics functionality from `AgentBuilder` to dedicated `metrics.py` module
- Logging levels upgraded from DEBUG to INFO for builder configuration operations
- Prompt loading strategy changed from pre-load at build time to lazy-load on demand
- Removed `_prompts` pre-loading from `AgentBuilder` - now uses lazy loading with caching in `AgentRuntime`
- Cleaned up public API exports - removed unused factory classes

### Removed
- `AgentFactory` - not used, AgentBuilder creates agents directly
- `ResponseHandlerFactory` - not integrated into agent creation flow
- `_prompts` attribute from `AgentBuilder` (prompts now lazy-loaded)
- `_load_prompt()` internal method from `AgentBuilder`
- Unused factory and handler exports from public API

### Deprecated
- `with_system_prompt_text()` - use `with_system_prompt(prompt_text)` instead
- `with_system_prompt_file()` - use `with_system_prompt()` to load from config
- `with_system_prompt_from_config()` - use `with_system_prompt()` instead
- `with_prompt()` - use `agent.get_prompt(prompt_name)` for lazy loading instead
- `AgentRuntime.prompts` property - use `agent.get_prompt(name)` instead
- `AgentRuntime.register_prompt()` - use `agent.get_prompt(name)` instead

### Fixed
- All 73 unit tests passing with backward compatibility maintained
- Performance improved by eliminating unnecessary pre-loading of prompts

### Migration Guide
**Old (Deprecated):**
```python
agent = (
    AgentBuilder(config)
    .with_model_from_config()
    .with_system_prompt_text("prompt")
    .with_prompt("template")
    .build()
)
prompt = agent.prompts["template"]
```

**New (Recommended):**
```python
agent = (
    AgentBuilder(config)
    .with_model_from_config()
    .with_system_prompt("prompt")  # or .with_system_prompt() to load from config
    .build()
)
prompt = agent.get_prompt("template")  # lazy-loaded and cached
prompt = prompt.format(difficulty="hard")
```

### Notes
- ✅ All 73 unit tests passing
- ✅ Simpler, cleaner API with lazy loading and caching
- ✅ Better performance - no unnecessary pre-loading
- ✅ Clear separation of concerns - builder sets system prompt, runtime loads instruction prompts

## [0.2.6] - 2025-11-23

### Added
- Handlers can now return `list[HandlerResult]` to publish multiple events from a single handler
- Added 6 new tests for multiple handler results feature

### Changed
- `EventHandler.handle()` return type now includes `list[HandlerResult]`
- `ProcessingService.process_event()` now publishes each result with `event_type` separately
- `_ResultBuilder.extract_handler_result()` detects and handles list of results

### Fixed
- Proper handling of mixed results where some have `event_type=None`
- OpenTelemetry tracing now includes result count for multi-result scenarios

### Notes
- ✅ Fully backward compatible - all existing code continues to work
- ✅ All 137 unit tests passing (6 new tests added)
