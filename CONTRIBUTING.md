# Contributing to Agent Blueprint

Thank you for building on the Agent Blueprint! This guide focuses on what you need to start developing a custom agent, set up a Python workspace with `uv`, and run everything locally from VS Code.

## Table of Contents

- [Getting Started](#getting-started)
- [Setting Up the Developer Environment](#setting-up-the-developer-environment)
- [Project Anatomy](#project-anatomy)
- [Creating Your Custom Agent](#creating-your-custom-agent)
- [Running Locally in VS Code](#running-locally-in-vs-code)
- [Quality Gates: Linting, Tests, and Type Checking](#quality-gates-linting-tests-and-type-checking)
- [Submitting Changes](#submitting-changes)

## Getting Started

The blueprint ships with a working reference implementation plus the `agent/src/custom/` sandbox where you can plug in domain-specific logic. You will spend most of your time editing files inside that custom directory and optionally extending base components under `base/` when you need shared functionality.

Before you begin, confirm you have:

- **Python 3.11+** installed
- **uv** (`pip install uv`) for dependency and virtualenv management
- **VS Code** with the *Python* and *Pylance* extensions
- **Git** for version control

Docker is optional—this guide assumes you run locally without containers.

## Setting Up the Developer Environment

All steps below run from the repository root.

1. **Clone and enter the workspace**
   ```bash
   git clone <repository-url>
   cd Agents_Blueprint
   ```

2. **Create an isolated interpreter with uv**
   ```bash
   uv venv --python 3.12 .venv

   # macOS/Linux
   source .venv/bin/activate

   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   ```

3. **Install Python dependencies**
   ```bash
   uv pip install -r agent/requirements.txt
   uv pip install -r base/requirements.txt
   uv pip install -e .[dev]
   ```

4. **Sync tooling and hooks**
   ```bash
   pre-commit install
   ```

5. **Configure environment variables (optional)**
   ```bash
   cp .env.example .env
   # Update values to match your environment, credentials, or feature flags
   ```

The VS Code workspace settings (`.vscode/settings.json`) point `python.defaultInterpreterPath` to `${workspaceFolder}/venv/bin/python`. If your virtual environment lives elsewhere, update that setting or run `uv venv` again to match.

## Project Anatomy

Key directories when developing a custom agent:

- **`agent/src/main.py`** – FastAPI entrypoint used by both Uvicorn and VS Code launch configs.
- **`agent/src/custom/`** – Home for your domain-specific agent code.
  - `agent/src/custom/models/` – Pydantic schemas that extend the base asset/event types.
  - `agent/src/custom/agent/` – Custom strategy, handlers, and orchestration logic.
  - `agent/src/custom/prompts/` – Prompt templates for LLM-powered steps.
  - `agent/src/custom/api/` – Optional HTTP routes that expose bespoke APIs.
- **`base/src/`** – Shared framework components you can reuse or extend (decision engine, gateways, instrumentation).
- **`agent/tests/`** – Unit and integration tests covering both base and custom logic.

## Creating Your Custom Agent

1. **Model the data you need**
   Add or extend schemas inside `agent/src/custom/models/`. Use Pydantic models and align with existing base contracts.

2. **Define decision handlers**
   - Implement new handlers in `agent/src/custom/agent/handlers/`.
   - Subclass the base chain-of-responsibility classes from `base/src/agent/base/decisions/`.
   - Register the handler in `agent/src/custom/agent/registry.py`, respecting priority so that predicates run fast and deterministically.

3. **Wire the runtime**
   - Update `agent/src/custom/agent/runtime.py` to assemble your handler chain and agent-specific services.
   - Ensure any external lookups go through adapters in `base/src/gateways/` or new gateway abstractions under `agent/src/custom/gateways/`.

4. **Add prompts or LLM tools** (optional)
   - Extend prompt templates in `agent/src/custom/prompts/`.
   - Add tool definitions that surface the required context to the LLM while keeping sensitive data redacted.

5. **Document assumptions**
   Leave a README in `agent/src/custom/` outlining input expectations, feature flags, and manual testing steps for reviewers.

## Running Locally in VS Code

### Configure the interpreter

1. Open the workspace folder in VS Code.
2. When prompted, select the interpreter located at `${workspaceFolder}/venv/bin/python` (or use *Python: Select Interpreter* from the command palette).

### Use the provided launch configurations

1. Press `F5` or choose **Run ▸ Start Debugging**.
2. Select **FastAPI: agent-service** to launch `uvicorn agent.src.main:app --reload`.
3. Access the service at [http://localhost:8000/docs](http://localhost:8000/docs) for the generated OpenAPI UI.

### Run tests directly from VS Code

1. Choose the **Pytest: agent/tests** configuration to execute the full test suite under `agent/tests/`.
2. Alternatively, use the Test Explorer sidebar to run or debug individual tests.

### Managing environment variables

- Set temporary overrides in the VS Code *Run and Debug* panel for each configuration.
- For persistent values, edit `.vscode/launch.json` or register them in `.env` and load with Dynaconf.

## Quality Gates: Linting, Tests, and Type Checking

- **Format on save** – The workspace enforces Black via VS Code (`.vscode/settings.json`).
- **Linting** – Ruff runs automatically on save and in pre-commit; resolve warnings locally.
- **Type checking** – MyPy is configured in the workspace; run it ad hoc with `uv run mypy agent/src`.
- **Unit tests** – Execute with `uv run pytest agent/tests` for CLI parity with VS Code.
- **Pre-commit** – Always run `pre-commit run --all-files` before opening a PR to catch formatting, security, and style violations.

## Submitting Changes

1. **Create a feature branch**
   ```bash
   git checkout -b feature/<short-description>
   ```

2. **Commit frequently**
   ```bash
   git add <files>
   git commit -m "feat: describe change"
   ```

3. **Verify quality gates**
   ```bash
   uv run pytest agent/tests
   uv run ruff check --fix
   uv run mypy agent/src
   pre-commit run --all-files
   ```

4. **Open a pull request**
   - Summarize the custom agent capabilities you implemented.
   - Link to any design docs or diagrams.
   - Highlight manual testing or workflows used in VS Code.

5. **Respond to review feedback** quickly and keep your branch rebased on `main`.

## Need Help?

- **Questions about the runtime** – Start a discussion in the repository or ping the maintainers on the team channel.
- **Issues or bugs** – Open a GitHub issue with reproduction steps and logs.
- **Security disclosures** – Contact the maintainers privately; do not file public tickets.

Enjoy building your custom agent! 🚀
