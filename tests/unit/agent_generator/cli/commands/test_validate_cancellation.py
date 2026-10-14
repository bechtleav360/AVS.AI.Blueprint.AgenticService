"""asbs validate warns about agent code that swallows asyncio.CancelledError (nats_handler_timeout)."""

from argparse import Namespace
from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands import validate
from blueprint.agent_generator.cli.utils.cancellation_check import swallowed_cancellation_warning, swallowed_cancellations


def _src(tmp_path: Path, code: str, name: str = "handler.py") -> Path:
    src = tmp_path / "src"
    (src / "handlers").mkdir(parents=True, exist_ok=True)
    (src / "handlers" / name).write_text(code, encoding="utf-8")
    return src


SWALLOWING = {
    "bare-except": "try:\n    pass\nexcept:\n    pass\n",
    "base-exception": "try:\n    pass\nexcept BaseException:\n    return_value = None\n",
    "cancelled-error": "import asyncio\ntry:\n    pass\nexcept asyncio.CancelledError:\n    pass\n",
    "imported-name": "from asyncio import CancelledError\ntry:\n    pass\nexcept CancelledError:\n    pass\n",
    "in-a-tuple": "import asyncio\ntry:\n    pass\nexcept (ValueError, asyncio.CancelledError):\n    pass\n",
    "suppress": "import asyncio, contextlib\nwith contextlib.suppress(asyncio.CancelledError):\n    pass\n",
    "raise-only-in-nested-def": "try:\n    pass\nexcept BaseException:\n    def later():\n        raise RuntimeError()\n",
}

FINE = {
    "exception": "try:\n    pass\nexcept Exception:\n    pass\n",
    "re-raised": "import asyncio\ntry:\n    pass\nexcept asyncio.CancelledError:\n    cleanup = 1\n    raise\n",
    "re-raised-base": "try:\n    pass\nexcept BaseException as exc:\n    raise RuntimeError() from exc\n",
    "suppress-other": "import contextlib\nwith contextlib.suppress(KeyError):\n    pass\n",
    "only-mentioned": '"""except asyncio.CancelledError: pass -- in a docstring"""\n# except BaseException:\n',
}


class TestTheCheck:
    @pytest.mark.parametrize("code", SWALLOWING.values(), ids=SWALLOWING.keys())
    def test_a_swallowed_cancellation_is_found_with_its_line(self, tmp_path: Path, code: str) -> None:
        found = swallowed_cancellations(_src(tmp_path, code))
        assert len(found) == 1
        assert found[0].startswith("src/handlers/handler.py:")

    @pytest.mark.parametrize("code", FINE.values(), ids=FINE.keys())
    def test_code_that_lets_it_through_is_not_reported(self, tmp_path: Path, code: str) -> None:
        assert swallowed_cancellations(_src(tmp_path, code)) == []

    def test_a_file_that_does_not_parse_is_not_this_checks_to_report(self, tmp_path: Path) -> None:
        assert swallowed_cancellations(_src(tmp_path, "def broken(:\n")) == []

    def test_the_warning_says_what_follows(self) -> None:
        warning = swallowed_cancellation_warning("orders", [f"src/x.py:{line}" for line in range(1, 8)])
        assert "Agent 'orders'" in warning
        assert "nats_handler_timeout" in warning and "nak'd" in warning
        assert "src/x.py:1" in warning and "and 2 more" in warning


class TestValidateReportsIt:
    def test_validate_warns_and_still_passes(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _src(
            tmp_path,
            "import asyncio\nasync def handle():\n    try:\n        pass\n    except asyncio.CancelledError:\n        return None\n",
        )
        (tmp_path / "tests").mkdir()
        (tmp_path / "settings.toml").write_text("[default]\nidempotency_enabled = true\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        (tmp_path / "src" / "main.py").write_text("from blueprint.agents.app_builder import AppBuilder\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exit_info:
            validate.run(Namespace(project_dir=str(tmp_path), group=False))

        assert exit_info.value.code == 0, "a warning, not an issue"
        out = capsys.readouterr().out
        assert "catches asyncio.CancelledError without re-raising it (src/handlers/handler.py:5)" in out
