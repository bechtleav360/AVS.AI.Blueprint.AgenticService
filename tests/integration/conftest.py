"""Everything in this directory needs something running, and is marked so automatically.

The split used to be enforced three ways at once and agreed with itself in none of them (#80):
CI selected by *directory* (`tests/unit`), the `integration` marker was applied by *hand* to three
tests out of roughly sixty, and the rest of this directory was unmarked -- so `-m "not integration"`
deselected almost nothing, and `tests/integration/` was simultaneously red and invisible.

One rule now: **a test here requires an external service.** The marker is applied by location, so
the directory and the marker cannot drift apart and no contributor has to remember the decorator.
The other half of the rule is what this file cannot enforce and a review must -- a test that needs
nothing running does not belong here. Two that did were moved out rather than marked.
"""

from pathlib import Path

import pytest

INTEGRATION_ROOT = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test collected from this directory as ``integration``."""
    for item in items:
        if INTEGRATION_ROOT in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.integration)
