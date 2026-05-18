# Spec: Fix kebab-case input in CLI naming utilities

**Issue:** bechtleav360/AVS.AI.Blueprint.AgenticService#3

## Goal

`asbs create <component> <name>` and `asbs setup <name>` must produce valid Python identifiers (module names, variable names, file names) when the user provides a kebab-case name like `my-agent`.

## Why now

The bug causes generated filenames and snake_case variable names to contain literal hyphens (e.g., `my-agent_handler.py`, `my-agent_handler`). Python cannot import a module whose filename contains a hyphen. This blocks every user who names their component using the common `kebab-case` convention.

## Root cause

`camel_to_snake` in `src/blueprint/agent_generator/cli/utils/naming_utils.py` applies only CamelCase → snake_case regex. It does not normalize hyphens to underscores first. When `normalize_component_name("my-agent", "handler")` is called:

- `snake_name_base = camel_to_snake("my-agent")` → `"my-agent"` (hyphen preserved)
- `snake_name = "my-agent_handler"` (invalid)
- `filename = "my-agent_handler.py"` (invalid Python module name)

Each `create_*` function in `create.py` patches `file_name` with a manual `.replace("-", "_")`, but `snake_name` itself is not fixed in most cases (only `create_agent` also fixes `snake_name`). The downstream effects — docstrings, settings.toml keys, variable declarations in `main.py` — may still contain hyphens.

`asbs setup` was partially fixed (commit adding `PartGeneratorBase.to_class_name` call at `setup.py:120`) but the same `camel_to_snake` gap affects the `create` commands.

## In scope

1. Fix `camel_to_snake` in `naming_utils.py`: normalize hyphens to underscores before applying CamelCase regex.
2. Update `test_normalize_scheduler_kebab_case` in `tests/unit/agent_generator/cli/utils/test_naming_utils.py`: the test currently asserts the broken behavior (`snake_name == "cleanup-job_scheduler"`, `filename == "cleanup-job_scheduler.py"`); update expected values to the correct output.
3. Remove ad-hoc `file_name.replace("-", "_")` and `snake_name.replace("-", "_")` workarounds in `create.py` (they become dead code once the root is fixed).

## Out of scope

- `PartGeneratorBase.to_class_name` / `PartGeneratorBase.camel_to_snake` in `part_generator_base.py` (used only by `setup.py`; already handles hyphens via split on non-alphanumeric).
- Output directory naming convention for `asbs setup` (PascalCase directory is a separate UX question, not causing broken imports).
- Any changes to generated class names (they are already valid Python identifiers).

## Acceptance criteria

1. `normalize_component_name("my-agent", "handler")` returns `("MyAgentHandler", "my_agent_handler", "my_agent_handler.py")`.
2. `normalize_component_name("cleanup-job", "scheduler")` returns `("CleanupJobScheduler", "cleanup_job_scheduler", "cleanup_job_scheduler.py")`.
3. `camel_to_snake("my-agent")` returns `"my_agent"`.
4. All existing tests pass.
5. `test_normalize_scheduler_kebab_case` asserts correct (post-fix) values.

## Entities / contracts

| Function | File | Change |
|---|---|---|
| `camel_to_snake(name)` | `naming_utils.py` | Add `name = name.replace("-", "_")` before existing regex |
| `test_normalize_scheduler_kebab_case` | `test_naming_utils.py` | Update expected `snake_name` and `filename` |
| `create_handler` / `create_service` / `create_api` / `create_scheduler` | `create.py` | Remove `.replace("-", "_")` workarounds |

## Constraints

- Line length 140 chars.
- No new dependencies.
- Must not break CamelCase input paths (e.g., `"MyHandler"` → still `"my_handler"`).

## Open questions

None.

## Related issues

None.
