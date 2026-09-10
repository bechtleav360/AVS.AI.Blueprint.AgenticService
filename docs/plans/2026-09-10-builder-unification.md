# Proposal -- One builder, collected into a group

| | |
|---|---|
| **Status** | Proposal. Decided in discussion 2026-09-09/10; not implemented. |
| **Amends** | `docs/specs/2026-08-28-multi-agent-grouping.md` sec. 4.1, 4.2, 8, 11; `docs/plans/2026-08-28-multi-agent-grouping.md` phases 0 (part 3), 3, 6, 8 |
| **Does not touch** | Configuration validation -- see `2026-09-10-config-validation-unification.md` |

## The problem this solves

Adding one `with_*` method today means editing **four** places:

| Place | If forgotten |
|---|---|
| `AppBuilder.with_*` | standalone cannot use it |
| `AgentRegistration.with_*` | grouped agents cannot declare it |
| `NamespaceBuilder.with_*` | the block form cannot use it |
| `AgentRegistration.apply`'s `appliers` dict | `KeyError` at apply time |

Three of those fail **silently** -- the capability simply is not there on that surface. Only the
fourth is loud. Nothing tells the next developer that the four exist.

The duplication is not an accident of style. `AppBuilder.with_handler(H)` **constructs `H`
immediately**, and a component constructed before a namespace exists belongs to the root for
ever -- so a second class had to exist to defer construction until a namespace was in force.
`AgentRegistration` is that class, `NamespaceBuilder` is the block-form sugar over it, and the
`appliers` dict is the bridge between them.

**So the fix is not to share the methods -- it is to remove the reason they diverged.** If
`AppBuilder` records instead of constructing, one class serves both roles and the other two have
no purpose.

## The shape

### One builder, which records

```python
class AppBuilder:
    def __init__(self, config: Config | None = None) -> None: ...
    def with_handler(self, handler, *, name=None, **kwargs) -> Self: ...     # records
    def with_service(self, service, *, name=None, **kwargs) -> Self: ...     # records
    def with_agent(self, agent, *, name=None, **kwargs) -> Self: ...         # records
    def with_scheduler(self, scheduler, *, name=None, **kwargs) -> Self: ... # records
    def with_rest_api(self, api, *, name=None, **kwargs) -> Self: ...        # records
    def with_cache(self, enabled=True, enable_locking=True, *, name="default") -> Self: ...
    def with_health_checker(self, name: str, checker) -> Self: ...
    def build(self, config: Config | None = None) -> FastAPI: ...            # wires, at the root
    @property
    def declarations(self) -> tuple[Declaration, ...]: ...                   # read by the collector
```

Nothing is constructed until `build()`. `build()` wires everything at the **root namespace**:
standalone knows nothing about namespaces, which is the decision below.

### A collector, which is a different thing

`AppBuilder` does not know it can be collected. Assembling a group is its own unit -- it takes
named builders and one configuration, enforces the group's rules, and drives one process-level
wiring pass:

```python
def assemble(agents: Mapping[str, AppBuilder], config: Config) -> FastAPI: ...
```

This is where `with_group` and `from_group` move to, and where every refusal below lives. The
division is the one the plan already states for phase 8 -- resolution versus wiring, with the I/O
outside the builder -- extended one step: **group policy is not the builder's business either.**

### Deleted

- `AgentRegistration` -- `AppBuilder` used without `build()` is the declaration.
- `NamespaceBuilder` and `AppBuilder.with_namespace` -- the collector takes named builders instead.
- The `namespace=` parameter on the five `with_*` -- it existed only for `NamespaceBuilder`.
- `AgentRegistration.apply` and its `appliers` dict.

Four duplication sites become **one**. Adding a `with_*` method is one edit, and the collector
replays whatever was recorded without knowing what it is.

## Decisions

### D1 -- Standalone knows nothing about namespaces

`build()` wires at the root. An agent's name exists only in a group context, so it has exactly
one home: the group configuration. `main.py` never names its agent, which is what keeps
*a developer never sees namespaces* true.

**Consequence, already documented:** moving an agent from standalone into a group changes its
queue group and its JetStream durable, so the first grouped deploy is a consumer migration. See
the phase 5 migration note.

### D2 -- Standalone is permissive; the group has rules

Everything that works today keeps working standalone. The group refuses what it cannot honour,
at assembly time, with a message naming the agent and the fix. No deprecation warnings: spec
sec. 10 makes the standalone shape supported indefinitely, so warning about it every startup
would be crying wolf, and `DeprecationWarning` is invisible by default anyway.

The refusals follow from what a group *is* -- one process, one configuration, one port, every
component constructed inside a namespace scope, and no agent deciding for another:

| Recorded call | In a group | Capability lost? |
|---|---|---|
| the five `with_*` with a class + kwargs | allowed | -- |
| the five `with_*` with a factory | allowed; called inside the namespace scope | -- |
| the five `with_*` with an **instance** | **refused** -- its namespace and registry key were fixed at construction | No: the factory form recovers it |
| `with_cache(...)` | allowed; name qualified per agent (D3) | -- |
| `with_health_checker(...)` | allowed; key qualified per agent (D4) | No: a checker is not a `Component` |
| `AppBuilder(config)` | **refused** -- one process, one settings tree and one port | No, once D5 lands |
| `build()` already called | **refused** -- already wired at the root | No |

The instance refusal reuses wording that already exists in `AppBuilder._register`; it moves from
record time to assembly time.

### D3 -- A cache is private to the agent that declared it

An agent has access to **exactly** the caches it declared, and to nothing else. `get_cache(name)`
resolves within the declaring agent and raises otherwise -- no fallback of any kind. Cache names
are qualified by namespace, so two agents may both declare `sessions` and get separate stores.

This implements what spec sec. 8 actually requires -- *"Cache names MUST therefore be
namespace-scoped by default"* -- of which only the data-partition half was ever built.

**Deleted by this decision:**

- `GroupConfig.cache_names` -- there is no shared cache, so a group has none to declare.
- `AgentScopedCache` -- the partition-prefixing lens exists only to stop two agents colliding
  inside one shared store, which can no longer happen. Separate stores make the isolation
  structural rather than dependent on a prefix being applied correctly.

**Knock-ons:** an agent with `idempotency_enabled` must declare `with_cache()` (its existing
error message already says so), and `/cache/*` becomes per-agent rather than process-wide.

### D4 -- A health checker's key carries its agent

Two agents calling `with_health_checker("db", ...)` currently collide in a dict and one
disappears silently. The key is qualified by namespace; the root keeps the bare name, so a
standalone application's `/health/ready` payload does not change.

The attribution is stored **as data** -- `(namespace, name)` -- and the prefix is its rendering.
Phase 9's `readiness_policy = "critical"` needs to know which agent a failing checker belongs to,
and recovering that by splitting a string breaks the moment a name contains the separator.

For the record, the current policy this inherits: every checker is polled on a timer and ANDed
(`health_cache.py:139`), so one unhealthy checker returns 503 for the whole pod. In a group that
means one agent's outage removes every agent from rotation. That is `readiness_policy = "all"`,
which phase 9 makes selectable; nothing here changes it.

### D5 -- A group's settings are the defaults; an agent's own file is only its own

- The group's `settings.toml` supplies **defaults, and only defaults**.
- Each agent ships its own `settings.toml`, merged **under that agent's scope** -- never at root.

Therefore an agent may set any key for itself, and can **never** change what another agent or the
process sees. There is no collision to detect, because the two never occupy the same slot.

This closes the settings-fragment merge open point outstanding since config rework step 3a; both
of its unanswered questions dissolve. The one hole to close deliberately: **process-scope keys in
an agent's file must raise**, from an explicit list (`app_port`, `event_bus`, `envvar_prefix`,
`nats_stream_name`, ...). Scoped, they would be silently inert -- read by nothing, reported by
nothing.

### D6 -- `AgentBuilder` records too, and is wired with the agent's own configuration view

`AgentBuilder.__init__` requires a `Config` as its first argument, and `Component._shared_config`
deliberately has **no public read path**. So in a declaration-only `main.py` there is no
configuration in scope, and the documented factory form

```python
.with_agent(lambda: AgentBuilder(config, runtime_name="orders").build())
```

**cannot be written at all.** That is a live defect in what phase 8 shipped, not a consequence of
this proposal.

The fix is the same change as for `AppBuilder`: `config` optional in `__init__`, accepted by
`build()`. An unbuilt `AgentBuilder` is then handed straight to `with_agent`, and the wiring calls
`agent.build(config)` with **that namespace's configuration view**:

```python
agent = AgentBuilder(runtime_name="orders").with_model_from_config()
app_builder.with_agent(agent)          # recorded, not built
```

This deletes the lambda escape hatch for the common case and fixes a second latent bug with it: a
lambda closes over whichever configuration was in scope where it was written, which in a group is
the wrong one. Handing the scoped view in at wiring time makes the right one structural.

`with_agent` accepts: a class, an unbuilt `AgentBuilder`, a factory, or -- standalone only -- a
built `AgentRuntime`.

### D7 -- Group rules are documented on the methods

Each `with_*` docstring states what the group does with it. There is no authoring-time
validation: every refusal necessarily lands at assembly, because `with_cache()` is called at
import, long before anything knows whether this builder will be collected. `asbs validate` is
where authoring-time gates would go if they are ever wanted.

## Behavioural changes to state

**Registration order.** An instance passed to `with_*` is constructed by the caller at its source
line; a class is constructed during `build()`. So an instance recorded *after* a class registers
*before* it, which can flip equal-priority handler tie-breaking -- resolved by registration order
today, as `DispatchIndex.build` already documents. `build()` can detect exactly this case, since
it knows both the recorded order and which entries were instances, and raise. Order therefore
still means what it means; the violation surfaces at `build()`.

**Nothing is in the registry until `build()`.** Code that looks a component up between `with_*`
calls breaks. The framework's own convention already forbids it -- collaborators are resolved in
`on_startup`, and components must not read configuration in `__init__` -- so the fix is the
documented pattern.

**`configure_logging()` moves into `build()`.** It runs in `__init__` today so that component
construction is logged with the right format. With deferred wiring nothing is constructed until
`build()`, so configuring logging there is strictly more correct.

**A builder is single-use, and says so.** `build()` calls `Component.configure`, which refuses a
second call -- today that surfaces as someone else's error. It gets its own message.

## Why this is not a Builder anti-pattern

It is the pattern. GoF Builder accumulates parts; `build()` produces the product. What exists
today is the smell: `with_handler` constructs a component and registers it into a process-global
registry *during accumulation*, which is exactly why a second class was needed.

The four anti-patterns this design is checked against:

1. **Side effects during accumulation** -- removed; recording only.
2. **A silently single-use builder** -- made explicit (above).
3. **Requiring the product's context in the constructor** -- `config` moves to `build()`;
   remaining in `__init__` only as the compatibility concession.
4. **Replay drift** -- a recorder can diverge from the API it replays. Mitigated by storing the
   *method name* and resolving it with `getattr`, which fails loudly, plus a test asserting the
   builder's declaration surface and the collector's replay agree.

`AppBuilder` is deliberately **not** a composite builder: it never absorbs another builder, and
does not know it can be collected. Collection is the collector's job, and so are the group's
rules.

## Migration

Unchanged for an existing project -- spec sec. 10's MUST holds: `AppBuilder(config)...build()` and
`uvicorn src.main:app` behave exactly as today.

To become groupable, `main.py` drops one argument and splits the last call off:

```python
agent = AppBuilder().with_service(OrderService).with_handler(OrderHandler)

def create_app():                       # uvicorn src.main:create_app --factory --reload
    return agent.build()
```

`uvicorn` resolves dotted attributes after the colon (`importer.py`), so
`uvicorn src.main:agent.build --factory` also works -- and because it is an import string,
`--reload` works, which `run_app` cannot offer today.

Three shapes, one implementation:

| Shape | Command |
|---|---|
| Standalone, today's | `uvicorn src.main:app` |
| Standalone, migrated | `uvicorn src.main:create_app --factory` |
| Grouped | `python -m blueprint.agents.entrypoint` |

## Work breakdown

1. `Declaration` value object; `AppBuilder` records; `build(config=None)` wires at the root.
2. `AgentBuilder` records; `config` optional in `__init__`, accepted by `build()` (D6).
3. The collector: named builders in, one `FastAPI` out; every refusal in D2; `with_group` and
   `from_group` move here; the entry point calls it.
4. Delete `AgentRegistration`, `NamespaceBuilder`, `with_namespace`, the `namespace=` parameter,
   `apply` and the `appliers` dict.
5. Caches per agent (D3): qualify names, delete `cache_names` and `AgentScopedCache`, per-agent
   `/cache/*`.
6. Health-checker attribution (D4).
7. Settings fragments (D5), including the process-scope key refusal.
8. Docstrings (D7); the surfaces-agree test; the frozen compatibility suite that pins the
   standalone shape.

Each step is its own commit, reported before the next begins, per `CLAUDE.md`.

## Explicitly out of scope

- **Configuration validation and its unification** -- `2026-09-10-config-validation-unification.md`.
- **`readiness_policy` and per-namespace degradation** -- phase 9.
- **Generating `agents.toml` and the group file** -- parked with manifest generation.
- **Whether the group's composition should live in `settings.toml` rather than its own YAML.**
  Raised in discussion and worth doing: the spec's justification for a separate mechanism is that
  resolution happens "before `Config` is constructed", and it does not -- the entry point builds
  `Config` first and passes it in. Deferred so that this proposal changes one thing at a time.
