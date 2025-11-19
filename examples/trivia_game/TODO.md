# Trivia Game Example - Implementation Plan

## Overview
A RESTful trivia game API that uses an LLM agent to generate questions and evaluate answers. Demonstrates using the Blueprint Agents framework for REST-based AI applications without event handlers.

## Architecture
```
HTTP Request
    ↓
FastAPI Routes
    ↓
Trivia Service (uses LLM Agent)
    ↓
HTTP Response
```

## Implementation Plan

### Phase 1: Project Structure
- [ ] Create `src/` directory
  - [ ] `main.py` - FastAPI app entry point
  - [ ] `api/` - REST API endpoints
    - [ ] `__init__.py`
    - [ ] `routes.py` - Game API route definitions
  - [ ] `models/` - Data models
    - [ ] `__init__.py`
    - [ ] `schemas.py` - Request/response schemas
  - [ ] `services/` - Business logic
    - [ ] `__init__.py`
    - [ ] `trivia_service.py` - Game logic with LLM agent
- [ ] Create configuration files
  - [ ] `settings.toml` - App configuration
  - [ ] `secrets.toml.example` - Secrets template
  - [ ] `pyproject.toml` - Dependencies

### Phase 2: Core Implementation
- [ ] Create request/response schemas
  - [ ] `GameStartRequest` - Start new game
  - [ ] `GameQuestion` - Question response
  - [ ] `AnswerRequest` - Player answer
  - [ ] `AnswerResult` - Evaluation result
- [ ] Create Trivia Service with LLM Agent
  - [ ] Use Pydantic AI to create agent
  - [ ] Generate trivia questions
  - [ ] Evaluate player answers
  - [ ] Track score
- [ ] Create REST API routes
  - [ ] POST `/api/game/start` - Start new game
  - [ ] GET `/api/game/question` - Get current question
  - [ ] POST `/api/game/answer` - Submit answer
  - [ ] GET `/api/game/score` - Get current score

### Phase 3: Configuration & Setup
- [ ] Create `settings.toml` with:
  - [ ] App name and version
  - [ ] Server configuration
  - [ ] LLM model configuration
  - [ ] Logging settings
- [ ] Create `pyproject.toml` with:
  - [ ] Dependency on `avs-blueprint-agents`
  - [ ] Dev dependencies
- [ ] Create `.env.example` for environment variables

### Phase 4: Documentation & Testing
- [ ] Create `README.md` with:
  - [ ] Quick start instructions
  - [ ] API endpoint documentation
  - [ ] Example game flow
  - [ ] How to configure LLM
- [ ] Create `tests/` directory
  - [ ] `test_routes.py` - Route tests
  - [ ] `test_services.py` - Service tests
- [ ] Create `.env.example` for environment variables

### Phase 5: Verification
- [ ] Ensure app runs: `python -m uvicorn src.main:app --reload`
- [ ] Test game flow end-to-end
- [ ] Verify all tests pass
- [ ] Document any special setup needed

## Key Features

| Feature | Description |
|---------|-------------|
| **LLM Integration** | Uses Pydantic AI for intelligent question generation and answer evaluation |
| **REST API** | Clean HTTP endpoints for game interaction |
| **No Handlers** | Pure REST-based, no event-driven architecture |
| **Session Management** | Tracks game state and score |
| **Type Safety** | Pydantic models for all requests/responses |

## Success Criteria
- ✅ App starts without errors
- ✅ Game flow works end-to-end
- ✅ LLM generates reasonable questions
- ✅ Answer evaluation works correctly
- ✅ All tests pass
- ✅ Clear API documentation
- ✅ Serves as learning example for LLM integration
