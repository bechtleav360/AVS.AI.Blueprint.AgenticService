"""Where an agent's files belong, and what it means to find one somewhere else.

An agent is the same directory whether it runs on its own or as one of twenty, which is what
lets it move between repositories unchanged. That only holds if every artefact has exactly one
place it can be, so this module states those places once and both the runtime and ``asbs
validate`` read them from here rather than each having an opinion.

A file in the wrong place is **refused, not ignored**. The failure this prevents is the one that
started this module: a ``settings.toml`` the framework did not look at is not an error at
startup, it is an agent quietly running on the group's defaults -- discovered later, from
behaviour, in an environment where it matters.
"""

from dataclasses import dataclass
from pathlib import Path

__all__ = ["MISPLACED", "MisplacedArtifact", "ExpectedArtifact", "check_agent_layout"]


@dataclass(frozen=True)
class ExpectedArtifact:
    """One file with a single legal location, and the places that are certainly mistakes.

    Attributes:
        filename: The file's name.
        expected: Where it belongs, relative to the agent's root. ``""`` is the root itself;
            ``None`` means it does not belong under an agent at all.
        wrong: Directories relative to the agent's root where finding it is a mistake rather
            than a coincidence.
        reason: What goes wrong when it sits in the wrong place, in the message the author reads.
    """

    filename: str
    expected: str | None
    wrong: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class MisplacedArtifact:
    """One artefact found where it cannot be read from."""

    filename: str
    found_at: Path
    belongs_at: Path
    reason: str

    def describe(self, agent: str) -> str:
        """Return the message shown for this agent, naming both paths and the consequence."""
        return (
            f"Agent '{agent}' has '{self.filename}' at {self.found_at}, and that is not where it is read from. "
            f"Move it to {self.belongs_at}. {self.reason}"
        )


MISPLACED: tuple[ExpectedArtifact, ...] = (
    ExpectedArtifact(
        filename="settings.toml",
        expected="",
        wrong=("src",),
        reason=(
            "An agent's settings sit beside its 'src', exactly as they do when it runs standalone -- that sameness "
            "is what lets the directory move between a group and its own repository untouched."
        ),
    ),
    ExpectedArtifact(
        filename=".secrets.toml",
        expected="",
        wrong=("src",),
        reason="Secrets are read from beside 'src', alongside settings.",
    ),
    ExpectedArtifact(
        filename="agents.toml",
        expected=None,
        wrong=("", "src"),
        reason=(
            "The agent map belongs to the image, not to an agent: it says which agents an image contains, which is "
            "a packaging decision. An agent that carries one is an agent that knows whether it is running alone. "
            "An agent served on its own needs no map at all -- 'uvicorn src.main:create_app --factory' builds this "
            "declaration directly, because a group of one is still a group."
        ),
    ),
)
"""Every artefact with one legal location. Seeded with the three we have been bitten by; a new
entry is one tuple, and both the runtime refusal and ``asbs validate`` pick it up."""


def check_agent_layout(root: Path) -> list[MisplacedArtifact]:
    """Return every artefact of ``root`` that is somewhere it cannot be read from.

    Args:
        root: The agent's own directory, as the agent map's ``root`` names it.

    Returns:
        One entry per misplaced file, in the order :data:`MISPLACED` declares them. Empty when
        the layout is right, which is the only case that starts.
    """
    found: list[MisplacedArtifact] = []
    for artifact in MISPLACED:
        for wrong in artifact.wrong:
            candidate = root / wrong / artifact.filename if wrong else root / artifact.filename
            if not candidate.is_file():
                continue
            belongs = root / artifact.expected / artifact.filename if artifact.expected is not None else Path("the image root")
            found.append(
                MisplacedArtifact(
                    filename=artifact.filename,
                    found_at=candidate,
                    belongs_at=belongs,
                    reason=artifact.reason,
                )
            )
    return found
