---
description: Create default VSCode launch.json and tasks.json for a Blueprint Agents project
---

## Steps

1. Create the `.vscode/` directory in the project root if it does not exist.

2. Create `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Run: FastAPI app",
            "type": "debugpy",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "src.main:app",
                "--reload",
                "--host", "0.0.0.0",
                "--port", "8000"
            ],
            "jinja": true,
            "justMyCode": false,
            "env": {
                "PYTHONPATH": "${workspaceFolder}/src",
                "ENV_FOR_DYNACONF": "development"
            },
            "cwd": "${workspaceFolder}"
        },
        {
            "name": "Debug: FastAPI app",
            "type": "debugpy",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "src.main:app",
                "--host", "0.0.0.0",
                "--port", "8000"
            ],
            "jinja": true,
            "justMyCode": false,
            "env": {
                "PYTHONPATH": "${workspaceFolder}/src",
                "ENV_FOR_DYNACONF": "development"
            },
            "cwd": "${workspaceFolder}"
        },
        {
            "name": "Test: All tests",
            "type": "debugpy",
            "request": "launch",
            "module": "pytest",
            "args": [
                "tests/",
                "-v",
                "--tb=short"
            ],
            "jinja": true,
            "justMyCode": false,
            "env": {
                "PYTHONPATH": "${workspaceFolder}/src",
                "ENV_FOR_DYNACONF": "testing"
            },
            "cwd": "${workspaceFolder}"
        },
        {
            "name": "Test: Current file",
            "type": "debugpy",
            "request": "launch",
            "module": "pytest",
            "args": [
                "${file}",
                "-v",
                "--tb=short"
            ],
            "jinja": true,
            "justMyCode": false,
            "env": {
                "PYTHONPATH": "${workspaceFolder}/src",
                "ENV_FOR_DYNACONF": "testing"
            },
            "cwd": "${workspaceFolder}"
        }
    ]
}
```

3. Create `.vscode/tasks.json`:

```json
{
    "version": "2.0.0",
    "tasks": [
        {
            "label": "Run: FastAPI app",
            "type": "shell",
            "command": "${workspaceFolder}/.venv/bin/uvicorn",
            "args": [
                "src.main:app",
                "--reload",
                "--host", "0.0.0.0",
                "--port", "8000"
            ],
            "options": {
                "cwd": "${workspaceFolder}",
                "env": {
                    "PYTHONPATH": "${workspaceFolder}/src",
                    "ENV_FOR_DYNACONF": "development"
                }
            },
            "group": {
                "kind": "build",
                "isDefault": true
            },
            "presentation": {
                "reveal": "always",
                "panel": "dedicated"
            },
            "problemMatcher": []
        },
        {
            "label": "Test: All",
            "type": "shell",
            "command": "${workspaceFolder}/.venv/bin/python",
            "args": ["-m", "pytest", "tests/", "-v", "--tb=short"],
            "options": {
                "cwd": "${workspaceFolder}",
                "env": {
                    "PYTHONPATH": "${workspaceFolder}/src",
                    "ENV_FOR_DYNACONF": "testing"
                }
            },
            "group": "test",
            "presentation": {
                "reveal": "always",
                "panel": "shared"
            },
            "problemMatcher": []
        },
        {
            "label": "Lint: ruff check",
            "type": "shell",
            "command": "${workspaceFolder}/.venv/bin/ruff",
            "args": ["check", "src/", "tests/"],
            "options": {
                "cwd": "${workspaceFolder}"
            },
            "group": "test",
            "presentation": {
                "reveal": "always",
                "panel": "shared"
            },
            "problemMatcher": []
        },
        {
            "label": "Format: black",
            "type": "shell",
            "command": "${workspaceFolder}/.venv/bin/black",
            "args": ["src/", "tests/"],
            "options": {
                "cwd": "${workspaceFolder}"
            },
            "group": "test",
            "presentation": {
                "reveal": "silent",
                "panel": "shared"
            },
            "problemMatcher": []
        },
        {
            "label": "Install: dev dependencies",
            "type": "shell",
            "command": "${workspaceFolder}/.venv/bin/pip",
            "args": ["install", "-e", ".[dev]"],
            "options": {
                "cwd": "${workspaceFolder}"
            },
            "presentation": {
                "reveal": "always",
                "panel": "shared"
            },
            "problemMatcher": []
        }
    ]
}
```

4. Optionally create `.vscode/settings.json` for Python interpreter and editor settings:

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": ["tests/"],
    "python.testing.unittestEnabled": false,
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "ms-python.black-formatter",
    "[python]": {
        "editor.defaultFormatter": "ms-python.black-formatter",
        "editor.codeActionsOnSave": {
            "source.organizeImports": "explicit"
        }
    },
    "ruff.enable": true,
    "ruff.organizeImports": true
}
```

## Notes

- All tasks assume a virtual environment at `.venv/` in the project root.
- Adjust `src.main:app` if your entry point module path differs.
- The `ENV_FOR_DYNACONF` environment variable controls which dynaconf environment is active (`development`, `testing`, `production`).
- Add `secrets.toml` to `.gitignore` — never commit API keys.
