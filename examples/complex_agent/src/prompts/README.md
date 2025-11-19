# Custom Prompts

This directory contains the prompt files used by your custom agent runtime.

## How prompts are loaded

- The base runtime (`base/src/agent/base/runtime/base_agent.py`) declares an abstract method `_get_system_prompt()`.
- Your custom agent (`agent/src/custom/agent/runtime.py`) implements `_get_system_prompt()` and loads a prompt file from this folder.
- By default, the example runtime returns the prompt named by `_get_prompt_name()` (default: `system`).

## File naming

- Use the `.prompt` extension for plain text prompt files.
- Example: `system.prompt`
- You can add additional prompts and switch which one is used by overriding `_get_prompt_name()` in your `AgentRuntime`.

## Example

1. Create a new prompt file:

```
agent/src/custom/prompts/my_production.prompt
```

Content:
```
You are an expert agent. Provide concise, high-quality answers. Always include justification.
```

2. Update runtime to pick it:

```python
# agent/src/custom/agent/runtime.py
class AgentRuntime(BaseAgent):
    def _get_prompt_name(self) -> str:
        return "my_production"
```

3. (Optional) Keep multiple prompts for different environments and choose based on config:

```python
# Example selection logic
if settings.get("env") == "production":
    prompt_name = "my_production"
else:
    prompt_name = "system"
```

## Tips

- Keep prompts short, stable, and versioned.
- Prefer declarative guidance over procedural instructions.
- Avoid including secrets or environment-specific tokens.
- Consider maintaining different prompts for dev/test/prod and selecting via configuration.
