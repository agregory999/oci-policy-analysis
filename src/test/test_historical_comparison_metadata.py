"""Historical comparison respects snapshot coverage and ttk Treeview's API."""

from types import SimpleNamespace

from oci_policy_analysis.application.services.historical_analysis_service import HistoricalAnalysisService
from oci_policy_analysis.presentation.desktop.historical_tab import HistoricalTab


class _Tree:
    def __init__(self):
        self.rows = []

    def get_children(self):
        return list(range(len(self.rows)))

    def delete(self, *args):
        self.rows.clear()

    def insert(self, parent, index, **kwargs):
        self.rows.append(kwargs.get('text'))

    def configure(self, **kwargs):
        if 'state' in kwargs:
            raise RuntimeError('unknown option -state')


def test_historical_tree_display_does_not_use_unsupported_state_option():
    tab = SimpleNamespace(
        policy_tree=_Tree(),
        identity_tree=_Tree(),
        identity_heading=SimpleNamespace(configure=lambda **kw: None),
        _populate_group_section=lambda *args: None,
        _set_status=lambda *args: None,
    )
    HistoricalTab._display_grouped(tab, [], [], False)
    HistoricalTab._display_grouped(tab, [], [], True)


def _service(left, right):
    return HistoricalAnalysisService(
        SimpleNamespace(
            load_cache_into_local_json=lambda *, cached_tenancy: left if cached_tenancy == 'left' else right
        )
    )


def test_policy_reload_still_compares_compartments_but_not_inherited_iam():
    left = {
        'tenancy_ocid': 'T',
        'snapshot_kind': 'full',
        'compartments': [{'id': 'c', 'name': 'Old'}],
        'dynamic_groups': [],
    }
    right = {**left, 'snapshot_kind': 'policy_reload', 'compartments': [{'id': 'c', 'name': 'New'}]}
    result = _service(left, right).compare_caches(left_cache='left', right_cache='right')
    assert [s.key for s in result.identity_sections] == ['compartments']
    assert result.identity_sections[0].modified == 1
    assert 'Dynamic Groups' in result.skipped_sections


def test_missing_inventory_is_not_reported_as_mass_deletion():
    left = {'groups': [{'group_ocid': 'g', 'group_name': 'G'}], 'users': []}
    right = {'users': [], 'load_all_users': False}
    result = _service(left, right).compare_caches(left_cache='left', right_cache='right')
    assert result.identity_sections == []
    assert 'Groups' in result.skipped_sections
    assert 'Users' in result.skipped_sections


def test_full_reload_with_legacy_reload_timestamp_can_compare_iam():
    snapshot = {'snapshot_kind': 'full_reload', 'policy_data_reloaded': 'old', 'groups': []}
    result = _service(snapshot, snapshot).compare_caches(left_cache='left', right_cache='right')
    assert [section.key for section in result.identity_sections] == ['groups']
    assert 'Groups' not in result.skipped_sections
    assert 'Reload All (IAM + policies)' in HistoricalAnalysisService.describe_snapshot(snapshot)


def test_different_tenancies_and_missing_cache_rejected():
    import pytest

    for left, right in [({'tenancy_ocid': 'A'}, {'tenancy_ocid': 'B'}), ({'groups': []}, None)]:
        with pytest.raises(ValueError):
            _service(left, right).compare_caches(left_cache='left', right_cache='right')


def test_scope_and_compliance_metadata_explain_unavailable_comparisons():
    left = {'recursive': True, 'policies': [], 'groups': []}
    right = {'recursive': False, 'policies': [], 'groups': [], 'compliance_capabilities': {'groups_inventory': False}}
    result = _service(left, right).compare_caches(left_cache='left', right_cache='right')
    assert not result.policy_sections
    assert not result.identity_sections
    assert 'scope differs' in result.skipped_sections['Policies']
    assert 'compliance export' in result.skipped_sections['Groups']


def test_reload_description_shows_provenance():
    description = HistoricalAnalysisService.describe_snapshot(
        {
            'policy_data_reloaded': '2026-09-09',
            'identity_data_as_of': '2026-09-08',
            'reload_source_cache_name': 'base.json',
            'load_all_users': False,
        }
    )
    assert 'Policy / compartment reload' in description
    assert 'Policies reloaded: 2026-09-09' in description
    assert 'IAM as of: 2026-09-08' in description
    assert 'Reload source: base.json' in description
    assert 'Users: not loaded' in description
