# Getting Started with Agent Blueprint

**Time to complete:** 15-20 minutes  
**Difficulty:** Beginner

This guide will help you set up your development environment and create your first agent.

## What You'll Build

By the end of this guide, you'll have:
- ✅ A working development environment
- ✅ A running agent that processes invoice data
- ✅ Understanding of the basic workflow

## Prerequisites

Before you start, make sure you have:

- **Python 3.13** installed ([Download](https://www.python.org/downloads/))
- **Git** installed ([Download](https://git-scm.com/downloads))
- **Docker & Docker Compose** ([Download](https://www.docker.com/products/docker-desktop))
- A code editor (we recommend [VS Code](https://code.visualstudio.com/))

> **💡 Tip for Junior Developers:** If you're missing any of these, install them first. The error messages will tell you what's missing!

## Step 1: Clone the Repository

First, get a copy of the Agent Blueprint code:

```bash
# Clone the repository
git clone https://dev.azure.com/av360/Bechtle-Index-of-Sovereignty/_git/Agents_Blueprint
cd Agents_Blueprint
```

**What just happened?**
- You downloaded all the code to your computer
- You're now in the project directory

## Step 2: Set Up Python Environment

We use `uv` for fast Python package management:

### Install uv

**On macOS/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL  # Restart your shell
```

**On Windows (PowerShell):**
```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

Verify it works:
```bash
uv --version
```

### Create Virtual Environment

```bash
# Create a virtual environment
uv venv .venv --python 3.13

# Activate it
source .venv/bin/activate  # macOS/Linux
# OR
.\.venv\Scripts\activate  # Windows
```

**What's a virtual environment?**
- It's like a separate Python installation just for this project
- Keeps your system Python clean
- You'll see `(.venv)` in your terminal when it's active

### Install Dependencies

```bash
# Install all required packages
uv pip install -e "custom/.[dev]"
```

This installs:
- The base framework
- Your custom agent code
- Development tools (testing, linting, etc.)

## Step 3: Configure Your Agent

### Copy Configuration Files

```bash
# Copy the example configuration
cp custom/secrets.toml.example custom/secrets.toml
```

### Edit Configuration

Open `custom/secrets.toml` and add your AI model credentials:

```toml
[default]
# For OpenAI
ai_model_api_key = "sk-your-api-key-here"

# OR for vLLM (local model)
ai_model_base_url = "https://your-vllm-server.com/v1"
ai_model_api_key = "your-key"
```

> **🔒 Security Note:** Never commit `secrets.toml` to git! It's already in `.gitignore`.

## Step 4: Run Your First Agent

### Start the Agent

```bash
cd custom
uv run uvicorn src.main:app --reload --port 8001
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8001
INFO:     Application startup complete.
```

**What's happening?**
- `uvicorn` is a web server that runs your agent
- `--reload` automatically restarts when you change code
- `--port 8001` means your agent listens on port 8001

### Test It!

Open a new terminal and try this:

```bash
curl -X POST http://localhost:8001/api/process-resource \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_text": "Invoice #INV-001\nAmount: 100.00 EUR",
    "details": {"action": "invoke_agent"}
  }'
```

You should get a JSON response with the processed invoice!

## Step 5: Explore the Code

Let's look at the key files:

### Project Structure

```
Agents_Blueprint/
├── base/                    # Framework code (don't modify)
│   ├── src/
│   │   ├── agent/          # Base agent classes
│   │   ├── api/            # API endpoints
│   │   └── models/         # Data models
│   └── requirements.txt
│
├── custom/                  # Your agent code (modify this!)
│   ├── src/
│   │   ├── agent/
│   │   │   ├── handlers.py # Event handlers
│   │   │   ├── runtime.py  # AI agent runtime
│   │   │   └── tools.py    # AI tools
│   │   ├── api/
│   │   │   └── rest.py     # Custom API endpoints
│   │   ├── models/         # Your data models
│   │   └── main.py         # Application entry point
│   ├── settings.toml       # Configuration
│   └── secrets.toml        # Secrets (not in git)
│
└── docs/                    # Documentation
```

### Key Files to Know

**`custom/src/main.py`** - Application setup
```python
# This is where you register handlers and agents
app = (
    AppBuilder()
    .with_handler(AgentInvokerHandler)
    .with_agent_runtime(AgentRuntime, is_default=True)
    .with_rest_api(CustomRestApi)
    .build()
)
```

**`custom/src/agent/handlers.py`** - Event processors
```python
# Handlers decide what to do with incoming events
class AgentInvokerHandler(EventHandler):
    async def _can_handle(self, event, context):
        # Should this handler process this event?
        return event.data.details.get("action") == "invoke_agent"
    
    async def _handle(self, event, context):
        # Process the event
        context["use_agent"] = True
        return None  # Pass to next handler
```

**`custom/src/agent/runtime.py`** - AI agent
```python
# This wraps your AI model and tools
class AgentRuntime(BaseAgent):
    def _get_tools(self):
        # Tools the AI can use
        return [Tool(name="calculate_invoice", function=...)]
```

## Step 6: Make Your First Change

Let's add a simple log message:

1. Open `custom/src/agent/handlers.py`
2. Find the `AgentInvokerHandler._handle()` method
3. Add this line at the top:
   ```python
   logger.info("🎉 Processing invoice: %s", payload.invoice_id)
   ```
4. Save the file

The agent will automatically reload! Try the curl command again and watch the logs.

## Next Steps

Congratulations! You have a working agent. Now you can:

1. **[Understand the Architecture](architecture.md)** - Learn how everything fits together
2. **[Set Up Events](events-setup.md)** - Connect to RabbitMQ for event-driven processing
3. **[Create Custom Handlers](handlers.md)** - Build your own event processors
4. **[Build an LLM Agent](llm-agents.md)** - Integrate AI models

## Common Issues

### "uv: command not found"
**Solution:** Restart your terminal after installing uv, or run `exec $SHELL`

### "Port 8001 already in use"
**Solution:** Either stop the other process or use a different port:
```bash
uv run uvicorn src.main:app --reload --port 8002
```

### "Module not found" errors
**Solution:** Make sure you installed dependencies and activated the virtual environment:
```bash
source .venv/bin/activate
uv pip install -e "custom/.[dev]"
```

### Agent starts but API doesn't respond
**Solution:** Check the logs for errors. Common causes:
- Missing API key in `secrets.toml`
- Wrong base URL for vLLM
- Firewall blocking the port

## Quick Reference

```bash
# Activate environment
source .venv/bin/activate

# Run agent
cd custom && uv run uvicorn src.main:app --reload --port 8001

# Run tests
uv run pytest

# Format code
uv run ruff format .

# Check code quality
uv run ruff check .
```

## Need Help?

- **Stuck?** Check the [Troubleshooting Guide](troubleshooting.md)
- **Want to learn more?** Read the [Architecture Overview](architecture.md)
- **Found a bug?** Open an issue on Azure DevOps

---

**Next:** [Architecture Overview](architecture.md) →
