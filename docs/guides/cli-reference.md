# CLI Reference - asbs

**asbs** (Agentic Service Blueprint System) is the unified command-line interface for the Blueprint Agents framework.

## Installation

```bash
pip install avs-blueprint-agents
```

This installs the `asbs` command globally.

## Command Overview

```bash
asbs -h                          # Show help
asbs setup <name>                # Create new project
asbs create <component> <name>   # Scaffold components
asbs windsurf                    # Generate Windsurf files
asbs validate                    # Validate project structure
asbs dev                         # Start development server
```

---

## asbs setup

Create a new Blueprint Agents project with complete structure.

### Usage

```bash
asbs setup PROJECT_NAME [OPTIONS]
```

### Arguments

- `PROJECT_NAME` - Name of the project (e.g., `invoice-processor`)

### Options

- `--output-dir DIR` - Parent directory (default: current directory)
- `--overwrite` - Overwrite existing files
- `--verbose`, `-v` - Enable verbose logging

### Examples

```bash
# Create project in current directory
asbs setup my-agent

# Create in specific location
asbs setup my-agent --output-dir ~/projects

# Overwrite existing files
asbs setup my-agent --overwrite

# Verbose output
asbs setup my-agent -v
```

### What Gets Created

```
my-agent/
├── src/
│   ├── api/routes.py
│   ├── handlers/my_handler.py
│   ├── services/my_service.py
│   ├── models/schemas.py
│   ├── prompts/system.prompt
│   └── main.py
├── tests/test_my_handler.py
├── settings.toml
├── secrets.toml.example
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── README.md
```

### Next Steps

```bash
cd my-agent
cp secrets.toml.example secrets.toml
# Edit secrets.toml with API keys
pip install -e .
asbs dev
```

---

## asbs create

Scaffold individual components in an existing project.

### Subcommands

- `asbs create handler` - Create EventHandler
- `asbs create service` - Create BusinessService
- `asbs create api` - Create RestApi
- `asbs create agent` - Create AgentRuntime
- `asbs create scheduler` - Create Scheduler

---

### asbs create handler

Create a new EventHandler for processing CloudEvents.

#### Usage

```bash
asbs create handler NAME [OPTIONS]
```

#### Arguments

- `NAME` - Handler name (e.g., `OrderPlaced`)

#### Options

- `--event-type TYPE` - Event type to handle (e.g., `order.placed`)
- `--priority NUM` - Handler priority (default: 10)
- `--output-dir DIR` - Output directory (default: `src/handlers`)

#### Examples

```bash
# Create handler (will prompt for event type)
asbs create handler OrderPlaced

# Create with event type
asbs create handler OrderPlaced --event-type order.placed

# Create with custom priority
asbs create handler OrderPlaced --event-type order.placed --priority 20

# Create in custom directory
asbs create handler OrderPlaced --output-dir src/custom_handlers
```

#### Generated File

Creates `src/handlers/order_placed_handler.py`:

```python
class OrderPlacedHandler(EventHandler):
    def __init__(self) -> None:
        super().__init__(name="OrderPlacedHandler", priority=10)

    async def can_handle_event(self, event, context) -> bool:
        return event.type == "order.placed"

    async def handle_event(self, event, context) -> HandlerResult | None:
        # Your logic here
        pass
```

---

### asbs create service

Create a new BusinessService for domain logic.

#### Usage

```bash
asbs create service NAME [OPTIONS]
```

#### Arguments

- `NAME` - Service name (e.g., `Invoice`)

#### Options

- `--output-dir DIR` - Output directory (default: `src/services`)

#### Examples

```bash
# Create service
asbs create service Invoice

# Create in custom directory
asbs create service Invoice --output-dir src/domain
```

#### Generated File

Creates `src/services/invoice_service.py`:

```python
class InvoiceService(BusinessService):
    def __init__(self) -> None:
        super().__init__("invoice_service")

    async def on_startup(self) -> None:
        # Initialize dependencies
        pass
```

---

### asbs create api

Create a new RestApi with FastAPI routes.

#### Usage

```bash
asbs create api NAME [OPTIONS]
```

#### Arguments

- `NAME` - API name (e.g., `Orders`)

#### Options

- `--output-dir DIR` - Output directory (default: `src/api`)

#### Examples

```bash
# Create API
asbs create api Orders

# Create in custom directory
asbs create api Orders --output-dir src/rest
```

#### Generated File

Creates `src/api/orders_api.py`:

```python
class OrdersApi(RestApi):
    def __init__(self) -> None:
        super().__init__(name="OrdersApi")

    @RestApi.get("/orders")
    async def list_orders(self) -> list[Order]:
        return await self._service.list_all()
```

---

### asbs create agent

Create a new AgentRuntime backed by pydantic-ai.

#### Usage

```bash
asbs create agent NAME [OPTIONS]
```

#### Arguments

- `NAME` - Agent name (e.g., `InvoiceAnalyzer`)

#### Options

- `--output-dir DIR` - Output directory (default: `src/agents`)

#### Examples

```bash
# Create agent
asbs create agent InvoiceAnalyzer

# Create in custom directory
asbs create agent InvoiceAnalyzer --output-dir src/ai
```

#### Generated File

Creates `src/agents/invoice_analyzer_agent.py`:

```python
def build_invoice_analyzer_agent(config: Config) -> AgentRuntime:
    """Build InvoiceAnalyzer agent."""
    return (
        AgentBuilder(config, runtime_name="invoice_analyzer")
        .with_model_from_config()
        .with_system_prompt()
        .build()
    )
```

---

### asbs create scheduler

Create a new Scheduler for background tasks.

#### Usage

```bash
asbs create scheduler NAME [OPTIONS]
```

#### Arguments

- `NAME` - Scheduler name (e.g., `DailyCleanup`)

#### Options

- `--cron EXPR` - Cron expression (default: `0 * * * *`)
- `--output-dir DIR` - Output directory (default: `src/schedulers`)

#### Examples

```bash
# Create scheduler (runs every hour)
asbs create scheduler DailyCleanup

# Create with custom cron
asbs create scheduler DailyCleanup --cron "0 0 * * *"

# Create in custom directory
asbs create scheduler DailyCleanup --output-dir src/jobs
```

#### Generated File

Creates `src/schedulers/daily_cleanup_scheduler.py`:

```python
class DailyCleanupScheduler(Scheduler):
    def __init__(self) -> None:
        super().__init__(crontab="0 * * * *", name="DailyCleanupScheduler")

    async def tick(self) -> None:
        # Your scheduled logic here
        pass
```

---

## asbs windsurf

Generate Windsurf IDE integration files (.windsurf/ directory).

### Usage

```bash
asbs windsurf [OUTPUT_DIR] [OPTIONS]
```

### Arguments

- `OUTPUT_DIR` - Project root directory (default: current directory)

### Options

- `--overwrite` - Overwrite existing files
- `--verbose`, `-v` - Enable verbose logging

### Examples

```bash
# Generate in current directory
asbs windsurf

# Generate in specific directory
asbs windsurf /path/to/project

# Overwrite existing files
asbs windsurf --overwrite

# Verbose output
asbs windsurf -v
```

### What Gets Created

```
.windsurf/
├── rules/
│   ├── architecture-conventions.md
│   ├── code-style-quality.md
│   ├── security-error-handling.md
│   ├── testing-conventions.md
│   └── strict-oop.md
├── workflows/
│   ├── create-agent-runtime.md
│   ├── create-business-service.md
│   ├── create-event-handler.md
│   ├── create-rest-api.md
│   └── create-scheduler.md
└── README.md
```

### Usage in Windsurf IDE

Once generated:
- **Rules** provide automatic context to Cascade
- **Workflows** are available as slash commands (e.g., `/create-handler`)

---

## asbs validate

Validate project structure and configuration.

### Usage

```bash
asbs validate [PROJECT_DIR]
```

### Arguments

- `PROJECT_DIR` - Project directory to validate (default: current directory)

### Examples

```bash
# Validate current directory
asbs validate

# Validate specific project
asbs validate /path/to/project
```

### What Gets Checked

- ✓ Required directories (`src/`, `tests/`)
- ✓ Configuration files (`settings.toml`, `pyproject.toml`)
- ✓ Entry point (`src/main.py`)
- ✓ AppBuilder usage
- ✓ Component directories
- ✓ Test files
- ✓ Docker files

### Output

```
Validating Blueprint Agents project: /path/to/project

✓ Found src/
✓ Found tests/
✓ Found settings.toml
✓ Found pyproject.toml
✓ Found src/main.py
✓ Found src/handlers/
✓ Found 3 test file(s)

============================================================
✓ Validation passed! Project structure looks good.
```

---

## asbs dev

Start development server with hot reload.

### Usage

```bash
asbs dev [OPTIONS]
```

### Options

- `--port PORT` - Port to run on (default: 8000)
- `--host HOST` - Host to bind to (default: 127.0.0.1)

### Examples

```bash
# Start on default port 8000
asbs dev

# Start on custom port
asbs dev --port 3000

# Bind to all interfaces
asbs dev --host 0.0.0.0

# Custom host and port
asbs dev --host 0.0.0.0 --port 8080
```

### Requirements

- Must be run from project root (where `src/main.py` exists)
- Requires `uvicorn` (installed with framework)

### Output

```
Starting development server on 127.0.0.1:8000
Press Ctrl+C to stop

INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

---

## Common Workflows

### Starting a New Project

```bash
# 1. Create project
asbs setup invoice-processor

# 2. Navigate and configure
cd invoice-processor
cp secrets.toml.example secrets.toml
# Edit secrets.toml

# 3. Install and run
pip install -e .
asbs dev
```

### Adding Components

```bash
# Add handler
asbs create handler InvoiceReceived --event-type invoice.received

# Add service
asbs create service InvoiceProcessor

# Add API
asbs create api Invoices

# Add agent
asbs create agent InvoiceAnalyzer

# Add scheduler
asbs create scheduler DailyReport --cron "0 6 * * *"
```

### Generating Windsurf Files

```bash
# In your project
asbs windsurf

# Update existing files
asbs windsurf --overwrite
```

### Validating Project

```bash
# Check structure
asbs validate

# Fix any issues, then validate again
asbs validate
```

---

## Troubleshooting

### Command Not Found

```bash
# Verify installation
pip show avs-blueprint-agents

# Reinstall if needed
pip install --force-reinstall avs-blueprint-agents

# Check PATH
which asbs
```

### Permission Errors

```bash
# Use virtual environment
python -m venv .venv
source .venv/bin/activate
pip install avs-blueprint-agents
```

### File Already Exists

```bash
# Use --overwrite flag
asbs setup my-agent --overwrite

# Or manually remove/rename existing files
```

---

## Legacy Commands

The following commands are deprecated but still available for backward compatibility:

- `setup_config` → Use `asbs setup`
- `create` → Use `asbs create`
- `windsurf` → Use `asbs windsurf`

**Migration:** Replace old commands with `asbs` subcommands.

---

## Related Documentation

- **[Agent Generator Guide](agent-generator.md)** - Detailed generator documentation
- **[Getting Started Guide](getting-started.md)** - Complete setup walkthrough
- **[Architecture Overview](architecture.md)** - Framework architecture
- **[Creating Handlers](handlers.md)** - Event handler patterns
- **[Building LLM Agents](llm-agents.md)** - AI agent integration
