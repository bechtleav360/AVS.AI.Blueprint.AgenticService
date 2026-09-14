# Unit Tests — `blueprint.agents.utils`

Test coverage for `src/blueprint/agents/utils/utils.py`.

---

## File overview

| File | Function under test | What is covered |
|---|---|---|
| `test_camel_to_snake.py` | `camel_to_snake` | Standard CamelCase, acronyms (leading/mid/trailing), numbers, edge cases |
| `test_run_app.py` | `run_app`, `uvicorn_log_level` | Arguments handed to uvicorn (host, port, coerced string port, defaults); development logs at `debug` and forces one worker; production translates `log_level` and defaults to `info`; `app_workers > 1` raises before `uvicorn.run` is called; `reload` is never enabled; unknown level falls back to `info` with a warning |
| `test_parse_bool.py` | `parse_bool` | Real bools pass through; the truthy and falsy strings an environment override delivers (`true`/`1`/`yes`, `false`/`0`/`no`, case and whitespace tolerant); everything else raises rather than reading as false, including empty and whitespace-only; the error names the key |

---

## Decisions

### No conftest needed
`camel_to_snake` and `parse_bool` are pure functions with no dependencies or side effects.
All inputs are inline string literals — no fixtures, no shared state.

### `run_app` is tested through a patched `uvicorn.run`
`run_app` imports uvicorn inside the function, so `patch("uvicorn.run")` is enough and no server
is ever started. What is asserted is the argument set uvicorn is handed, which is the whole of
what `run_app` decides. Two local helpers in the test module stand in for a conftest: `make_config`
builds a `Config` stand-in answering `get` from a dict, and `serve` runs the function and returns
the keyword arguments uvicorn received.
