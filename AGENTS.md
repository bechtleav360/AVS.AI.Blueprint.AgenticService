# AGENTS.md

Architecture, component patterns, testing conventions and **design rules** for this repository,
shared across every AI assistant and every human working in it. `CLAUDE.md` holds the commands
and the per-feature process; this file holds what the code has to be like and why.

Each rule below states the rule, the reason, and **the failure it prevents**. That last part is
not decoration: a rule without its failure is advice, and advice gets argued away by the next
person with a deadline. Most of these were bought with a defect -- either one that shipped or one
found by probing -- and the failure line is the receipt.

If a rule and the code disagree, one of them is wrong and it is worth finding out which before
writing anything. If a rule and a specification disagree, see *The spec wins on precedence, not
on correctness* below.

---

## Where things are

`src/blueprint/agents/` is the framework; `src/blueprint/agent_generator/` is the `asbs`
scaffolder that generates projects against it. Inside the framework:

| Path | What lives there |
|---|---|
| `app_builder.py` | The declaration API. `with_*` records; `build()` constructs, wires and returns the `FastAPI` app |
| `agent_group.py` | Several agents in one process: named declarations in, one application out |
| `group_config.py` | Which agents *this* process runs, resolved from the environment and the group file |
| `entrypoint.py` | `python -m blueprint.agents.entrypoint` -- the container's command |
| `component/` | `Component` (registry name, namespace, config view, executor), `Registry`, `namespace.py` |
| `handler/` | `EventHandlerBase`, the `HandlerChain`, dispatch and deduplication |
| `services/` | `ServiceBase`, the eventing services, and the infrastructure services (caches) |
| `io/api/` | `RestApiBase`, the actuators (`/health`, `/info`, `/status`), the eventing endpoints, schedulers |
| `clients/` | `ClientBase`, `IOClientBase` (NATS, Dapr), the AI clients |
| `agent/` | `AgentRuntime` and `AgentBuilder` -- an LLM runtime and its fluent declaration |
| `config/` | `Config` (Dynaconf), the logging manager |
| `models/` | Pydantic models: events, configuration, API payloads, status |

Prose for users lives in `docs/`: `docs/concepts/architecture.md` for the assembly model,
`docs/concepts/event-processing.md` for the dispatch pipeline, `docs/concepts/configuration.md`
for settings, `docs/guides/` for deployment, testing and the CLI. Specifications and plans are in
`docs/specs/` and `docs/plans/`; a feature's changelog beside its plan is the running record of
what was done and why.

---

## Component patterns

A project's component is an ordinary class extending one base:

| Base | For |
|---|---|
| `EventHandlerBase` | Reacting to an event. Declares its topics, decides whether it can handle a delivery, handles it |
| `ServiceBase` | Business logic with no transport of its own |
| `RestApiBase` | HTTP endpoints, declared with the `@RestApiBase.get/post/...` decorators |
| `SchedulerBase` | Recurring work, either from an in-process timer or from an external tick |
| `ClientBase` / `IOClientBase` | Talking to something outside the process |
| `HealthCheckerBase` | One entry in the readiness payload. Not a `Component` |

What every one of them has in common:

- **The constructor takes what its author wrote, and nothing the framework added.**
  `super().__init__()` is enough. A component is never handed a namespace, a registry or a
  configuration object -- it reads them from `self`.
- **`self.registry`, `self.config` and `self.executor` answer for the component's own agent.**
  A lookup written as `self.registry.get_service(OrderService)` finds this agent's service, and
  `self.config.get("model_name")` reads this agent's value, with no namespace at the call site.
- **Collaborators are resolved in `on_startup`, not in `__init__`.** Nothing is constructed until
  `build()` runs, and within that pass the order is the declaration order, so a component's
  collaborator may not exist yet while it is being constructed.
- **`on_startup` / `on_shutdown` are the lifecycle.** The application's lifespan drives them; a
  component that opens something in the first closes it in the second.
- **`should_register=False`** is for a component nobody looks up -- the actuator API, the eventing
  endpoints. It keeps a second registry entry per agent from existing.

**The acknowledgement contract, for handlers:** a normal return acknowledges the delivery; a
raised exception does not. `NO_HANDLER_FOUND` acknowledges too -- an event nobody declared is not
a failure of this process. `ProcessingResult` describes the outcome and never controls delivery.
*Failure:* if a result object could nak, two independent concerns -- "what happened" and "should
the broker send this again" -- would be encoded in one value, and a handler returning a failure
result would silently loop the broker.

---

## Design rules

Every rule below that a machine can check is checked by `tests/unit/agents/test_design_rules.py`,
one section per rule, each failure message naming the rule it enforces. Prose alone has already
failed here once: this file was cited by `CLAUDE.md` for months while it did not exist, so the
guards -- including the one that checks that a cited file exists -- are what keep the rest of this
document true.

### Construction and assembly

**Collect, then wire.** A declaration API records; nothing is constructed, registered or
connected until `build()`. *Failure:* a component constructed during accumulation exists before
any namespace does and belongs to the root for ever -- which is what forced a second builder
class to exist for three phases, until deferred wiring removed the reason for it.

**One declaration surface.** Adding a capability is one edit: a `with_*` method on `AppBuilder`.
A second class whose only job is to defer construction is the smell that was removed, not a
pattern to copy. *Failure:* four places to edit, three of which fail *silently* -- the capability
is simply absent from that surface, and only in the deployment shape nobody tested.

**A builder is single-use, and says so.** *Failure:* a second `build()` surfaces
`Component.configure`'s "already set" error, which names neither the builder nor the second call
and sends the reader into framework internals.

**Group policy belongs to the collector.** Standalone stays permissive; the group refuses what it
cannot honour, at assembly, naming the agent and the fix. *Failure:* restrictions scattered into
the builder punish the single-agent case for constraints that only a group has.

### Namespaces and isolation

**A component never learns it is in a group.** The namespace is ambient, read by
`Component.__init__` from the scope in force; it is never a constructor parameter of a project's
component, and never enumerable from anything a component can reach. *Failure:* an agent that can
read its neighbours can be written to depend on them, and regrouping then breaks it in
production.

**Isolation is structural where it can be, audited where it cannot.** Separate stores beat a
shared store with a key prefix; where walling something off would break a supported use, log the
access and name the reader instead. *Failure:* a prefix has to be applied correctly at every call
site, and the one site that forgets is a silent cross-agent read.

**A lookup never falls back across agents.** Components resolve namespace-then-root, deliberately;
caches do not resolve at all outside the declaring agent. *Failure:* two agents that both asked
for `sessions` silently share one store, and only in production.

**An omitted namespace on the root registry means every namespace, not the root.** Framework code
that dispatches or resolves per agent names its namespace explicitly, even where it looks
redundant. *Failure:* a root dispatch runs every agent's handlers, or `build()` sees only root
handlers and silently short-staffs a grouped process.

**Entering a scope for the root is not a no-op.** `namespace_scope("")` *sets* the root, so code
that constructs on behalf of a namespace it was handed uses the guarded form
(`construction_scope`). *Failure:* replaying one agent's declarations resets every component of
every agent back to the root, silently.

### Names and values that leave the process

**A name that crosses the process boundary is validated, never repaired.** Queue groups, JetStream
durables, subjects, cache names, namespaces, environment-variable prefixes. *Failure:* silent
rewriting breaks an external dependency with nothing in the logs to debug -- a spaced `app_name`
becomes a subject the CronJob author cannot know they must match.

**Two components of one class collide on the derived registry name.** A name is qualified with
its agent automatically, so a collision means two of one class in one agent, or two explicit
names that clash. Give one an explicit `name=`. *Failure:* the second registration raises at
startup, or -- worse, before names were qualified -- replaced the first.

**A check answerable at the call stays at the call.** *Failure:* an error reported several
`with_*` calls later, or at `build()`, names the wrong line and the author looks for the mistake
where it is not.

### Declarations and defaults

**An empty declaration means everything, not nothing.** `get_handled_event_types() -> []` is the
wildcard bucket. *Failure:* treating an empty set as authoritative silences the application, and
an unhandled event acknowledges -- so the deliveries vanish rather than piling up where somebody
would see them.

**A key whose absence changes behaviour is required, not defaulted.** `scheduler_mode` and
`idempotency_ttl` have no default because neither value is safe to inherit. `must_exist=True`
beside a `default=` is a lie: Dynaconf fills the default and the validator then passes.
*Failure:* a deployment gets a behaviour nobody chose -- every replica running every tick, or a
deduplication window shorter than the broker's redelivery window.

### Configuration and logging

**Configuration is injected before any component exists**, and is read through the component's
own scoped view. There is **no public read path to the unscoped loader**: `Component.config` is a
view, and the class-level accessor was deleted. *Failure:* a component reads a neighbour's or the
process's value under a name that means "mine", and the bug appears only once a second agent
exists.

**Configuration isolation is audited, not enforced.** Reading the raw settings tree from a scoped
view logs a WARNING naming the reader, rather than raising. *Failure (of the alternative):*
legitimate framework reads break, and the ones that matter are not the ones a wall would catch.

**A key that describes the process cannot be set per agent.** One process has one port, one
environment, one prefix, one event bus and one logging configuration. Such a key in an agent's
own settings file is dropped and reported. *Failure:* the author sets a value that is read by
nothing and reported by nothing, and the pod does something other than what the file says.

**Logging is configured by the application**, never by library code, a constructor, or at import
time. Modules get `getLogger(__name__)` and emit; the application attaches handlers, once.
*Failure:* N scoped configurations each build a logging manager, each re-attaches filters, and
the last one to load decides the whole process's level.

### Versioning and releases

**The version is the git tag; the repository is never bumped by hand.** `.github/workflows/publish.yml`
extracts the version from the tag and rewrites `pyproject.toml` at build time. A change adds a
`CHANGELOG.md` entry under `[Unreleased]` and touches no version string. *Failure:* a
hand-edited version disagrees with the tag that published it, and the artefact on the index
cannot be traced back to a commit.

---

## Testing conventions

- **`tests/unit` needs nothing running.** `tests/integration` may, and anything requiring an
  external service is marked `@pytest.mark.integration` (`pytest.ini`, `--strict-markers`).
- **Every package under `tests/unit/agents/` has a `TESTS.md`** listing each file, the class
  under test, and what is covered; the one at the top level covers the files that sit directly in
  it. It is updated with the tests, not after them. (`tests/unit/agent_generator/` and
  `tests/integration/` have none yet.)
- **Probe against real objects.** Every real defect this framework's grouping work surfaced was
  found by testing against a real `Registry`, a real `Config` and a real cache rather than a
  mock. *Failure:* a mock registry answers every lookup and hides resolution bugs by
  construction -- six ownership tests passed against a `MagicMock` while the code could not have
  worked.
- **Assert on the observable thing, not on the call.** Paths from `app.openapi()`, names from the
  registry, values from `config.get`, files on disk. A test that asserts a mock was called with
  certain arguments passes when the arguments are wrong for the caller.
- **A test says what it pins down.** The docstring is the reason the case exists, and for a
  regression it names the failure. `test_that_it_works` is not a name.
- **The frozen compatibility suite is frozen.** `tests/unit/agents/test_frozen_compatibility.py`
  exercises what existing projects already do. **Never edit it to accommodate an API change**: if
  it needs editing, a break shipped, and the break is the finding.
- **A guard test states the rule it enforces in its failure message.** Someone hitting it should
  learn the rule from the failure, not from this file. The guards for the design rules above live
  in `tests/unit/agents/test_design_rules.py`; a rule that is not mechanically checkable says so
  there, so that its absence is not read as an oversight.

---

## How the work is done

**No unused code in the framework.** Git history is where removed work belongs. *Failure:* a
plausible unused abstraction misleads the next reader into building on something nothing has ever
exercised -- a renderer written and deleted before it was committed cost less than one left in
place would have.

**Probe, do not assume**, and say which it was. "Verified by probe" and "read from the code" are
different claims, and a report that blurs them cannot be checked.

**The spec wins on precedence, not on correctness.** Where a specification and this repository
disagree, the specification decides what ships -- but challenge a requirement's premise before
building it, and record every departure, with its argument, in the feature's changelog. *Failure:*
a requirement is implemented as written although its premise is false (a key that is "read by
nothing" turns out to be read per agent), or quietly diverged from, and nobody can tell which.

**Report the code, not the wrapper.** A change is reported by walking through what the production
code now does -- the functions, the branches, the call sites -- and showing the lines that matter.
"Tests pass and lint is clean" is the wrapper around a change, not the change.
