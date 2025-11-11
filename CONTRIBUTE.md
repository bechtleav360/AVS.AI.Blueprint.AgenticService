# Contributing to Agents Blueprint

Thank you for your interest in contributing to the Agents Blueprint project! This guide explains how to set up your development environment, build the package locally, and run tests.

## Prerequisites

- Python 3.13 or higher
- `pip` and `venv` (included with Python)
- Git

## Setting Up Your Development Environment

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Agents_Blueprint
```

### 2. Create a Virtual Environment

Create an isolated Python environment to avoid conflicts with system packages:

```bash
python3.13 -m venv .venv
```

### 3. Activate the Virtual Environment

**On Linux/macOS:**

```bash
source .venv/bin/activate
```

**On Windows:**

```bash
.venv\Scripts\activate
```

### 4. Install Development Dependencies

Install the base package in editable mode with development dependencies:

```bash
cd base
pip install -e ".[dev]"
```

This installs:
- The `avs-blueprint-agents` package in editable mode (changes to source code are immediately reflected)
- All development dependencies: `pytest`, `pytest-asyncio`, `black`, `ruff`, `mypy`, etc.

## Building and Running Tests Locally

### Run All Tests

```bash
pytest base/tests
```

### Run Tests with Coverage

```bash
pytest base/tests --cov=base.src --cov-report=html
```

This generates an HTML coverage report in `htmlcov/index.html`.

### Run Tests for a Specific Module

```bash
pytest base/tests/unit/test_agent_builder.py
```

### Run Tests in Watch Mode (with pytest-watch)

Install `pytest-watch`:

```bash
pip install pytest-watch
```

Then run:

```bash
ptw base/tests
```

### Run Tests with Verbose Output

```bash
pytest base/tests -v
```

### Run a Specific Test

```bash
pytest base/tests/unit/test_agent_builder.py::TestAgentBuilder::test_with_model_sets_model_name -v
```

## Building the Package Locally

### 1. Ensure Build Tools Are Installed

The build tools should already be installed from the dev dependencies, but you can verify:

```bash
pip install build setuptools wheel
```

### 2. Clean Previous Builds

Remove old build artifacts to ensure a clean build:

```bash
cd base
rm -rf dist build src/avs_blueprint_agents.egg-info
```

### 3. Build the Package

Build both the wheel and source distribution:

```bash
python -m build
```

This generates:
- `dist/avs_blueprint_agents-X.Y.Z-py3-none-any.whl` (wheel distribution)
- `dist/avs_blueprint_agents-X.Y.Z.tar.gz` (source distribution)

### 4. Verify the Build

List the contents of the wheel to ensure all modules are correctly packaged under the `blueprint.agents` namespace:

```bash
python -m zipfile -l dist/avs_blueprint_agents-*.whl | head -20
```

You should see entries like:
```
blueprint/agents/__init__.py
blueprint/agents/agent/__init__.py
blueprint/agents/agent/agent_builder.py
blueprint/agents/api/__init__.py
...
```

## Installing the Built Package

### Install in Development Environment

To test the built package in your current virtual environment:

```bash
pip install --force-reinstall --no-deps dist/avs_blueprint_agents-*.whl
```

### Install in a Separate Virtual Environment

To test in isolation:

```bash
python3.13 -m venv test_env
source test_env/bin/activate
pip install dist/avs_blueprint_agents-*.whl
python -c "from blueprint.agents import AppBuilder; print(AppBuilder)"
```

## Code Quality and Linting

### Format Code with Black

```bash
black base/src base/tests
```

### Check Code with Ruff

```bash
ruff check base/src base/tests
```

### Type Check with Mypy

```bash
mypy base/src
```

### Run All Checks

```bash
black base/src base/tests && ruff check base/src base/tests && mypy base/src
```

## Pre-commit Hooks

To automatically run linting and formatting before each commit:

```bash
pre-commit install
```

This will run configured checks on staged files before allowing commits.

## Troubleshooting

### Virtual Environment Not Activating

Ensure you're using the correct activation command for your OS. On Linux/macOS, the command is:

```bash
source .venv/bin/activate
```

### Build Fails with "Invalid initial character for a key part"

This usually indicates a TOML syntax error in `pyproject.toml`. Check the file for:
- Unquoted keys with dots (e.g., `blueprint.agents` must be quoted)
- Mismatched brackets or quotes

### Tests Fail with "ModuleNotFoundError"

Ensure the package is installed in editable mode:

```bash
pip install -e ".[dev]"
```

### Package Metadata Not Found

If the root API returns default metadata, the package may not be installed. Rebuild and reinstall:

```bash
cd base
rm -rf dist build src/avs_blueprint_agents.egg-info
python -m build
pip install --force-reinstall --no-deps dist/avs_blueprint_agents-*.whl
```

## Publishing to PyPI (for maintainers)

See the main README for instructions on publishing to PyPI or Azure Artifacts.

## Questions or Issues?

If you encounter issues, please:

1. Check the `TROUBLESHOOTING.md` file for known issues
2. Review the test output carefully for error messages
3. Open an issue on the repository with details about your environment and the error

Thank you for contributing!
