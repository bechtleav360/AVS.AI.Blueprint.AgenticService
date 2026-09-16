# asbs validate

Validate the project structure and configuration. Reads files only -- it never imports the
project -- and reports what it finds in three grades: **issues** (the project will not start, exit
status 1), **warnings** (it will start, and something is missing) and **notices** (a decision the
framework must not make for you).

```bash
asbs validate [<project-dir>]
```

## Checks Performed

Project shape:

- Required directories (`src/`, `tests/`) and files (`settings.toml`, `pyproject.toml`) exist
- `src/main.py` exists and uses `AppBuilder`
- `.secrets.toml.example` and `.secrets.toml` are present
- A `Dockerfile` is present

Group readiness -- what this project must state before it can be hosted beside another agent:

- `agents.toml` exists; without it the project cannot be run by
  `python -m blueprint.agents.entrypoint`, and the three changes that make it hostable are named
- Every `[agents.<name>]` entry has a `module` written as `"package.module:attribute"`
- Every agent name is a legal namespace (`[a-z][a-z0-9_]*` -- no dashes), because it becomes the
  queue group, the durable, the cache partition and the telemetry `service.name`
- Every declared module exists in the project and assigns the attribute the map names
- Once there is more than one agent: each ships its own `settings.toml` beside its declaration,
  and declares no process-scope key (`app_port`, `event_bus`, `envvar_prefix`, ...) there, since
  one process binds one port and speaks one bus

Schedulers:

- `scheduler_mode` is set when `src/schedulers/` holds anything, and is one of `in_process` or
  `event` -- it has no default, and `build()` fails without it
- In `event` mode, `event_bus` is set; and a notice that **nothing in this project generates the
  `CronJob`** that must publish the tick. A scheduler waiting for a tick nobody publishes reports
  itself healthy and never runs, which nothing else reports
- In `in_process` mode, a notice when `src/main.py` declares no cache: each tick is claimed in the
  agent's own cache so that one replica runs it, and with no cache every replica runs every tick

Delivery:

- A notice when handlers exist and `idempotency_enabled` is not declared either way. Delivery is
  at-least-once, so the decision is the author's to make and the framework will not make it

## Example

```bash
asbs validate
```

```
Validating Blueprint Agents project: /work/my-ai-service

[ok] Found agents.toml (1 agent(s): my_ai_service)

============================================================

Notices (1):
  - 'scheduler_mode' is 'event', so no timer runs in this process: each tick
    arrives as an event on '<agent>.scheduler.<scheduler name>', published by an external
    CronJob. ...
```

---

## asbs validate --group

Validates an *image* rather than a single agent: the agent map, and every agent directory it
points at. Run it where `agents.toml` is.

```bash
asbs validate --group
```

It checks, per agent:

- `root` and `module` are both present -- neither is derived from the other
- `root` resolves to a directory, inside the image, not shared with another agent
- no file sits where the framework will not read it (a `settings.toml` under `src/`, an
  `agents.toml` inside an agent)
- which `settings.toml` each agent actually reads, printed, so "is it picking mine up?" is
  answerable without starting the process
- process-wide keys left in an agent's settings, which are dropped before the merge
- whether the map key matches the directory name, since `asbs dev` defaults to the latter

Exit status is 1 when anything would stop the image starting, 0 otherwise.

Most of these were, until recently, things the process did silently: none of them stops a pod
starting and passing its probes, which is what made them expensive to find.
