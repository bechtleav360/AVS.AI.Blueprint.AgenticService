"""What ``asbs claude`` copies into a project, and what it tells the user it copied.

The skill list used to be printed from a hand-maintained block, so a skill added to
``claude_docs/skills/`` was copied but never announced -- and nothing noticed that the migration
guide had no skill at all. These tests hold the shipped skills, the generator's announcement and
the shipped ``CLAUDE.md`` to one another.
"""

import re
from pathlib import Path

import pytest

from blueprint.agent_generator.generator.claude_generator import ClaudeGenerator

CLAUDE_DOCS = Path(__file__).resolve().parents[4] / "src" / "blueprint" / "agent_generator" / "claude_docs"

SKILL_DIRS = sorted(path.parent for path in (CLAUDE_DOCS / "skills").glob("*/SKILL.md"))

FRONTMATTER_NAME = re.compile(r"\A---\s*\n(?:.*\n)*?name:\s*(\S+)\s*\n(?:.*\n)*?---\s*\n")


def test_the_migration_guide_has_a_skill() -> None:
    assert "blueprint-migration" in [d.name for d in SKILL_DIRS]


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda d: d.name)
def test_skill_frontmatter_name_matches_its_directory(skill_dir: Path) -> None:
    match = FRONTMATTER_NAME.match((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    assert match is not None, f"{skill_dir.name}/SKILL.md has no frontmatter name"
    assert match.group(1) == skill_dir.name


def test_skill_names_reads_every_shipped_skill() -> None:
    assert ClaudeGenerator(".").skill_names() == [d.name for d in SKILL_DIRS]


def test_generate_copies_and_announces_every_skill(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ClaudeGenerator(tmp_path).generate()
    out = capsys.readouterr().out

    for skill_dir in SKILL_DIRS:
        assert (tmp_path / ".claude" / "skills" / skill_dir.name / "SKILL.md").is_file()
        assert f"/{skill_dir.name}\n" in out
    for agent in (CLAUDE_DOCS / "agents").glob("*.md"):
        assert f"@{agent.stem}\n" in out


@pytest.mark.parametrize("skill_dir", [d for d in SKILL_DIRS if d.name.startswith("blueprint-")], ids=lambda d: d.name)
def test_shipped_claude_md_points_at_every_reference_skill(skill_dir: Path) -> None:
    assert f"`{skill_dir.name}`" in (CLAUDE_DOCS / "CLAUDE.md").read_text(encoding="utf-8")
