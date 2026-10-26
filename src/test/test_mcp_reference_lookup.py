"""Catalog discovery, reverse lookup and real MCP schema/transport contracts."""

import asyncio
from types import SimpleNamespace

import pytest
from fastmcp import Client

from oci_policy_analysis import mcp_server
from oci_policy_analysis.application.core.models.models_reference_lookup import (
    OperationReferenceQuery,
    PermissionReferenceQuery,
    ResourceReferenceQuery,
)
from oci_policy_analysis.application.core.repo.reference_data_repo import ReferenceDataRepo
from oci_policy_analysis.application.services.reference_lookup_service import ReferenceLookupService


@pytest.fixture
def service():
    catalog = ReferenceDataRepo()
    catalog.load_data()
    return ReferenceLookupService(catalog)


def test_discovery_distinguishes_wording_aliases_and_exact_identifiers(service):
    result = service.resource_reference(ResourceReferenceQuery(query='virtual machines'))
    assert result.matches[0].canonical_name == 'instances'
    assert result.matches[0].match_type == 'search_term'
    assert service.resource_reference(ResourceReferenceQuery(query='virtual machines', match='exact')).matches == []
    assert (
        service.resource_reference(ResourceReferenceQuery(query='INSTANCE', match='exact')).matches[0].match_type
        == 'alias'
    )
    family = service.resource_reference(ResourceReferenceQuery(query='instance-family', kind='family', match='exact'))
    assert 'instances' in family.matches[0].member_resources
    assert 'INSTANCE_CREATE' in family.matches[0].permissions_by_verb['manage'].permissions
    assert 'INSTANCE_CREATE' not in family.matches[0].permissions_by_verb['read'].permissions


def test_explicit_empty_and_unpublished_mappings_do_not_invent_permissions(service):
    audit = service.resource_reference(ResourceReferenceQuery(query='audit-events', verb='inspect', match='exact'))
    assert audit.matches[0].mapping_status == 'documented_empty'
    assert audit.matches[0].permissions_by_verb['inspect'].total_count == 0
    cloud = service.resource_reference(ResourceReferenceQuery(query='cloud shell'))
    assert cloud.matches[0].mapping_status == 'no_published_mapping'
    assert cloud.matches[0].supported_verbs == ['use']
    assert not any(v.permissions for v in cloud.matches[0].permissions_by_verb.values())
    assert cloud.matches[0].notes and cloud.matches[0].source_urls


def test_operation_qualification_related_checks_and_alternatives(service):
    result = service.operation_reference(OperationReferenceQuery(query='CreateSession', match='exact'))
    assert len(result.matches) >= 2
    assert all(':' in row.canonical_name for row in result.matches)
    assert result.warnings
    filtered = service.operation_reference(
        OperationReferenceQuery(query='CreateSession', api_group='bastion', match='exact')
    )
    assert [row.canonical_name for row in filtered.matches] == ['bastion:CreateSession']
    launch = service.operation_reference(OperationReferenceQuery(query='create virtual machine')).matches[0]
    assert launch.canonical_name == 'core:LaunchInstance'
    assert 'INSTANCE_CREATE' in launch.permissions
    assert any(check.resource == 'subnets' and 'SUBNET_ATTACH' in check.permissions for check in launch.related_checks)
    assert launch.notes
    inherited = service.operation_reference(
        OperationReferenceQuery(query='core:GetWorkRequests', match='exact')
    ).matches[0]
    assert inherited.mapping_status == 'context_dependent' and inherited.permissions == []


def test_reverse_lookup_returns_lowest_verb_and_additional_grants(service):
    result = service.permission_reference(PermissionReferenceQuery(query='BUCKET_CREATE', match='exact'))
    permission = result.matches[0]
    bucket = next(row for row in permission.resource_mappings if row.resource == 'buckets')
    assert bucket.lowest_granting_verb == 'manage'
    assert 'object-family' in bucket.families
    assert 'BUCKET_DELETE' in bucket.additional_permissions.permissions
    assert 'objectstorage:CreateBucket' in permission.operations
    assert service.permission_reference(PermissionReferenceQuery(query='bucket create')).matches
    assert service.permission_reference(
        PermissionReferenceQuery(query='BUCKET_CREATE', resource='bucket', match='exact')
    ).matches
    with pytest.raises(ValueError, match='Unknown resource'):
        service.permission_reference(PermissionReferenceQuery(query='BUCKET_CREATE', resource='made-up'))


def test_operation_only_permissions_survive_and_synthetic_placeholders_do_not(service):
    result = service.permission_reference(PermissionReferenceQuery(query='BOOT_VOLUME_MOVE', match='exact'))
    assert result.matches[0].mapping_status == 'operation_only'
    assert not result.matches[0].resource_mappings
    assert 'core:ChangeBootVolumeCompartment' in result.matches[0].operations
    assert not service.permission_reference(PermissionReferenceQuery(query='UNKNOWN_PERMISSION_CLOUD_SHELL')).matches
    operation = service.operation_reference(
        OperationReferenceQuery(query='core:ChangeBootVolumeCompartment', match='exact')
    )
    assert 'BOOT_VOLUME_MOVE' in operation.matches[0].unmapped_permissions


def test_cursor_is_deterministic_query_bound_and_catalog_bound(service):
    query = ResourceReferenceQuery(query='instance', limit=1)
    first = service.resource_reference(query)
    assert first.next_cursor and len(first.matches) == 1
    following = service.resource_reference(query.model_copy(update={'cursor': first.next_cursor}))
    assert following.matches[0].canonical_name != first.matches[0].canonical_name
    assert service.resource_reference(query) == first
    for cursor in ('not-a-cursor', 'W10=', first.next_cursor):
        with pytest.raises(ValueError, match='Cursor'):
            service.resource_reference(ResourceReferenceQuery(query='buckets', cursor=cursor))
    service.catalog_id = 'different-catalog'
    with pytest.raises(ValueError, match='Cursor'):
        service.resource_reference(query.model_copy(update={'cursor': first.next_cursor}))


def test_large_expansions_are_bounded_and_report_totals(service):
    result = service.resource_reference(ResourceReferenceQuery(query='all-resources', match='exact'))
    row = result.matches[0]
    assert row.member_count > len(row.member_resources)
    assert row.members_truncated
    permissions = row.permissions_by_verb['manage']
    assert permissions.total_count > len(permissions.permissions)
    assert permissions.truncated
    assert len(permissions.permissions) == 50
    assert all(not permission.startswith('UNKNOWN_') for permission in permissions.permissions)


def test_schemas_and_transport_work_without_loaded_context(monkeypatch):
    def forbidden():
        raise AssertionError('Reference tools must not require tenancy state.')

    monkeypatch.setattr(mcp_server, '_require_service_context', forbidden)
    monkeypatch.setattr(mcp_server, '_track_mcp_tool', lambda *args, **kwargs: None)

    async def exercise():
        async with Client(mcp_server.mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            for name in ('resource_reference', 'operation_reference', 'permission_reference'):
                schema = tools[name].inputSchema
                assert schema['required'] == ['query']
                assert schema['additionalProperties'] is False
                assert schema['properties']['limit']['maximum'] == 25
                assert tools[name].outputSchema['properties']['matches']
                assert tools[name].annotations.readOnlyHint
                assert tools[name].annotations.destructiveHint is False
                result = await client.call_tool(name, {'query': 'instance'})
                assert result.structured_content['catalog_id']
                assert result.structured_content['matches']
            for arguments in (
                {'query': ''},
                {'query': '   '},
                {'query': 'x', 'limit': 26},
                {'query': 'x', 'surprise': True},
                {'query': 'x', 'verb': 'delete'},
            ):
                with pytest.raises(Exception, match='validation|keyword|character|maximum'):
                    await client.call_tool('resource_reference', arguments)
            with pytest.raises(Exception, match='Cursor'):
                await client.call_tool('resource_reference', {'query': 'instance', 'cursor': 'bad'})

    asyncio.run(exercise())


def test_snapshot_server_exposes_same_reference_tools_and_no_mutations(monkeypatch):
    monkeypatch.setattr(mcp_server, '_track_mcp_tool', lambda *args, **kwargs: None)
    context = SimpleNamespace(
        policy_repo=SimpleNamespace(regular_statements=[], users=[], groups=[], dynamic_groups=[])
    )

    async def exercise():
        snapshot = await mcp_server.create_snapshot_server(context)
        async with Client(snapshot) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert {'resource_reference', 'operation_reference', 'permission_reference'} <= names
            assert not {'data_operations', 'policy_history_search'} & names
            resource = await client.call_tool(
                'resource_reference', {'query': 'audit-events', 'match': 'exact', 'verb': 'read'}
            )
            assert resource.structured_content['matches'][0]['permissions_by_verb']['read']['permissions'] == [
                'AUDIT_EVENT_READ'
            ]

    asyncio.run(exercise())


def test_packaged_reference_schemas_match_registered_tools():
    import json
    from importlib.resources import files

    packaged = json.loads(
        files('oci_policy_analysis.application.core.resources.mcp_tools_list').joinpath('mcp_tools.json').read_text()
    )
    records = {row['name']: row for row in packaged['result']['tools']}
    tools = asyncio.run(mcp_server.mcp.get_tools())
    for name in ('resource_reference', 'operation_reference', 'permission_reference'):
        assert records[name]['inputSchema'] == tools[name].parameters
        assert records[name]['outputSchema'] == tools[name].output_schema
        assert records[name]['description'] == tools[name].description
