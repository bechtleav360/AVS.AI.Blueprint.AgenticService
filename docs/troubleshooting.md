# Troubleshooting Guide

Common issues and solutions.

---

## Application Won't Start

### Error: "Module not found"

**Problem:** `ModuleNotFoundError: No module named 'blueprint'`

**Solution:**
```bash
# Install the package in development mode
pip install -e .
```

### Error: "Configuration file not found"

**Problem:** `FileNotFoundError: settings.toml not found`

**Solution:**
1. Create `settings.toml` in your project root
2. Verify the path in your code:
   ```python
   config = Config(
       settings_files=["settings.toml"],
       root_path=Path(__file__).parent.parent,  # Adjust as needed
   )
   ```

### Error: "API key not configured"

**Problem:** `ValueError: api_key not configured`

**Solution:**
1. Add API key to `secrets.toml`:
   ```toml
   [default.ai.default]
   api_key = "sk-..."
   ```
2. Or set environment variable:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

---

## Event Handling Issues

### Events Not Being Processed

**Problem:** Handler is registered but events aren't processed.

**Solution:**
1. Check handler priority (lower number = higher priority)
2. Verify `can_handle_event()` returns True for your event type
3. Check event topic matches subscription:
   ```toml
   [[default.event_publishing.topic_mapping]]
   topic = "user.created"  # Must match event type
   ```
4. Enable debug logging:
   ```toml
   log_level = "DEBUG"
   ```

### Handler Not Called

**Problem:** `can_handle_event()` is never called.

**Solution:**
1. Verify handler is registered:
   ```python
   app = AppBuilder(config).with_handler(MyHandler).build()
   ```
2. Check Dapr is running:
   ```bash
   dapr --version
   ```
3. Verify event is being published to the correct topic

### "Component not found" Error

**Problem:** `RuntimeError: Agent 'my_agent' not registered`

**Solution:**
1. Register the component before using it:
   ```python
   app = AppBuilder(config).with_agent(my_agent).build()
   ```
2. Use correct component name:
   ```python
   agent = self._registry.get_agent("my_agent")  # Must match registration
   ```

---

## AI Agent Issues

### Agent Returns Empty Response

**Problem:** Agent runs but returns no data.

**Solution:**
1. Check system prompt is loaded:
   ```python
   .with_system_prompt_file("system")
   ```
2. Verify result type is correct:
   ```python
   .with_result_type(MyOutputModel)
   ```
3. Check model is configured:
   ```python
   .with_model_from_config("my_agent")
   ```

### "System prompt not found" Error

**Problem:** `FileNotFoundError: Prompt file 'system.prompt' not found`

**Solution:**
1. Create the prompt file:
   ```bash
   mkdir -p prompts
   echo "You are a helpful assistant" > prompts/system.prompt
   ```
2. Or specify inline:
   ```python
   .with_system_prompt_text("You are a helpful assistant")
   ```
3. Check search paths in `settings.toml`:
   ```toml
   prompt_search_paths = ["prompts", "src/prompts"]
   ```

### Agent Hallucinating or Making Mistakes

**Problem:** AI agent returns incorrect or made-up information.

**Solution:**
1. Improve system prompt with clear instructions
2. Add tools for the agent to call:
   ```python
   .with_tools([database_lookup_tool, validation_tool])
   ```
3. Use more capable model:
   ```toml
   model_name = "gpt-4"  # Instead of gpt-4-mini
   ```
4. Set max tokens to limit response length:
   ```toml
   max_tokens = 500
   ```

---

## REST API Issues

### "404 Not Found" on Custom Endpoint

**Problem:** Custom endpoint returns 404.

**Solution:**
1. Verify endpoint is registered in `_register_routes()`:
   ```python
   def _register_routes(self):
       @self.router.post("/my-endpoint")
       async def my_endpoint(request):
           return {"status": "ok"}
   ```
2. Check prefix in app builder:
   ```python
   app.include_router(api.router, prefix="/api")  # Endpoint becomes /api/my-endpoint
   ```
3. Verify REST API is registered:
   ```python
   app = AppBuilder(config).with_rest_api(MyRestApi()).build()
   ```

### "405 Method Not Allowed"

**Problem:** Endpoint exists but HTTP method is wrong.

**Solution:**
1. Use correct HTTP method:
   ```python
   @self.router.post("/users")  # Use POST, not GET
   ```
2. Check client is using correct method:
   ```bash
   curl -X POST http://localhost:8000/api/users  # Correct
   ```

---

## Dapr Issues

### "Dapr sidecar not reachable"

**Problem:** `RuntimeError: Dapr sidecar unreachable`

**Solution:**
1. Start Dapr sidecar:
   ```bash
   dapr run --app-id my-app \
     --app-port 8000 \
     --dapr-http-port 3500 \
     uvicorn src.main:app --reload
   ```
2. Verify Dapr is installed:
   ```bash
   dapr --version
   ```
3. Check port is not in use:
   ```bash
   lsof -i :3500
   ```

### "RabbitMQ connection failed"

**Problem:** `ConnectionError: Cannot connect to RabbitMQ`

**Solution:**
1. Start RabbitMQ:
   ```bash
   docker run -d --name rabbitmq -p 5672:5672 rabbitmq:latest
   ```
2. Verify connection in Dapr component:
   ```yaml
   metadata:
   - name: host
     value: "localhost"
   - name: port
     value: "5672"
   ```

---

## Performance Issues

### Application is Slow

**Problem:** Requests are taking too long.

**Solution:**
1. Enable caching:
   ```python
   app = AppBuilder(config).with_cache().build()
   ```
2. Use faster model:
   ```toml
   model_name = "gpt-4-mini"  # Faster than gpt-4
   ```
3. Reduce max tokens:
   ```toml
   max_tokens = 200
   ```
4. Check logs for bottlenecks:
   ```toml
   log_level = "DEBUG"
   ```

### High Memory Usage

**Problem:** Application uses too much memory.

**Solution:**
1. Reduce cache size:
   ```toml
   [default.cache]
   size_limit = 100000000  # 100MB instead of 1GB
   ```
2. Clear cache periodically:
   ```bash
   curl -X DELETE http://localhost:8000/api/cache/evict
   ```
3. Check for memory leaks in handlers

---

## Debugging Tips

### Enable Debug Logging

```toml
[default]
log_level = "DEBUG"
```

### Use VS Code Debugger

1. Set breakpoint in your code
2. Launch with F5
3. Inspect variables in Debug Console

### Print Event Data

```python
async def handle_event(self, event: CloudEvent, context):
    print(f"Event type: {event.get_type()}")
    print(f"Event data: {event.get_data()}")
```

### Check Component Registry

```python
# List all registered handlers
handlers = self._registry.get_event_handler()
print(f"Handlers: {[h.name for h in handlers]}")

# List all agents
agents = self._registry.get_agents()
print(f"Agents: {agents}")
```

---

## Getting Help

1. **Check logs** — Enable DEBUG logging and look for error messages
2. **Read examples** — See `/examples` directory for working code
3. **Check API reference** — See [API Reference](reference/api.md)
4. **Run tests** — `pytest tests/unit/ -v` to verify setup
5. **Open an issue** — Report bugs on GitHub

---

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `ModuleNotFoundError` | Package not installed | `pip install -e .` |
| `FileNotFoundError` | Missing config/prompt file | Create the file or check path |
| `ValueError` | Invalid configuration | Check settings.toml format |
| `RuntimeError` | Component not registered | Register with AppBuilder |
| `ConnectionError` | Cannot connect to service | Start Dapr/RabbitMQ |
| `TimeoutError` | Request took too long | Increase timeout or optimize |
| `HTTPException 503` | Service unavailable | Check cache/Dapr status |
| `HTTPException 404` | Endpoint not found | Check route registration |

---

## Still Stuck?

1. Enable maximum debug logging
2. Check the examples in `/examples`
3. Review the [API Reference](reference/api.md)
4. Open an issue with error logs and code snippet
