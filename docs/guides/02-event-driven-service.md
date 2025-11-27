# Guide: Build an Event-Driven Service

**Goal:** Add event handlers and Dapr pub/sub for message processing.

**Time:** 30 minutes | **Difficulty:** Intermediate

**Prerequisites:** Complete [Simple REST API](01-simple-rest-api.md) guide first.

---

## What You'll Build

A user service that:
1. Receives `user.created` events from RabbitMQ (via Dapr)
2. Processes the user with a handler
3. Publishes `user.processed` events
4. Exposes REST endpoints to create users

---

## Step 1: Install Dapr

Follow the [Dapr installation guide](https://docs.dapr.io/getting-started/install-dapr-cli/).

Verify installation:
```bash
dapr --version
```

---

## Step 2: Create Event Models

**File:** `src/models.py`

```python
from pydantic import BaseModel

class UserCreatedEvent(BaseModel):
    """Event when a user is created."""
    email: str
    name: str

class UserProcessedEvent(BaseModel):
    """Event when a user is processed."""
    email: str
    status: str
```

---

## Step 3: Create an Event Handler

**File:** `src/handlers.py`

```python
from blueprint.agents import EventHandler, HandlerResult
from cloudevents.http import CloudEvent
from .models import UserCreatedEvent, UserProcessedEvent

class UserHandler(EventHandler):
    """Handle user.created events."""

    async def can_handle_event(self, event: CloudEvent, context) -> bool:
        """Check if this handler can process the event."""
        return event.get_type() == "user.created"

    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        """Process the user.created event."""
        # Parse event data
        data = event.get_data()
        user_event = UserCreatedEvent(**data)

        # Get service from registry
        service = self._component_registry.get_service("user_service")

        # Process user
        result = await service.process_user(user_event.email, user_event.name)

        # Publish new event
        return HandlerResult(
            event_type="user.processed",
            data=UserProcessedEvent(
                email=user_event.email,
                status="processed"
            ).model_dump()
        )
```

---

## Step 4: Update Your Service

**File:** `src/services.py`

```python
from blueprint.agents import BusinessService

class UserService(BusinessService):
    """User business logic."""

    async def process_user(self, email: str, name: str) -> dict:
        """Process a user."""
        # Your database logic here
        return {
            "email": email,
            "name": name,
            "processed_at": "2025-11-26T20:00:00Z"
        }
```

---

## Step 5: Update Your Main Application

**File:** `src/main.py`

```python
from pathlib import Path
from blueprint.agents import AppBuilder, Config
from .api import UserRestApi
from .services import UserService
from .handlers import UserHandler

config = Config(
    settings_files=["settings.toml"],
    root_path=Path(__file__).parent.parent,
)

app = (
    AppBuilder(config)
    .with_handler(UserHandler)  # Add handler
    .with_service(UserService())
    .with_rest_api(UserRestApi())
    .build()
)
```

---

## Step 6: Configure Dapr

**File:** `dapr/components/pubsub.yaml`

```yaml
apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: pubsub
spec:
  type: pubsub.rabbitmq
  version: v1
  metadata:
  - name: host
    value: "localhost"
  - name: port
    value: "5672"
  - name: durable
    value: "true"
```

---

## Step 7: Configure Subscriptions

**File:** `dapr/components/subscription.yaml`

```yaml
apiVersion: dapr.io/v1alpha1
kind: Subscription
metadata:
  name: user-subscription
spec:
  pubsubname: pubsub
  topic: user.created
  route: /dapr/subscribe/user.created
  deadLetterTopic: user.created.deadletter
```

---

## Step 8: Update Settings

**File:** `settings.toml`

```toml
[default]
app_name = "user-service"
log_level = "INFO"

[default.event_publishing]
enabled = true
dapr_http_port = 3500

[[default.event_publishing.topic_mapping]]
topic = "user.created"
subscription_path = "/dapr/subscribe/user.created"

[[default.event_publishing.topic_mapping]]
topic = "user.processed"
```

---

## Step 9: Run with Dapr

Start Dapr sidecar:
```bash
dapr run --app-id user-service \
  --app-port 8000 \
  --dapr-http-port 3500 \
  --resources-path ./dapr/components \
  uvicorn src.main:app --reload
```

---

## Step 10: Test Event Flow

Publish an event:
```bash
curl -X POST http://localhost:3500/v1.0/publish/pubsub/user.created \
  -H "Content-Type: application/json" \
  -d '{
    "email": "john@example.com",
    "name": "John Doe"
  }'
```

Check logs to see the handler process the event and publish `user.processed`.

---

## Key Concepts

- **EventHandler** — Process incoming events with `can_handle_event()` and `handle_event()`
- **HandlerResult** — Return this to publish a new event
- **Chain of Responsibility** — Handlers process events in priority order
- **Dapr** — Handles pub/sub communication (RabbitMQ, Kafka, etc.)
- **CloudEvent** — Standard event format for all events

---

## Debugging

Enable debug logs in `settings.toml`:
```toml
log_level = "DEBUG"
```

Use VS Code debugger:
1. Set breakpoint in your handler
2. Launch "FastAPI: custom-service with Dapr" configuration
3. Press F5

---

## What's Next?

- Ready for AI? → [AI Agent Service](03-ai-agent-service.md)
- Need help? → [Troubleshooting](../troubleshooting.md)
