"""Windsurf resource generator.

Copies the Blueprint Agents Windsurf rules and workflows into a target project,
creating the standard .windsurf/ directory structure that Cascade reads.
"""

import importlib.resources
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class WindsurfGenerator:
    """Generates Windsurf rules and workflow files for a Blueprint Agents project.

    Copies the canonical rules and workflows from the framework's
    ``docs/windsurf/`` directory into the target project's ``.windsurf/``
    directory so that Cascade can read them as persistent context.

    Output layout in the target project::

        .windsurf/
        ├── rules/
        │   ├── architecture.md
        │   ├── component-registry.md
        │   ├── rest-api-routes.md
        │   ├── business-service.md
        │   ├── event-handler.md
        │   ├── scheduler.md
        │   └── agent-runtime.md
        └── workflows/
            ├── create-rest-api.md
            ├── create-business-service.md
            ├── create-event-handler.md
            ├── create-scheduler.md
            ├── create-agent-runtime.md
            └── create-vscode-settings.md
    """

    def __init__(self, output_dir: str | Path) -> None:
        """Initialise the generator.

        Args:
            output_dir: Root directory of the target project.  The
                ``.windsurf/`` folder will be created (or updated) inside it.

        Raises:
            FileNotFoundError: If the framework's ``docs/windsurf/`` source
                directory cannot be located.
        """
        self.output_dir = Path(output_dir).resolve()
        self._source_dir = self._locate_source()

        logger.info("WindsurfGenerator: source=%s  target=%s", self._source_dir, self.output_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, overwrite: bool = False) -> None:
        """Copy rules and workflows into the target project.

        Args:
            overwrite: When *True*, existing files are replaced.  When
                *False* (default), existing files are left untouched and a
                warning is logged.
        """
        windsurf_dir = self.output_dir / ".windsurf"
        windsurf_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        skipped = 0

        for subdir in ("rules", "workflows"):
            src_subdir = self._source_dir / subdir
            dst_subdir = windsurf_dir / subdir
            dst_subdir.mkdir(parents=True, exist_ok=True)

            if not src_subdir.exists():
                logger.warning("Source directory not found, skipping: %s", src_subdir)
                continue

            for src_file in sorted(src_subdir.glob("*.md")):
                dst_file = dst_subdir / src_file.name
                if dst_file.exists() and not overwrite:
                    logger.warning("Skipping existing file (use --overwrite to replace): %s", dst_file)
                    skipped += 1
                    continue

                shutil.copy2(src_file, dst_file)
                logger.info("Wrote %s", dst_file.relative_to(self.output_dir))
                copied += 1

        self._print_summary(windsurf_dir, copied, skipped)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _locate_source(self) -> Path:
        """Locate the ``windsurf_docs/`` directory inside the installed package.

        Uses ``importlib.resources`` so the path is resolved correctly from
        both an editable install and a built wheel / PyPI installation.

        Raises:
            FileNotFoundError: If the packaged windsurf_docs directory cannot
                be found or is missing the expected ``rules/`` sub-directory.
        """
        # importlib.resources.files() returns a Traversable backed by a real
        # Path for non-zip (wheel/editable) installs — which is always the
        # case for setuptools packages.  We cast to Path so callers can use
        # standard pathlib operations.
        try:
            pkg_ref = importlib.resources.files("blueprint.agent_generator")
            resolved = Path(str(pkg_ref)) / "windsurf_docs"
            if resolved.exists() and (resolved / "rules").exists():
                return resolved.resolve()
        except (TypeError, ModuleNotFoundError):
            pass

        # Fallback: direct sibling path (covers running from source without
        # an editable install, e.g. bare pytest runs)
        fallback = Path(__file__).parent.parent / "windsurf_docs"
        if fallback.exists() and (fallback / "rules").exists():
            return fallback.resolve()

        raise FileNotFoundError(
            "Could not locate the Windsurf documentation source directory.\n"
            "Expected it at: blueprint.agent_generator/windsurf_docs/\n"
            "Make sure the package is installed with: pip install -e ."
        )

    @staticmethod
    def _print_summary(windsurf_dir: Path, copied: int, skipped: int) -> None:
        """Print a human-readable summary to stdout."""
        print(f"\nWindsurf resources generated in: {windsurf_dir}")
        print(f"  Files written : {copied}")
        if skipped:
            print(f"  Files skipped : {skipped}  (use --overwrite to replace)")
        print("\nNext steps:")
        print("  1. Open the project in Windsurf — Cascade will pick up the rules automatically.")
        print("  2. Use slash commands in the chat panel:")
        print("       /create-rest-api        /create-business-service")
        print("       /create-event-handler   /create-scheduler")
        print("       /create-agent-runtime   /create-vscode-settings")
