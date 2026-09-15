"""The documentation is reachable from the installed package, not just from the repository.

``README.md`` becomes the wheel's ``METADATA``, and it linked twenty-one pages that lived at the
repository root and were never packaged -- so every one of those links resolved to nothing once
installed, and an assistant working in a consuming project could not read the guide it was told to
read. The pages now ship inside ``blueprint/agent_generator/docs`` and ``asbs docs`` is what finds
them, wherever site-packages happens to be.

These tests hold the packaging, not the prose: that the directory is found through the package
rather than a path relative to the checkout, and that the pages the skills name by slug are the
pages that are actually there.
"""

import re
from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.docs import list_topics, locate_docs_root, resolve_topic

CLAUDE_DOCS = Path(__file__).resolve().parents[5] / "src" / "blueprint" / "agent_generator" / "claude_docs"

# "asbs docs <slug>" as written anywhere in a shipped skill or in the shipped CLAUDE.md.
DOCS_INVOCATION = re.compile(r"asbs docs ([A-Za-z0-9_][A-Za-z0-9_./-]*)")

# Flags, not slugs: "asbs docs --root" names no page.
NOT_A_SLUG = {"--root", "--cat"}


def cited_slugs() -> list[tuple[str, str]]:
    """Every (citing file, slug) pair the shipped assistant material tells a reader to open."""
    found = []
    for md in sorted(CLAUDE_DOCS.rglob("*.md")):
        for slug in DOCS_INVOCATION.findall(md.read_text(encoding="utf-8")):
            if slug not in NOT_A_SLUG:
                found.append((md.relative_to(CLAUDE_DOCS).as_posix(), slug))
    return found


class TestLocateDocsRoot:
    """Finding the packaged documentation."""

    def test_root_is_found_through_the_package(self) -> None:
        root = locate_docs_root()
        assert root.is_dir()
        # Resolved from the package, so it follows the package wherever it is installed.
        assert root.parent.name == "agent_generator"

    def test_root_holds_pages(self) -> None:
        assert list_topics(locate_docs_root())


class TestEveryPageIsReachable:
    """Every page that ships can be opened by the slug the listing gives for it."""

    def test_every_page_is_listed_by_its_slug(self) -> None:
        root = locate_docs_root()
        for slug in list_topics(root):
            assert resolve_topic(root, slug).is_file()


class TestResolveTopic:
    """What the caller is allowed to type."""

    def test_full_slug(self, tmp_path: Path) -> None:
        (tmp_path / "guides").mkdir()
        (tmp_path / "guides" / "testing.md").write_text("# Testing", encoding="utf-8")
        assert resolve_topic(tmp_path, "guides/testing").name == "testing.md"

    def test_md_suffix_is_tolerated(self, tmp_path: Path) -> None:
        (tmp_path / "testing.md").write_text("# Testing", encoding="utf-8")
        assert resolve_topic(tmp_path, "testing.md").name == "testing.md"

    def test_bare_name_when_unambiguous(self, tmp_path: Path) -> None:
        (tmp_path / "guides").mkdir()
        (tmp_path / "guides" / "troubleshooting.md").write_text("# T", encoding="utf-8")
        assert resolve_topic(tmp_path, "troubleshooting").name == "troubleshooting.md"

    def test_bare_name_matching_two_pages_is_refused(self, tmp_path: Path) -> None:
        """Refused rather than guessed: picking one of two silently sends half the readers wrong."""
        for folder in ("guides", "concepts"):
            (tmp_path / folder).mkdir()
            (tmp_path / folder / "caching.md").write_text("# Caching", encoding="utf-8")

        with pytest.raises(FileNotFoundError, match="ambiguous"):
            resolve_topic(tmp_path, "caching")

    def test_unknown_topic_names_the_way_out(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="asbs docs"):
            resolve_topic(tmp_path, "no-such-page")


class TestListTopics:
    """Slugs are what a skill writes, so they are posix and suffix-free."""

    def test_slugs_are_relative_posix_without_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "guides").mkdir()
        (tmp_path / "guides" / "deployment.md").write_text("# D", encoding="utf-8")
        (tmp_path / "top.md").write_text("# T", encoding="utf-8")

        assert list_topics(tmp_path) == ["guides/deployment", "top"]


class TestSkillsCiteRealPages:
    """The skills point at the docs rather than restating them, so the pointers have to land.

    A skill is written once and the docs move afterwards; the citation is the part that rots.
    Parsing the skills rather than listing their slugs here keeps this guard true of skills
    written after this test.
    """

    def test_some_skill_cites_the_docs(self) -> None:
        """Guards the parser: a regex that silently matches nothing would pass every case below."""
        assert cited_slugs()

    @pytest.mark.parametrize(
        ("citing_file", "slug"),
        cited_slugs(),
        ids=lambda v: v.replace("/", "-"),
    )
    def test_cited_slug_resolves(self, citing_file: str, slug: str) -> None:
        root = locate_docs_root()
        try:
            resolve_topic(root, slug)
        except FileNotFoundError as e:
            pytest.fail(f"{citing_file} tells the reader to run 'asbs docs {slug}', which fails: {e}")
