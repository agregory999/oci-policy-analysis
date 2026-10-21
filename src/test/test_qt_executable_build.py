"""Check platform-specific Qt packaging choices without a compiler or GUI."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('qt_executable_builder', ROOT / 'run-build/build_qt_executable.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


@pytest.mark.parametrize(
    ('target', 'requested_mode', 'compiler_mode'),
    [
        ('darwin', 'standalone', 'app-dist'),
        ('darwin', 'onefile', 'onefile'),
        ('win32', 'standalone', 'standalone'),
        ('win32', 'onefile', 'onefile'),
        ('linux', 'standalone', 'standalone'),
        ('linux', 'onefile', 'onefile'),
    ],
)
def test_qt_native_build_has_plugin_resources_and_platform_mode(
    monkeypatch, tmp_path, target, requested_mode, compiler_mode
):
    monkeypatch.setattr(BUILDER.sys, 'platform', target)
    command = BUILDER.build_command(mode=requested_mode, output_dir=tmp_path / 'output with spaces', jobs=2)
    assert f'--mode={compiler_mode}' in command
    project_options = (ROOT / 'run-build/qt_entry.py').read_text()
    assert '--enable-plugin=pyside6' in project_options
    assert '--user-package-configuration-file={MAIN_DIRECTORY}/qt.nuitka-package.config.yml' in project_options
    assert '--include-package-data=oci_policy_analysis' in project_options
    assert '--include-distribution-metadata=fastmcp' in project_options
    assert '--include-distribution-metadata=mcp' in project_options
    assert f'--output-dir={tmp_path / "output with spaces"}' in command
    assert command[-1] == 'run-build/qt_entry.py'
    if target == 'darwin':
        assert '--macos-app-icon={MAIN_DIRECTORY}/../icons/oci-policy-dg-viewer.icns' in project_options
        assert '--macos-create-app-bundle' not in command  # Conflicts with Nuitka 4 mode.
    elif target == 'win32':
        assert '--output-filename=oci-policy-analysis-qt.exe' in command
        assert '--windows-console-mode=disable' in project_options
        assert '--windows-icon-from-ico={MAIN_DIRECTORY}/../icons/oci-policy-dg-viewer.ico' in project_options


def test_oci_packaging_replacement_matches_the_pinned_sdk_source():
    import inspect

    import oci

    source = inspect.getsource(oci)
    configuration = (ROOT / 'run-build/qt.nuitka-package.config.yml').read_text()
    condition = 'if sys.version_info >= (3, 7) and os.getenv("OCI_PYTHON_SDK_LAZY_IMPORTS_DISABLED", "False").lower() != "true":'
    assert condition in source
    assert condition in configuration


def test_shared_project_options_are_accepted_by_the_pinned_compiler():
    pytest.importorskip('nuitka')
    from nuitka.options.OptionParsing import getNuitkaProjectOptions
    from nuitka.Tracing import options_logger

    options = getNuitkaProjectOptions(options_logger, str(ROOT / 'run-build/qt_entry.py'), False)
    assert '--include-distribution-metadata=fastmcp' in options
    assert '--include-distribution-metadata=mcp' in options
    configuration = next(option.split('=', 1)[1] for option in options if option.startswith('--user-package'))
    assert Path(configuration).is_file()


def test_size_experiments_keep_runtime_metadata_and_explicit_compiler_options(tmp_path):
    command = BUILDER.build_command(mode='onefile', output_dir=tmp_path, jobs=2, lto='yes', lean_data=True)
    assert '--lto=yes' in command
    assert '--noinclude-qt-translations' in command
    assert '--noinclude-data-files=oci_policy_analysis/application/core/resources/parsers/*.jar' in command
    assert not any('no_docstrings' in arg or 'no_asserts' in arg for arg in command)


def test_packaging_keeps_runtime_files_and_checks_the_distributable(monkeypatch, tmp_path):
    import json
    import tarfile

    monkeypatch.setattr(BUILDER.sys, 'platform', 'linux')
    native = tmp_path / 'compiler'
    bundle = native / 'oci-policy-analysis-qt.dist'
    bundle.mkdir(parents=True)
    (bundle / 'oci-policy-analysis-qt').write_text('frozen executable placeholder')
    (bundle / 'runtime-library.so').write_text('required adjacent library')
    (native / 'operator.env').write_text('excluded operator configuration')
    output = tmp_path / 'distributables'
    calls = []
    monkeypatch.setattr(BUILDER.subprocess, 'run', lambda command, **kwargs: calls.append((command, kwargs)))

    assert BUILDER.main(['--package-only', '--build-dir', str(native), '--output-dir', str(output)]) == 0
    result = json.loads((output / 'build-result-standalone.json').read_text())
    executable = output / 'oci-policy-analysis-qt' / 'oci-policy-analysis-qt'
    assert Path(result['executable']) == executable
    assert calls[0][0] == [str(executable), '--self-test']
    assert calls[0][1]['env']['PYTHONPATH'] == ''
    with tarfile.open(result['archive']) as archive:
        members = archive.getnames()
        assert 'oci-policy-analysis-qt/runtime-library.so' in members
        assert not any('operator.env' in member for member in members)
    assert result['smoke_test'] == 'passed'
    assert result['bundle_bytes'] > 0 and result['archive_bytes'] > 0


@pytest.mark.parametrize('target', ['darwin', 'win32'])
def test_true_onefile_is_a_binary_not_an_app_directory(monkeypatch, tmp_path, target):
    import json

    monkeypatch.setattr(BUILDER.sys, 'platform', target)
    native = tmp_path / 'compiler'
    native.mkdir()
    extension = '.exe' if target == 'win32' else ''
    (native / f'oci-policy-analysis-qt{extension}').write_text('onefile payload')
    output = tmp_path / 'dist'
    monkeypatch.setattr(BUILDER.subprocess, 'run', lambda *args, **kwargs: None)
    assert (
        BUILDER.main(['--mode', 'onefile', '--package-only', '--build-dir', str(native), '--output-dir', str(output)])
        == 0
    )
    result = json.loads((output / 'build-result-onefile.json').read_text())
    executable = Path(result['executable'])
    assert executable.name == f'oci-policy-analysis-qt-onefile{extension}'
    assert executable.is_file() and executable.suffix != '.app'
