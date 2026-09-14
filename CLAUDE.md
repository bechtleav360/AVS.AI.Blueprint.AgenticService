# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See `AGENTS.md` for the architecture, the component patterns, the testing conventions and the **design rules** --
each with the failure it prevents -- shared across all AI assistants and every human working here.

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
  (blocking defects) and phases 0-10.

**Work this feature in reviewable steps.** Make one change, then stop and report what changed and
why before starting the next. Do not chain phases together, and do not chain the work items within
a phase, into a single unreviewed run -- each step is meant to be looked at before the next one
begins. This rule applies to every prerequisite and phase in that plan, and only to this feature.

**Record every change in the feature changelog.** `docs/plans/2026-08-28-multi-agent-grouping-changelog.md`
is updated as part of each change, not reconstructed at the end: it is the running record of what
was done and why, and it becomes the pull-request description. Smaller fixes found along the way
belong in it too -- they are the ones most easily lost.

**Explain new code, not just its arrival.** When a change introduces real implementation -- new
behaviour, new control flow, a new abstraction -- report what was built and how it works, not only
which files changed and whether the checks passed. Formatting and lint fixes, type annotations,
tests and documentation need no walkthrough.

**Report the production code in detail, and report it first.** The walkthrough is about
`src/`: name each function, branch and call site that changed, show the lines that matter, and say
what the code now does that it did not do before and what breaks if it is removed. A list of files
touched, a summary of intent, or "tests pass and lint is clean" is not a report of the code -- that
is the wrapper around it. Tests, documentation and the changelog are listed, not walked through:
they are how the change is verified and recorded, not the change itself.

This is not satisfied by having reported the code in an earlier message. **Every message that
reports a step as done carries the walkthrough**, including the one that follows a background test
run finishing -- that message reports the step, so it repeats the code detail rather than shrinking
to a status line. Err towards showing the actual changed lines: a paraphrase of what a function now
does is weaker than the function.

The rule has been missed repeatedly, so treat it as a checklist item before writing any completion
message: *have I shown the changed code, not described it?*

Read the spec before changing `component/registry.py`, `app_builder.py`, `handler/`,
`services/eventing/`, `io/api/eventing/`, `clients/io/nats_client.py`, the schedulers or
telemetry: those paths carry invariants that are not visible from the code.

---

## Commits

Commit messages follow **Conventional Commits** -- `.pre-commit-config.yaml` runs the commitizen
hook at the `commit-msg` stage, so the subject line must be `<type>(<scope>): <description>` with
a type from `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`,
`revert`. A prefix like `P0:` is not a type and will be rejected once the hook is installed.

Install every hook stage, not just the default one:

```bash
pre-commit install
pre-commit install --hook-type commit-msg
pre-commit install --hook-type pre-push
```

End every commit message with the repo's trailer:

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```
