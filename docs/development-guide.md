# Development Guide

Use this guide to bootstrap a development workstation for the **Agents Blueprint** with the `uv` Python toolchain, a project-local virtual environment, and the VS Code workflow required to run and test agents.

## Quick reference
- **Create environment:** `uv venv .venv --python 3.13`
- **Activate environment:** `source .venv/bin/activate`
- **Install deps:** `uv pip install -e ".[dev]"`
- **Run agent:** `uv run uvicorn custom.src.main:app --reload --port 8001`
- **Run tests:** `uv run pytest`

## Prerequisites
- Python **3.13** (see `custom/pyproject.toml`)
- [`uv`](https://docs.astral.sh/uv/) 0.4+ for environment and dependency management
- Git
- Docker & Docker Compose (required for local services)
- VS Code with the **Python** and **Docker** extensions

### Install uv (one time)
- **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  exec $SHELL
  ```
- **Windows (PowerShell):**
  ```powershell
  irm https://astral.sh/uv/install.ps1 | iex
  ```
Verify the installation:
```bash
uv --version
```

## Environment setup with uv
1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/Agents_Blueprint.git
   cd Agents_Blueprint
   ```

2. **Create a project virtual environment** (stored at `./.venv`)
   ```bash
   uv venv .venv --python 3.13
   ```
   `uv` downloads the requested interpreter if it is missing.

3. **Activate the environment**
   ```bash
   source .venv/bin/activate          # macOS/Linux
   .\.venv\Scripts\activate          # Windows PowerShell
   ```
   The shell prompt will show `(.venv)` while active. Use `deactivate` to leave the environment.

4. **Install project dependencies** (based on `custom/pyproject.toml`)
   ```bash
   uv pip install -e "custom/.[dev]"
   ```
   - Run from the repository root so the path resolves to `custom/pyproject.toml`.
   - The editable install exposes both the shared `base/` package and the `custom/` implementation.
   - The `dev` extra pulls in tooling such as Ruff, Black, MyPy, pytest, and pre-commit.

5. **Set up pre-commit hooks**
   ```bash
   uv run pre-commit install
   ```

6. **Configure environment variables**
   ```bash
   cp custom/secrets.toml.example custom/secrets.toml
        # Edit the copied file with local secrets and runtime overrides
   ```

7. **Launch Docker dependencies (optional)**
   If your agent requires backing services:
   ```bash
   docker compose up -d
   ```

## Working with the virtual environment
- Re-activate the env in new shells with `source .venv/bin/activate` (or `./.venv/Scripts/activate` on Windows).
- Use `uv pip list` to inspect installed packages and `uv pip install PACKAGE` for ad-hoc additions.
- Update dependencies by re-running `uv pip install -e ".[dev]"` after `pyproject.toml` changes.

## Running the agent
### Command line
```bash
uv run uvicorn custom.src.main:app --host 0.0.0.0 --port 8001 --reload
```
- Uses the editable package defined in `custom/pyproject.toml`.
- Pick a different port if `8001` is busy.
- Add environment overrides inline, for example:
  ```bash
  LOG_LEVEL=DEBUG uv run uvicorn custom.src.main:app --reload
  ```

### Visual Studio Code workflow
1. **Select the interpreter**
   - Open the Command Palette → *Python: Select Interpreter*.
   - Choose `./.venv/bin/python` (`.venv\Scripts\python.exe` on Windows).

2. **Use the provided launch configuration**
   - Open the *Run and Debug* pane.
   - Choose **FastAPI: custom-service** (from `.vscode/launch.json`).
   - Press *Start Debugging* to run the agent with auto-reload and the env vars defined in the launch config.

3. **Optional tasks**
   - The `.vscode/tasks.json` file defines formatting and linting commands that rely on the `.venv` interpreter.

## Testing
### Command line
```bash
uv run pytest
```
- Runs the default suite located in `custom/tests/`.
- Add options such as coverage or markers: `uv run pytest --cov=custom --maxfail=1`.

Alternative make targets (if you prefer existing recipes):
```bash
uv run make test
uv run make lint
uv run make format
```

### VS Code
- Use the **Pytest: custom/tests** configuration in `.vscode/launch.json` to debug tests.
- Enable the built-in VS Code testing UI: Command Palette → *Python: Configure Tests* → *pytest* → `custom/tests`.

### Pre-commit checks
Run all hooks locally before opening a PR:
```bash
uv run pre-commit run --all-files
```

## Troubleshooting tips
- **Interpreter missing in VS Code:** Ensure `uv venv .venv` was executed and the interpreter is selected.
- **Dependencies out of date:** Re-run `uv pip install -e ".[dev]"` after pulling main.
- **Docker services unavailable:** Run `docker compose ps` to confirm containers are up.
- **Port already in use:** Supply `--port 8002` (or another free port) to `uvicorn`.

## Additional references
- Documentation index: `docs/README.md`
- Contribution guidelines: `CONTRIBUTING.md`
- Troubleshooting playbook: `docs/troubleshooting.md`

---

*Maintained by the Agents Blueprint team. Report issues or improvements via the standard contribution process.*
