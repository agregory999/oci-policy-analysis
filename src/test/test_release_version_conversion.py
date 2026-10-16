"""Release preparation preserves prerelease sequence numbers without requiring a lockfile."""

import json
import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is used by the release workflow')
@pytest.mark.parametrize(
    ('release', 'expected'),
    [
        ('6.5.7', '6.5.7'),
        ('7.0.0-7-0-0-policy-corpus-cross-tenancy.1', '7.0.0.dev1'),
        ('7.0.0-7-0-0-policy-corpus-cross-tenancy.2', '7.0.0.dev2'),
        ('7.0.0-dev.3', '7.0.0.dev3'),
        ('7.0.0-rc.2', '7.0.0rc2'),
    ],
)
def test_release_prepare_command_updates_package_version_without_lockfile(tmp_path, release, expected):
    root = Path(__file__).parents[2]
    config = json.loads((root / '.releaserc.json').read_text())
    command = next(plugin[1]['prepareCmd'] for plugin in config['plugins'] if plugin[0] == '@semantic-release/exec')
    command = command.replace('scripts/prepare_release_version.cjs', str(root / 'scripts/prepare_release_version.cjs'))
    command = command.replace('${nextRelease.version}', release)
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "oci-policy-analysis"\nversion = "7.0.0.dev0"\n')
    subprocess.run(shlex.split(command), cwd=tmp_path, capture_output=True, text=True, check=True)
    assert tomllib.loads((tmp_path / 'pyproject.toml').read_text())['project']['version'] == expected
    assert not (tmp_path / 'uv.lock').exists()
    assets = next(plugin[1]['assets'] for plugin in config['plugins'] if plugin[0] == '@semantic-release/git')
    assert 'uv.lock' not in assets
