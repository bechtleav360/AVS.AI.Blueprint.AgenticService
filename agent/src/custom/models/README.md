# Custom Models

This package is for your domain-specific model extensions. The base framework provides core models in `base/src/models/`. You should extend those base classes to add fields, constraints, and behaviour specific to your agent.

## Where are the base models?

- `base/src/models/domain.py` — generic domain-level models (e.g., `AgentOutput`)
- `base/src/models/events.py` — event envelopes and related types
- `base/src/models/asset.py` — example resource models (assets)
- `base/src/models/result.py` — result payloads and typed outputs

## Extending a base model

Create a file under this folder, e.g. `my_models.py`, and extend the base model classes:

```python
# agent/src/custom/models/my_models.py
from typing import Optional
from pydantic import Field

from base.src.models.domain import AgentOutput
from base.src.models.events import CloudEvent

class MyAgentOutput(AgentOutput):
    """Custom agent output with additional fields."""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    notes: Optional[str] = None

class MyCloudEvent(CloudEvent):
    """Custom event that extends the standard envelope with domain data."""
    source_system: Optional[str] = None
```

## Using your custom models

Import and use your extended models from your custom logic:

```python
from agent.src.custom.models.my_models import MyAgentOutput

# example usage in a handler or tool
result = MyAgentOutput(status="ok", summary="All checks passed", confidence=0.92)
```

## Tips

- Keep compatibility with the base model fields to ensure serialization between components.
- Prefer additive fields rather than removing or renaming base fields.
- Use `pydantic` validators to enforce domain constraints.
- Consider separating model files by domain areas for clarity (e.g., `assets.py`, `events.py`).
