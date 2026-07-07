import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.check_public_docstrings import find_missing  # noqa: E402


def test_public_docstring_coverage() -> None:
    """Maintained public source symbols have Google/Napoleon docstrings."""

    root = Path(__file__).parents[1] / 'oci_policy_analysis'
    assert find_missing(root) == []
