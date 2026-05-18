# Unit Tests — `blueprint.agents.models`

Test coverage for `src/blueprint/agents/models/`.

---

## File overview

| File | Classes under test | What is covered |
|---|---|---|
| `test_config.py` | `EventPublishingConfig` | `normalize_topic_mapping`: `TopicConfig` / dict / plain-string / invalid-type values, non-dict mapping → error; `_parse_mapping_string`: empty string, quoted-key string, unquoted-key string (auto-quoting regex), non-brace format → error, malformed brace string → error; `_parse_topic_config_value`: plain string, `map[topic:t]`, `map[topic:t routing_key:rk]`, empty `map[]` → error, missing `topic` entry → error, entry without `:` → error |
| `test_events.py` | `CloudEvent` | `validate_time_format`: Z-suffix, `+00:00` offset, missing timezone → error, non-string → error, default factory produces valid timestamp; `validate_data_exclusivity`: data-only, data_base64-only, neither, both → error |
| `test_result.py` | `Evidence`, `AgentOutput`, `AnalysisRequest` | `Evidence.confidence` ge/le constraints (0.0/1.0 pass, outside → error); `AgentOutput.sort_evidence_by_confidence`: empty list, single item, multiple items sorted descending, already-sorted input; `AnalysisRequest.check_resource_or_id_provided`: resource_id only, resource only, neither → error, both → error |

---

## Decisions

### Only files with non-trivial logic are tested

`api.py`, `status.py`, and `event_routing.py` contain only Pydantic field definitions with no custom validators or methods. `errors.py` defines three trivial exception subclasses. None of these files have test modules.

### Private helpers tested via model construction, not called directly

`_parse_mapping_string` and `_parse_topic_config_value` are `@staticmethod` private helpers. Tests exercise them by constructing `EventPublishingConfig(topic_mapping=...)` with string inputs, which validates the full normalisation path and stays resilient to internal refactoring.

### `CloudEvent` validators were silently not called — fixed decorator style

Both `validate_time_format` and `validate_data_exclusivity` used `@classmethod` before the Pydantic decorator (`@classmethod @field_validator(...)` and `@classmethod @model_validator(...)`). In Pydantic v2 this registers the outer classmethod wrapper — not the validator — so neither function was ever invoked at construction time. Neither validator uses `cls` in its body, so the fix was to remove both `@classmethod` and the `cls` parameter, leaving plain validator functions that Pydantic v2 calls directly.
