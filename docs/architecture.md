# Architecture

This document explains the Agents Blueprint system architecture with a focus on data flow and component relationships.

## Overview

The Agents Blueprint is a microservice framework for building AI-powered agents. It provides a structured way to process requests through configurable handlers and AI runtimes.

## Current Architecture (Consolidated Registry)

The system uses a simplified architecture with a single ComponentRegistry managing all components.

### Request Flow

```
1. API Request (REST or Event)
   |
2. EventApi or RestApi receives request
   |
3. ProcessingService orchestrates the workflow
   |
4. Handler Chain processes request (priority-sorted)
   |
5. Agent Runtime (if needed)
   |
6. Pydantic AI Agent calls LLM
   |
7. Response returned to caller
```

### Component Layers

**Layer 1: API Endpoints**
- `EventApi` - Processes CloudEvents
- `RestApi` - Processes REST requests
- Validates input and creates CloudEvent format

**Layer 2: Processing Service**
- Orchestrates the entire workflow
- Manages handler chain execution
- Invokes agent runtime when needed
- Contains all business logic

**Layer 3: Component Registry**
- Stores handlers and runtimes
- Provides component retrieval
- No business logic (pure container)

**Layer 4: Event Handlers**
- Chain of Responsibility pattern
- Sorted by priority (lower runs first)
- Each handler can process or pass to next
- Examples: AgentInvokerHandler, ProcessingHandler

**Layer 5: Agent Runtime**
- Wraps Pydantic AI agent
- Loads prompts and tools
- Manages AI model configuration
- Returns structured output

**Layer 6: AI Model**
- OpenAI or vLLM backend
- Executes tools
- Returns structured responses

## Data Flow Examples

### Example 1: Simple REST Request

```
POST /api/process-resource
Body: {"invoice_text": "...", "details": {"action": "invoke_agent"}}

Step 1: RestApi receives request
Step 2: Converts to CloudEvent format
Step 3: ProcessingService.process_event() called
Step 4: Handler chain executes:
        - AgentInvokerHandler checks action="invoke_agent" → matches
        - Sets context["use_agent"] = True
        - Returns None (passes to next)
Step 5: ProcessingService sees use_agent=True
Step 6: Calls AgentRuntime.process_request()
Step 7: Agent calls LLM with prompt + tools
Step 8: LLM returns structured output
Step 9: Response returned through layers
```

### Example 2: Event Processing

```
POST /events/process
Body: CloudEvent with invoice data

Step 1: EventApi receives CloudEvent
Step 2: ProcessingService.process_event() called
Step 3: Handler chain executes (same as above)
Step 4: Agent processes if needed
Step 5: CloudEventResponse returned
```

### Example 3: Handler-Only Processing

```
POST /api/process-resource
Body: {"invoice_text": "...", "details": {"action": "simple_process"}}

Step 1: RestApi receives request
Step 2: ProcessingService.process_event() called
Step 3: Handler chain executes:
        - AgentInvokerHandler checks action → no match, skips
        - SimpleProcessorHandler checks action="simple_process" → matches
        - Processes and returns result directly
Step 4: No agent invocation needed
Step 5: Handler result returned
```

## Key Components

### ComponentRegistry

**Purpose**: Manages handlers and runtimes  
**Location**: `base/src/registry/component_registry.py`

**Responsibilities**:
- Register handlers (sorted by priority)
- Register runtimes (with default selection)
- Provide component retrieval
- Link components to registry

**Does NOT**:
- Execute business logic
- Process events
- Make decisions

### ProcessingService

**Purpose**: Orchestrates request processing  
**Location**: `base/src/services/processing_service.py`

**Responsibilities**:
- Execute handler chain
- Invoke agent runtime when needed
- Manage context between handlers
- Handle errors and logging
- Coordinate the workflow

### EventHandler (Base Class)

**Purpose**: Template for custom handlers  
**Location**: `base/src/agent/event_handler.py`

**Pattern**: Chain of Responsibility + Template Method

**Methods to Implement**:
- `_can_handle(event, context)` - Return True if handler should process
- `_handle(event, context)` - Process and return result or None

**Handler Priority**:
- Lower numbers run first (10, 20, 30...)
- Handlers sorted automatically
- First handler to return non-None stops the chain

### BaseAgent (Base Class)

**Purpose**: Template for custom agents  
**Location**: `base/src/agent/base_agent.py`

**Methods to Implement**:
- `_get_prompt_name()` - Return prompt file name
- `_get_tools()` - Return list of tools
- `_get_processing_context_type()` - Return context model type
- `_get_result_type()` - Return output model type
- `custom_health_check()` - Custom health check logic

## Configuration

**Files**:
- `settings.toml` - Application configuration
- `secrets.toml` - Sensitive data (API keys)
- Environment variables - Override settings

**Key Settings**:
- `app_name` - Service name
- `app_port` - HTTP port
- `ai_model_provider` - openai or vllm
- `ai_model_name` - Model to use
- `ai_model_api_key` - API key

## Adding New Functionality

### Add a New Handler

1. Create handler class in `custom/src/agent/handlers.py`
2. Extend `EventHandler`
3. Implement `_can_handle()` and `_handle()`
4. Register in `custom/src/main.py` with `.with_handler()`

### Add a New Agent Runtime

1. Create runtime class in `custom/src/agent/runtime.py`
2. Extend `BaseAgent`
3. Implement required abstract methods
4. Register in `custom/src/main.py` with `.with_agent_runtime()`

### Add a New API Endpoint

1. Create API class extending `RestApi`
2. Define payload model
3. Register in `custom/src/main.py` with `.with_rest_api()`

## Architecture Metrics

**Complexity**:
- Total layers: 5
- Registry classes: 1
- Indirection levels: 4

**For Simple Changes**:
- Files to touch: 2-3
- Test mocks needed: 1
- Onboarding time: 1-2 days

## Design Principles

**Separation of Concerns**:
- ComponentRegistry = Component storage only
- ProcessingService = Business logic only
- Handlers = Domain-specific processing
- Agent = AI interaction only

**Extensibility**:
- Add handlers without modifying framework
- Add runtimes without changing core
- Override base behavior through inheritance

**Testability**:
- Single registry to mock
- Handlers testable in isolation
- Clear interfaces

## Observability

**Tracing**: OpenTelemetry spans automatically added  
**Logging**: Structured logging with lazy % formatting  
**Metrics**: Health check endpoints at `/actuators/health`

## Deployment

**Local Development**: `uvicorn custom.src.main:app --reload`  
**Docker**: Multi-stage build with `docker-compose.yml`  
**Production**: Container orchestration (Kubernetes ready)

---

For implementation details, see:
- [Registry Consolidation](../REGISTRY_CONSOLIDATION.md)
- [Testing Guide](testing-guide.md)
- [Development Guide](development-guide.md)
