"""Tests for CLI permissions report export helpers."""

from pathlib import Path

from oci_policy_analysis.cli import _export_permissions_report, _permissions_report_paths


class _Logger:
    def __init__(self) -> None:
        self.messages: list[tuple] = []

    def info(self, *args) -> None:
        self.messages.append(args)

    def warning(self, *args) -> None:
        self.messages.append(args)


def _payload() -> dict:
    return {
        'report': {
            'root': {
                'resource-principal:compute/ocid1.compartment.oc1..app': {
                    'allow': ['OBJECT_READ'],
                    'deny': [],
                    'subject_type': 'resource-principal',
                    'original_subject_keys': ['any-group:None/any-group'],
                }
            }
        },
        'grant_rows': [
            {
                'effective_path': 'root',
                'grant_path': 'root',
                'principal_key': 'resource-principal:compute/ocid1.compartment.oc1..app',
                'original_subject_key': 'any-group:None/any-group',
                'principal_kind': 'resource-principal',
                'action': 'allow',
                'resource': 'objects',
                'permission': 'OBJECT_READ',
                'conditional': True,
                'inherited': False,
                'inherited_from': '',
                'policy_name': 'policy1',
                'statement_id': 'stmt1',
                'statement_text': 'allow any-group to read objects in tenancy',
            }
        ],
        'summary': {'allow_grant_count': 1, 'deny_grant_count': 0},
    }


def test_permissions_report_paths_for_both_formats(tmp_path: Path) -> None:
    paths = _permissions_report_paths(str(tmp_path / 'permissions'), 'both')

    assert paths == [
        ('json', tmp_path / 'permissions.json'),
        ('csv', tmp_path / 'permissions.csv'),
    ]


def test_export_permissions_report_writes_json_and_csv(tmp_path: Path) -> None:
    output_prefix = tmp_path / 'permissions'

    _export_permissions_report(_payload(), str(output_prefix), 'both', _Logger())

    assert (tmp_path / 'permissions.json').read_text(encoding='utf-8')
    csv_text = (tmp_path / 'permissions.csv').read_text(encoding='utf-8')
    assert 'effective_path,grant_path,principal_key,original_subject_key' in csv_text
    assert 'resource-principal:compute/ocid1.compartment.oc1..app' in csv_text
