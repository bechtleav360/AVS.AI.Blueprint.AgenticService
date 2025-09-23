# Generic Agent Service Blueprint

This repository provides a generic, production-ready blueprint for building intelligent, event-driven microservices using Python, FastAPI, and Pydantic AI. The blueprint is designed to be easily extensible and customizable for any domain.

## Features

- **Generic and Extensible**: Easily adapt the blueprint to your specific domain by customizing the models, logic, and tools.
- **Production-Ready**: Includes a multi-stage Dockerfile, docker-compose for local development, and a comprehensive telemetry setup with OpenTelemetry.
- **Event-Driven**: Built around a Chain of Responsibility pattern for processing events, with support for both thin and fat event envelopes.
- **Intelligent**: Integrated with Pydantic AI to enable intelligent processing and decision-making.
- **Modular Architecture**: A clean and modular architecture that separates concerns, making the codebase easy to understand, maintain, and extend.

## Project Structure

The project is organized into a `src` directory containing the core application logic, with each module designed to be generic and reusable:

- `main.py`: The main entry point for the FastAPI application.
- `agent/`: The core agent logic, including:
  - `runtime.py`: The generic Pydantic AI agent runtime.
  - `decision.py`: The Chain of Responsibility decision engine.
  - `logic.py`: Pure, stateless business logic functions.
  - `tools.py`: Tools for the Pydantic AI agent.
- `models/`: Pydantic models for events and domain-specific data.
  - `events.py`: Generic models for thin and fat event envelopes.
  - `domain.py`: Domain-specific models like `ResourceMetadata` and `AgentOutput`.
- `config.py`: Configuration management using Dynaconf.
- `telemetry.py`: OpenTelemetry setup and configuration.

## Getting Started

### Prerequisites

- Docker and Docker Compose

### Running Locally

1.  **Clone the repository**:

    ```bash
    git clone <repository-url>
    cd agent
    ```

2.  **Run the service with Docker Compose**:

    ```bash
    docker-compose up --build
    ```

This will build the Docker image and start the agent service. The API will be available at `http://localhost:8000`.

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
