"""Environment settings and deployment payload safety contracts."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('value', ['0', '7', 'invalid'])
def test_invalid_mcp_depth_fails_with_variable_name(monkeypatch, value):
    monkeypatch.setenv('OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH', value)
    from oci_policy_analysis import mcp_server

    with pytest.raises(ValueError, match='OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH'):
        mcp_server._build_arg_parser()


def test_saved_ui_settings_are_not_changed_by_operator_environment(monkeypatch, tmp_path):
    from oci_policy_analysis.application.core.support import config

    saved = {'domain_compartment_depth': 3, 'font_size': 'Large', 'load_all_users': False}
    file = tmp_path / 'settings.json'
    file.write_text(json.dumps(saved))
    monkeypatch.setattr(config, 'SETTINGS_PATH', str(file))
    monkeypatch.setenv('OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH', '2')
    monkeypatch.setenv('OCI_POLICY_ANALYSIS_DOMAIN_COMPARTMENT_DEPTH', '6')
    assert config.load_settings() == saved


def payload_environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith(('OCI_', 'MCP_', 'WEB_', 'OPA_'))}
    env.update(
        OCI_REGISTRY_HOST='example.ocir.io',
        OCI_NAMESPACE='namespace',
        OCI_REPOSITORY='repo',
        IMAGE_TAG_WEB='web-1',
        IMAGE_TAG_MCP='mcp-1',
        MCP_PORT='8001',
        OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH='2',
        OCI_PROFILE='operator-secret-profile',
        OCIR_AUTH_TOKEN='must-not-forward',
        OCI_SESSION_TOKEN='must-not-forward',
    )
    return env


def test_combined_payload_preserves_depth_and_excludes_operator_credentials():
    result = subprocess.run(
        ['python3', str(ROOT / 'run/container-config.py'), 'combined'],
        env=payload_environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    web, mcp = json.loads(result.stdout)
    assert web['environmentVariables']['OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH'] == '2'
    assert mcp['environmentVariables']['OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH'] == '2'
    assert mcp['healthChecks'][0]['port'] == 8001
    assert mcp['environmentVariables']['MCP_AUTH_MODE'] == 'resource_principal'
    assert web['isResourcePrincipalDisabled'] is False
    assert 'operator-secret-profile' not in result.stdout
    assert 'must-not-forward' not in result.stdout


def test_container_payload_ignores_preferences_diagnostics_and_disabled_oauth():
    env = payload_environment()
    env.update(
        OCI_POLICY_ANALYSIS_DOMAIN_COMPARTMENT_DEPTH='6',
        OCI_POLICY_ANALYSIS_FONT_SIZE='Large',
        OCI_POLICY_ANALYSIS_IAM_API_DIAGNOSTICS_CSV='/tmp/debug.csv',
        MCP_OAUTH_ENABLED='false',
        MCP_OAUTH_ISSUER='https://unused.example',
    )
    result = subprocess.check_output(['python3', str(ROOT / 'run/container-config.py'), 'combined'], env=env, text=True)
    web, mcp = json.loads(result)
    assert set(web['environmentVariables']) == {
        'WEB_RESOURCE_PRINCIPAL_ONLY',
        'WEB_HOST',
        'WEB_PORT',
        'OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH',
    }
    assert set(mcp['environmentVariables']) == {
        'MCP_AUTH_MODE',
        'MCP_TRANSPORT',
        'MCP_HOST',
        'MCP_PORT',
        'OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH',
        'MCP_LOG_LEVEL',
    }
    assert web['environmentVariables']['OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH'] == '2'
    assert mcp['environmentVariables']['OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH'] == '2'


def test_web_only_payload_does_not_require_unused_mcp_configuration():
    env = payload_environment()
    env.update(MCP_OAUTH_ENABLED='true', MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH='invalid', MCP_LOG_LEVEL='invalid')
    result = subprocess.run(
        ['python3', str(ROOT / 'run/container-config.py'), 'web'], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_incomplete_oauth_fails_before_deployment():
    env = payload_environment()
    env['MCP_OAUTH_ENABLED'] = 'true'
    result = subprocess.run(
        ['python3', str(ROOT / 'run/container-config.py'), 'mcp'], env=env, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert 'MCP_OAUTH_ISSUER' in result.stderr


def test_one_run_override_survives_env_and_loader_exports_values(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('OCI_REDEPLOY=false\nOPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH=2\n')
    env = dict(os.environ, RUN_ENV_FILE=str(env_file), OCI_REDEPLOY='true')
    env.pop('OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH', None)
    result = subprocess.run(
        [
            'bash',
            '-c',
            'set -euo pipefail; source run/common.sh; '
            "python3 -c \"import os; print(os.environ['OCI_REDEPLOY'], "
            "os.environ['OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH'])\"",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == 'true 2'


def test_mcp_environment_defaults_and_explicit_depth_override(monkeypatch):
    from oci_policy_analysis import mcp_server

    monkeypatch.setenv('OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH', '2')
    monkeypatch.setenv('MCP_RECURSIVE', 'false')
    parser = mcp_server._build_arg_parser()
    defaults = parser.parse_args(['--profile', 'DEFAULT'])
    explicit = parser.parse_args(['--profile', 'DEFAULT', '--compartment-domain-search-depth', '3'])
    assert defaults.compartment_domain_search_depth == 2
    assert defaults.recursive is False
    assert explicit.compartment_domain_search_depth == 3


def test_loader_handles_clean_macos_bash_environment():
    result = subprocess.run(
        ['/bin/bash', '-c', 'set -euo pipefail; source run/common.sh; echo loaded'],
        cwd=ROOT,
        env={'PATH': os.environ['PATH']},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'loaded'


@pytest.mark.parametrize('current_depth,override,expected', [('2', None, 0), ('1', None, 2), ('1', 'true', 0)])
def test_deployment_detects_environment_drift_without_mutating_in_dry_run(tmp_path, current_depth, override, expected):
    """Same tags must not mask depth drift; dry runs and no-ops never delete/create."""
    env = payload_environment()
    env.update(
        OCI_PROFILE='DEFAULT',
        OCI_REGION='region',
        OCI_COMPARTMENT_ID='COMPARTMENT',
        OCI_SUBNET_ID='SUBNET',
        OCI_NSG_ID='NSG',
        OCI_AVAILABILITY_DOMAIN='AD',
        OCI_INSTANCE_NAME='test-instance',
        OCI_DRY_RUN='true',
    )
    config = tmp_path / '.env'
    config.write_text('OCI_REDEPLOY=false\n')
    env['RUN_ENV_FILE'] = str(config)
    if override:
        env['OCI_REDEPLOY'] = override
    desired = json.loads(
        subprocess.check_output(['python3', str(ROOT / 'run/container-config.py'), 'combined'], env=env, text=True)
    )
    records = []
    for mode, container in zip(('web', 'mcp'), desired, strict=True):
        runtime_env = dict(container['environmentVariables'])
        if mode == 'mcp':
            runtime_env['OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH'] = current_depth
        records.append(
            {
                'image-url': container['imageUrl'],
                'is-resource-principal-disabled': False,
                'environment-variables': runtime_env,
                'health-checks': [{'port': container['healthChecks'][0]['port']}],
            }
        )
    fixtures = {
        'ads': {'data': [{'name': 'AD'}]},
        'shapes': {
            'data': {
                'items': [
                    {
                        'name': 'CI.Standard.E4.Flex',
                        'ocpu-options': {'min': 1, 'max': 64},
                        'memory-options': {
                            'min-in-gbs': 1,
                            'max-in-gbs': 1024,
                            'min-per-ocpu-in-gbs': 1,
                            'max-per-ocpu-in-gbs': 64,
                        },
                    }
                ]
            }
        },
        'instances': {
            'data': {'items': [{'id': 'INSTANCE', 'display-name': 'test-instance', 'lifecycle-state': 'ACTIVE'}]}
        },
        'instance': {
            'data': {
                'lifecycle-state': 'ACTIVE',
                'shape': 'CI.Standard.E4.Flex',
                'availability-domain': 'AD',
                'shape-config': {'ocpus': 1, 'memory-in-gbs': 8},
                'containers': [{'container-id': 'WEB'}, {'container-id': 'MCP'}],
                'vnics': [{'vnic-id': 'VNIC'}],
            }
        },
        'WEB': {'data': records[0]},
        'MCP': {'data': records[1]},
        'network': {'data': {'vcn-id': 'VCN', 'subnet-id': 'SUBNET', 'nsg-ids': ['NSG'], 'private-ip': '10.0.0.10'}},
    }
    (tmp_path / 'fixtures.json').write_text(json.dumps(fixtures))
    stub = tmp_path / 'oci'
    stub.write_text("""#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
root=Path(os.environ['OCI_TEST_DIR']); args=sys.argv[1:]
with (root/'calls').open('a') as stream: stream.write(' '.join(args)+'\\n')
f=json.loads((root/'fixtures.json').read_text())
if 'delete' in args or 'create' in args: sys.exit(99)
if args[:3]==['iam','availability-domain','list']: key='ads'
elif 'list-shapes' in args: key='shapes'
elif args[:3]==['container-instances','container-instance','list']: key='instances'
elif args[:3]==['container-instances','container-instance','get']: key='instance'
elif args[:3]==['container-instances','container','get']: key=args[args.index('--container-id')+1]
elif args[0]=='network': key='network'
else: print('{}'); sys.exit(0)
print(json.dumps(f[key]))
""")
    stub.chmod(0o755)
    env.update(PATH=str(tmp_path) + os.pathsep + os.environ['PATH'], OCI_TEST_DIR=str(tmp_path))
    result = subprocess.run(
        ['bash', str(ROOT / 'run/deploy-container-instance.sh'), 'combined'],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    calls = (tmp_path / 'calls').read_text()
    assert ' delete ' not in calls and ' create ' not in calls
    if current_depth == '2':
        assert 'no changes' in result.stdout
    elif override:
        assert 'Dry run' in result.stdout
    else:
        assert 'OCI_REDEPLOY=true' in result.stderr
