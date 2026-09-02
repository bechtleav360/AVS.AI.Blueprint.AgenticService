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

---

## Multi-Agent Grouping

- **Spec (normative):** `docs/specs/2026-08-28-multi-agent-grouping.md` -- invariants C1-C7, API
  surface, config reference, acceptance criteria. Where any other document disagrees with the
  spec, the spec wins.
- **Implementation plan:** `docs/plans/2026-08-28-multi-agent-grouping.md` -- prerequisites P0-P6
  (blocking defects) and phases 0-9.

**Work this feature in reviewable steps.** Make one change, then stop and report what changed and
why before starting the next. Do not chain phases together, and do not chain the work items within
a phase, into a single unreviewed run -- each step is meant to be looked at before the next one
begins. This rule applies to every prerequisite and phase in that plan, and only to this feature.

Read the spec before changing `component/registry.py`, `app_builder.py`, `handler/`,
`services/eventing/`, `io/api/eventing/`, `clients/io/nats_client.py`, the schedulers or
telemetry: those paths carry invariants that are not visible from the code.
