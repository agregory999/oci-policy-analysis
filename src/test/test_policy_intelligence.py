"""Tests for policy intelligence invalid-statement checks.

Focused coverage for tag namespace/key validation in where-clause conditions.
"""

from types import SimpleNamespace

import pytest
from oci_policy_analysis.logic.policy_helpers import calculate_principal_key
from oci_policy_analysis.logic.policy_intelligence import PolicyIntelligenceEngine


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
