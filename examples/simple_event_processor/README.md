# Simple Event Processor Example

A minimal, runnable example demonstrating the Blueprint Agents framework with just an event handler (no AI agent). Perfect for understanding the core event processing pipeline.

## Features

- ✅ **Single Event Handler** - Simple event processor without AI
- ✅ **Framework Integration** - Uses Blueprint Agents framework
- ✅ **Type-Safe** - Pydantic models for events and results
- ✅ **Minimal Dependencies** - Only depends on the framework
- ✅ **Production-Ready** - Health checks and proper logging

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
- **Health Check**: http://localhost:8000/health
- **Info Endpoint**: http://localhost:8000/info

## How It Works

### Architecture

```
Event Input
    ↓
SimpleProcessorHandler
    ↓
Process Event
    ↓
Return Result
```

### The Handler

The `SimpleProcessorHandler` class:
1. Checks if it can handle the event (event type == "data.received")
2. Parses the event data
3. Performs simple processing (echoes data with metadata)
4. Returns a `ProcessedResult`

### Example Event

```json
{
  "event_id": "evt-123",
  "event_type": "data.received",
  "source": "api",
  "data": {
    "key1": "value1",
    "key2": "value2"
  },
  "timestamp": "2025-11-19T20:00:00Z"
}
```

### Example Result

```json
{
  "event_id": "evt-123",
  "status": "success",
  "message": "Successfully processed event from api",
  "processed_data": {
    "original_data": {
      "key1": "value1",
      "key2": "value2"
    },
    "processed_at": "2025-11-19T20:00:00Z",
    "source": "api",
    "item_count": 2
  },
  "error": null
}
```

## Project Structure

```
simple_event_processor/
├── src/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── simple_handler.py   # Event handler implementation
│   └── models/
│       ├── __init__.py
│       └── events.py           # Event models
├── tests/
│   ├── __init__.py
│   ├── test_handler.py         # Handler tests
│   └── test_app.py             # App endpoint tests
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
- Event publishing settings

## Extending the Example

To add more functionality:

1. **Add more handlers**: Create new handler classes in `src/handlers/`
2. **Add more event types**: Update `can_handle_event()` logic
3. **Add processing logic**: Enhance the `handle_event()` method
4. **Add persistence**: Integrate with a database
5. **Add AI**: Use Pydantic AI for intelligent processing (see invoice_analyzer example)

## Comparison with Other Examples

| Aspect | Simple Event Processor | Invoice Analyzer |
|--------|----------------------|------------------|
| **Handlers** | 1 simple handler | Multiple handlers |
| **AI/LLM** | None | Pydantic AI agent |
| **Complexity** | Minimal | Full-featured |
| **Use Case** | Learning/reference | Production invoice analysis |

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
