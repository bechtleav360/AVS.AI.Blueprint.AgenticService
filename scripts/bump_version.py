"""Utility for bumping the project version for PyPI releases."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import re
import subprocess
import sys
import tomllib

import semver


class VersionBumpError(RuntimeError):
    """Raised when the version bump process fails."""


@dataclass
class VersionContext:
    """Holds contextual information for the version bump operation."""

    pyproject_path: Path
    repo_root: Path
    tag_prefix: str


class PyProjectVersionBumper:
    """Encapsulates the logic for bumping the patch version in pyproject.toml."""

    VERSION_PATTERN = re.compile(r'^(\s*version\s*=\s*")(?P<version>[^\"]+)(")', re.MULTILINE)

    def __init__(self, context: VersionContext) -> None:
        self._context = context
        self._original_content = self._read_text()
        self._updated_content: str | None = None
        self._current_version = self._read_current_version()

    def bump_patch_version(self) -> str:
        """Bumps the patch component of the current version."""

        next_version = semver.VersionInfo.parse(self._current_version).bump_patch()
        replacement = self.VERSION_PATTERN.sub(
            rf'\g<1>{next_version}\3',
            self._original_content,
            count=1,
        )
        if replacement == self._original_content:
            raise VersionBumpError("Failed to update version in pyproject.toml")

        self._updated_content = replacement
        self._write_text(replacement)
        return str(next_version)

    def stage_changes(self) -> None:
        """Stages the modified pyproject.toml for commit."""

        self._run_git_command(["git", "add", str(self._context.pyproject_path)])

    def commit_changes(self, new_version: str) -> None:
        """Commits the staged version bump change."""

        message = f"chore: bump version to {new_version}"
        self._run_git_command(["git", "commit", "-m", message])

    def create_tag(self, new_version: str) -> str:
        """Creates an annotated git tag for the new version."""

        tag_name = f"{self._context.tag_prefix}{new_version}"
        self._run_git_command(["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"])
        return tag_name

    def has_changes(self) -> bool:
        """Checks whether the version update produced file changes."""

        return self._updated_content is not None and self._updated_content != self._original_content

    def _read_text(self) -> str:
        return self._context.pyproject_path.read_text(encoding="utf-8")

    def _write_text(self, content: str) -> None:
        self._context.pyproject_path.write_text(content, encoding="utf-8")

    def _read_current_version(self) -> str:
        with self._context.pyproject_path.open("rb") as handle:
            pyproject_data = tomllib.load(handle)

        project_section = pyproject_data.get("project")
        if project_section is None or "version" not in project_section:
            raise VersionBumpError("Missing [project] version in pyproject.toml")
        return str(project_section["version"])

    def _run_git_command(self, command: list[str]) -> None:
        subprocess.run(command, check=True, cwd=self._context.repo_root)


class VersionBumpCLI:
    """Command-line interface for the version bump utility."""

    def run(self, argv: list[str] | None = None) -> None:
        args = self._parse_args(argv)
        context = VersionContext(
            pyproject_path=args.pyproject_path.resolve(),
            repo_root=args.repo_root.resolve(),
            tag_prefix=args.tag_prefix,
        )
        bumper = PyProjectVersionBumper(context)

        new_version = bumper.bump_patch_version()
        if not bumper.has_changes():
            return

        if not args.skip_commit:
            bumper.stage_changes()
            bumper.commit_changes(new_version)

        if not args.skip_tag:
            bumper.create_tag(new_version)

        if args.push:
            self._push_changes(context.repo_root)

    def _parse_args(self, argv: list[str] | None) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Bump the patch version for the base package.")
        parser.add_argument(
            "--pyproject-path",
            type=Path,
            default=Path("base/pyproject.toml"),
            help="Path to pyproject.toml",
        )
        parser.add_argument(
            "--repo-root",
            type=Path,
            default=Path("."),
            help="Path to the repository root (used for git commands)",
        )
        parser.add_argument(
            "--tag-prefix",
            type=str,
            default="v",
            help="Prefix to prepend to git tag names",
        )
        parser.add_argument(
            "--skip-commit",
            action="store_true",
            help="Skip committing the version bump",
        )
        parser.add_argument(
            "--skip-tag",
            action="store_true",
            help="Skip creating a git tag",
        )
        parser.add_argument(
            "--push",
            action="store_true",
            help="Push commits and tags to origin after bumping",
        )
        return parser.parse_args(argv)

    def _push_changes(self, repo_root: Path) -> None:
        self._run_git_command(["git", "push", "origin", "HEAD"], repo_root)
        self._run_git_command(["git", "push", "origin", "--tags"], repo_root)

    def _run_git_command(self, command: list[str], repo_root: Path) -> None:
        subprocess.run(command, check=True, cwd=repo_root)


if __name__ == "__main__":
    try:
        VersionBumpCLI().run(sys.argv[1:])
    except VersionBumpError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as error:
        print(f"Git command failed: {error}", file=sys.stderr)
        sys.exit(error.returncode)
