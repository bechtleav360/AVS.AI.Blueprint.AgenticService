# asbs validate

Check a project -- or, with `--group`, an image -- for what its process would refuse or warn
about at startup, before anything is deployed. It reads and parses files; it does not import or
build the project. The one exception is `nats_connection_source`: finding that module imports its
parent packages, as the import at startup would (the module itself is not executed).

Findings come in three grades: **issues** (the process will not start, exit status 1),
**warnings** (it starts, and something is ignored or logged as a warning) and **notices** (a
decision the framework must not make for you).

```bash
asbs validate [<project-dir>] [--environment NAME]
asbs validate --group [<image-root>] [--agent-map PATH] [--group-config PATH] [--group-name NAME] [--environment NAME]
```

## Which settings are checked

Settings are read the way the process reads them, for **one environment**:

- the target environment is `--environment`, else `DYNACONF_APP_ENVIRONMENT` (or
  `<PREFIX>_APP_ENVIRONMENT` with a declared `envvar_prefix`), else **`production`** -- what both
  scaffolded Dockerfiles set in the image that is deployed. Use `--environment development` for
  what `asbs dev` runs.
- the process's own `settings.toml` and `.secrets.toml` are loaded through Dynaconf in environment
  mode: `[default]`, then the target environment's section, then `[global]`. A key set only in
  another environment's section counts as **unset**, and so does a key written at the top level
  outside any section -- the process loads nothing from there, and that is reported as a warning
  (`envvar_prefix` and `app_environment` are exempt: they are read from the top level).
- environment overrides in the shell running the command (`DYNACONF_<KEY>`,
  `DYNACONF_<AGENT>__<KEY>`, or the declared prefix) count, as they do for the pod.
- an agent in a group reads its own scope first -- the image's `[default.<agent>]`, its own
  `.secrets.toml`, its own `settings.toml`, each layered for the target environment -- and then
  the image's keys. The keys the merge drops from an agent's files (see below) resolve to the
  image's value, which is what the agent then reads.

No value from a `.secrets.toml` is ever printed; only key names are.

## Checks performed

Project shape (`asbs validate` only):

- Required directories (`src/`, `tests/`) and files (`settings.toml`, `pyproject.toml`) exist
- `src/main.py` exists and uses `AppBuilder`
- `.secrets.toml.example` and `.secrets.toml` are present (an undotted `secrets.toml` is read by
  nothing and is reported as the rename it needs)
- A `Dockerfile` is present

The agent map:

- No `agents.toml` is the right shape for an agent and gets a notice: the map belongs to the
  image that hosts the agent, never to the agent itself.
- An `agents.toml` with entries makes the directory an image, and it is checked by the
  `--group` rules below -- every entry needs `root`, and an agent's `settings.toml` is read from
  its root, next to the agent's `src/` (one under `src/` is refused by the runtime's layout
  check). An empty or unreadable map is an issue.

Schedulers (per agent with `--group`):

- `scheduler_mode` is set for the target environment when `src/schedulers/` holds anything, and is
  `in_process` or `event` (read as the runtime reads it: trimmed, case-insensitive) -- it has no
  default, and `build()` fails without it
- every literal `crontab="..."` passes the runtime's `validate_crontab` in that mode: five fields,
  no day `7`, and in `event` mode no day of the week given by number (`0` is Monday to the
  blueprint and Sunday to an external cron -- use `mon-fri`, `sun`)
- in `in_process` mode, `scheduler_timezone` is an IANA name (`Europe/Berlin`, `UTC`)
- in `event` mode, `event_bus` is one that delivers a tick (`dapr` or `nats`); a notice when none is
  set (the deployment may set it), and a notice that **nothing in this project generates the
  `CronJob`** that must publish the tick -- a scheduler waiting for a tick nobody publishes reports
  itself healthy and never runs
- in `in_process` mode, a notice when `src/main.py` declares no cache (every replica then runs
  every tick), and a notice when the cache is not Redis: a disk cache's claim holds within one
  process only, so replicas sharing its directory can each run the same tick

Delivery (per agent with `--group`), for an agent with handlers or an event-mode scheduler:

- A notice when `idempotency_enabled` is not set for the target environment. Delivery is
  at-least-once, so the decision is the author's to make and the framework will not make it
- With `idempotency_enabled = true` (read with the runtime's `parse_bool`): `idempotency_ttl` is an
  integer above 0, and `src/main.py` declares `.with_cache()` -- the markers live in the agent's
  cache. Either missing fails startup
- Warnings the handler chain logs at startup: dedup with `nats_heartbeat_enabled = false`, and dedup
  under Dapr, which has no heartbeat; a notice when the dedup cache is not Redis
- A warning when handlers exist and no usable `event_bus` (`dapr`, `nats`, `sessions`) is set:
  event handling is then disabled, and the runtime only logs it
- With `--group` and `event_bus = "dapr"`: a warning for a topic two agents declare (literal
  `get_subscribed_topics` returns) while one of them does not deduplicate -- Dapr delivers it once
  for both, so one agent's retry runs it again in the other
- A warning, with file and line, for code under `src/` that catches `asyncio.CancelledError`
  without re-raising it: a bare `except:`, `except BaseException`, `except asyncio.CancelledError`
  (alone or in a tuple) whose body raises nothing, or `contextlib.suppress(...)` naming one of them.
  When a run exceeds `nats_handler_timeout` it is cancelled; code that swallows that keeps working
  past the limit, holding its slot, and when it returns the delivery is nak'd and redelivered
  anyway. `except Exception` does not catch a cancellation and is fine

NATS (per agent with `--group`):

- The delivery keys are parsed with the client's own parsers: `nats_max_concurrent_runs`,
  `nats_extra_runs_per_process`, `nats_handler_timeout`, `nats_connections_readiness`,
  `nats_unclaimed_subjects`, and `nats_connection_source` (form, and its module found). Checked
  whatever `event_bus` the files say, because the deployment can set it; a value from the image is
  reported once, an agent's own value under the agent's name
- With `event_bus = "nats"`, for an agent that consumes or publishes: `nats_heartbeat_enabled` is a
  boolean, and one `nats_durable_name` does not serve several topics under JetStream. An unset
  `nats_url` outside `development` is a **notice**, not an issue: the deployment usually injects it
  when the container starts (`DYNACONF_NATS_URL`), so a validation that runs while the image is
  built cannot see it -- and the process still refuses to start without one
- Standalone, the queue group (`nats_queue_group`, else `app_name`) can appear in a subject: no
  whitespace, `*` or `>`. A grouped agent's queue group is its name, which is checked as a
  namespace

Process keys:

- `event_loop_debug` is a boolean (read with the runtime's `parse_bool`); anything else fails
  startup

## Example

```bash
asbs validate
```

```
Validating Blueprint Agents project: /work/orders
Environment: production (choose another with --environment)

[ok] Found src/
[ok] Found tests/
[ok] Found settings.toml
...

============================================================

Notices (2):
  - No agents.toml here, which is right for an agent: the map says which agents an *image*
    contains, ...
  - Event deduplication is off ('idempotency_enabled' is not set), so every handler in
    this project can be run more than once for the same event. ...

Warnings (1):
  - This project has event handlers registered but no valid event_bus is configured for
    'production' ('dapr', 'nats', 'sessions'). Event handling will be disabled -- the runtime
    only logs this.

[ok] Validation passed with warnings.
```

That is a project fresh from `asbs setup`: it starts, and its handler receives nothing until an
`event_bus` is set.

---

## asbs validate --group

Validates an *image* rather than a single agent: the agent map, the group file when there is one,
and every agent directory the map points at.

```bash
asbs validate --group                                        # map at the image root
asbs validate --group --agent-map deploy/agents.toml         # map kept elsewhere
asbs validate --group --group-config deploy/finance.yaml     # check the group file a deployment mounts
asbs validate --group --group-name finance                   # one group of a multi-group file
```

The directory argument is the **image root** -- what agent `root` values resolve against, and what
the process would run in. `--agent-map` says where the map itself is, which is a separate question:
the map is a packaging manifest, and `BLUEPRINT_AGENT_MAP` lets a repository keep it in `deploy/`
while its agents stay at the top. A relative `--agent-map` resolves against the image root, and the
environment variable is read when the flag is absent, so the command sees the layout the container
will.

It checks, per agent:

- the name is a legal namespace: `[a-z][a-z0-9_]*`, no dashes, and none of the reserved names
  `cache`, `event_publishing`, `runtime`, `runtimes` -- it becomes the queue group, the durable, the
  cache partition, the telemetry `service.name` and the `/api/<name>` prefix
- `root` and `module` are both present -- neither is derived from the other; `module` is written as
  `"package.module:attribute"`
- `root` resolves to a directory, inside the image, not shared with another agent
- the module is a file of the image that assigns the attribute (a module whose top-level package is
  installed outside the image, as a distribution, is not looked into)
- no file sits where the framework will not read it (a `settings.toml` or `.secrets.toml` under
  `src/`, an `agents.toml` inside an agent)
- which `settings.toml` each agent actually reads, printed, so "is it picking mine up?" is
  answerable without starting the process
- the keys the merge drops from an agent's `settings.toml` **and** `.secrets.toml`: process-wide
  keys (`app_port`, `event_bus`, `log_level`, `envvar_prefix`, ...) and deployment identity
  (`hostname`, `pod_name`, `blueprint_group`). Reported in any section, which is stricter than the
  merge: a section inactive here is active in another deployment
- an agent file that scopes keys under the agent's own name (`[default.<agent>]`), which the merge
  refuses, and an image key of an agent's name that is not a table, which it refuses too
- everything under "Schedulers", "Delivery" and "NATS" above, on that agent's resolved settings
- whether the map key matches the directory name, and the `asbs dev --name` that gives the image's
  routes
- imports of the agent's own code as the top-level package `src`, which work standalone and fail
  in a group

The group file:

- read from `--group-config`, else `BLUEPRINT_GROUP_CONFIG`, else `deployment-groups.yaml` in the
  image root, and resolved by the runtime's own `GroupConfig` with the map above and whichever of
  `BLUEPRINT_GROUP`, `BLUEPRINT_AGENTS` and `BLUEPRINT_CRITICAL_AGENTS` the environment sets
  (`--group-name` wins over `BLUEPRINT_GROUP`). Its refusals are issues, in its own words: an
  `agents` or `critical_agents` that is not a list, a group name declared twice, a critical name the
  group does not run, an agent the image does not contain, a group with no agents
- without a name, every group of a multi-group file is resolved in turn
- a non-critical agent missing from the map is a warning: the process skips it
- with no group file and no `BLUEPRINT_GROUP`/`BLUEPRINT_AGENTS`, nothing is resolved and a notice
  says so -- which agents a process runs is the deployment's decision, made at container start

An empty agent map -- what `asbs setup --group` writes -- is an issue: an image with no agents
refuses to start.

Exit status is 1 when anything would stop the image starting, 0 otherwise.

Most of these were, until recently, things the process did silently or reported only in its log:
none of them stops a pod starting and passing its probes, which is what made them expensive to
find.
