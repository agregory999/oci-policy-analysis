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


def test_json_field_changes_preserve_null_presence_types_and_literal_paths():
    service = _service({}, {})
    changes = service._extract_changed_fields(
        {'null_removed': None, 'flag': True, 'a.b': {'x/y': 1}, 'array': [None]},
        {'null_added': None, 'flag': 1, 'a.b': {'x/y': 2}, 'array': []},
    )
    by_field = {item['field']: item for item in changes}
    assert by_field['null_removed']['action'] == 'Removed'
    assert by_field['null_removed']['old_present'] and not by_field['null_removed']['new_present']
    assert by_field['null_added']['action'] == 'Added'
    assert by_field['null_added']['new'] is None
    assert by_field['flag']['old'] is True and type(by_field['flag']['new']) is int
    assert by_field['a.b.x/y']['path'] == ['a.b', 'x/y']
    assert by_field['array[0]']['new_present'] is False


def test_meaningful_comparison_ignores_ephemeral_ids_but_keeps_full_source():
    from copy import deepcopy

    left = {
        'tenancy_ocid': 'T',
        'groups': [{'group_ocid': 'g', 'group_name': 'G', 'internal_id': 'old', 'members': ['A'], '_runtime': 1}],
    }
    right = deepcopy(left)
    right['groups'][0].update(internal_id='new', _runtime=2)
    service = _service(left, right)
    assert service.compare_caches(left_cache='left', right_cache='right').identity_sections[0].modified == 1
    assert (
        service.compare_caches(left_cache='left', right_cache='right', meaningful_only=True)
        .identity_sections[0]
        .modified
        == 0
    )
    right['groups'][0]['members'].append('B')
    before = deepcopy((left, right))
    result = service.compare_caches(left_cache='left', right_cache='right', meaningful_only=True)
    item = result.identity_sections[0].items[0]
    assert item.old_value['internal_id'] == 'old' and item.new_value['internal_id'] == 'new'
    assert item.changed_fields[0]['field'] == 'members[1]'
    assert (left, right) == before
    assert result.metadata['tenancy_verified'] is True


def test_runtime_only_fields_do_not_count_as_modified_and_entity_order_is_ignored():
    left = {'groups': [{'group_ocid': 'g1', '_runtime': 1}, {'group_ocid': 'g2'}]}
    right = {'groups': [{'group_ocid': 'g2'}, {'group_ocid': 'g1', '_runtime': 2}]}
    section = _service(left, right).compare_caches(left_cache='left', right_cache='right').identity_sections[0]
    assert (section.added, section.removed, section.modified) == (0, 0, 0)


def test_meaningful_statement_matching_ignores_runtime_keys_and_preserves_duplicates():
    from copy import deepcopy

    statement = {
        'policy_ocid': 'p',
        'statement_text': 'allow group G to read buckets in tenancy',
        'internal_id': 'old',
        'stable_key': 'old-key',
    }
    left = {'policy_statements': [statement, deepcopy(statement)], 'cross_tenancy_statements': [statement]}
    right = deepcopy(left)
    for key in ('policy_statements', 'cross_tenancy_statements'):
        for row in right[key]:
            row.update(internal_id='new', stable_key='new-key')
    result = _service(left, right).compare_caches(left_cache='left', right_cache='right', meaningful_only=True)
    assert all(section.modified == section.added == section.removed == 0 for section in result.policy_sections)
    right['policy_statements'].pop()
    result = _service(left, right).compare_caches(left_cache='left', right_cache='right', meaningful_only=True)
    regular = next(section for section in result.policy_sections if section.key == 'policy_statements')
    assert (regular.added, regular.removed, regular.modified) == (0, 1, 0)


def test_meaningful_comparison_keeps_arbitrary_nested_tag_keys_literal():
    from copy import deepcopy

    left = {
        'policies': [
            {
                'policy_ocid': 'p',
                'internal_id': 'old',
                'freeform_tags': {'internal_id': 'before', '_owner': 'Alice'},
                'defined_tags': {'Audit': {'stable_key': 'before'}},
            }
        ]
    }
    right = deepcopy(left)
    right['policies'][0]['internal_id'] = 'new'
    right['policies'][0]['freeform_tags'] = {'internal_id': 'after', '_owner': 'Bob'}
    right['policies'][0]['defined_tags']['Audit']['stable_key'] = 'after'
    result = _service(left, right).compare_caches(left_cache='left', right_cache='right', meaningful_only=True)
    item = result.policy_sections[0].items[0]
    assert {field['field'] for field in item.changed_fields} == {
        'freeform_tags.internal_id',
        'freeform_tags._owner',
        'defined_tags.Audit.stable_key',
    }


def test_incomplete_snapshot_policy_removal_is_observable_only_with_explicit_warning():
    from copy import deepcopy

    left = {
        'tenancy_ocid': 'T',
        'inventory_complete': False,
        'policies': [
            {'policy_ocid': 'p1', 'policy_name': 'retained'},
            {'policy_ocid': 'p2', 'policy_name': 'deleted'},
        ],
        'policy_statements': [],
        'snapshot_kind': 'full',
    }
    right = deepcopy(left)
    right['policies'].pop()
    before = deepcopy((left, right))
    service = _service(left, right)
    strict = service.compare_caches(left_cache='left', right_cache='right')
    assert not strict.policy_sections and not strict.identity_sections
    observed = service.compare_caches(left_cache='left', right_cache='right', include_incomplete=True)
    policies = next(section for section in observed.policy_sections if section.key == 'policies')
    assert policies.removed == 1 and policies.items[0].title == 'deleted'
    assert 'not confirmed OCI' in observed.section_warnings[policies.section]
    assert 'Users' in observed.skipped_sections
    assert (left, right) == before


def test_incomplete_opt_in_does_not_override_inherited_iam_or_scope_mismatch():
    left = {
        'inventory_complete': False,
        'groups': [],
        'snapshot_kind': 'policy_reload',
        'recursive': True,
        'policies': [],
    }
    right = {'inventory_complete': False, 'groups': [], 'snapshot_kind': 'full', 'recursive': False, 'policies': []}
    result = _service(left, right).compare_caches(left_cache='left', right_cache='right', include_incomplete=True)
    assert not result.identity_sections and not result.policy_sections
    assert result.skipped_sections


def test_comment_only_statement_edits_are_modifications_without_mutating_snapshots():
    from copy import deepcopy

    for key, source in (
        ('policy_statements', 'allow group G to read buckets in tenancy'),
        ('cross_tenancy_statements', 'admit group G of tenancy T to read buckets in tenancy'),
    ):
        left = {key: [{'policy_ocid': 'p', 'statement_text': source + ' // old', 'comments': 'old'}]}
        right = {key: [{'policy_ocid': 'p', 'statement_text': source + ' // new', 'comments': 'new'}]}
        before = deepcopy((left, right))
        section = _service(left, right).compare_snapshots(left, right, meaningful_only=True).policy_sections[0]
        assert (section.added, section.removed, section.modified) == (0, 0, 1)
        assert {change['field'] for change in section.items[0].changed_fields} == {'statement_text', 'comments'}
        assert (left, right) == before


def test_comment_matching_keeps_exact_duplicate_matches_before_pairing_edits():
    source = 'allow group G to read buckets in tenancy'
    left = {'policy_statements': [{'policy_ocid': 'p', 'statement_text': source + ' // ' + c} for c in ('A', 'B')]}
    right = {'policy_statements': [{'policy_ocid': 'p', 'statement_text': source + ' // ' + c} for c in ('C', 'A')]}
    section = _service(left, right).compare_snapshots(left, right, meaningful_only=True).policy_sections[0]
    assert (section.added, section.removed, section.modified) == (0, 0, 1)
    assert section.items[0].old_value['statement_text'].endswith('// B')
    assert section.items[0].new_value['statement_text'].endswith('// C')


def test_comment_matching_preserves_quoted_slashes_permissions_and_policy_scope():
    source = "allow group G to read buckets in tenancy where target.bucket.name = 'a//b'"
    left = {'policy_statements': [{'policy_ocid': 'p', 'statement_text': source + ' // old'}]}
    for policy, text in (
        ('p', source.replace('a//b', 'a//c') + ' // new'),
        ('p', source.replace('read', 'manage') + ' // new'),
        ('other-policy', source + ' // new'),
    ):
        right = {'policy_statements': [{'policy_ocid': policy, 'statement_text': text}]}
        section = _service(left, right).compare_snapshots(left, right, meaningful_only=True).policy_sections[0]
        assert (section.added, section.removed, section.modified) == (1, 1, 0)
    right = {'policy_statements': [{'policy_ocid': 'p', 'statement_text': source}]}
    section = _service(left, right).compare_snapshots(left, right, meaningful_only=True).policy_sections[0]
    assert (section.added, section.removed, section.modified) == (0, 0, 1)
