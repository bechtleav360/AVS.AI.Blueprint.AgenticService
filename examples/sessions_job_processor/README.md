# Sessions Job Processor Example

This example demonstrates how to use the Blueprint Agents framework to consume and process jobs from the sessions service via Server-Sent Events (SSE).

## Overview

The example shows:
- Connecting to sessions service via SSE
- Processing job notifications through EventHandler chain
- Using JobHandler base class for convenient job processing
- Fetching job details with session keys
- Completing jobs with results
- Error handling and retry logic

## Architecture

```
Sessions Service (SSE)
    ↓
SessionsBus (api layer)
    ↓
Convert to CloudEvent + Add context
    ↓
ProcessingService
    ↓
TextExtractionHandler (EventHandler)
    ↓
Complete job with results (via context)
```

The architecture follows the same pattern as NatsEventBus:
- **SessionsBus** handles SSE connection and event conversion (framework layer)
- **EventHandlers** process jobs using standard can_handle_event/handle_event pattern
- **Context** provides sessions API client and session key to handlers

## Configuration

Create a `settings.toml` file:

```toml
app_name = "sessions-job-processor"
app_description = "Processes text extraction jobs from sessions service"
app_port = 8000

# Sessions service integration
[sessions_service]
base_url = "http://localhost:8001"
agent_id = "text-extractor-001"
agent_type = "extractor"
capabilities = ["extract_text"]
api_key = "@format {env[SESSIONS_API_KEY]}"

# Session key management
session_key_source = "env"
session_key_env_var = "SESSION_KEY"
session_key_cache_ttl_seconds = 3600

# Concurrency settings
max_concurrent_jobs = 10
job_timeout_seconds = 300

# LLM configuration (optional, if using agents)
[runtimes.text_extractor]
model_provider = "openai"
model_name = "gpt-4"
model_api_key = "@format {env[OPENAI_API_KEY]}"
```

## Environment Variables

```bash
export SESSIONS_API_KEY="your-sessions-api-key"
export SESSION_KEY="your-session-key"
export OPENAI_API_KEY="your-openai-api-key"  # If using LLM agents
```

## Running

```bash
# Install dependencies
pip install -e .

# Run the application
python examples/sessions_job_processor/main.py
```

## Handler Implementation

The example includes a `TextExtractionHandler` that:
1. Filters for "extract_text" job types via `can_handle_event()`
2. Fetches full job details using sessions API client from context
3. Processes the job (extracts text from document)
4. Completes the job with results using sessions API client from context

The handler is a regular `EventHandler` - no special base class needed!

## Testing

You can test the integration by:
1. Starting the sessions service
2. Running this example
3. Creating a job via the sessions service API
4. Watching the logs as the job is processed

## Health Checks

The application exposes health checks at:
- `GET /health` - Overall application health
- `GET /actuator/health` - Detailed component health including sessions service connectivity

## Key Features Demonstrated

### 1. Regular EventHandler Pattern
```python
class TextExtractionHandler(EventHandler):
    async def can_handle_event(self, event, context) -> bool:
        # Filter for sessions job events
        if not event.type.startswith("sessions.job.created."):
            return False
        return event.data.get("job_type") == "extract_text"

    async def handle_event(self, event, context):
        # Get API client and session key from context
        api_client = context["sessions_api_client"]
        session_key = context["session_key"]

        # Use API client to interact with sessions service
        job = await api_client.get_job_details(...)
        await api_client.complete_job(...)
```

### 2. Automatic Component Registration
The framework automatically:
- Creates SessionsBus (similar to NatsEventBus)
- Registers SessionsApiClient and SessionKeyProvider
- Connects to SSE stream on startup

No manual wiring needed!

### 3. Error Handling
```python
# Transient failures - job remains pending
raise RetryableHandlerError("Temporary API error")

# Permanent failures - job auto-cancelled
raise InvalidEventError("Invalid job payload")
```

### 4. Concurrency Control
Jobs are processed concurrently with configurable limits via `max_concurrent_jobs` setting.

## Next Steps

- Implement additional job handlers for different job types
- Add custom validation logic in handlers
- Integrate with LLM agents for AI-powered processing
- Add metrics and monitoring
- Deploy to production
