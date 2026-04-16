# Contributing to Blueprint Agents

Thank you for your interest in contributing to Blueprint Agents! This guide explains how to set up your development environment, build the package locally, and run tests.

## Prerequisites

- Python 3.13 or higher
- `pip` and `venv` (included with Python)
- Git

## Setting Up Your Development Environment

### 1. Clone the Repository

```bash
git clone https://github.com/2SpeakAI/blueprint-agents.git
cd blueprint-agents
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

Install the framework package in editable mode with development dependencies:

```bash
pip install -e ".[dev]"
```

This installs:
- The `avs-blueprint-agents` package in editable mode (changes to source code are immediately reflected)
- All development dependencies: `pytest`, `pytest-asyncio`, `black`, `ruff`, `mypy`, etc.

## Building and Running Tests Locally

### Run All Tests

```bash
pytest tests/
```

### Run Tests with Coverage

```bash
pytest tests/ --cov=blueprint.agents --cov-report=html
```

This generates an HTML coverage report in `htmlcov/index.html`.

### Run Tests for a Specific Module

```bash
pytest tests/unit/test_agent_builder.py
```

### Run Tests in Watch Mode (with pytest-watch)

Install `pytest-watch`:

```bash
pip install pytest-watch
```

Then run:

```bash
ptw tests/
```

### Run Tests with Verbose Output

```bash
pytest tests/ -v
```

### Run a Specific Test

```bash
pytest tests/unit/test_agent_builder.py::TestAgentBuilder::test_with_model_sets_model_name -v
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
rm -rf dist build *.egg-info
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
python -m zipfile -l dist/avs_blueprint_agents-*.whl | grep "blueprint/agents" | head -20
```

You should see entries like:
```
blueprint/agents/__init__.py
blueprint/agents/agent/__init__.py
blueprint/agents/agent/agent_builder.py
blueprint/agents/api/__init__.py
blueprint/agents/config/__init__.py
...
```

## Installing the Built Package

### Install in Development Environment

To test the built package in your current virtual environment:

```bash
pip install --force-reinstall --no-deps dist/avs_blueprint_agents-*.whl
```

### Install in a Separate Virtual Environment

Publish to a local “index” directory (behaves like a mini PyPI)
```bash
mkdir -p ~/local-pypi
cp dist/* ~/local-pypi/

```

In the other project, install from that local index (example)
```bash
uv pip install --no-cache-dir --find-links file:///home/pajoma/pypi/ avs-blueprint-agents==0.1.16
```

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
black src/ tests/
```

### Check Code with Ruff

```bash
ruff check src/ tests/
```

### Type Check with Mypy

```bash
mypy src/
```

### Run All Checks

```bash
black src/ tests/ && ruff check src/ tests/ && mypy src/
```

## Pre-commit & Pre-push Hooks

Set up both commit and push hooks:

```bash
pre-commit install
pre-commit install --hook-type pre-push
```

- **Pre-commit** runs linting and formatting checks on staged files before each commit.
- **Pre-push** runs the unit test suite before pushing, so CI won't fail on basic issues.

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
rm -rf dist build *.egg-info
python -m build
pip install --force-reinstall --no-deps dist/avs_blueprint_agents-*.whl
```

## Publishing to PyPI (for maintainers)

Publishing is handled by the CI/CD pipeline. See `.github/workflows/publish.yml` for details.

- Alpha versions (e.g., `0.6.0a3`) are published to TestPyPI
- Stable versions are published to PyPI

## Submitting Pull Requests

1. Fork the repository and create a feature branch
2. Make your changes with tests
3. Ensure all checks pass: `black src/ tests/ && ruff check src/ tests/ && mypy src/ && pytest tests/`
4. Submit a pull request with a clear description of changes

## Questions or Issues?

If you encounter issues, please:

1. Check the [Troubleshooting Guide](docs/guides/troubleshooting.md) for known issues
2. Review the test output carefully for error messages
3. Open an issue on GitHub with details about your environment and the error

Thank you for contributing!
