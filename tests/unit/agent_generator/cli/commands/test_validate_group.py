"""`asbs validate --group` -- the image, its agent map, and the agents the map points at.

What these hold is the one thing the command exists for: that it agrees with the runtime. It is
worse than useless when it does not, because its verdict is phrased as "would stop this image
starting" -- so a disagreement is not a missing check, it is a false statement about a working
image, and the reader's correct response is to break a layout that worked.

The disagreement these pin is real and shipped: the runtime resolves every agent `root` against
the image root and lets `BLUEPRINT_AGENT_MAP` put the map anywhere, while this command used to
resolve roots against whichever directory the map sat in. The two coincide in the scaffolded
layout, where the map is at the image root, which is why nothing caught it.
"""

from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.validate_group import _agent_map_path, _findings

MAP_ENV = "BLUEPRINT_AGENT_MAP"


def _agent_dir(root: Path) -> None:
    """Write the smallest directory that is a valid agent: settings beside `src/`."""
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text("agent = None\n", encoding="utf-8")
    (root / "settings.toml").write_text('[default]\nmodel_name = "x"\n', encoding="utf-8")


def _map_text(root: str, module: str = "agents.orders.src.main:agent") -> str:
    return f'[agents.orders]\nroot   = "{root}"\nmodule = "{module}"\n'


class TestWhereTheMapMayLive:
    """The map is a packaging manifest; where it sits does not define the image root."""

    def test_the_scaffolded_layout_has_the_map_at_the_image_root(self, tmp_path: Path) -> None:
        _agent_dir(tmp_path / "agents" / "orders")
        (tmp_path / "agents.toml").write_text(_map_text("agents/orders"), encoding="utf-8")

        issues, _, _ = _findings(tmp_path, _agent_map_path(tmp_path, None))

        assert issues == []

    def test_a_map_below_the_image_root_still_resolves_roots_against_that_root(self, tmp_path: Path) -> None:
        """The reported case: `deploy/agents.toml`, agents at the top. The runtime accepts it."""
        _agent_dir(tmp_path / "agents" / "riskmanagement" / "risk_identifier")
        (tmp_path / "deploy").mkdir()
        (tmp_path / "deploy" / "agents.toml").write_text(
            '[agents.risk_identifier]\nroot   = "agents/riskmanagement/risk_identifier"\n'
            'module = "agents.riskmanagement.risk_identifier.src.main:agent"\n',
            encoding="utf-8",
        )

        issues, _, _ = _findings(tmp_path, _agent_map_path(tmp_path, "deploy/agents.toml"))

        assert issues == [], "Resolving the root against deploy/ rather than the image root is the defect."

    def test_an_absent_map_names_the_flag_that_points_at_one(self, tmp_path: Path) -> None:
        issues, _, _ = _findings(tmp_path, _agent_map_path(tmp_path, None))

        assert len(issues) == 1
        assert "--agent-map" in issues[0], "A reader whose map is elsewhere needs to be told there is a way to say so."
        assert MAP_ENV in issues[0]

    def test_a_root_outside_the_image_is_still_refused(self, tmp_path: Path) -> None:
        """Relocating the map does not relax the rule that an agent's files are part of the image."""
        _agent_dir(tmp_path / "outside")
        image = tmp_path / "image"
        image.mkdir()
        (image / "agents.toml").write_text(_map_text("../outside"), encoding="utf-8")

        issues, _, _ = _findings(image, _agent_map_path(image, None))

        assert any("outside the image" in issue for issue in issues)


class TestResolvingTheMapPath:
    """`--agent-map` and `BLUEPRINT_AGENT_MAP` resolve the way the runtime resolves them."""

    def test_the_default_is_the_map_in_the_directory_being_validated(self, tmp_path: Path) -> None:
        assert _agent_map_path(tmp_path, None) == tmp_path / "agents.toml"

    def test_a_relative_flag_resolves_against_the_image_root(self, tmp_path: Path) -> None:
        assert _agent_map_path(tmp_path, "deploy/agents.toml") == tmp_path / "deploy" / "agents.toml"

    def test_an_absolute_flag_is_taken_as_it_is(self, tmp_path: Path) -> None:
        absolute = tmp_path / "elsewhere" / "agents.toml"

        assert _agent_map_path(tmp_path, str(absolute)) == absolute

    def test_the_environment_supplies_it_when_the_flag_does_not(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MAP_ENV, "deploy/agents.toml")

        assert _agent_map_path(tmp_path, None) == tmp_path / "deploy" / "agents.toml"

    def test_the_flag_wins_over_the_environment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MAP_ENV, "from/env.toml")

        assert _agent_map_path(tmp_path, "from/flag.toml") == tmp_path / "from" / "flag.toml"
