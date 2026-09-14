# Unit Tests — `blueprint.agents.utils`

Test coverage for `src/blueprint/agents/utils/utils.py`.

---

## File overview

| File | Function under test | What is covered |
|---|---|---|
| `test_camel_to_snake.py` | `camel_to_snake` | Standard CamelCase, acronyms (leading/mid/trailing), numbers, edge cases |
| `test_parse_bool.py` | `parse_bool` | Real bools pass through; the truthy and falsy strings an environment override delivers (`true`/`1`/`yes`, `false`/`0`/`no`, case and whitespace tolerant); everything else raises rather than reading as false, including empty and whitespace-only; the error names the key |

---

## Decisions

### No conftest needed
`camel_to_snake` and `parse_bool` are pure functions with no dependencies or side effects.
All inputs are inline string literals — no fixtures, no shared state.
