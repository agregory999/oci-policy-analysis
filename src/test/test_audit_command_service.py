"""CLI command generation is deterministic, quoted and entirely offline."""

import shlex
from datetime import datetime

import pytest

from oci_policy_analysis.application.services.audit_command_service import AuditCommandService


def inputs(**updates):
    return {
        'compartment_id': 'ocid1.compartment.oc1..example',
        'resource_id': 'ocid1.policy.oc1..example',
        'start_time': '2026-09-01T00:00:00Z',
        'end_time': '2026-10-01T00:00:00Z',
        'profile': 'DEFAULT',
        'shell': 'posix',
        **updates,
    }


def test_audit_ranges_are_contiguous_end_exclusive_and_at_most_14_days():
    result = AuditCommandService.generate(inputs())
    assert len(result['commands']) == 3
    assert result['windows'][0]['start_time'] == '2026-09-01T00:00:00Z'
    assert result['windows'][-1]['end_time'] == '2026-10-01T00:00:00Z'
    for first, second in zip(result['windows'], result['windows'][1:], strict=False):
        assert first['end_time'] == second['start_time']
    for window in result['windows']:
        assert (datetime.fromisoformat(window['end_time']) - datetime.fromisoformat(window['start_time'])).days <= 14
    args = shlex.split(result['commands'][0])
    assert args[:3] == ['oci', 'logging-search', 'search-logs'] and '--all' not in args
    assert result['limit'] == 100
    search = args[args.index('--search-query') + 1]
    assert search.startswith('search "ocid1.compartment.oc1..example/_Audit"')
    assert "where data.resourceId = 'ocid1.policy.oc1..example'" in search
    assert "where (data.eventName = 'CreatePolicy' or data.eventName = 'UpdatePolicy'" in search
    assert "or data.eventName = 'DeletePolicy')" in search
    assert "time_format(datetime, 'yyyy-MM-dd HH:mm:ss z') as event_time" in search
    assert 'data.identity.principalId as actor_ocid' in search
    assert 'data.identity.principalName as actor' in search
    assert 'data.identity.ipAddress as ip' in search
    assert 'data.response.status as status' in search
    assert 'message' not in search and 'GetPolicy' not in search
    assert args[args.index('--query') + 1] == 'data.results[].data'
    assert args[args.index('--limit') + 1] == '100'
    assert args[args.index('--is-return-field-info') + 1] == 'false'
    assert args[args.index('--time-start') + 1] == result['windows'][0]['start_time']
    assert args[args.index('--time-end') + 1] == result['windows'][0]['end_time']
    assert args[args.index('--output') + 1] == 'table'


def test_non_policy_resources_are_not_filtered_to_policy_operations():
    result = AuditCommandService.generate(inputs(resource_id='ocid1.group.oc1..example'))
    args = shlex.split(result['commands'][0])
    search = args[args.index('--search-query') + 1]
    assert "where data.resourceId = 'ocid1.group.oc1..example'" in search
    assert 'CreatePolicy' not in search


def test_clearing_resource_searches_policy_mutations_across_compartment():
    result = AuditCommandService.generate(inputs(resource_id='', compartment_id='ocid1.tenancy.oc1..example'))
    args = shlex.split(result['commands'][0])
    search = args[args.index('--search-query') + 1]
    assert search.startswith('search "ocid1.tenancy.oc1..example/_Audit"')
    assert 'data.resourceId' not in search
    assert 'UpdatePolicy' in search


def test_command_quoting_retains_literal_profile_and_query():
    profile = "work' profile; $(touch nope)"
    result = AuditCommandService.generate(inputs(profile=profile))
    args = shlex.split(result['commands'][0])
    assert args[args.index('--profile') + 1] == profile
    powershell = AuditCommandService.generate(inputs(profile=profile, shell='powershell'))
    assert "work'' profile; $(touch nope)" in powershell['commands'][0]


@pytest.mark.parametrize('enabled', [True, 'true', 'on', False, 'false', ''])
def test_instance_principal_auth_is_optional_for_both_shells(enabled):
    expected = enabled in (True, 'true', 'on')
    for shell in ('posix', 'powershell'):
        result = AuditCommandService.generate(inputs(shell=shell, instance_principal=enabled))
        assert all(('--auth instance_principal' in command) == expected for command in result['commands'])


def test_powershell_json_request_preserves_query_and_each_time_window():
    posix = AuditCommandService.generate(inputs())
    powershell = AuditCommandService.generate(inputs(shell='powershell', region='us-ashburn-1'))
    assert powershell['windows'] == posix['windows']
    for command, original, window in zip(powershell['commands'], posix['commands'], powershell['windows'], strict=True):
        args = shlex.split(original)
        search = args[args.index('--search-query') + 1]
        assert f"$searchQuery = @'\n{search}\n'@" in command
        assert f"timeStart         = '{window['start_time']}'" in command
        assert f"timeEnd           = '{window['end_time']}'" in command
        assert 'searchQuery       = $searchQuery' in command
        assert 'isReturnFieldInfo = $false' in command
        assert 'limit             = 100' in command
        assert 'System.Text.UTF8Encoding($false)' in command
        assert '--from-json "file://$jsonPath"' in command
        assert "--region 'us-ashburn-1' --profile 'DEFAULT'" in command


def test_audit_minute_rounding_does_not_drop_fractional_capture_times():
    result = AuditCommandService.generate(inputs(start_time='2026-10-01T12:00:53Z', end_time='2026-10-01T12:01:09Z'))
    assert result['windows'] == [{'start_time': '2026-10-01T12:00:00Z', 'end_time': '2026-10-01T12:02:00Z'}]


@pytest.mark.parametrize(
    'updates',
    [
        {'compartment_id': 'sample-tenant'},
        {'resource_id': "ocid1.x';not-ocid"},
        {'start_time': '2026-10-01T12:00:00'},
        {'start_time': '2027-01-01T00:00:00Z'},
        {'shell': 'cmd'},
        {'region': 'region\ncommand'},
    ],
)
def test_invalid_audit_inputs_are_rejected(updates):
    with pytest.raises(ValueError):
        AuditCommandService.generate(inputs(**updates))


def test_audit_defaults_use_policy_ocid_instead_of_internal_id_and_compared_tenancy():
    defaults = AuditCommandService.defaults(
        {
            'new_value': {
                'internal_id': 'runtime-id',
                'policy_ocid': 'ocid1.policy.example',
                'compartment_ocid': 'ocid1.compartment.example',
            }
        },
        {
            'audit_context': {
                'compartment_id': 'ocid1.tenancy.before',
                'start_time': '2026-10-01T00:00:00Z',
                'end_time': '2026-10-15T00:00:00Z',
            }
        },
    )
    assert defaults['resource_id'] == 'ocid1.policy.example'
    assert defaults['compartment_id'] == 'ocid1.compartment.example'
    assert defaults['start_time'].startswith('2026-10-01')


def test_deleted_policy_defaults_use_original_compartment():
    defaults = AuditCommandService.defaults(
        {'old_value': {'policy_ocid': 'ocid1.policy.deleted', 'compartment_id': 'ocid1.compartment.original'}},
        {'audit_context': {'compartment_id': 'ocid1.tenancy.fallback'}},
    )
    assert defaults['resource_id'] == 'ocid1.policy.deleted'
    assert defaults['compartment_id'] == 'ocid1.compartment.original'
