"""Tests for policy intelligence invalid-statement checks.

Focused coverage for tag namespace/key validation in where-clause conditions.
"""

from types import SimpleNamespace

import pytest
from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key
from oci_policy_analysis.application.core.engine.policy_intelligence_engine import PolicyIntelligenceEngine


class _RiskRefRepo:
    """Minimal reference repo for risk-scoring tests."""

    family_name_map: dict[str, str] = {}
    resource_name_map: dict[str, str] = {}
    data = {'resources': {}, 'families': {}}

    def get_verb_resource_risk(self, verb: str, resource: str) -> int:
        if verb == 'manage' and resource == 'all-resources':
            return 1000
        return 0

    def get_permissions_risk_sum(self, _permissions, _resource=None) -> int:
        return 0


def _build_engine_with_statement(statement: dict, catalog: dict):
    """Create a PolicyIntelligenceEngine with a minimal repo stub for tests."""
    repo = SimpleNamespace(
        regular_statements=[statement],
        dynamic_groups=[],
        groups=[],
        defined_tag_namespace_keys=catalog,
    )
    return PolicyIntelligenceEngine(repo, strategies=[]), repo


def _base_statement() -> dict:
    return {
        'statement_text': 'allow group Administrators to manage all-resources in tenancy',
        'subject_type': 'group',
        'subject': [('Default', 'Administrators')],
        'verb': 'manage',
        'conditions': "request.principal.group.tag.MyTagNamespace.MyTag = 'sample'",
        'valid': True,
        'invalid_reasons': [],
    }


def _build_engine_with_compartment_repo() -> tuple[PolicyIntelligenceEngine, dict[str, str]]:
    """Create a minimal repo with a deterministic compartment hierarchy for path tests."""

    tenancy_ocid = 'ocid1.tenancy.oc1..tenancy'
    ids = {
        'tenancy': tenancy_ocid,
        'finance': 'ocid1.compartment.oc1..finance',
        'apps': 'ocid1.compartment.oc1..apps',
        'subapps': 'ocid1.compartment.oc1..subapps',
        'dev': 'ocid1.compartment.oc1..dev',
    }

    repo = SimpleNamespace(
        tenancy_ocid=tenancy_ocid,
        compartments=[
            {
                'id': ids['tenancy'],
                'name': 'root',
                'parent_id': None,
                'hierarchy_path': 'root',
            },
            {
                'id': ids['finance'],
                'name': 'Finance',
                'parent_id': ids['tenancy'],
                'hierarchy_path': 'root/finance',
            },
            {
                'id': ids['apps'],
                'name': 'Apps',
                'parent_id': ids['finance'],
                'hierarchy_path': 'root/finance/apps',
            },
            {
                'id': ids['subapps'],
                'name': 'SubApps',
                'parent_id': ids['apps'],
                'hierarchy_path': 'root/finance/apps/subapps',
            },
            {
                'id': ids['dev'],
                'name': 'Dev',
                'parent_id': ids['tenancy'],
                'hierarchy_path': 'root/dev',
            },
        ],
        regular_statements=[],
        dynamic_groups=[],
        groups=[],
        defined_tag_namespace_keys={},
    )
    return PolicyIntelligenceEngine(repo, strategies=[]), ids


def test_find_invalid_statements_flags_missing_tag_namespace():
    statement = _base_statement()
    engine, repo = _build_engine_with_statement(
        statement,
        {
            'AnotherNamespace': {
                'keys': {'MyTag': None},
            }
        },
    )

    engine.find_invalid_statements()

    st = repo.regular_statements[0]
    assert st.get('valid') is False
    assert any('Tag namespace' in reason and 'MyTagNamespace' in reason for reason in st.get('invalid_reasons', []))


def test_find_invalid_statements_flags_missing_tag_key_in_existing_namespace():
    statement = _base_statement()
    engine, repo = _build_engine_with_statement(
        statement,
        {
            'MyTagNamespace': {
                'keys': {'AnotherKey': None},
            }
        },
    )

    engine.find_invalid_statements()

    st = repo.regular_statements[0]
    assert st.get('valid') is False
    assert any("Tag key 'MyTag'" in reason for reason in st.get('invalid_reasons', []))


def test_find_invalid_statements_accepts_existing_namespace_and_key_case_insensitive():
    statement = _base_statement()
    # Purposefully vary case to ensure case-insensitive matching.
    statement['conditions'] = "request.principal.group.tag.mytagnamespace.mytag = 'sample'"
    engine, repo = _build_engine_with_statement(
        statement,
        {
            'MyTagNamespace': {
                'keys': {'MyTag': None},
            }
        },
    )

    engine.find_invalid_statements()

    st = repo.regular_statements[0]
    assert not any('Tag namespace' in reason or 'Tag key' in reason for reason in st.get('invalid_reasons', []))


def test_find_invalid_statements_skips_tag_existence_when_catalog_unavailable():
    statement = _base_statement()
    engine, repo = _build_engine_with_statement(statement, {})

    engine.find_invalid_statements()

    st = repo.regular_statements[0]
    assert not any('Tag namespace' in reason or 'Tag key' in reason for reason in st.get('invalid_reasons', []))
    assert 'Tag namespace catalog unavailable; tag existence validation skipped.' in st.get('parsing_notes', [])


def test_run_dg_in_use_analysis_marks_dg_in_use_when_referenced_by_dynamic_group_id_subject():
    dg_ocid = 'ocid1.dynamicgroup.oc1..aaaaexampledynamicgroup'
    repo = SimpleNamespace(
        regular_statements=[
            {
                'statement_text': f'allow dynamic-group id {dg_ocid} to inspect instances in tenancy',
                'subject_type': 'dynamic-group-id',
                'subject': [(None, dg_ocid)],
            }
        ],
        dynamic_groups=[
            {
                'domain_name': 'Default',
                'dynamic_group_name': 'DG1',
                'dynamic_group_ocid': dg_ocid,
                'in_use': False,
            }
        ],
        groups=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])

    engine.run_dg_in_use_analysis()

    assert repo.dynamic_groups[0].get('in_use') is True


def test_run_dg_in_use_analysis_leaves_unreferenced_dynamic_group_not_in_use():
    referenced_ocid = 'ocid1.dynamicgroup.oc1..aaaareferenced'
    unreferenced_ocid = 'ocid1.dynamicgroup.oc1..aaaamissing'
    repo = SimpleNamespace(
        regular_statements=[
            {
                'statement_text': f'allow dynamic-group id {referenced_ocid} to inspect instances in tenancy',
                'subject_type': 'dynamic-group-id',
                'subject': [(None, referenced_ocid)],
            }
        ],
        dynamic_groups=[
            {
                'domain_name': 'Default',
                'dynamic_group_name': 'DG_REFERENCED',
                'dynamic_group_ocid': referenced_ocid,
                'in_use': False,
            },
            {
                'domain_name': 'Default',
                'dynamic_group_name': 'DG_UNREFERENCED',
                'dynamic_group_ocid': unreferenced_ocid,
                'in_use': True,
            },
        ],
        groups=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])

    engine.run_dg_in_use_analysis()

    assert repo.dynamic_groups[0].get('in_use') is True
    assert repo.dynamic_groups[1].get('in_use') is False


def test_calculate_effective_compartment_supports_absolute_root_location_path():
    repo = SimpleNamespace(
        tenancy_ocid='ocid1.tenancy.oc1..tenancy',
        compartments=[
            {
                'id': 'ocid1.compartment.oc1..finance',
                'name': 'Finance',
                'parent_id': 'ocid1.tenancy.oc1..tenancy',
                'hierarchy_path': 'root/finance',
            },
            {
                'id': 'ocid1.compartment.oc1..apps',
                'name': 'Apps',
                'parent_id': 'ocid1.compartment.oc1..finance',
                'hierarchy_path': 'root/finance/apps',
            },
        ],
        regular_statements=[],
        dynamic_groups=[],
        groups=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])

    st = {
        'statement_text': 'Allow group Dev to use buckets in compartment Apps',
        'location_type': 'compartment',
        'location': 'ROOT/Finance/Apps',
        'compartment_path': 'ROOT/Finance',
    }

    engine.calculate_effective_compartment_for_statement(st)

    assert st.get('effective_path') == 'root/finance/apps'


def test_policy_helpers_calculate_principal_key_handles_default_domain():
    assert calculate_principal_key('dynamic-group', None, 'DG1') == 'dynamic-group:Default/DG1'
    assert calculate_principal_key('dynamic-group', 'default', 'DG1') == 'dynamic-group:Default/DG1'


def test_resolve_cross_tenancy_aliases_marks_unresolved_alias_invalid():
    repo = SimpleNamespace(
        regular_statements=[],
        dynamic_groups=[],
        groups=[],
        defined_tag_namespace_keys={},
        defined_aliases=[
            {
                'defined_name': 'ResourceTenancy',
                'ocid_alias': 'ocid1.tenancy.oc1..resource',
            }
        ],
        cross_tenancy_statements=[
            {
                'statement_text': 'endorse group A to read buckets in tenancy ResourceTenancy',
                'tenancy_aliases': ['ResourceTenancy', 'MissingTenancy'],
                'valid': True,
                'invalid_reasons': [],
            }
        ],
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])

    engine.resolve_cross_tenancy_aliases()

    st = repo.cross_tenancy_statements[0]
    assert st.get('aliases_resolved') is False
    assert st.get('valid') is False
    resolved = st.get('resolved_aliases', {})
    assert resolved.get('ResourceTenancy', {}).get('resolved') is True
    assert resolved.get('ResourceTenancy', {}).get('ocid') == 'ocid1.tenancy.oc1..resource'
    assert resolved.get('MissingTenancy', {}).get('resolved') is False
    assert any('Unresolved tenancy alias: MissingTenancy' in r for r in st.get('invalid_reasons', []))


def test_calculate_effective_compartment_avoids_duplicate_basename_when_compartment_ocid_missing():
    repo = SimpleNamespace(
        tenancy_ocid='ocid1.tenancy.oc1..tenancy',
        compartments=[
            {
                'id': 'ocid1.compartment.oc1..dev',
                'name': 'Dev',
                'parent_id': 'ocid1.tenancy.oc1..tenancy',
                'hierarchy_path': 'root/dev',
            }
        ],
        regular_statements=[],
        dynamic_groups=[],
        groups=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])

    st = {
        'statement_text': 'Allow group Dev to use buckets in compartment Dev',
        'location_type': 'compartment',
        'location': 'Dev',
        'compartment_path': 'ROOT/Dev',
        # compartment_ocid intentionally omitted to match prospective flows
    }

    engine.calculate_effective_compartment_for_statement(st)

    assert st.get('effective_path') == 'root/dev'
    assert st.get('effective_compartment_ocid') == 'ocid1.compartment.oc1..dev'


def test_build_permissions_report_includes_subject_type_and_principal_key():
    statement = {
        'statement_text': 'allow group Administrators to manage all-resources in tenancy',
        'subject_type': 'group',
        'subject': [('Default', 'Administrators')],
        'permission': ['MANAGE_ALL_RESOURCES'],
        'effective_path': 'root',
    }
    engine, _repo = _build_engine_with_statement(statement, {})

    report = engine.build_permissions_report().get('report', {})

    subject_key = calculate_principal_key('group', 'Default', 'Administrators')
    assert subject_key in report.get('root', {})
    assert report['root'][subject_key].get('subject_type') == 'group'


def test_build_permissions_report_handles_any_user_string_subject():
    statement = {
        'statement_text': 'allow any-user to read buckets in tenancy',
        'subject_type': 'any-user',
        'subject': ['any-user'],
        'permission': ['BUCKET_READ'],
        'effective_path': 'root',
    }
    engine, _repo = _build_engine_with_statement(statement, {})

    payload = engine.build_permissions_report()
    subject_key = calculate_principal_key('any-user', None, 'any-user')

    assert subject_key in payload.get('report', {}).get('root', {})
    assert payload['grant_rows'][0]['principal_key'] == subject_key


def test_build_permissions_report_derives_resource_principal_key():
    statement = {
        'policy_name': 'resource-principal-policy',
        'statement_text': 'allow any-group to use objects in tenancy',
        'subject_type': 'any-group',
        'subject': ['any-group'],
        'permission': ['OBJECT_READ'],
        'effective_path': 'root',
        'conditions': (
            "all { request.principal.type = 'computecontainerinstance', "
            "request.principal.compartment.id = 'ocid1.compartment.oc1..app' }"
        ),
    }
    engine, _repo = _build_engine_with_statement(statement, {})

    payload = engine.build_permissions_report()
    principal_key = 'resource-principal:computecontainerinstance/ocid1.compartment.oc1..app'

    assert principal_key in payload.get('report', {}).get('root', {})
    assert payload['report']['root'][principal_key]['subject_type'] == 'resource-principal'
    assert payload['grant_rows'][0]['original_subject_key'] == 'any-group:None/any-group'


def test_build_permissions_report_derives_oke_workload_identity_key():
    statement = {
        'policy_name': 'oke-workload-policy',
        'statement_text': 'allow any-user to read repos in tenancy',
        'subject_type': 'any-user',
        'subject': ['any-user'],
        'permission': ['REPOSITORY_READ'],
        'effective_path': 'root',
        'conditions': (
            "all { request.principal.type = 'workload', "
            "request.principal.namespace = 'finance', "
            "request.principal.service_account = 'financesa', "
            "request.principal.cluster_id = 'ocid1.cluster.oc1..oke1' }"
        ),
    }
    engine, _repo = _build_engine_with_statement(statement, {})

    payload = engine.build_permissions_report()
    principal_key = 'oke-workload-identity:ocid1.cluster.oc1..oke1/finance/financesa'

    assert principal_key in payload.get('report', {}).get('root', {})
    assert payload['report']['root'][principal_key]['subject_type'] == 'oke-workload-identity'
    assert payload['grant_rows'][0]['principal_key'] == principal_key


def test_build_permissions_report_preserves_deny_rows_and_summary():
    statement = {
        'statement_text': 'deny group Developers to read buckets in tenancy',
        'action': 'deny',
        'subject_type': 'group',
        'subject': [('Default', 'Developers')],
        'permission': ['BUCKET_READ'],
        'effective_path': 'root',
    }
    engine, _repo = _build_engine_with_statement(statement, {})

    payload = engine.build_permissions_report()
    subject_key = calculate_principal_key('group', 'Default', 'Developers')

    assert payload['report']['root'][subject_key]['deny'] == ['BUCKET_READ']
    assert payload['grant_rows'][0]['action'] == 'deny'
    assert payload['summary']['deny_grant_count'] == 1


def test_build_permissions_report_expands_effective_rows_to_descendant_compartments():
    statement = {
        'statement_text': 'allow group Developers to read buckets in tenancy',
        'subject_type': 'group',
        'subject': [('Default', 'Developers')],
        'permission': ['BUCKET_READ'],
        'effective_path': 'root',
    }
    repo = SimpleNamespace(
        regular_statements=[statement],
        dynamic_groups=[],
        groups=[],
        defined_tag_namespace_keys={},
        compartments=[
            {'id': 'tenancy', 'name': 'root', 'hierarchy_path': 'root'},
            {'id': 'dev', 'name': 'Dev', 'hierarchy_path': 'root/dev'},
            {'id': 'app', 'name': 'App', 'hierarchy_path': 'root/dev/app'},
        ],
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])

    payload = engine.build_permissions_report()
    rows = sorted(payload['grant_rows'], key=lambda row: row['effective_path'])

    assert [row['effective_path'] for row in rows] == ['root', 'root/dev', 'root/dev/app']
    inherited_rows = [row for row in rows if row['inherited']]
    assert {row['inherited_from'] for row in inherited_rows} == {'root'}
    assert payload['summary']['direct_grant_row_count'] == 1
    assert payload['summary']['effective_grant_row_count'] == 3


def test_build_overall_recommendations_flags_incomplete_oke_workload_identity_conditions():
    repo = SimpleNamespace(
        regular_statements=[
            {
                'policy_name': 'oke-workload-policy',
                'statement_text': 'allow any-user to read repos in tenancy',
                'subject_type': 'any-user',
                'subject': ['any-user'],
                'verb': 'read',
                'resource': 'repos',
                'effective_path': 'root',
                'conditions': (
                    "all { request.principal.type = 'workload', " "request.principal.namespace = 'finance' }"
                ),
            }
        ],
        dynamic_groups=[],
        groups=[],
        compartments=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])
    engine.overlay['cleanup_items'] = {}
    engine.overlay['consolidations'] = []

    engine.build_overall_recommendations()

    rec = next(r for r in engine.overlay['recommendations'] if r.get('ActionId') == 'oke_workload_identity_hygiene')
    assert rec['Priority'] == 'High'
    assert rec['Category'] == 'Workload Identity'
    assert rec['Recommendation']
    assert rec['Action']
    assert rec['ActionDetail']
    assert rec['Destination'] == '/workload-principals-analysis.html'
    assert 'namespace existence' in rec['Notes']
    assert 'request.principal.cluster_id' in rec['Evidence'][0]['Missing Conditions']


def test_build_overall_recommendations_flags_resource_principal_without_compartment_constraint():
    repo = SimpleNamespace(
        regular_statements=[
            {
                'policy_name': 'resource-principal-policy',
                'statement_text': 'allow any-group to use objects in tenancy',
                'subject_type': 'any-group',
                'subject': ['any-group'],
                'verb': 'use',
                'resource': 'objects',
                'effective_path': 'root',
                'conditions': "request.principal.type = 'computecontainerinstance'",
            }
        ],
        dynamic_groups=[],
        groups=[],
        compartments=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])
    engine.overlay['cleanup_items'] = {}
    engine.overlay['consolidations'] = []

    engine.build_overall_recommendations()

    rec = next(r for r in engine.overlay['recommendations'] if r.get('ActionId') == 'resource_principal_hygiene')
    assert rec['Category'] == 'Resource Principal'
    assert 'request.principal.compartment.id' in rec['Evidence'][0]['Missing Conditions']


def test_build_overall_recommendations_flags_tag_based_policy_hygiene():
    repo = SimpleNamespace(
        regular_statements=[
            {
                'policy_name': 'tag-policy',
                'statement_text': 'allow group Developers to use buckets in tenancy',
                'subject_type': 'group',
                'subject': [('Default', 'Developers')],
                'verb': 'use',
                'resource': 'buckets',
                'effective_path': 'root',
                'conditions': "target.resource.tag.Operations.Environment = 'prod'",
            }
        ],
        dynamic_groups=[],
        groups=[],
        compartments=[],
        defined_tag_namespace_keys={'Operations': {'keys': {'Environment': None}}},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])
    engine.overlay['cleanup_items'] = {}
    engine.overlay['consolidations'] = []

    engine.build_overall_recommendations()

    rec = next(r for r in engine.overlay['recommendations'] if r.get('ActionId') == 'tag_based_policy_hygiene')
    assert rec['Category'] == 'Tag-Based Access'
    assert rec['Action']
    assert rec['ActionDetail']
    assert rec['EvidenceCount'] == 1


def test_recommendation_rows_preserve_legacy_fields_with_catalog_details():
    repo = SimpleNamespace(
        regular_statements=[],
        dynamic_groups=[],
        groups=[],
        compartments=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])
    engine.overlay['cleanup_items'] = {'invalid_statements': [{'statement_text': 'bad', 'invalid_reasons': ['x']}]}
    engine.overlay['consolidations'] = []

    engine.build_overall_recommendations()

    rec = engine.overlay['recommendations'][0]
    for key in ['Recommendation', 'Priority', 'Category', 'Notes', 'Action']:
        assert key in rec
    assert rec['ActionId'] == 'invalid_statements'
    assert rec['ActionDetail']


def test_risk_scoring_unknown_resource_uses_current_verb_weights():
    repo = SimpleNamespace(
        permission_reference_repo=_RiskRefRepo(),
        regular_statements=[
            {
                'internal_id': 'st1',
                'statement_text': 'allow group Devs to use mystery-widgets in compartment Dev',
                'subject_type': 'group',
                'verb': 'use',
                'resource': 'mystery-widgets',
                'permission': [],
                'effective_path': 'root/dev',
            }
        ],
        compartments=[
            {'id': 'tenancy', 'name': 'root', 'parent_id': None, 'hierarchy_path': 'root'},
            {'id': 'dev', 'name': 'Dev', 'parent_id': 'tenancy', 'hierarchy_path': 'root/dev'},
        ],
        tenancy_ocid='tenancy',
        dynamic_groups=[],
        groups=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])

    engine.calculate_potential_risk_scores()

    risk = engine.overlay['risk_scores'][0]
    assert risk['score'] == 50
    assert 'verb weight 50' in risk['notes']


def test_risk_scoring_compartment_exposure_uses_path_boundaries():
    repo = SimpleNamespace(
        permission_reference_repo=_RiskRefRepo(),
        regular_statements=[
            {
                'internal_id': 'st1',
                'statement_text': 'allow group Devs to read mystery-widgets in compartment Dev',
                'subject_type': 'group',
                'verb': 'read',
                'resource': 'mystery-widgets',
                'permission': [],
                'effective_path': 'root/dev',
            }
        ],
        compartments=[
            {'id': 'tenancy', 'name': 'root', 'parent_id': None, 'hierarchy_path': 'root'},
            {'id': 'dev', 'name': 'Dev', 'parent_id': 'tenancy', 'hierarchy_path': 'root/dev'},
            {'id': 'app', 'name': 'App', 'parent_id': 'dev', 'hierarchy_path': 'root/dev/app'},
            {'id': 'development', 'name': 'Development', 'parent_id': 'tenancy', 'hierarchy_path': 'root/development'},
        ],
        tenancy_ocid='tenancy',
        dynamic_groups=[],
        groups=[],
        defined_tag_namespace_keys={},
    )
    engine = PolicyIntelligenceEngine(repo, strategies=[])

    engine.calculate_potential_risk_scores()

    risk = engine.overlay['risk_scores'][0]
    assert risk['score'] == 10
    assert 'Compartments at or below effective path "root/dev": 2' in risk['notes']


# ---------------------------------------------------------------------------
# Effective compartment calculation matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('statement', 'expected_path', 'expected_ocid_key'),
    [
        pytest.param(
            {
                'statement_text': 'allow group G to use buckets in tenancy',
                'location_type': 'tenancy',
                'location': 'tenancy',
                'compartment_ocid': 'ocid1.compartment.oc1..finance',
            },
            'root',
            'tenancy',
            id='tenancy-location',
        ),
        pytest.param(
            {
                'statement_text': 'allow group G to use buckets in compartment id apps',
                'location_type': 'compartment id',
                'location': 'ocid1.compartment.oc1..apps',
                'compartment_ocid': 'ocid1.compartment.oc1..finance',
            },
            'root/finance/apps',
            'apps',
            id='compartment-id-location',
        ),
        pytest.param(
            {
                'statement_text': 'allow group G to use buckets in compartment Apps:SubApps',
                'location_type': 'compartment',
                'location': 'Apps:SubApps',
                'compartment_ocid': 'ocid1.compartment.oc1..finance',
            },
            'root/finance/apps/subapps',
            'subapps',
            id='relative-colon-path',
        ),
        pytest.param(
            {
                'statement_text': 'allow group G to use buckets in compartment Finance',
                'location_type': 'compartment',
                'location': 'Finance',
                'compartment_ocid': 'ocid1.compartment.oc1..finance',
            },
            'root/finance',
            'finance',
            id='same-as-policy-compartment-name',
        ),
        pytest.param(
            {
                'statement_text': 'allow group G to use buckets in compartment ROOT/Finance/Apps',
                'location_type': 'compartment',
                'location': 'ROOT/Finance/Apps',
                'compartment_ocid': 'ocid1.compartment.oc1..finance',
            },
            'root/finance/apps',
            'apps',
            id='absolute-root-path',
        ),
        pytest.param(
            {
                'statement_text': 'allow group G to use buckets in compartment Dev',
                'location_type': 'compartment',
                'location': 'Dev',
                # Prospective-like shape: no compartment_ocid available
                'compartment_path': 'ROOT/Dev',
            },
            'root/dev',
            'dev',
            id='missing-compartment-ocid-uses-compartment-path',
        ),
    ],
)
def test_calculate_effective_compartment_matrix(statement, expected_path, expected_ocid_key):
    engine, ids = _build_engine_with_compartment_repo()

    engine.calculate_effective_compartment_for_statement(statement)

    assert statement.get('effective_path') == expected_path
    assert statement.get('effective_compartment_ocid') == ids[expected_ocid_key]
