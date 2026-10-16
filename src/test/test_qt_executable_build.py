"""Check platform-specific Qt packaging choices without a compiler or GUI."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('qt_executable_builder', ROOT / 'scripts/build_qt_executable.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


@pytest.mark.parametrize(
    ('target', 'requested_mode', 'compiler_mode'),
    [
        ('darwin', 'standalone', 'app-dist'),
        ('darwin', 'onefile', 'app'),
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
    project_options = (ROOT / 'scripts/qt_entry.py').read_text()
    assert '--enable-plugin=pyside6' in project_options
    assert '--user-package-configuration-file={MAIN_DIRECTORY}/qt.nuitka-package.config.yml' in project_options
    assert '--include-package-data=oci_policy_analysis' in project_options
    assert '--include-distribution-metadata=fastmcp' in project_options
    assert '--include-distribution-metadata=mcp' in project_options
    assert f'--output-dir={tmp_path / "output with spaces"}' in command
    assert command[-1] == 'scripts/qt_entry.py'
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
    configuration = (ROOT / 'scripts/qt.nuitka-package.config.yml').read_text()
    condition = 'if sys.version_info >= (3, 7) and os.getenv("OCI_PYTHON_SDK_LAZY_IMPORTS_DISABLED", "False").lower() != "true":'
    assert condition in source
    assert condition in configuration


def test_shared_project_options_are_accepted_by_the_pinned_compiler():
    pytest.importorskip('nuitka')
    from nuitka.options.OptionParsing import getNuitkaProjectOptions
    from nuitka.Tracing import options_logger

    options = getNuitkaProjectOptions(options_logger, str(ROOT / 'scripts/qt_entry.py'), False)
    assert '--include-distribution-metadata=fastmcp' in options
    assert '--include-distribution-metadata=mcp' in options
    configuration = next(option.split('=', 1)[1] for option in options if option.startswith('--user-package'))
    assert Path(configuration).is_file()
