# Agent Generator Guide

The Agent Generator is a unified CLI tool (`asbs`) that scaffolds new Blueprint Agents projects, generates components, and provides Windsurf IDE integration.

## What Is asbs?

**asbs** (Agentic Service Blueprint Client) is the command-line interface for the Blueprint Agents framework. It provides:

1. **`asbs setup`** - Create complete project structures
2. **`asbs create`** - Scaffold individual components (handlers, services, APIs, agents, schedulers)
3. **`asbs windsurf`** - Generate Windsurf IDE integration files
4. **`asbs validate`** - Validate project structure
5. **`asbs dev`** - Start development server

## Installation

```bash
pip install avs-blueprint-agents
```

This installs the `asbs` command globally.

## Quick Reference

```bash
asbs -h                          # Show help
asbs setup my-agent              # Create new project
asbs create handler MyHandler    # Scaffold handler
asbs windsurf                    # Generate Windsurf files
asbs validate                    # Validate project
asbs dev                         # Start dev server
```

For complete CLI documentation, see **[CLI Reference](cli-reference.md)**.

## Command 1: Setup - Create a New Project

### Basic Usage

```bash
asbs setup my-agent
```

This creates a complete project structure:

```
my-agent/
├── src/
│   ├── api/
│   │   └── routes.py           # REST API endpoints
│   ├── handlers/
│   │   └── my_handler.py       # Event handlers
│   ├── services/
│   │   └── my_service.py       # Business logic
│   ├── models/
│   │   └── schemas.py          # Pydantic models
│   ├── prompts/
│   │   └── system.prompt       # LLM prompts
│   └── main.py                 # Application entry point
├── tests/
│   └── test_my_handler.py      # Unit tests
├── settings.toml               # Configuration
├── secrets.toml.example        # Secrets template
├── pyproject.toml              # Dependencies
├── Dockerfile                  # Container image
├── docker-compose.yml          # Local development
└── README.md                   # Project documentation
```

### Advanced Options

```bash
# Specify output directory
asbs setup my-agent --output-dir /path/to/projects

# Overwrite existing files (use with caution)
asbs setup my-agent --overwrite

# Enable verbose logging
asbs setup my-agent --verbose
```

### What Gets Created

#### 1. Application Structure

**`src/main.py`** - Application entry point with AppBuilder configuration:
```python
from blueprint.agents import AppBuilder, Config
from pathlib import Path

config = Config(
    settings_files=["settings.toml", "secrets.toml"],
    root_path=Path(__file__).parent.parent,
)

app = (
    AppBuilder(config)
    .with_service(MyService())
    .with_handler(MyHandler())
    .with_rest_api(MyApi())
    .build()
)
```

#### 2. Component Templates

- **Handler** (`src/handlers/my_handler.py`) - Event processing with chain-of-responsibility pattern
- **Service** (`src/services/my_service.py`) - Business logic and state management
- **API** (`src/api/routes.py`) - REST endpoints using FastAPI
- **Models** (`src/models/schemas.py`) - Pydantic data models

#### 3. Configuration Files

**`settings.toml`** - Application configuration:
```toml
[default]
log_level = "INFO"

[default.runtimes.default]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_api_key = "@format {env[OPENAI_API_KEY]}"
```

**`secrets.toml.example`** - Template for secrets (copy to `secrets.toml`):
```toml
[default]
# Add your secrets here
# OPENAI_API_KEY = "sk-..."
```

#### 4. Development Files

- **`pyproject.toml`** - Project dependencies and metadata
- **`Dockerfile`** - Production container image
- **`docker-compose.yml`** - Local development with RabbitMQ and Dapr
- **`tests/`** - Unit test templates with pytest

#### 5. Documentation

- **`README.md`** - Project-specific documentation with setup instructions

### Next Steps After Setup

1. **Copy secrets template:**
   ```bash
   cd my-agent
   cp secrets.toml.example secrets.toml
   # Edit secrets.toml with your API keys
   ```

2. **Install dependencies:**
   ```bash
   pip install -e .
   ```

3. **Run tests:**
   ```bash
   pytest tests/ -v
   ```

4. **Start the application:**
   ```bash
   python -m uvicorn src.main:app --reload --port 8000
   ```

5. **Generate Windsurf files** (if using Windsurf IDE):
   ```bash
   asbs windsurf
   ```

## Command 2: Create - Scaffold Components

### Basic Usage

```bash
# Create handler
asbs create handler OrderPlaced --event-type order.placed

# Create service
asbs create service Invoice

# Create API
asbs create api Orders

# Create agent
asbs create agent InvoiceAnalyzer

# Create scheduler
asbs create scheduler DailyCleanup --cron "0 0 * * *"
```

See **[CLI Reference](cli-reference.md)** for complete `asbs create` documentation.

## Command 3: Windsurf - Generate IDE Integration

### Basic Usage

```bash
# Run from your project root
cd my-agent
asbs windsurf
```

This creates:

```
.windsurf/
├── rules/                      # Always-on context rules
│   ├── architecture-conventions.md
│   ├── code-style-quality.md
│   ├── security-error-handling.md
│   ├── testing-conventions.md
│   └── strict-oop.md
├── workflows/                  # Slash-command workflows
│   ├── create-agent-runtime.md
│   ├── create-business-service.md
│   ├── create-event-handler.md
│   ├── create-rest-api.md
│   ├── create-scheduler.md
│   └── ...
└── README.md                   # Windsurf integration docs
```

### Advanced Options

```bash
# Generate in specific directory
asbs windsurf /path/to/project

# Overwrite existing files
asbs windsurf --overwrite

# Enable verbose logging
asbs windsurf --verbose
```

### What Gets Generated

#### 1. Rules (Always-On Context)

Rules provide continuous guidance to Windsurf Cascade:

- **`architecture-conventions.md`** - Component patterns, dependency injection, registration order
- **`code-style-quality.md`** - OOP principles, type hints, async/await, docstrings
- **`security-error-handling.md`** - Secure coding, exception handling, input validation
- **`testing-conventions.md`** - Test organization, mocking, fixtures, coverage
- **`strict-oop.md`** - Enforce object-oriented design

#### 2. Workflows (Slash Commands)

Workflows provide step-by-step guides for common tasks:

- **`/create-agent-runtime`** - Create a new AgentRuntime backed by pydantic-ai
- **`/create-business-service`** - Create a new BusinessService for domain logic
- **`/create-event-handler`** - Create a new EventHandler for CloudEvents
- **`/create-rest-api`** - Create a new RestApi with FastAPI routes
- **`/create-scheduler`** - Create a new Scheduler for background tasks
- **`/create-vscode-settings`** - Generate VSCode launch/tasks configuration

### Using Windsurf Integration

Once generated, you can use Windsurf Cascade with:

1. **Automatic context** - Rules are always active, providing guidance
2. **Slash commands** - Type `/create-rest-api` to scaffold new components
3. **Consistent patterns** - All generated code follows framework conventions

## Common Workflows

### Starting a New Project

```bash
# 1. Create project structure
asbs setup invoice-processor

# 2. Navigate to project
cd invoice-processor

# 3. Set up secrets
cp secrets.toml.example secrets.toml
# Edit secrets.toml with your API keys

# 4. Install dependencies
pip install -e .

# 5. Generate Windsurf files (if using Windsurf IDE)
asbs windsurf

# 6. Run tests
pytest tests/ -v

# 7. Start development
asbs dev
```

### Adding Components to Existing Project

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

### Adding Windsurf to Existing Project

```bash
# Navigate to your project root
cd my-existing-project

# Generate Windsurf files
asbs windsurf

# Files created in .windsurf/
ls -la .windsurf/
```

### Updating Windsurf Files

```bash
# Regenerate with overwrite flag
asbs windsurf --overwrite

# This updates all rules and workflows to latest versions
```

### Validating Project Structure

```bash
# Check project structure
asbs validate

# Fix any issues, then validate again
asbs validate
```

## Customizing Generated Files

### Modifying Templates

The generator uses templates from the framework. To customize:

1. **For your project** - Edit generated files directly after creation
2. **For all projects** - Contribute to the framework repository

### Project-Specific Rules

Add custom rules to `.windsurf/rules/`:

```bash
# Create custom rule
cat > .windsurf/rules/custom-conventions.md << 'EOF'
---
trigger: always_on
---

# Custom Project Conventions

## Database Access

Always use the DatabaseService for database operations:

```python
# Correct
db_service = self.get_registry().get_service(DatabaseService)
result = await db_service.query(...)
```
EOF
```

### Project-Specific Workflows

Add custom workflows to `.windsurf/workflows/`:

```bash
# Create custom workflow
cat > .windsurf/workflows/deploy-staging.md << 'EOF'
---
description: Deploy to staging environment
---

# Deploy to Staging

1. Run tests
   ```bash
   pytest tests/ -v
   ```

2. Build Docker image
   ```bash
   docker build -t my-agent:staging .
   ```

3. Push to registry
   ```bash
   docker push my-agent:staging
   ```

4. Deploy to Kubernetes
   ```bash
   kubectl apply -f k8s/staging/
   ```
EOF
```

## Troubleshooting

### Command Not Found

If `asbs` is not found:

```bash
# Verify installation
pip show avs-blueprint-agents

# Reinstall if needed
pip install --force-reinstall avs-blueprint-agents

# Check PATH
which asbs
```

### Permission Errors

If you get permission errors:

```bash
# Use --user flag
pip install --user avs-blueprint-agents

# Or use virtual environment
python -m venv .venv
source .venv/bin/activate
pip install avs-blueprint-agents
```

### Overwrite Warnings

If files already exist:

```bash
# Skip existing files (default)
asbs setup my-agent

# Overwrite all files (use with caution)
asbs setup my-agent --overwrite

# Manually review and merge changes
```

## Best Practices

### 1. Start with Setup

Always use `asbs setup` for new projects to ensure consistent structure:

```bash
asbs setup my-new-agent
```

### 2. Use Create for Components

Scaffold individual components with `asbs create`:

```bash
asbs create handler MyHandler --event-type my.event
asbs create service MyService
asbs create api MyApi
```

### 3. Generate Windsurf Files

If using Windsurf IDE, generate integration files immediately:

```bash
cd my-new-agent
asbs windsurf
```

### 3. Customize After Generation

Edit generated files to match your specific needs:
- Update `settings.toml` with your configuration
- Modify handlers, services, and APIs
- Add custom rules and workflows

### 4. Keep Windsurf Files Updated

Regenerate Windsurf files when framework updates:

```bash
asbs windsurf --overwrite
```

### 5. Validate Regularly

Check project structure periodically:

```bash
asbs validate
```

### 6. Version Control

Commit generated files to version control:

```bash
git add .windsurf/
git commit -m "Add Windsurf integration"
```

But exclude secrets:

```bash
# .gitignore
secrets.toml
.env
```

## Examples

### Minimal Agent

```bash
# Create minimal structure
asbs setup minimal-agent

# Result: Basic handler + service + API
```

### Multi-Agent System

```bash
# Create project
asbs setup multi-agent-system

# Add multiple agents
cd multi-agent-system
asbs create agent InvoiceAnalyzer
asbs create agent CustomerSupport
asbs create agent ReportGenerator
```

### Microservice with REST API

```bash
# Create project
asbs setup api-service

# Add API endpoints
cd api-service
asbs create api Orders
asbs create api Products
asbs create api Customers

# Add supporting services
asbs create service OrderProcessor
asbs create service InventoryManager
```

## Related Documentation

- **[Getting Started Guide](getting-started.md)** - Complete setup walkthrough
- **[Architecture Overview](architecture.md)** - Framework architecture
- **[Creating Handlers](handlers.md)** - Event handler patterns
- **[Building LLM Agents](llm-agents.md)** - AI agent integration
- **[Windsurf Rules Documentation](../../.windsurf/rules/README.md)** - IDE integration details

## Support

For issues or questions:

1. Check [Troubleshooting Guide](troubleshooting.md)
2. Review [Full Documentation](../README.md)
3. Open an issue on Azure DevOps
