# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See `AGENTS.md` for architecture, component patterns, and testing conventions shared across all AI assistants.

## Dev Commands

```bash
# Install in editable mode with dev deps
uv pip install -e ".[dev]"

# Run all tests (bare pytest not in PATH — always use uv run)
uv run pytest tests/

# Skip integration tests (no external services needed)
uv run pytest tests/ -m "not integration"

# Run a single test
uv run pytest tests/unit/agents/app_builder/test_app_builder.py::TestClass::test_name -v

# Run tests with coverage
uv run pytest tests/ --cov=blueprint.agents --cov-report=html

# Lint / format / type-check
ruff check src/ tests/
black src/ tests/
mypy src/

# Run all quality checks
black src/ tests/ && ruff check src/ tests/ && mypy src/

# Build the package
python3 -m build

# Scaffold a new Blueprint project
asbs setup <project-name>
asbs create handler <name>
asbs create service <name>
asbs create api <name>
asbs create agent <name>
asbs create scheduler <name> [--cron <expr>]
asbs validate
asbs dev [--port 8000]
```

Line length is 140 chars (black + ruff both configured for this).

## GitHub CLI Notes

`gh issue view` without `--json` fails with a GraphQL Projects-classic deprecation error. Always use:
```bash
gh issue view <n> --repo <owner/repo> --json title,body,labels,state,comments,assignees
```

## Local Install for Testing Against IDAC Services

```bash
# Publish to local PyPI dir, then install from it in consumer projects
python -m build
cp dist/* ~/local-pypi/
# In consumer project:
uv pip install --no-cache-dir --find-links file:///home/pajoma/pypi/ avs-blueprint-agents==<version>
```

## Project names

This repository is public and used by many projects. The names of projects, products, customers,
teams and internal systems do not belong in it -- not in code, comments, tests, docs, plans, specs,
changelogs or commit messages. AI assistants pick them up from the context a feature is built in,
which is how such names got into this history before.

- **While writing:** describe where a change came from generically ("a consuming project", "an agent
  that calls a backend API"), never by the project it came from.
- **Before every commit:** review the staged diff (`git diff --cached`, new files included) and the
  commit message for any name that could be such a name. If there is one, stop: show the user each
  name and where it occurs, and ask whether this specific name may be used. Commit only after an
  explicit yes; otherwise replace it with a generic description.
- **No question needed** for a name approved in this section, a public open-source project or
  library, or this repository's own name.
- **Approved:** IDAC, including its repositories and services (e.g. the sessions service).

This rule holds whether or not hooks run. In Claude Code, `.claude/hooks/project-name-review.sh`
additionally holds every `git commit` until the command carries `PROJECT_NAMES_REVIEWED=1` -- add it
only after doing the review above.
