# API Reference

Complete API documentation for the Agent Blueprint.

## REST Endpoints

### Health Checks

**GET /actuators/health**
- Returns overall health status
- Response: `{"status": "healthy", "checks": {...}}`

**GET /actuators/health/liveness**
- Kubernetes liveness probe
- Response: `{"status": "alive"}`

**GET /actuators/health/readiness**
- Kubernetes readiness probe
- Response: `{"status": "ready"}`

### Event Processing

**POST /events/process**
- Processes CloudEvents
- Content-Type: `application/json`
- Body: CloudEvent format

### Custom Endpoints

See your `custom/src/api/rest.py` for custom endpoint documentation.

## CloudEvent Format

```json
{
  "specversion": "1.0",
  "type": "event.type",
  "source": "source-service",
  "id": "unique-id",
  "time": "2025-10-10T10:00:00Z",
  "datacontenttype": "application/json",
  "data": {
    // Your event data
  }
}
```

## Data Models

See `base/src/models/` and `custom/src/models/` for Pydantic model definitions.

---

For more details, see the auto-generated OpenAPI docs at `/docs` when running your agent.
