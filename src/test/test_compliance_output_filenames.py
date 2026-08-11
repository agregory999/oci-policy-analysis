from pathlib import Path

import pytest
from oci_policy_analysis.application.core.repo.policy_analysis_repository import _resolve_compliance_output_csv


def test_resolves_legacy_compliance_output_filename(tmp_path: Path) -> None:
    expected = tmp_path / 'raw_data_identity_compartments.csv'
    expected.touch()

    assert _resolve_compliance_output_csv(str(tmp_path), expected.name) == str(expected)


def test_resolves_directory_prefixed_compliance_output_filename(tmp_path: Path) -> None:
    expected_names = (
        'raw_data_identity_domains.csv',
        'raw_data_identity_compartments.csv',
        'raw_data_identity_dynamic_groups.csv',
        'raw_data_identity_groups_and_membership.csv',
        'raw_data_identity_users.csv',
        'raw_data_identity_policies.csv',
    )

    for filename in expected_names:
        expected = tmp_path / f'{tmp_path.name}_{filename}'
        expected.touch()

        assert _resolve_compliance_output_csv(str(tmp_path), filename) == str(expected)


def test_missing_compliance_output_filename_lists_both_supported_names(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match='Expected one of') as error:
        _resolve_compliance_output_csv(str(tmp_path), 'raw_data_identity_compartments.csv')

    assert 'raw_data_identity_compartments.csv' in str(error.value)
    assert f'{tmp_path.name}_raw_data_identity_compartments.csv' in str(error.value)
