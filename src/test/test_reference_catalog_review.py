"""Regression coverage for source-reviewed reference mappings and known gaps."""

import re

import pytest

from oci_policy_analysis.application.core.engine.policy_simulation_engine import PolicySimulationEngine
from oci_policy_analysis.application.core.repo.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.application.services.reference_data_service import ReferenceDataService


@pytest.fixture
def catalog():
    """Load packaged reference data without tenancy or cache access."""
    repo = ReferenceDataRepo()
    repo.load_data()
    return repo


def test_catalog_permission_tokens_do_not_contain_prose_fragments(catalog):
    """Fragments such as I, DRG and _CREATE must not become permission IDs."""
    token = re.compile(r'[A-Z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+')
    for section in ('resources', 'operations'):
        for name, metadata in catalog.data[section].items():
            groups = metadata.get('verbs', {}).values() if section == 'resources' else [metadata.get('permissions', [])]
            for permissions in groups:
                assert isinstance(permissions, list), (section, name)
                assert len(permissions) == len(set(permissions)), (section, name)
                assert all(token.fullmatch(permission) for permission in permissions), (section, name, permissions)


def test_audit_read_is_mapped_but_inspect_has_no_permissions(catalog):
    """Audit's documented inspect absence must not erase its read permission."""
    assert catalog.get_permissions('audit-events', 'inspect') == []
    for verb in ('read', 'use', 'manage'):
        assert catalog.get_permissions('audit-events', verb) == ['AUDIT_EVENT_READ']
    assert 'AUDIT_EVENT_READ' in catalog.get_permissions('all-resources', 'manage')
    assert catalog.has_api_operation_permissions('audit:ListEvents', ['AUDIT_EVENT_READ'])
    assert not catalog.has_api_operation_permissions('audit:ListEvents', [])
    assert catalog.get_source('audit-events').endswith('/auditpolicyreference.htm')


def test_network_permission_increments_match_reviewed_reference(catalog):
    """Updates need the documented verb rather than guessed verb symmetry."""
    assert set(catalog.get_permissions('vcns', 'use')) == {'VCN_READ'}
    assert {'VCN_UPDATE', 'VCN_ATTACH', 'VCN_DETACH'} <= set(catalog.get_permissions('vcns', 'manage'))
    assert catalog.get_permissions('dhcp-options', 'inspect') == ['DHCP_READ']
    assert 'CAPTURE_FILTER_LIST' in catalog.get_permissions('capture-filters', 'inspect')
    assert {'CAPTURE_FILTER_ATTACH', 'CAPTURE_FILTER_DETACH'} <= set(catalog.get_permissions('capture-filters', 'use'))
    assert 'DRG_ROUTE_RULE_UPDATE' in catalog.get_permissions('drg-route-tables', 'manage')
    assert {'DRG_ATTACH', 'DRG_DETACH', 'DRG_ROUTE_RULE_READ'} <= set(catalog.get_permissions('drgs', 'manage'))
    assert 'DRG_READ' in catalog.get_permissions('drg-object', 'inspect')


def test_oke_family_and_permission_names_preserve_legacy_lookup(catalog):
    """Documented OKE names resolve while the old family remains an alias."""
    assert 'cluster-family' in catalog.data['families']
    assert catalog.get_permissions('cluster-node-pools', 'inspect') == ['CLUSTER_NODE_POOL_INSPECT']
    assert catalog.get_permissions('cluster-node-pools', 'use') == catalog.get_permissions('cluster-node-pools', 'read')
    assert 'CLUSTER_NODE_POOL_UPDATE' in catalog.get_permissions('cluster-node-pools', 'manage')
    assert 'CLUSTER_USE' in catalog.get_permissions('clusters', 'use')
    assert 'CLUSTER_MANAGE' not in catalog.get_permissions('clusters', 'use')
    assert 'CLUSTER_MANAGE' in catalog.get_permissions('clusters', 'manage')
    assert set(catalog.get_permissions('container-engine-family', 'manage')) == set(
        catalog.get_permissions('cluster-family', 'manage')
    )


def test_joined_and_misspelled_operation_tokens_are_corrected(catalog):
    """Source-confirmed transcription errors cannot become lookup suggestions."""
    assert set(catalog.data['operations']['organizations:DeleteLink']['permissions']) == {
        'ORGANIZATIONS_LINK_CHILD_DELETE',
        'ORGANIZATIONS_LINK_PARENT_DELETE',
    }
    assert 'IPSEC_CONNECTION_CREATE' in catalog.data['operations']['core:CreateIPSecConnection']['permissions']
    assert 'IPSEC_CONNECTION_CREATER' not in catalog.data['operations']['core:CreateIPSecConnection']['permissions']
    assert 'DB_BACKUP_DELETE' in catalog.data['operations']['database_all:DeleteDbHome']['permissions']
    assert 'subtype' in catalog.data['operations']['core:CreateInstanceConfiguration']['notes']


@pytest.mark.parametrize('operation', ['core:GetWorkRequests', 'core:ListWorkRequestLogs', 'MoveCompartment'])
def test_context_dependent_empty_mapping_cannot_establish_access(catalog, operation):
    """A missing fixed mapping differs from an explicitly public API."""
    service = ReferenceDataService(catalog)
    detail = service.get_operation_detail(operation)
    assert detail['mapping_status'] == 'context_dependent'
    assert detail['permissions'] == []
    assert detail['notes']
    assert not catalog.has_api_operation_permissions(operation, [])
    assert not catalog.has_api_operation_permissions(operation, catalog.get_permissions('all-resources', 'manage'))
    assert catalog.has_api_operation_permissions('ListDedicatedVmHostShapes', [])


def test_simulation_explains_context_dependent_mapping(catalog):
    """Simulation exposes uncertainty instead of claiming an empty list passes."""
    engine = PolicySimulationEngine(policy_repo=None, ref_data_repo=catalog)
    result = engine.simulate_and_record('group:default/admins', 'ROOT', 'core:GetWorkRequests', {}, [])
    assert result['api_call_allowed'] is False
    assert result['operation_mapping_status'] == 'context_dependent'
    assert result['simulation_trace']['operation_mapping_status'] == 'context_dependent'
    assert 'cannot establish access' in result['failure_reason']


def test_search_terms_and_unresearched_metadata_do_not_invent_permissions(catalog):
    """Discovery vocabulary remains separate from accepted policy identifiers."""
    assert 'virtual machines' in catalog.get_catalog_metadata('instances')['search_terms']
    assert catalog.get_permissions('virtual machines', 'manage') == []
    assert catalog.get_permissions('app-catalog-listing', 'manage') == catalog.get_permissions(
        'app-catalog-listings', 'manage'
    )
    assert catalog.get_catalog_metadata('cloud-shell')['mapping_status'] == 'no_published_mapping'
    assert catalog.get_permissions('cloud-shell', 'use') == []
    assert 'UNKNOWN_PERMISSION_CLOUD_SHELL' not in catalog.get_permissions('all-resources', 'manage')
    assert not any('cloud-shell' in name for name in catalog.data['operations'])
    assert catalog.get_source('cloud-shell').endswith('/cloudshellintro.htm')
    # This operation permission remains evidence even though no resource/verb mapping is known.
    assert 'BOOT_VOLUME_MOVE' in catalog.data['operations']['core:ChangeBootVolumeCompartment']['permissions']


def test_cloud_shell_source_survives_without_invented_grant_facts(catalog):
    """An unmapped resource remains source evidence and an explicit exclusion."""
    from types import SimpleNamespace

    from oci_policy_analysis.application.core.policy_corpus import PolicyCorpusBuilder

    statement = {
        'internal_id': 'cloud-shell-source',
        'valid': True,
        'resource': 'cloud-shell',
        'verb': 'use',
        'action': 'allow',
        'principal_keys': ['group:default/operators'],
        'effective_path': 'ROOT',
        'statement_text': 'allow group Operators to use cloud-shell in tenancy',
    }
    original = dict(statement)
    corpus = PolicyCorpusBuilder().build(
        SimpleNamespace(regular_statements=[statement], permission_reference_repo=catalog)
    )
    assert not corpus.facts
    assert len(corpus.exclusions) == 1
    assert corpus.exclusions[0].category == 'unmapped_permission_expansion'
    assert corpus.exclusions[0].statement_text == statement['statement_text']
    assert statement == original
