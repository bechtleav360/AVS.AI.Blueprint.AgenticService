"""Claude Code resource generator.

Copies the Blueprint Agents CLAUDE.md into a target project's .claude/ directory
so that Claude Code picks it up as persistent project context.
"""

import importlib.resources
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class ClaudeGenerator:
    """Generates the Claude Code context file for a Blueprint Agents project.

    Copies ``CLAUDE.md`` from the framework's ``claude_docs/`` directory into
    the target project's ``.claude/`` directory so that Claude Code loads it
    automatically as project instructions.

    Output layout in the target project::

        .claude/
        └── CLAUDE.md
    """

    def __init__(self, output_dir: str | Path) -> None:
        """Initialise the generator.

        Args:
            output_dir: Root directory of the target project. The ``.claude/``
                folder will be created (or updated) inside it.

        Raises:
            FileNotFoundError: If the framework's ``claude_docs/`` source
                directory cannot be located.
        """
        self.output_dir = Path(output_dir).resolve()
        self._source_dir = self._locate_source()

        logger.info("ClaudeGenerator: source=%s  target=%s", self._source_dir, self.output_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, overwrite: bool = False) -> None:
        """Copy CLAUDE.md into the target project's .claude/ directory.

        Args:
            overwrite: When *True*, an existing CLAUDE.md is replaced.
                When *False* (default), an existing file is left untouched
                and a warning is logged.
        """
        claude_dir = self.output_dir / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        src_file = self._source_dir / "CLAUDE.md"
        dst_file = claude_dir / "CLAUDE.md"

        if dst_file.exists() and not overwrite:
            logger.warning("Skipping existing file (use --overwrite to replace): %s", dst_file)
            print(f"\nClaude Code resources generated in: {claude_dir}")
            print("  Files written : 0")
            print(f"  Files skipped : 1  (use --overwrite to replace)")
            return

        shutil.copy2(src_file, dst_file)
        logger.info("Wrote %s", dst_file.relative_to(self.output_dir))

        print(f"\nClaude Code resources generated in: {claude_dir}")
        print("  Files written : 1")
        print("\nNext steps:")
        print("  1. Open the project in Claude Code — it will pick up CLAUDE.md automatically.")
        print("  2. Use slash commands in the chat:")
        print("       /create-handler   /create-service   /create-agent-runtime")
        print("       /create-scheduler /create-rest-api  /new-agent-service")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _locate_source(self) -> Path:
        """Locate the ``claude_docs/`` directory inside the installed package.

        Raises:
            FileNotFoundError: If the packaged claude_docs directory cannot
                be found or is missing CLAUDE.md.
        """
        try:
            pkg_ref = importlib.resources.files("blueprint.agent_generator")
            resolved = Path(str(pkg_ref)) / "claude_docs"
            if resolved.exists() and (resolved / "CLAUDE.md").exists():
                return resolved.resolve()
        except (TypeError, ModuleNotFoundError):
            pass

        # Fallback for running from source without editable install
        fallback = Path(__file__).parent.parent / "claude_docs"
        if fallback.exists() and (fallback / "CLAUDE.md").exists():
            return fallback.resolve()

        raise FileNotFoundError(
            "Could not locate the Claude Code documentation source directory.\n"
            "Expected it at: blueprint.agent_generator/claude_docs/\n"
            "Make sure the package is installed with: pip install -e ."
        )
