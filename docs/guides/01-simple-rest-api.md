# Guide: Build a Simple REST API

**Goal:** Create a web service with just REST endpoints (no event handlers, no AI agents).

**Time:** 15 minutes | **Difficulty:** Beginner

---

## What You'll Build

A calculator API with two endpoints:
- `POST /api/calculate/add` — Add two numbers
- `POST /api/calculate/multiply` — Multiply two numbers

---

## Step 1: Create Your Project Structure

```
my-calculator/
├── src/
│   ├── main.py
│   ├── api.py
│   └── services.py
├── settings.toml
└── requirements.txt
```

---

## Step 2: Install Dependencies

```bash
pip install fastapi uvicorn blueprint-agents pydantic
```

---

## Step 3: Define Your Service

**File:** `src/services.py`

```python
from blueprint.agents import BusinessService

class CalculatorService(BusinessService):
    """Simple calculator service."""

    async def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        return a + b

    async def multiply(self, a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b
```

---

## Step 4: Define Your REST API

**File:** `src/api.py`

```python
from pydantic import BaseModel
from blueprint.agents import RestApi

class CalculateRequest(BaseModel):
    a: float
    b: float

class CalculateResponse(BaseModel):
    result: float

class CalculatorRestApi(RestApi):
    """Calculator REST API."""

    async def on_startup(self):
        """Called when service starts."""
        pass

    async def on_shutdown(self):
        """Called when service stops."""
        pass

    def _register_routes(self):
        """Register API endpoints."""

        @self.router.post("/add", response_model=CalculateResponse)
        async def add(request: CalculateRequest):
            service = self._component_registry.get_service("calculator")
            result = await service.add(request.a, request.b)
            return CalculateResponse(result=result)

        @self.router.post("/multiply", response_model=CalculateResponse)
        async def multiply(request: CalculateRequest):
            service = self._component_registry.get_service("calculator")
            result = await service.multiply(request.a, request.b)
            return CalculateResponse(result=result)
```

---

## Step 5: Create Your Main Application

**File:** `src/main.py`

```python
from pathlib import Path
from blueprint.agents import AppBuilder, Config
from .api import CalculatorRestApi
from .services import CalculatorService

# Load configuration
config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent.parent,
)

# Build the app
app = (
    AppBuilder(config)
    .with_service(CalculatorService())
    .with_rest_api(CalculatorRestApi())
    .build()
)
```

---

## Step 6: Configure Your Settings

**File:** `settings.toml`

```toml
[default]
app_name = "calculator-api"
app_description = "Simple calculator REST API"
log_level = "INFO"
```

---

## Step 7: Run Your Service

```bash
uvicorn src.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` to see the interactive API documentation.

---

## Step 8: Test Your API

```bash
# Add two numbers
curl -X POST http://localhost:8000/api/add \
  -H "Content-Type: application/json" \
  -d '{"a": 5, "b": 3}'

# Response: {"result": 8}

# Multiply two numbers
curl -X POST http://localhost:8000/api/multiply \
  -H "Content-Type: application/json" \
  -d '{"a": 5, "b": 3}'

# Response: {"result": 15}
```

---

## Key Concepts

- **RestApi** — Define custom endpoints by extending this class
- **BusinessService** — Keep business logic separate from API routes
- **AppBuilder** — Fluent interface to wire everything together
- **Component Registry** — Access services from your API routes

---

## What's Next?

- Ready for events? → [Event-Driven Service](02-event-driven-service.md)
- Ready for AI? → [AI Agent Service](03-ai-agent-service.md)
- Need help? → [Troubleshooting](../troubleshooting.md)
