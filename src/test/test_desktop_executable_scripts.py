"""Local PyInstaller builds resolve resources from the repository, not the spec directory."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('platform', ['Darwin', 'Linux', 'MINGW64_NT'])
def test_local_desktop_build_resources_exist_relative_to_spec_directory(tmp_path, platform):
    project = tmp_path / 'project with spaces'
    (project / 'run').mkdir(parents=True)
    (project / 'run-build').mkdir()
    (project / 'dist/tk').mkdir(parents=True)
    for name in ('common.sh', 'build-executable.sh'):
        shutil.copy(ROOT / 'run' / name, project / 'run' / name)
    for resource in ('permissions', 'mcp_tools_list', 'parsers'):
        path = project / 'src/oci_policy_analysis/application/core/resources' / resource
        path.mkdir(parents=True)
        (path / 'sample').write_text('resource')
    config = tmp_path / 'empty.env'
    config.touch()
    commands = tmp_path / 'commands'
    commands.mkdir()
    (project / '.venv/bin').mkdir(parents=True)
    (project / '.venv/bin/activate').write_text('')
    for name, body in {
        'uv': 'exit 0',
        'python': 'echo 7.0.0.dev12',
        'python3': 'echo /tmp/python-library',
        'uname': f'echo {platform}',
        'tar': 'exit 0',
        'zip': 'exit 0',
    }.items():
        command = commands / name
        command.write_text('#!/bin/sh\n' + body + '\n')
        command.chmod(0o755)
    pyinstaller = commands / 'pyinstaller'
    pyinstaller.write_text(
        f'#!{sys.executable}\n'
        'import pathlib, sys\n'
        'args = sys.argv[1:]\n'
        'spec_dir = pathlib.Path(args[args.index("--specpath") + 1]).resolve()\n'
        'for index, argument in enumerate(args):\n'
        '    if argument == "--add-data":\n'
        '        source = args[index + 1].replace(";", ":").split(":")[0]\n'
        '        resolved = spec_dir / source\n'
        '        assert resolved.exists(), f"Missing bundled source: {resolved}"\n'
    )
    pyinstaller.chmod(0o755)
    result = subprocess.run(
        ['bash', str(project / 'run/build-executable.sh')],
        env={**os.environ, 'PATH': str(commands) + os.pathsep + os.environ['PATH'], 'RUN_ENV_FILE': str(config)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
