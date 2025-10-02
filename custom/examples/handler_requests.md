# Handler Request Examples

This document provides example REST API requests that demonstrate different handler behaviors in the agent service.

## Example 1: Invoke Agent Handler

This request triggers `AgentInvokerHandler` which invokes the Pydantic AI agent.

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/process" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-123",
    "asset_id": "asset-456",
    "resource_type": "backup",
    "details": {
      "action": "invoke_agent",
      "description": "Analyze backup status for critical server",
      "priority": "high"
    }
  }'
```

**Handler Flow:**
1. `AgentInvokerHandler` (priority 10) matches on `action == "invoke_agent"`
2. Sets `use_agent = True` and `agent_name = "AgentRuntime"`
3. Returns `None` to continue processing
4. Processing service invokes the Pydantic AI agent
5. Agent analyzes the request and returns structured output

**Expected Response:**
```json
{
  "resource_id": "asset-456",
  "status": "analyzed",
  "summary": "Backup analysis completed for critical server",
  "confidence": 0.85,
  "notes": "Agent-generated analysis",
  "metadata": {
    "tenant_id": "tenant-123",
    "processed_by_agent": true
  }
}
```

---

## Example 2: Simple Processor Handler (No Agent)

This request triggers `SimpleProcessorHandler` which processes the request **without** invoking the agent.

**Request:**
```bash
curl -X POST "http://localhost:8000/api/v1/process" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "tenant-789",
    "asset_id": "asset-012",
    "resource_type": "server",
    "details": {
      "action": "simple_process",
      "description": "Quick status check",
      "priority": "low"
    }
  }'
```

**Handler Flow:**
1. `SimpleProcessorHandler` (priority 15) matches on `action == "simple_process"`
2. Sets `use_agent = False` and `processed_without_agent = True`
3. Returns enriched result immediately
4. Processing service skips agent invocation
5. Returns handler result directly

**Expected Response:**
```json
{
  "status": "processed",
  "processed_by": ["SimpleProcessorHandler"],
  "data": {
    "tenant_id": "tenant-789",
    "asset_id": "asset-012",
    "resource_type": "server",
    "enriched_at": "timestamp_placeholder",
    "details": {
      "action": "simple_process",
      "description": "Quick status check",
      "priority": "low"
    }
  }
}
```

---

## Handler Priority Order

Handlers are executed in priority order (lower numbers first):

1. **AgentInvokerHandler** (priority 10) - Invokes AI agent
2. **SimpleProcessorHandler** (priority 15) - Processes without agent
3. **ProcessingHandler** (priority 30) - Fallback enrichment (only if `validated_at` is set)

---

## Key Differences

| Aspect | AgentInvokerHandler | SimpleProcessorHandler |
|--------|---------------------|------------------------|
| **Action** | `invoke_agent` | `simple_process` |
| **Agent Invocation** | ✅ Yes | ❌ No |
| **Processing Time** | Slower (AI model call) | Faster (direct processing) |
| **Use Case** | Complex analysis, reasoning | Simple enrichment, validation |
| **Concurrency Impact** | Subject to semaphore throttling | No throttling needed |

---

## Testing Both Handlers

Run both requests sequentially to see the different behaviors:

```bash
# Test agent invocation
curl -X POST "http://localhost:8000/api/v1/process" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"t1","asset_id":"a1","resource_type":"backup","details":{"action":"invoke_agent"}}'

# Test simple processing (no agent)
curl -X POST "http://localhost:8000/api/v1/process" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"t2","asset_id":"a2","resource_type":"server","details":{"action":"simple_process"}}'
```

---

## Notes

- **ProcessingHandler** only runs if `validated_at` is in context (set by `AgentInvokerHandler`)
- If no handler matches, the processing service may invoke the default agent runtime
- Handlers can return `None` to pass control to the next handler in the chain
- Returning a result stops the handler chain and returns that result
