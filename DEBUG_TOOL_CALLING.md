# Debugging Tool Calling Issue

## Problem
- Your curl test with vLLM works perfectly and returns proper OpenAI `tool_calls`
- Pydantic AI requests to the same vLLM instance return `<think>` XML tags before tool calls
- This causes a parsing error: `Invalid JSON: expected value at line 1 column 1`

## Root Cause (RESOLVED)
**Issue 1**: vLLM's Hermes parser emits `<think>...</think>` reasoning blocks before tool call JSON when `tool_choice="required"`. Pydantic AI's `OpenAIChatModel._process_response()` expects pure JSON and fails when it encounters the leading `<think>` tag.

**Issue 2**: vLLM doesn't support `$defs` in JSON schemas. Pydantic generates schemas with `$defs` for nested models, causing 400 Bad Request errors.

## Solutions Implemented

### Solution 1: Disable Thinking Tags (Option A)
Created a custom `ModelProfile` in `base/src/agent/base_agent.py` that disables thinking tag processing for vLLM:

```python
vllm_profile = ModelProfile(
    thinking_tags=('', ''),  # Empty tags disable thinking block processing
    ignore_streamed_leading_whitespace=True,
)

model = OpenAIChatModel(
    provider=provider,
    model_name=ai_config["model_name"],
    profile=vllm_profile,
)
```

### Solution 2: Flatten JSON Schema
Overrode `model_json_schema()` in `InvoiceInput` (`custom/src/models/resource.py`) to generate a flattened schema without `$defs`:

```python
@classmethod
def model_json_schema(cls, **kwargs):
    """Generate vLLM-compatible JSON schema without $defs."""
    return {
        "type": "object",
        "properties": {
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", ...},
                        "quantity": {"anyOf": [...]},
                        # ... inline properties instead of $ref
                    }
                }
            }
        }
    }
```

This inlines the `InvoiceLineItem` structure directly into the `line_items` array definition, avoiding `$defs` references.

## Possible Differences

### Your Working Curl Request:
```json
{
  "model": "default",
  "tool_choice": "auto",
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "calculate_invoice",
        "description": "...",
        "parameters": { "type": "object", "properties": {...} }
      }
    }
  ]
}
```

### What Pydantic AI Might Be Sending:
- Different `tool_choice` format
- Additional fields like `parallel_tool_calls`
- Different parameter schema format
- Missing or extra fields

## Solutions

### Option 1: Intercept and Log Requests
Add logging to see exactly what Pydantic AI sends:

```python
# In base_agent.py
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("openai").setLevel(logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.DEBUG)
```

### Option 2: Use Plain JSON Mode (Current Workaround)
- Disable tool calling
- Have model return JSON as plain text
- Parse manually

### Option 3: Custom Model Wrapper
Create a wrapper that intercepts requests and modifies them before sending to vLLM:

```python
class VLLMCompatibleModel(OpenAIChatModel):
    async def request(self, messages, tools=None, **kwargs):
        # Modify request to match your working curl format
        if tools:
            # Ensure tools are in exact format vLLM expects
            pass
        return await super().request(messages, tools, **kwargs)
```

### Option 4: Wait for vLLM Update
The vLLM Hermes parser might need updates to handle all variations of OpenAI tool calling format.

## Validation Steps
1. **Test the fix**: Run your invoice processing request again to verify tool calls work correctly
2. **Monitor logs**: Check that no `<think>` tags or `$defs` errors appear in the model responses
3. **Verify tool execution**: Confirm `calculate_invoice` tool is called and returns proper `InvoiceAnalysisOutput`
4. **Check schema**: Inspect the generated tool schema in debug logs to confirm no `$defs` present

## Rollback Instructions
If these fixes cause issues:

**For Solution 1** (thinking tags):
- Revert changes in `base/src/agent/base_agent.py`
- Remove the `vllm_profile` creation
- Remove the `profile=vllm_profile` parameter from `OpenAIChatModel`

**For Solution 2** (schema flattening):
- Remove the `model_json_schema()` method from `InvoiceInput` in `custom/src/models/resource.py`
- This will revert to Pydantic's default schema generation (with `$defs`)
