# Multi-Agent Setup

How to run several agents in one process, and how to move an agent you already have into one.

The model in one sentence: **an agent's code says nothing about which other agents it runs beside.**
A project declares what it is made of; a deployment decides which of those declarations a given
process hosts. Changing that decision is an edit to a Deployment, not a rebuild, and -- after the
first grouped deploy -- it is invisible to the broker, to your dashboards and to the agent's own
code.

Why you would want it: one process per agent is the safest shape and the most expensive one. A
group of ten agents shares one port, one health endpoint, one NATS connection and one Python
runtime. The dial runs from a group of one (full process isolation) to a group of twenty, and it is
a runtime setting rather than an architectural commitment.

---

## Read this first: which of the two are you doing?

Everything below splits along one question, and the answers differ in ways that matter:

| | You are here if | What changes |
|---|---|---|
| **A. A new project** | You are running `asbs setup` today | Nothing to migrate. Your agent has a real namespace from the first run |
| **B. An existing single-agent project** | You have a `main.py` that builds and serves an application | Three files change, and your **broker-side identity changes once** -- see [What changes](#what-changes-and-what-does-not) |

A third answer is legitimate and costs nothing: **do nothing.** An existing project that is
deployed on its own keeps working, unchanged, indefinitely. There is no deprecation here.

---

## A. A new project

```bash
asbs setup order-processor
cd OrderProcessor
```

Two of the files it writes are what make the project hostable:

**`src/main.py` is a declaration, not an application.**

```python
order_processor_agent = (
    AgentBuilder(runtime_name="order_processor_agent")
    .with_model_from_config()
    .with_system_prompt("order_processor_agent_system")
)

agent = (
    AppBuilder()
    .with_service(OrderProcessorService)
    .with_agent(order_processor_agent, name="order_processor_agent")
    .with_handler(OrderProcessorHandler)
    .with_rest_api(OrderProcessorApi)
)
```

There is no `Config` and no `build()`. Every `with_*` call *records* what the agent is made of;
nothing is constructed until whoever hosts this file calls `build()`, which is what lets the same
file be served alone and be hosted beside other agents. Note that components are registered as
**classes**, not instances: a component constructed on the `with_*` line is constructed before any
namespace exists and belongs to the root for ever, which is why a group refuses one.

**`agents.toml` maps the agent's name to that declaration.**

```toml
[agents.order_processor]
module = "src.main:agent"
```

This file is **baked into the image**: it says what the image contains. It does not say which of
those agents any particular process runs -- that is the deployment's decision, and it arrives
separately.

The `Dockerfile` runs `python -m blueprint.agents.entrypoint`, which reads `agents.toml`, works out
this process's group, and serves it.

### Running it

```bash
asbs dev                      # every agent in agents.toml, with hot reload
asbs dev --agents order_processor
asbs validate                 # what this project has not said yet
```

`asbs dev` runs your agents under their **real** namespaces, so a local route is
`/api/order_processor/orders/{id}` -- byte-identical to production -- and the local consumer
identity is the production queue group. A development server at the root namespace would give every
developer URLs and integration tests that differ from the deployed ones, in a way nothing reports.

```bash
docker build -t order-processor .
docker run -e BLUEPRINT_AGENTS=order_processor -p 8000:8000 order-processor
```

### Adding a second agent to the same image

Put the second agent's code in its own package, give it its own declaration module and its own
`settings.toml` **beside that module**, and add it to the map:

```toml
[agents.order_processor]
module = "src.order_processor.main:agent"

[agents.billing]
module = "src.billing.main:agent"
```

Each agent's `settings.toml` is read from the directory its declaration lives in and merged under
that agent's own scope, so both may write plain top-level keys and neither sees the other's. Keys
that describe the *process* -- `app_port`, `app_host`, `app_workers`, `app_environment`,
`envvar_prefix`, `event_bus`, `log_level`, `log_format`, `readiness_policy`, `nats_stream_name` and
the rest -- belong in the group's own settings file: one process binds one port, speaks one bus and
answers one readiness probe, so a copy under one agent's scope is read by nothing. `asbs validate`
names them if you leave them there.

---

## B. Migrating an existing single-agent project

Three files change, and nothing else. Read
[the one decision to get right first](#the-one-decision-to-get-right-first) before you start: one
of the three is a name you cannot cheaply change afterwards.

### 1. `src/main.py` -- remove two things, add nothing

Before:

```python
config = Config(settings_files=["settings.toml", "secrets.toml"])

app = (
    AppBuilder(config)
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_rest_api(OrderApi)
    .with_cache()
    .build()
)
```

After -- **the same builder**, minus its `config` argument and minus the `.build()`:

```python
agent = (
    AppBuilder()
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_rest_api(OrderApi)
    .with_cache()
)
```

Every `with_*` call stays exactly where it was. `with_cache()` included. That is the point of there
being one builder class: migration removes two things and adds none, because the declaration and
the application builder are the same object.

If the agent is **also** still to be served on its own, add a factory -- optional, and it repeats no
component:

```python
def create_app():
    return agent.build(Config(settings_files=["settings.toml", "secrets.toml"]))
```

Two things the module must not do, because it is imported into a shared runtime: construct clients
or other components at import time, and call `logging.basicConfig()`. Configuration and logging
belong to the process that hosts the declaration.

If you are passing **instances** anywhere -- `with_rest_api(OrderApi())` -- change them to classes.
An instance is constructed at that line, before any namespace exists, so it belongs to the root for
ever; a group refuses one at assembly and names the agent and the fix.

### 2. `Dockerfile` -- one command

```diff
-CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
+CMD ["python", "-m", "blueprint.agents.entrypoint"]
```

and copy the map into the image beside your settings:

```dockerfile
COPY --chown=appuser:appuser agents.toml ./
```

### 3. `agents.toml` -- a new file

```toml
[agents.order]
module = "src.main:agent"
```

Required even for a group of one: it is the only thing that turns an agent's name into code. There
is discovery by convention nowhere in this, deliberately -- a set of agents that depends on what
happens to be importable makes a renamed directory a silently removed agent.

### 4. Check it

```bash
asbs validate
```

It reads the map, holds the name to the namespace alphabet, confirms the module exists and assigns
the attribute you named, and reports anything about schedulers or settings that would not survive
the move. It never imports your project.

### One declaration, three ways to run it

| Shape | Command |
|---|---|
| Standalone, unmigrated | `uvicorn src.main:app` |
| Standalone, migrated (with `create_app`) | `uvicorn src.main:create_app --factory` |
| Grouped, including a group of one | `python -m blueprint.agents.entrypoint` |

---

## The one decision to get right first

**The agent's name in `agents.toml` is its identity everywhere outside that file.** It becomes:

- the NATS **queue group** it consumes under;
- part of every **JetStream durable** name (`<agent>-<topic>-durable`);
- its **cache** directory and Redis key prefix;
- its OpenTelemetry **`service.name`**;
- its **route prefix**, `/api/<agent>`;
- the prefix on every **registry key** its components take.

So renaming it after the first grouped deploy is a consumer migration -- new durables, messages
still pending on the old ones -- not a rename. Choose it once, before you deploy.

It must satisfy the namespace alphabet: **`[a-z][a-z0-9_]*`**. Lower case, starting with a letter,
underscores allowed, and **no dashes**. The dash is excluded because it is the separator inside a
durable name: `orders-eu` on topic `created` and `orders` on topic `eu-created` would otherwise
produce the same durable, and two agents would bind one consumer and eat each other's events. The
alphabet is the intersection of what a registry key, a queue group, a consumer name and a telemetry
resource all accept, and a name outside it is **refused, never repaired** -- a name quietly rewritten
by four subsystems is four names for one agent.

---

## What changes, and what does not

Say which of the two you are doing before reading the table: an agent **left standalone** and an
agent **moved into a group** are affected differently, and only one of them changes anything.

### An agent left standalone: nothing changes

A project you do not migrate, or one you migrate and still deploy on its own, runs at the **root
namespace**. Every identity below is byte-identical to what it was, and that is enforced by tests
rather than asserted in prose:

| | Root namespace (standalone) |
|---|---|
| Registry keys | `nats_client`, `order_service`, ... -- unqualified |
| NATS queue group | `nats_queue_group`, else `app_name` |
| JetStream durable | `<topic>-durable` |
| REST routes | `/api/orders/{id}` |
| OpenAPI tag | `Orders` |
| Telemetry `service.name` | `otel_service_name` |
| Disk cache directory | `cache.cache_dir` |
| Redis key prefix | `cache.key_prefix` |

This is why a migration is a no-op on the broker for anything you keep standalone, and it is a claim
you can check: none of the above reads a namespace when there is none.

### An agent moved into a group: its identity changes once

On the **first grouped deploy**, the agent stops taking its identity from `app_name` and takes it
from its own name. That is one consumer migration, and then it is over:

| | Agent `order` in a group |
|---|---|
| Registry keys | `order_nats_client`, `order_order_service`, ... |
| NATS queue group | `order` |
| JetStream durable | `order-<topic>-durable` |
| REST routes | `/api/order/orders/{id}` |
| OpenAPI tag | `order.Orders` |
| Telemetry `service.name` | `order` |
| Disk cache directory | `<cache_dir>/order.default` |
| Redis key prefix | `<key_prefix>:order.default` |

**Regrouping afterwards changes none of these.** Moving `order` from a group of three to a group of
ten, or out to a group of one, changes which process hosts it and nothing else -- the group's name
reaches the NATS connection name and the telemetry `deployment.group` attribute, and no broker-side
identifier derives from it. That property is the whole point of the feature, and it is what makes
group size a dial you can turn in response to a real failure.

What does **not** move even in a group: the process-level endpoints. `/health/live`,
`/health/ready`, `/info`, `/status/*` and the OpenAPI document are served by the process, once,
wherever the agents are. `/cache/*` does move -- it becomes `/api/<agent>/cache/*`, one endpoint set
per agent that declared a cache, because a cache belongs to the agent that declared it and to no
other.

### The cache is cold after the move

The cache key layout has changed twice during this work, so an application upgrading with a
**persistent Redis cache or a mounted disk cache will not find its old entries.** Nothing errors; the
cache is simply cold and refills. Plan for the first request after the deploy being slow rather than
for a failure, and if any cache entry is load-bearing rather than an optimisation, migrate it
yourself before cutting over.

One deployment constraint survives: an agent's disk cache is a **subdirectory** of
`cache.cache_dir`, not a sibling, so a group still needs exactly one writable mount.

---

## Group configuration and the entry point

Two files, with different lifetimes, and the difference is the reason there are two.

**`agents.toml` -- what the image contains.** Baked in; it changes only when an agent is added or
removed, which is a rebuild anyway.

```toml
[agents.order]
module = "src.order.main:agent"

[agents.billing]
module = "src.billing.main:agent"
```

**`deployment-groups.yaml` -- what this process runs.** Never baked in: one image serves every
group, so it arrives as a mount, or is replaced entirely by environment variables.

```yaml
groups:
  - name: checkout
    agents: [order, billing]
    critical_agents: [order]
  - name: order-only
    agents: [order]
```

`critical_agents` decides what happens when an agent cannot be loaded, and what it can do to the
pod's readiness. The default is **critical**: an agent that fails to load stops the process, because
a pod that passes its probes while one agent's queue silently backs up is a worse failure than no
pod at all. Naming an agent non-critical is the deliberate choice to run the rest without it.

### Environment

Every value can come from the environment, and the environment **overrides the file key by key** --
so one Deployment can change the agent list without editing or duplicating a mounted file.

| Variable | Default | Meaning |
|---|---|---|
| `BLUEPRINT_GROUP` | -- | Which group in the file to run. Optional when the file declares exactly one |
| `BLUEPRINT_AGENTS` | -- | Comma-separated agent names, supplying the group with no file at all |
| `BLUEPRINT_CRITICAL_AGENTS` | -- | Comma-separated subset to mark critical |
| `BLUEPRINT_GROUP_CONFIG` | `./deployment-groups.yaml` | Where the group file is |
| `BLUEPRINT_AGENT_MAP` | `./agents.toml` | Where the agent map is |

Setting `BLUEPRINT_AGENTS` supplies the whole group and the file is not consulted for it at all,
which is the `docker run` and CI shape:

```bash
docker run -e BLUEPRINT_AGENTS=order,billing -e BLUEPRINT_CRITICAL_AGENTS=order my-image
```

Every resolved value is logged with the source it came from, because "which agents did this pod
actually start" is the first question asked of a group that misbehaves.

If the group cannot be resolved -- no agents named, a group that is not in the file, an agent the
image does not contain -- the process **stops before binding its port** and prints one line saying
which. Kubernetes then crash-loops the pod with something an operator can act on, rather than
reporting a healthy replica that is quietly short one consumer.

### What agent code can see of all this

Nothing. There is no supported API that exposes the group's name, its membership or its size, and
that is what makes regrouping incapable of breaking agent code: an agent that could read its
neighbours could be written to depend on them. `deployment.group` is set by the framework on
telemetry resources and is not readable through any public API.

### A group assembled in code

If you would rather write the composition yourself than use the entry point -- a test, or a process
that wants its own `main.py` -- `AgentGroup` is the class that does it:

```python
from blueprint.agents import AgentGroup, Config

from src.order.main import agent as order
from src.billing.main import agent as billing

config = Config(settings_files=["settings.toml"])
app = AgentGroup("checkout", {"order": order, "billing": billing}).assemble(config)
```

`AgentGroup` is a different class from `AppBuilder` on purpose: an `AppBuilder` never absorbs
another builder and never learns it can be collected, so every refusal a group has to make lives in
the class that imposes it, and the single-agent case is not punished for the group's constraints.

---

## Once it is running

**Readiness.** `readiness_policy` decides how a degraded agent affects the pod: `all` (the default
-- any degraded agent makes the pod not ready), `critical` (only agents flagged critical in the
group gate it) or `any` (ready while at least one agent is up). Liveness is never agent-dependent:
if one degraded agent failed the pod's liveness probe, Kubernetes would restart every agent in the
group, reintroducing exactly the blast radius grouping was paid to remove.

**Attribution.** Grouping removes the pod restart that used to serve as the alert, so the alert is
emitted deliberately instead. Every path that stops an agent serving emits an ERROR-level event
carrying that agent's own telemetry identity, and drives `blueprint.namespace.up{agent} = 0`. A
degraded agent's transports are **paused**, not closed -- a closed client is unhealthy for ever, so
the pause would latch and a transient fault would take the agent off its topics permanently.

**Schedulers.** `scheduler_mode` resolves per agent, so one agent may run an in-process timer beside
a neighbour driven by external ticks. Both modes need something of the agent's own: `in_process`
claims each tick in a cache **that agent declared**, and `event` needs `event_bus`, which is the
group's to set.

**Dapr.** A group has one Dapr endpoint, which publishes the union of every agent's topics and fans
each delivery out to the agents that declared it; the single acknowledgement is their combination.
So a retry asked for by one agent redelivers to every agent in the group, and grouped Dapr therefore
wants `idempotency_enabled`. NATS has no such coupling -- each agent has its own subscription.

---

## See also

- [CLI Reference](cli-reference.md) -- `asbs setup`, `asbs dev`, `asbs validate` in full
- [Deployment](deployment.md) -- images, Helm, probes, scaling
- [Caching](../concepts/caching.md) -- named caches, per-agent stores, the management endpoints
- [Observability](../concepts/observability.md) -- what each agent reports, and under which identity
