import pytest
from oci_policy_analysis.logic.consolidation_helpers import rewritten_location_for_target


@pytest.mark.parametrize(
    'effective_path, target_path, expected',
    [
        (['ROOT', 'LZ1-Top', 'application-cmp'], ['ROOT', 'LZ1-Top'], 'application-cmp'),
        (['ROOT', 'LZ1-Top', 'App', 'DB'], ['ROOT', 'LZ1-Top', 'App'], 'DB'),
        (['ROOT', 'LZ1-Top', 'App', 'DB'], ['ROOT', 'LZ1-Top', 'App', 'DB'], 'DB'),
        (['ROOT', 'LZ1-Top', 'App', 'DB'], ['ROOT', 'LZ1-Top'], 'App:DB'),
        (['ROOT', 'Main', 'App'], ['ROOT', 'Other'], ''),
        (['ROOT', 'Region'], ['ROOT', 'Region'], 'Region'),
        (['ROOT', 'Comp1'], ['ROOT', 'Comp1'], 'Comp1'),
        (['ROOT', 'A', 'B'], ['ROOT', 'A'], 'B'),
        (['ROOT', 'A', 'B'], ['ROOT', 'A', 'B'], 'B'),
        ([], ['ROOT'], ''),
    ],
)
def test_rewritten_location_for_target(effective_path, target_path, expected):
    result = rewritten_location_for_target(effective_path, target_path)
    assert result == expected, f'expected {expected!r} but got {result!r} for {effective_path=}, {target_path=}'
