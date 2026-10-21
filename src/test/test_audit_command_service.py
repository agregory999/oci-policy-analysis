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
    assert args[:4] == ['oci', 'audit', 'event', 'list'] and '--all' in args
    query = args[args.index('--query') + 1]
    assert query == 'data[?data."resource-id" == \'ocid1.policy.oc1..example\']'


def test_command_quoting_retains_literal_profile_and_query():
    profile = "work' profile; $(touch nope)"
    result = AuditCommandService.generate(inputs(profile=profile))
    args = shlex.split(result['commands'][0])
    assert args[args.index('--profile') + 1] == profile
    powershell = AuditCommandService.generate(inputs(profile=profile, shell='powershell'))
    assert "work'' profile; $(touch nope)" in powershell['commands'][0]


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
