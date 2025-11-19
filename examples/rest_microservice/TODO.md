# RESTful Microservice Example - Implementation Plan

## Overview
A RESTful microservice example demonstrating the Blueprint Agents framework used as a foundation for building REST APIs. No event handlers, no AI agents - just clean REST endpoints with proper structure.

## Architecture
```
HTTP Request
    ↓
FastAPI Routes
    ↓
Service Logic
    ↓
HTTP Response
```

## Implementation Plan

### Phase 1: Project Structure
- [ ] Create `src/` directory
  - [ ] `main.py` - FastAPI app entry point
  - [ ] `api/` - REST API endpoints
    - [ ] `__init__.py`
    - [ ] `routes.py` - API route definitions
  - [ ] `models/` - Data models
    - [ ] `__init__.py`
    - [ ] `schemas.py` - Request/response schemas
  - [ ] `services/` - Business logic
    - [ ] `__init__.py`
    - [ ] `calculator.py` - Example service
- [ ] Create configuration files
  - [ ] `settings.toml` - App configuration
  - [ ] `secrets.toml.example` - Secrets template
  - [ ] `pyproject.toml` - Dependencies

### Phase 2: Core Implementation
- [ ] Create request/response schemas
  - [ ] `CalculationRequest` - Input model
  - [ ] `CalculationResult` - Output model
- [ ] Create service layer
  - [ ] `CalculatorService` - Business logic
  - [ ] Methods for basic operations (add, subtract, multiply, divide)
- [ ] Create REST API routes
  - [ ] GET `/api/calculate` - Perform calculation
  - [ ] GET `/api/health` - Health check (framework provides)
  - [ ] GET `/` - Root endpoint (framework provides)

### Phase 3: Configuration & Setup
- [ ] Create `settings.toml` with:
  - [ ] App name and version
  - [ ] Server configuration
  - [ ] Logging settings
- [ ] Create `pyproject.toml` with:
  - [ ] Dependency on `avs-blueprint-agents`
  - [ ] Dev dependencies
- [ ] Create `docker-compose.yml` (optional)

### Phase 4: Documentation & Testing
- [ ] Create `README.md` with:
  - [ ] Quick start instructions
  - [ ] API endpoint documentation
  - [ ] Example requests/responses
- [ ] Create `tests/` directory
  - [ ] `test_routes.py` - Route tests
  - [ ] `test_services.py` - Service tests
- [ ] Create `.env.example` for environment variables

### Phase 5: Verification
- [ ] Ensure app runs: `python -m uvicorn src.main:app --reload`
- [ ] Test all endpoints with curl or Postman
- [ ] Verify all tests pass
- [ ] Document any special setup needed

## Key Differences from Other Examples

| Aspect | REST Microservice | Simple Event Processor | Invoice Analyzer |
|--------|------------------|----------------------|------------------|
| **Architecture** | REST API | Event-driven | Event-driven + AI |
| **Handlers** | None | 1 handler | Multiple handlers |
| **AI/LLM** | None | None | Pydantic AI agent |
| **Use Case** | REST API service | Event processing | Production invoice analysis |
| **Entry Point** | HTTP endpoints | Event queue | HTTP + Events |

## Success Criteria
- ✅ App starts without errors
- ✅ All REST endpoints work correctly
- ✅ All tests pass
- ✅ Clear API documentation
- ✅ Serves as a learning example for REST API usage
- ✅ Shows how to use framework for non-event-driven apps
