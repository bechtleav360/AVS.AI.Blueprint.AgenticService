# REST Microservice Example

A RESTful microservice example demonstrating the Blueprint Agents framework used as a foundation for building REST APIs. No event handlers, no AI agents - just clean REST endpoints with proper structure.

## Features

- ✅ **RESTful API** - Clean REST endpoints with GET and POST methods
- ✅ **Framework Integration** - Uses Blueprint Agents framework foundation
- ✅ **Type-Safe** - Pydantic models for request/response validation
- ✅ **Service Layer** - Separation of concerns with business logic
- ✅ **Production-Ready** - Health checks and proper logging
- ✅ **Well-Tested** - Comprehensive test coverage

## Prerequisites

1. **Install the Blueprint Agents Framework**:

   ```bash
   pip install avs-blueprint-agents>=0.1.17
   ```

   Or install from the root repository in development mode:

   ```bash
   cd /path/to/Agents_Blueprint
   pip install -e .
   ```

2. **Python 3.13+**

## Getting Started

### 1. Install Dependencies

```bash
pip install -e .
```

### 2. Run the Service

```bash
python -m uvicorn src.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.

### 3. Access the API

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health/live
- **Root Endpoint**: http://localhost:8000/

## API Endpoints

### Calculate (GET)

Perform a calculation using query parameters.

```bash
curl "http://localhost:8000/api/calculate?a=5&b=3&operation=add"
```

**Response:**
```json
{
  "a": 5,
  "b": 3,
  "operation": "add",
  "result": 8,
  "error": null
}
```

### Calculate (POST)

Perform a calculation using JSON body.

```bash
curl -X POST http://localhost:8000/api/calculate \
  -H "Content-Type: application/json" \
  -d '{"a": 20, "b": 4, "operation": "divide"}'
```

**Response:**
```json
{
  "a": 20,
  "b": 4,
  "operation": "divide",
  "result": 5,
  "error": null
}
```

### Supported Operations

- `add` - Addition
- `subtract` - Subtraction
- `multiply` - Multiplication
- `divide` - Division (returns error if dividing by zero)

## Project Structure

```
rest_microservice/
├── src/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py           # REST API route definitions
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py          # Request/response schemas
│   └── services/
│       ├── __init__.py
│       └── calculator.py       # Business logic
├── tests/
│   ├── __init__.py
│   ├── test_routes.py          # Route tests
│   └── test_services.py        # Service tests
├── settings.toml               # Configuration
├── secrets.toml.example        # Secrets template
├── pyproject.toml              # Dependencies
└── README.md                   # This file
```

## Running Tests

```bash
pytest tests/ -v
```

## Configuration

Edit `settings.toml` to customize:
- App name and version
- Server host and port
- Logging level

## Key Differences from Other Examples

| Aspect | REST Microservice | Simple Event Processor | Invoice Analyzer |
|--------|------------------|----------------------|------------------|
| **Architecture** | REST API | Event-driven | Event-driven + AI |
| **Handlers** | None | 1 handler | Multiple handlers |
| **AI/LLM** | None | None | Pydantic AI agent |
| **Use Case** | REST API service | Event processing | Production invoice analysis |
| **Entry Point** | HTTP endpoints | Event queue | HTTP + Events |

## Extending the Example

To add more functionality:

1. **Add more endpoints**: Create new routes in `src/api/routes.py`
2. **Add more services**: Create new service classes in `src/services/`
3. **Add authentication**: Use FastAPI security utilities
4. **Add database**: Integrate with SQLAlchemy or similar
5. **Add caching**: Use Redis or similar for performance

## Troubleshooting

### Port already in use

```bash
python -m uvicorn src.main:app --port 8001
```

### Module not found errors

Ensure the framework is installed:

```bash
pip install -e .
```

### Tests failing

Make sure you're in the example directory and have installed dev dependencies:

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT License - See LICENSE file for details

## Support

For issues or questions about the framework, see the main [Blueprint Agents documentation](../../README.md).
