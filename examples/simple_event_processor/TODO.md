# Simple Event Processor Example - Implementation Plan

## Overview
A minimal, runnable example demonstrating the Blueprint Agents framework with just an event handler (no AI agent). Perfect for understanding the core event processing pipeline.

## Architecture
```
Event Source (RabbitMQ/Dapr)
         ↓
    Handler Chain
         ↓
    Simple Processing
         ↓
    Event Output
```

## Implementation Plan

### Phase 1: Project Structure
- [ ] Create `src/` directory
  - [ ] `main.py` - FastAPI app entry point
  - [ ] `handlers/` - Event handlers
    - [ ] `__init__.py`
    - [ ] `simple_handler.py` - Basic event processor
  - [ ] `models/` - Data models
    - [ ] `__init__.py`
    - [ ] `events.py` - Event definitions
- [ ] Create configuration files
  - [ ] `settings.toml` - App configuration
  - [ ] `secrets.toml.example` - Secrets template
  - [ ] `pyproject.toml` - Dependencies

### Phase 2: Core Implementation
- [ ] Create `SimpleHandler` class
  - [ ] Extends `EventHandler` from framework
  - [ ] Implements `can_handle_event()` - checks event type
  - [ ] Implements `handle_event()` - processes event
  - [ ] No AI/LLM integration
- [ ] Create event models
  - [ ] Input event schema
  - [ ] Output result schema
- [ ] Build FastAPI app with AppBuilder
  - [ ] Register handler
  - [ ] Add health check endpoint
  - [ ] Add event processing endpoint

### Phase 3: Configuration & Setup
- [ ] Create `settings.toml` with:
  - [ ] App name and port
  - [ ] Event source configuration
  - [ ] Logging settings
- [ ] Create `pyproject.toml` with:
  - [ ] Dependency on `avs-blueprint-agents`
  - [ ] Dev dependencies (pytest, etc.)
- [ ] Create `docker-compose.yml` (optional)
  - [ ] RabbitMQ service
  - [ ] App service

### Phase 4: Documentation & Testing
- [ ] Create `README.md` with:
  - [ ] Quick start instructions
  - [ ] How to run locally
  - [ ] Example requests
- [ ] Create `tests/` directory
  - [ ] `test_handler.py` - Handler tests
  - [ ] `test_app.py` - App endpoint tests
- [ ] Create `.env.example` for environment variables

### Phase 5: Verification
- [ ] Ensure app runs: `python -m uvicorn src.main:app --reload`
- [ ] Test handler with sample events
- [ ] Verify all tests pass
- [ ] Document any special setup needed

## Key Differences from invoice_analyzer Example

| Aspect | Simple Event Processor | Invoice Analyzer |
|--------|----------------------|------------------|
| **Handlers** | 1 simple handler | Multiple handlers (validation, enrichment, invocation) |
| **AI/LLM** | None | Pydantic AI agent |
| **Complexity** | Minimal | Full-featured |
| **Use Case** | Learning/reference | Production invoice analysis |
| **Event Flow** | Event → Handler → Output | Event → Handler Chain → Agent → Output |

## Success Criteria
- ✅ App starts without errors
- ✅ Handler processes events correctly
- ✅ All tests pass
- ✅ Can be run with `docker-compose up` (if included)
- ✅ Clear documentation for users to understand the flow
- ✅ Serves as a learning example for new framework users
