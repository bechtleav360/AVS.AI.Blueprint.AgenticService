# REST API Design Explanation

## Overview

This document explains the design decisions in `rest.py`, specifically addressing:
1. Why `process_resource` is needed
2. Why `_process_resource` is private
3. How to use Pydantic models for all requests and responses

---

## 1. Why is `process_resource` needed?

### The Problem

FastAPI requires route handlers to be defined at the time the router is created. However, our `RestApi` class is **generic** and needs to work with different payload types for different agent implementations.

### The Solution: Closure Pattern

```python
def _register_routes(self) -> None:
    @self.router.post("/process-resource", response_model=ProcessResourceResponse)
    async def process_resource(
        request: Request,
        payload: self.payload_type = Body(...),  # ← Uses the generic type
    ) -> ProcessResourceResponse:
        return await self._process_resource(request, payload)
```

**Why this is needed:**

1. **Generic Type Binding**: The closure captures `self.payload_type` at initialization time, allowing FastAPI to generate the correct OpenAPI schema for each agent's specific payload model.

2. **FastAPI Decorator Requirement**: FastAPI's `@router.post()` decorator needs a function, not a method. The closure provides this function while maintaining access to instance state.

3. **Type Safety**: This pattern ensures that FastAPI validates incoming requests against the correct Pydantic model for each agent implementation.

### Example Usage

```python
# Agent A uses InvoicePayload
class InvoicePayload(BaseModel):
    invoice_id: str
    amount: float

invoice_api = RestApi(payload_type=InvoicePayload, registry=registry)

# Agent B uses AssetPayload
class AssetPayload(BaseModel):
    asset_id: str
    tenant_id: str

asset_api = RestApi(payload_type=AssetPayload, registry=registry)
```

Each instance generates different OpenAPI schemas based on its `payload_type`.

---

## 2. Why is `_process_resource` private?

### Design Principles

The underscore prefix (`_process_resource`) indicates this is an **internal implementation method** that should not be called directly by external code.

### Reasons for Privacy:

1. **Encapsulation**: The public interface is the HTTP endpoint (`POST /process-resource`), not the Python method. External callers should use HTTP, not direct method calls.

2. **Separation of Concerns**:
   - `process_resource` (public closure): Handles FastAPI integration, routing, and schema generation
   - `_process_resource` (private method): Contains business logic, error handling, and processing

3. **Testing Flexibility**: Tests can still access `_process_resource` if needed (Python doesn't enforce privacy), but the underscore signals "internal use only."

4. **Future Refactoring**: Marking it private allows internal changes without breaking external contracts.

### Pattern Comparison

```python
# ✅ Current Design (Recommended)
def _register_routes(self):
    @self.router.post("/process-resource")
    async def process_resource(request, payload):
        return await self._process_resource(request, payload)  # Delegates to private method

# ❌ Alternative (Not Recommended)
def _register_routes(self):
    self.router.add_api_route(
        "/process-resource",
        self.process_resource,  # Direct method reference
        methods=["POST"]
    )
```

The current design is preferred because:
- It allows the closure to capture `self.payload_type` for proper type hints
- It keeps the implementation method private
- It provides better separation between routing and business logic

---

## 3. Using Pydantic Models for All Requests and Responses

### Current State

**Responses**: Already use Pydantic models ✅
- `ProcessResourceResponse` (defined in `models/api.py`)
- `JSONResponse` for errors (RFC 7807 Problem Details)

**Requests**: Use generic `PayloadT` (a TypeVar bound to `BaseModel`) ✅

### Adding a Standard Request Model

To provide a concrete base model for common use cases, we can add a `ProcessResourceRequest` model:

```python
# In models/api.py
class ProcessResourceRequest(BaseModel):
    """Standard request model for resource processing endpoints."""
    
    resource_id: str = Field(
        ...,
        description="Unique identifier for the resource to process",
        examples=["res-12345"]
    )
    tenant_id: Optional[str] = Field(
        None,
        description="Tenant identifier for multi-tenant scenarios",
        examples=["tenant-42"]
    )
    operation: Optional[str] = Field(
        None,
        description="Operation to perform on the resource",
        examples=["analyze", "validate", "transform"]
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters for the operation"
    )
    
    model_config = ConfigDict(
        extra="allow",  # Allow additional fields for extensibility
        json_schema_extra={
            "example": {
                "resource_id": "invoice-789",
                "tenant_id": "tenant-42",
                "operation": "analyze",
                "parameters": {
                    "include_details": True,
                    "language": "en"
                }
            }
        }
    )
```

### Usage Patterns

#### Pattern 1: Use the Standard Model
```python
from base.src.api.rest import RestApi
from base.src.models.api import ProcessResourceRequest

# Use the standard request model
api = RestApi(payload_type=ProcessResourceRequest, registry=registry)
```

#### Pattern 2: Extend the Standard Model
```python
class InvoiceProcessRequest(ProcessResourceRequest):
    """Invoice-specific processing request."""
    invoice_number: str = Field(..., description="Invoice number")
    amount: Decimal = Field(..., description="Invoice amount")

api = RestApi(payload_type=InvoiceProcessRequest, registry=registry)
```

#### Pattern 3: Create a Custom Model
```python
class CustomPayload(BaseModel):
    """Completely custom payload for specialized agents."""
    custom_field: str
    another_field: int

api = RestApi(payload_type=CustomPayload, registry=registry)
```

---

## 4. Complete Request/Response Flow

### Request Flow with Pydantic Validation

```
1. Client sends JSON → FastAPI receives request
                    ↓
2. FastAPI validates against payload_type (Pydantic model)
                    ↓
3. If valid: calls process_resource(request, payload)
   If invalid: returns 422 Unprocessable Entity
                    ↓
4. process_resource delegates to _process_resource
                    ↓
5. _process_resource calls ProcessingService
                    ↓
6. Returns ProcessResourceResponse (Pydantic model)
                    ↓
7. FastAPI serializes to JSON and returns to client
```

### Error Responses (RFC 7807 Problem Details)

All errors return a standardized format:

```json
{
  "type": "about:blank",
  "title": "Internal Server Error",
  "status": 500,
  "detail": "Processing failed: database connection timeout",
  "instance": "/api/process-resource",
  "traceId": "9f2c1f2e-09d8-4d0d-9b6f-2f6fef2ad87a"
}
```

This is implemented via `_build_problem_details()` method.

---

## 5. Best Practices

### ✅ DO:
- Define domain-specific request models that extend `ProcessResourceRequest`
- Use Pydantic's `Field()` for documentation and validation
- Include examples in `model_config` for OpenAPI documentation
- Use `extra="allow"` for extensibility when appropriate
- Return `ProcessResourceResponse` for successful operations
- Return RFC 7807 Problem Details for errors

### ❌ DON'T:
- Call `_process_resource` directly from external code
- Use plain dictionaries instead of Pydantic models
- Hardcode payload types in the `RestApi` class
- Skip validation by using `Any` types
- Return inconsistent response formats

---

## 6. Migration Path

If you have existing code using dictionaries or untyped payloads:

### Before:
```python
@router.post("/process")
async def process(data: dict):  # ❌ No validation
    return {"success": True}
```

### After:
```python
class MyRequest(ProcessResourceRequest):
    # Add your specific fields
    pass

api = RestApi(payload_type=MyRequest, registry=registry)
# Endpoint automatically created with validation ✅
```

---

## Summary

- **`process_resource`**: Required for FastAPI's closure pattern with generic types
- **`_process_resource`**: Private implementation method for business logic
- **Pydantic models**: Used for both requests (via `payload_type`) and responses (`ProcessResourceResponse`)
- **Pattern**: Extend `ProcessResourceRequest` for domain-specific needs
- **Error handling**: RFC 7807 Problem Details format for consistency
