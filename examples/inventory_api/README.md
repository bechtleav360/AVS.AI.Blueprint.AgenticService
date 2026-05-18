# Inventory API

A pure REST API microservice built with the Blueprint Agents framework. Demonstrates CRUD operations for product inventory management with no events and no LLM -- just a clean, cacheable REST API.

## What it demonstrates

- **RestApiBase** subclass with decorated route methods (`@RestApiBase.get`, `@RestApiBase.post`, etc.)
- **ServiceBase** subclass for business logic with in-memory storage
- **Cache integration** via `.with_cache()` for frequently accessed products
- **Pydantic models** for request/response validation
- Standard AppBuilder wiring pattern

## Setup

```bash
pip install -e .
```

## Running

Using the ASBS CLI:

```bash
asbs dev
```

Or directly with uvicorn:

```bash
uvicorn src.main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Example curl commands

**Create a product:**

```bash
curl -X POST http://localhost:8000/api/products \
  -H "Content-Type: application/json" \
  -d '{"name": "Widget", "description": "A useful widget", "price": 9.99, "stock": 100, "category": "tools"}'
```

**List all products:**

```bash
curl http://localhost:8000/api/products
```

**Filter by category:**

```bash
curl http://localhost:8000/api/products?category=tools
```

**Search products:**

```bash
curl http://localhost:8000/api/products/search?q=widget
```

**Get a single product:**

```bash
curl http://localhost:8000/api/products/{product_id}
```

**Update a product:**

```bash
curl -X PUT http://localhost:8000/api/products/{product_id} \
  -H "Content-Type: application/json" \
  -d '{"price": 12.99}'
```

**Adjust stock:**

```bash
curl -X PATCH http://localhost:8000/api/products/{product_id}/stock \
  -H "Content-Type: application/json" \
  -d '{"quantity": -5}'
```

**Delete a product:**

```bash
curl -X DELETE http://localhost:8000/api/products/{product_id}
```
