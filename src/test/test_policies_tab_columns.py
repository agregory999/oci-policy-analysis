from oci_policy_analysis.presentation.desktop.policies_tab import ALL_POLICY_COLUMNS, POLICY_COLUMN_WIDTHS


def test_policy_tab_uses_single_raw_condition_column():
    assert 'Conditions' not in ALL_POLICY_COLUMNS
    assert 'Conditions' not in POLICY_COLUMN_WIDTHS
    assert 'Conditions (where clause)' in ALL_POLICY_COLUMNS
    assert 'Conditions (parsed structure)' in ALL_POLICY_COLUMNS
    assert 'Conditions (elements)' in ALL_POLICY_COLUMNS
