# Unit Tests — `blueprint.agents.utils`

Test coverage for `src/blueprint/agents/utils/utils.py`.

---

## File overview

| File | Function under test | What is covered |
|---|---|---|
| `test_camel_to_snake.py` | `camel_to_snake` | Standard CamelCase, acronyms (leading/mid/trailing), numbers, edge cases |

---

## Decisions

### No conftest needed
`camel_to_snake` is a pure function with no dependencies or side effects.
All inputs are inline string literals — no fixtures, no shared state.
