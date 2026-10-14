"""The source and published-release build paths must remain explicitly separate."""

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def build_environment(tmp_path, version='6.5.5'):
    config = tmp_path / '.env'
    config.write_text(
        'OCI_REGISTRY_HOST=example.ocir.io\nOCI_NAMESPACE=namespace\nOCI_REPOSITORY=repo\n'
        'OCI_PROFILE=DEFAULT\nOCI_REGION=region\nOCI_COMPARTMENT_ID=compartment\n'
        'IMAGE_TAG_WEB=release-web\nIMAGE_TAG_MCP=release-mcp\n'
        + (f'OPA_VERSION={shlex.quote(version)}\n' if version is not None else '')
    )
    docker = tmp_path / 'docker'
    docker.write_text("""#!/usr/bin/env python3
import json,os,sys
with open(os.environ['BUILD_TEST_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
""")
    docker.chmod(0o755)
    oci = tmp_path / 'oci'
    oci.write_text("""#!/usr/bin/env python3
import json,sys
if sys.argv[1:4]==['artifacts','container','repository']:
 print(json.dumps({'data':{'items':[{'display-name':'repo'}]}}))
elif 'lookup' in sys.argv: sys.exit(1)
else: print('{}')
""")
    oci.chmod(0o755)
    env = {
        key: val
        for key, val in os.environ.items()
        if not key.startswith(('OCI_', 'OPA_', 'BUILD_', 'IMAGE_TAG_', 'RUN_ENV_'))
    }
    env.update(
        PATH=str(tmp_path) + os.pathsep + os.environ['PATH'],
        RUN_ENV_FILE=str(config),
        BUILD_TEST_LOG=str(tmp_path / 'calls'),
    )
    return env


@pytest.mark.parametrize('script,source', [('build-push-image.sh', 'local'), ('build-push-pypi.sh', 'pypi')])
def test_combined_build_uses_selected_source_and_both_tags(tmp_path, script, source):
    env = build_environment(tmp_path)
    result = subprocess.run(['bash', str(ROOT / 'run' / script), 'combined'], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in (tmp_path / 'calls').read_text().splitlines()]
    builds = [call for call in calls if call[:2] == ['buildx', 'build']]
    assert len(builds) == 2
    assert [call[call.index('--target') + 1] for call in builds] == ['web', 'mcp']
    assert len([call for call in calls if call[0] == 'push']) == 2
    for call in builds:
        if source == 'pypi':
            assert call[-1] == str(ROOT / 'docker')
            assert call[call.index('--file') + 1] == str(ROOT / 'Dockerfile.pypi')
            assert 'OPA_VERSION=6.5.5' in call
        else:
            assert call[-1] == str(ROOT)
            assert call[call.index('--file') + 1] == str(ROOT / 'Dockerfile')
            assert not any(value.startswith('OPA_VERSION=') for value in call)


@pytest.mark.parametrize('version', [None, 'latest', '>=6.5.5'])
def test_pypi_requires_exact_version_before_build_or_push(tmp_path, version):
    env = build_environment(tmp_path, version)
    result = subprocess.run(
        ['bash', str(ROOT / 'run/build-push-pypi.sh'), 'combined'], env=env, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert 'OPA_VERSION' in result.stderr
    assert not (tmp_path / 'calls').exists()
