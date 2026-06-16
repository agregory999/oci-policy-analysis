from oci_policy_analysis.presentation.desktop.workload_principals_tab import (
    ALL_POLICY_COLUMNS,
    BASIC_POLICY_COLUMNS,
    POLICY_COLUMN_WIDTHS,
)


def test_workload_principals_default_columns_show_condition_elements_and_match_details():
    assert 'Conditions' not in ALL_POLICY_COLUMNS
    assert 'Conditions' not in POLICY_COLUMN_WIDTHS
    assert 'Conditions (parsed structure)' in BASIC_POLICY_COLUMNS
    assert 'Conditions (elements)' in BASIC_POLICY_COLUMNS
    assert (
        BASIC_POLICY_COLUMNS.index('Conditions (elements)')
        == BASIC_POLICY_COLUMNS.index('Conditions (parsed structure)') + 1
    )
    assert 'Match Confidence' in BASIC_POLICY_COLUMNS
    assert 'Match Confidence Reason' in BASIC_POLICY_COLUMNS
