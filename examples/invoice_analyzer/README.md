# Invoice Analyzer Example

This is an example implementation of the Blueprint Agents framework, demonstrating how to build an intelligent invoice analysis microservice using FastAPI and Pydantic AI.

## Features

- **Framework-Based**: Built on top of the `avs-blueprint-agents` package
- **Production-Ready**: Includes Docker support, telemetry, and event-driven processing
- **Event-Driven**: Processes events through a Chain of Responsibility pattern
- **Intelligent**: Uses Pydantic AI for intelligent invoice analysis
- **Modular**: Clean separation between framework and domain-specific logic

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

### 2. Configure Your Settings

Edit `settings.toml` and `secrets.toml` to configure:
- AI model provider (OpenAI, vLLM, etc.)
- Event publishing settings
- Observability/telemetry settings

### 3. Run the Service

**Option A: Direct Python**

```bash
python -m uvicorn src.main:app --reload
```

**Option B: Docker Compose**

```bash
docker-compose up --build
```

The API will be available at `http://localhost:8000`.

### 4. Access the API

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## Customizing the Blueprint

To adapt this blueprint for your own domain, follow these steps and look for the `FIXME` comments in the code:

1.  **Define Your Domain Models** (`src/models/domain.py`):
    -   Customize the `ResourceMetadata` model to represent the data your agent will process.
    -   Customize the `AgentOutput` model to represent the structured output of your agent.

2.  **Define Your Event Types** (`src/models/events.py`):
    -   Replace the example `EventType` enum members with the event types relevant to your domain.

3.  **Implement Your Business Logic** (`src/agent/logic.py`):
    -   Replace the placeholder functions in the `ProcessingLogic` class with your own stateless business logic.

4.  **Implement Your Agent's Tools** (`src/agent/tools.py`):
    -   Replace the example tools with your own tools that the Pydantic AI agent can use to perform actions.

5.  **Customize the Agent Runtime** (`src/agent/runtime.py`):
    -   Update the system prompt in the `GenericAgent` class to be specific to your agent's purpose.
    -   Customize the `ProcessingContext` to include any additional data your agent needs.

6.  **Implement Your Decision Handlers** (`src/agent/decision.py`):
    -   Customize the `ValidationHandler`, `EnrichmentHandler`, and `ProcessingHandler` to implement your event processing workflow.

7.  **Configure Your Service** (`src/config.py`):
    -   Add your own configuration settings and validators.

8.  **Update the Main Application** (`src/main.py`):
    -   Add any additional endpoints or middleware your service requires.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
