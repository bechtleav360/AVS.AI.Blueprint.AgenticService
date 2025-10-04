# Custom Agent Examples

Examples demonstrating how to use the blueprint components.

## Available Examples

### `logging_handler_example.py`

Demonstrates how to use the built-in `LoggingHandler` to debug event flow.

**Usage:**
```bash
cd /home/pajoma/workspaces/Agents_Blueprint
python -m custom.examples.logging_handler_example
```

**What it shows:**
- Creating a `DecisionEngine`
- Adding `LoggingHandler` to the chain
- Processing CloudEvents
- Inspecting event content in console

## LoggingHandler

The `LoggingHandler` is a built-in handler in `base.src.agent` that prints event content to the console.

### Features

- **Automatic event inspection** - Logs all CloudEvent fields
- **Configurable priority** - Control when it runs in the chain
- **Configurable log level** - DEBUG, INFO, WARNING, ERROR
- **Pretty JSON formatting** - Easy to read event data
- **Context logging** - Shows processing context

### Usage in Your Agent

```python
from base.src.agent import DecisionEngine, LoggingHandler

# Create engine
engine = DecisionEngine()

# Add logging handler (priority=10 means it runs first)
logging_handler = LoggingHandler(priority=10, log_level="INFO")
engine.add_handler(logging_handler)

# Add your other handlers
engine.add_handler(your_validation_handler)
engine.add_handler(your_processing_handler)

# Process events - LoggingHandler will print details
result = await engine.process(event, context)
```

### Configuration

**Priority:**
- Lower numbers run first
- Default: `10` (runs early in chain)
- Use `priority=1` to run before everything
- Use `priority=999` to run after everything

**Log Level:**
- `"DEBUG"` - Detailed output
- `"INFO"` - Standard output (default)
- `"WARNING"` - Only warnings
- `"ERROR"` - Only errors

### Example Output

```
======================================================================
📨 EVENT RECEIVED
======================================================================

📋 CloudEvent Metadata:
   Spec Version: 1.0
   Event ID: 550e8400-e29b-41d4-a716-446655440000
   Type: resource.check.requested
   Source: asset-inventory
   Subject: vm-12345
   Time: 2025-10-04T19:20:30.123456

📦 Event Data:
{
   "resource_id": "vm-12345",
   "resource_type": "virtual_machine",
   "tags": {
      "environment": "production"
   }
}

🔧 Processing Context:
   correlation_id: 123e4567-e89b-12d3-a456-426614174000
   tenant_id: tenant-123

======================================================================
```

## Tips

1. **Development** - Use `LoggingHandler` with `priority=10` to see all events
2. **Production** - Remove or set `log_level="ERROR"` to reduce noise
3. **Debugging** - Add temporarily when troubleshooting event issues
4. **Testing** - Use to verify event structure in integration tests
