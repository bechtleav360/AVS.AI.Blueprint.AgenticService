# Debugging Tool Calling Issue

## Problem
- Your curl test with vLLM works perfectly and returns proper OpenAI `tool_calls`
- Pydantic AI requests to the same vLLM instance return `<tool_call>` XML tags
- This causes a parsing error in Pydantic AI

## Root Cause
Pydantic AI's OpenAI client might be sending requests in a slightly different format that causes vLLM's Hermes parser to return XML-style tool calls instead of OpenAI JSON format.

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

## Recommended Next Step
Enable debug logging to see the exact request Pydantic AI sends, then compare with your working curl request.
