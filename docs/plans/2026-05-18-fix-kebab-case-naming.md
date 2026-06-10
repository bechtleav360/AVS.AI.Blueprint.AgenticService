# Plan: Fix kebab-case input in CLI naming utilities

**Issue:** bechtleav360/AVS.AI.Blueprint.AgenticService#3  
**Spec:** [docs/specs/2026-05-18-fix-kebab-case-naming.md](../specs/2026-05-18-fix-kebab-case-naming.md)

## Approach

Single-function root fix in `naming_utils.py`. All downstream callers (`normalize_component_name`, every `create_*` command) inherit the fix automatically. Ad-hoc workarounds in `create.py` become dead code and are removed. Test file is updated to assert correct behavior and gains new direct coverage for the fixed function.

Trade-off considered: fixing at call sites instead would require touching every `create_*` function and still leave `snake_name` broken in some paths. Root fix is safer and smaller.

## Steps

1. **Fix `camel_to_snake` in `naming_utils.py`**  
   Prepend `name = name.replace("-", "_")` before the existing regex substitutions. No other logic changes.  
   File: `src/blueprint/agent_generator/cli/utils/naming_utils.py`

2. **Update `test_naming_utils.py`**  
   - Update `test_normalize_scheduler_kebab_case` expected values: `snake_name` → `"cleanup_job_scheduler"`, `filename` → `"cleanup_job_scheduler.py"`.  
   - Add `test_camel_to_snake_kebab_case`: asserts `camel_to_snake("my-agent") == "my_agent"`.  
   - Add `test_normalize_handler_kebab_case`: asserts `normalize_component_name("my-agent", "handler") == ("MyAgentHandler", "my_agent_handler", "my_agent_handler.py")`.  
   File: `tests/unit/agent_generator/cli/utils/test_naming_utils.py`

3. **Remove workarounds in `create.py`**  
   Remove these now-dead lines (all are `file_name = file_name.replace("-", "_")` or `snake_name = snake_name.replace("-", "_")`):
   - `create_handler`: line 90 `file_name = file_name.replace("-", "_")`
   - `create_service`: line 184 `file_name = file_name.replace("-", "_")`
   - `create_api`: line 286 `file_name = file_name.replace("-", "_")`
   - `create_agent`: line 539 `snake_name = snake_name.replace("-", "_")` and line 538 `file_name = file_name.replace("-", "_")`  
   - `create_scheduler`: line 690 `file_name = file_name.replace("-", "_")`  
   File: `src/blueprint/agent_generator/cli/commands/create.py`

## Test scenarios

| Scenario | Type | Covers AC |
|---|---|---|
| `camel_to_snake("my-agent") == "my_agent"` | unit | AC3 |
| `camel_to_snake("MyAgent") == "my_agent"` (regression) | unit | AC4 |
| `normalize_component_name("my-agent", "handler")` returns correct tuple | unit | AC1 |
| `normalize_component_name("cleanup-job", "scheduler")` returns correct tuple | unit | AC2 |
| All existing `TestNormalizeComponentName` cases still pass | unit | AC4 |

## Dependencies

None. All changes are in one self-contained module + its test file + cleanup of callers.

## Risk

Low. One-line change to a pure function. All paths through `normalize_component_name` still pass because CamelCase input with no hyphens is unaffected by `name.replace("-", "_")`.

## Rollback

Revert the single commit. No schema or config changes.
