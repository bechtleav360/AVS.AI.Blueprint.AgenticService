# Unit Tests — `blueprint.agents` (top level)

Test coverage for the modules that describe a whole *process* rather than one component:
`src/blueprint/agents/agent_group.py`, `src/blueprint/agents/group_config.py` and
`src/blueprint/agents/entrypoint.py` -- plus the frozen compatibility suite and the design-rule
guards, which are about the framework as a whole and therefore belong to no single package.

Each subdirectory has its own `TESTS.md` for the package it covers.

---

## File overview

| File | Class under test | What is covered |
|---|---|---|
| `test_agent_group.py` | `AgentGroup` | One namespace per agent (each agent's components qualified, a group of one, a mapping refusing two agents under one name); agent names (illegal names and the root refused); what a group refuses and does not (an already-built builder, `AppBuilder(config)`, a constructed instance, a factory accepted, nothing assembled when a refusal fires); caches (a group declares none, an agent's own is registered to it, two agents declaring one name get separate stores, neither can read the other's); loading a declaration (a missing module, a missing attribute, a non-`AppBuilder`, an import that raises -- each fatal for a critical agent and skipped with an ERROR otherwise); `from_config` performing no I/O of its own; `resolve` reading the environment and the group file; that the builder learns nothing about groups; and each agent's own settings file (looked for beside the declaration module, merged under that agent's scope, merged *before* its components are built, and not reaching a neighbour) |
| `test_group_config.py` | `GroupConfig`, `AgentSpec` | Reading the group file (the named group, another group in the same file, a single group needing no name, the agent's module coming from the image's agent map, a `cache_names` list now read by nothing); resolution from the environment alone; precedence (the environment overriding the file key by key, the file's other values surviving, the source of each value logged, the resolved group logged); criticality (a critical agent's failure fatal, a non-critical one skipped); validation against the agent map (an unknown name refused, a duplicate); agent names held to the namespace alphabet; and the value object itself (constructed literally, frozen) |
| `test_entrypoint.py` | `build_group_app`, `main` | `build_group_app` resolving the group and returning the application with its configuration; `main` returning `0` on a clean run and `1` for a group that cannot be resolved, printing the reason to stderr as well as logging it; that the module is runnable as `python -m blueprint.agents.entrypoint`; and that one declaration serves both deployment shapes -- the same `AppBuilder` built standalone and assembled into a group |
| `test_design_rules.py` | The design rules in `AGENTS.md` | One section per rule, each failure message naming the rule it enforces. *Collect, then wire* and *one declaration surface*: every `with_*` on `AppBuilder` and `AgentBuilder` is discovered rather than listed (a new one fails the file until it has a sample call) and called reflectively -- nothing constructed, no configuration needed, the builder returned; and per `AppBuilder` method, one declaration recorded, `replay` reproducing it, the namespace taken from the scope, and the recorded `kind` having a `with_<kind>`. *A lookup never falls back across agents*: two agents' caches of one name kept apart, and no fallback to a neighbour, to the root, or from an unknown name to the default. *A component never learns it is in a group*: the ambient namespace, no `get_known_namespaces`, and the two refusals a view gives (`cache_entries`, `for_namespace`). *A name is validated, never repaired*: five namespace entry points and the deployment route against seven illegal names, the cache alphabet, and a legal name coming back unchanged. *No public read path to the unscoped loader*: the public configuration surface is exactly `config`, `configure`, `has_config`, and a namespaced component reads through its view. *Logging is configured by the application*: no logging configuration at import time anywhere in `src/`, and none in the framework outside `LoggingManager`. *No diagnostics via print*: none in the framework beyond the two listed stderr writes. *References resolve*: every markdown link, every cited path in the documents that describe the tree as it stands, and every document cited by name |
| `test_frozen_compatibility.py` | `AppBuilder`, `Registry`, `Component` | **Frozen (spec sec. 10.2): never updated for an API change.** What an existing single-agent project already does -- the builder shapes the examples use including instance forms; `with_cache(False)` and `with_cache(True, False)` positionally; the registry names lookups use (derived, explicit, the cache backend's, the `cache_service` alias, two services resolving one cache); the paths a project serves (`/api/<resource>` with its own tags, `/api/cache/stats`, the actuators); the readiness entries (`cache`, a bare custom name); and a component constructed with `super().__init__()` needing no change |

---

## Fixtures (`conftest.py`)

| Fixture | Scope | Purpose |
|---|---|---|
| `mock_prompt_loader` | function / **autouse** | Stubs `PromptLoader.load_prompt` for every test under `tests/unit/agents`, so no test reads a prompt file from disk. Skipped by node id for the prompt-loader tests and the three `AgentBuilder` cases that patch it themselves |
