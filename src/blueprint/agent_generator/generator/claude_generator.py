"""Claude Code resource generator.

Copies the Blueprint Agents Claude Code resources (CLAUDE.md, agents/, skills/)
into a target project's .claude/ directory so that Claude Code picks them up
as persistent project context.
"""

import importlib.resources
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class ClaudeGenerator:
    """Generates Claude Code integration files for a Blueprint Agents project.

    Copies ``CLAUDE.md``, ``agents/``, and ``skills/`` from the framework's
    ``claude_docs/`` directory into the target project:
    - ``CLAUDE.md`` → ``src/CLAUDE.md`` (framework documentation)
    - ``agents/`` → ``.claude/agents/`` (architecture agents)
    - ``skills/`` → ``.claude/skills/`` (CLI skills)

    Output layout in the target project::

        src/
        └── CLAUDE.md
        .claude/
        ├── agents/
        │   ├── blueprint-architect.md
        │   └── blueprint-builder.md
        └── skills/
            ├── new-agent-service/
            │   └── SKILL.md
            └── add-component/
                └── SKILL.md
    """

    def __init__(self, output_dir: str | Path) -> None:
        """Initialise the generator.

        Args:
            output_dir: Root directory of the target project. The ``src/``
                and ``.claude/`` folders will be created (or updated) inside it.

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
        """Copy Claude Code resources into the target project.

        Copies from the framework's claude_docs/ source:
        - CLAUDE.md → src/CLAUDE.md (framework documentation)
        - agents/ → .claude/agents/ (architecture agents)
        - skills/ → .claude/skills/ (CLI skills)

        Existing files are skipped unless overwrite=True.

        Args:
            overwrite: When *True*, existing files are replaced.
                When *False* (default), existing files are left untouched
                and a warning is logged.
        """
        # Create directories
        src_dir = self.output_dir / "src"
        claude_dir = self.output_dir / ".claude"
        src_dir.mkdir(parents=True, exist_ok=True)
        claude_dir.mkdir(parents=True, exist_ok=True)

        # Copy CLAUDE.md to src/
        written_claude = self._copy_file(
            self._source_dir / "CLAUDE.md",
            src_dir / "CLAUDE.md",
            overwrite=overwrite,
        )

        # Copy agents/ to .claude/agents/
        written_agents = self._copy_tree(
            self._source_dir / "agents",
            claude_dir / "agents",
            overwrite=overwrite,
        )

        # Copy skills/ to .claude/skills/
        written_skills = self._copy_tree(
            self._source_dir / "skills",
            claude_dir / "skills",
            overwrite=overwrite,
        )

        total_written = written_claude + written_agents[0] + written_skills[0]
        total_skipped = written_agents[1] + written_skills[1]

        print("\nClaude Code resources generated:")
        print(f"  ✓ src/CLAUDE.md (framework documentation)")
        print(f"  ✓ .claude/agents/ (architecture agents)")
        print(f"  ✓ .claude/skills/ (CLI skills)")
        print(f"\n  Files written : {total_written}")
        if total_skipped:
            print(f"  Files skipped : {total_skipped}  (use --overwrite to replace)")
        print("\nNext steps:")
        print("  1. Open the project in Claude Code — it will pick up src/CLAUDE.md automatically.")
        print("  2. Use slash commands:")
        print("       /new-agent-service   /add-component")
        print("  3. Use agents:")
        print("       @blueprint-architect   @blueprint-builder")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _copy_file(self, src: Path, dst: Path, overwrite: bool) -> int:
        """Copy a single file from src to dst.

        Returns:
            1 if file was written, 0 if skipped.
        """
        if not src.exists():
            logger.warning("Source file does not exist: %s", src)
            return 0

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists() and not overwrite:
            logger.warning("Skipping existing file (use --overwrite to replace): %s", dst)
            return 0

        shutil.copy2(src, dst)
        logger.info("Wrote %s", dst.relative_to(self.output_dir))
        return 1

    def _copy_tree(self, src: Path, dst: Path, overwrite: bool) -> tuple[int, int]:
        """Recursively copy all files from src into dst.

        Returns:
            Tuple of (written_count, skipped_count).
        """
        written = 0
        skipped = 0

        for src_path in src.rglob("*"):
            if not src_path.is_file():
                continue

            relative = src_path.relative_to(src)
            dst_path = dst / relative
            dst_path.parent.mkdir(parents=True, exist_ok=True)

            if dst_path.exists() and not overwrite:
                logger.warning("Skipping existing file (use --overwrite to replace): %s", dst_path)
                skipped += 1
                continue

            shutil.copy2(src_path, dst_path)
            logger.info("Wrote %s", dst_path.relative_to(self.output_dir))
            written += 1

        return written, skipped

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
