# Troubleshooting Guide

This document covers common issues and their solutions when working with the Agents Blueprint.

## Table of Contents

- [vLLM Thinking Tags Error](#vllm-thinking-tags-error)
- [ArgoCD Volume Mount Error](#argocd-volume-mount-error)
- [Connection Issues](#connection-issues)
- [Configuration Issues](#configuration-issues)

---

## vLLM Thinking Tags Error

### Symptoms

```
pydantic_ai.exceptions.ModelHTTPError: status_code: 400, model_name: default
Invalid JSON: expected value at line 1 column 1
input_value='<think>\nOkay, let\'s ta...'
```

### Cause

The vLLM model is using a chat template with thinking/reasoning tags (e.g., DeepSeek R1, Qwen with reasoning). These tags break the OpenAI-compatible tool calling format.

### Quick Fix

**Option 1: Use Guided Decoding + tool_choice="auto" (Recommended - Already Implemented)**

The codebase now automatically applies **two fixes** for vLLM:

```python
# Automatically applied in base_agent.py for vLLM provider
model_settings = {
    "extra_body": {
        "guided_decoding_backend": "outlines",  # Prevents thinking tags
    },
    "allow_text_output": True,  # Uses tool_choice="auto" instead of "required"
}
```

**Why both fixes are needed:**
1. **Guided decoding** - Constrains output to valid JSON (prevents thinking tags)
2. **tool_choice="auto"** - Some vLLM models don't support `"required"` properly

**Ensure your vLLM server supports Outlines:**
- vLLM must be installed with: `pip install vllm[outlines]`
- Or use Docker image with Outlines support

**Option 2: Switch to OpenAI (For Testing)**

Edit `custom/settings.toml`:
```toml
ai_model_provider = "openai"
ai_model_name = "gpt-4"
# ai_model_api_key = "your-key"  # or set AI_MODEL_API_KEY env var
```

**Option 3: Configure vLLM Server with Custom Template**

If guided decoding doesn't work, configure the chat template:
```bash
vllm serve <model> \
  --chat-template /app/chat_template.jinja \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

See `docs/ai-assistant-vllm-configuration-guide.md` for template details.

### Detailed Documentation

See [docs/vllm-thinking-tags-issue.md](docs/vllm-thinking-tags-issue.md) for comprehensive solutions.

---

## ArgoCD Volume Mount Error

### Symptoms

```
ComparisonError: Failed to compare desired state to live state: 
failed to calculate diff: The order in patch list doesn't match $setElementOrder
```

### Cause

Duplicate or conflicting volume mounts in your vLLM Helm deployment, typically:
- Multiple mounts to `/data/huggingface`
- Conflicting paths between base deployment and `extraVolumeMounts`

### Quick Fix

**Update your Helm values to use a unique mount path:**

```yaml
vllm:
  extraArgs:
    - --chat-template
    - /app/chat_template.jinja  # Unique path
  
  extraVolumeMounts:
    - name: chat-template
      mountPath: /app/chat_template.jinja  # Not /data/huggingface
      subPath: pydantic_ai_tool_template.jinja
      readOnly: true
```

**Then force sync:**
```bash
argocd app sync <your-vllm-app> --force --prune
```

### Detailed Documentation

See [docs/ARGOCD_VLLM_FIX.md](docs/ARGOCD_VLLM_FIX.md) for step-by-step resolution.

---

## Connection Issues

### RabbitMQ Connection Failed

**Symptoms:**
```
Failed to connect to RabbitMQ
```

**Solutions:**
1. Ensure RabbitMQ is running: `docker-compose up -d rabbitmq`
2. Check connection settings in `settings.toml`:
   ```toml
   rabbitmq_host = "localhost:5672"
   rabbitmq_vhost = "bios"
   ```
3. Verify RabbitMQ is accessible: `curl http://localhost:15672`

### Dapr Sidecar Not Running

**Symptoms:**
```
Failed to connect to Dapr sidecar
```

**Solutions:**
1. Start with Dapr: `./start_with_dapr.sh`
2. Check Dapr is running: `dapr list`
3. Verify Dapr ports in `settings.toml`:
   ```toml
   dapr_http_port = 3500
   dapr_grpc_port = 50001
   ```

---

## Configuration Issues

### Environment Variable Not Loaded

**Symptoms:**
```
KeyError: 'AI_MODEL_API_KEY'
```

**Solutions:**
1. Create `.env` file from `.env.example`:
   ```bash
   cp .env.example .env
   ```
2. Set the required environment variable:
   ```bash
   export AI_MODEL_API_KEY="your-key"
   ```
3. Or set it in `settings.toml` (not recommended for secrets):
   ```toml
   ai_model_api_key = "your-key"
   ```

### Settings Not Applied

**Symptoms:**
- Changes to `settings.toml` don't take effect

**Solutions:**
1. Restart the application
2. Check the environment: `APP_ENVIRONMENT=development` (default)
3. Verify settings are loaded:
   ```python
   from base.src.config import Config
   config = Config()
   print(config.get_ai_config())
   ```

---

## Debugging Tips

### Enable Debug Logging

Edit `settings.toml`:
```toml
log_level = "DEBUG"
```

### Check Health Endpoints

```bash
# Application health
curl http://localhost:8000/actuators/health

# Readiness check
curl http://localhost:8000/actuators/ready

# Metrics
curl http://localhost:8000/actuators/metrics
```

### View Logs

```bash
# Application logs
tail -f logs/app.log

# Docker logs
docker-compose logs -f

# Dapr logs
dapr logs --app-id agent-blueprint
```

### Test Components Individually

```bash
# Test RabbitMQ connection
python trials/test_rabbitmq_connection.py

# Test vLLM endpoint
curl https://avs-vllm.q14.net/v1/models

# Test with curl
curl -X POST http://localhost:8000/events/generic \
  -H "Content-Type: application/json" \
  -d @trials/curls/request.json
```

---

## Getting Help

1. Check the [documentation](docs/README.md)
2. Review [architecture](docs/architecture.md)
3. Look at [examples](custom/examples/)
4. Check [GitHub issues](https://github.com/your-repo/issues)

## Common Error Patterns

| Error Pattern | Likely Cause | Solution |
|--------------|--------------|----------|
| `Invalid JSON: <think>` | vLLM thinking tags | See [vLLM Thinking Tags Error](#vllm-thinking-tags-error) |
| `Connection refused` | Service not running | Start required services |
| `401 Unauthorized` | Missing/invalid API key | Set `AI_MODEL_API_KEY` |
| `404 Not Found` | Wrong endpoint/URL | Check `base_url` in settings |
| `Validation error` | Schema mismatch | Check model definitions |
| `Timeout` | Slow model/network | Increase timeout in settings |
