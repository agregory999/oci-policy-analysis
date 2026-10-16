"""Build and smoke-test the checked-out Qt workbench with Nuitka/PySide6."""

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_command(*, mode: str, output_dir: Path, jobs: int) -> list[str]:
    """Construct a platform-native Nuitka command with packaged runtime data.

    Args:
        mode: Standalone directory/app bundle or single-file executable.
        output_dir: Build output directory; never contains operator configuration.
        jobs: Maximum concurrent C compiler processes.

    Returns:
        list[str]: Shell-independent subprocess arguments for the active Python.
    """
    compilation_mode = ('app' if mode == 'onefile' else 'app-dist') if sys.platform == 'darwin' else mode
    command = [
        sys.executable,
        '-m',
        'nuitka',
        f'--mode={compilation_mode}',
        f'--output-dir={output_dir}',
        '--output-filename=' + ('oci-policy-analysis-qt.exe' if sys.platform == 'win32' else 'oci-policy-analysis-qt'),
        f'--jobs={jobs}',
    ]
    command.append('scripts/qt_entry.py')
    return command


def main(argv: list[str] | None = None) -> int:
    """Compile local source and verify the resulting executable before archiving.

    Args:
        argv: Optional CLI arguments; defaults to the process arguments.

    Returns:
        int: Zero after a successful build, smoke test and distributable archive.

    Notes:
        Run on each target OS with its native C toolchain. The default standalone
        build includes shared libraries; onefile embeds them into one executable.
        Does not sign, notarize, publish, or include the external Codex CLI.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('standalone', 'onefile'), default='standalone')
    parser.add_argument('--jobs', type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist' / 'qt')
    stages = parser.add_mutually_exclusive_group()
    stages.add_argument(
        '--prepare-only', action='store_true', help='Stamp version and smoke-test source before the CI action'
    )
    stages.add_argument(
        '--package-only', action='store_true', help='Smoke-test and archive an already compiled CI bundle'
    )
    parser.add_argument('--build-dir', type=Path, default=ROOT / 'build' / 'qt' / 'native')
    parser.add_argument('--dry-run', action='store_true', help='Print the exact compile command without building')
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    command = build_command(mode=args.mode, output_dir=args.build_dir.resolve(), jobs=args.jobs)
    print(shlex.join(command), flush=True)
    if args.dry_run:
        return 0
    import shutil
    from importlib.metadata import version

    (ROOT / 'build' / 'qt').mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.build_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not args.package_only:
        build_version = version('oci-policy-analysis')
        (ROOT / 'src/oci_policy_analysis/version.txt').write_text(build_version + '\n', encoding='utf-8')
        subprocess.run(
            [sys.executable, 'scripts/qt_entry.py', '--self-test'],
            cwd=ROOT,
            env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
            check=True,
        )
        if args.prepare_only:
            return 0
        subprocess.run(command, cwd=ROOT, check=True)
    if sys.platform == 'darwin':
        candidates = list(output.glob('*.app/Contents/MacOS/oci-policy-analysis-qt'))
    elif args.mode == 'onefile':
        candidates = [output / ('oci-policy-analysis-qt.exe' if sys.platform == 'win32' else 'oci-policy-analysis-qt')]
    else:
        candidates = [
            output
            / 'qt_entry.dist'
            / ('oci-policy-analysis-qt.exe' if sys.platform == 'win32' else 'oci-policy-analysis-qt')
        ]
    if len(candidates) != 1 or not candidates[0].is_file():
        raise RuntimeError(f'Expected one packaged executable, found: {candidates}')
    executable = candidates[0]
    subprocess.run(
        [str(executable), '--self-test'],
        cwd=output,
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTHONPATH': ''},
        check=True,
        timeout=180,
    )
    bundle = (
        executable.parents[2]
        if sys.platform == 'darwin'
        else executable
        if args.mode == 'onefile'
        else executable.parent
    )
    archive_base = (
        args.output_dir.resolve()
        / f'oci-policy-analysis-qt-{platform.system().lower()}-{platform.machine()}-{version("oci-policy-analysis")}'
    )
    archive_format = 'zip' if sys.platform == 'win32' else 'gztar'
    archive = shutil.make_archive(str(archive_base), archive_format, root_dir=bundle.parent, base_dir=bundle.name)
    (args.output_dir / 'build-result.json').write_text(
        json.dumps({'executable': str(executable), 'archive': archive, 'smoke_test': 'passed'}, indent=2)
    )
    print(f'Verified executable: {executable}\nArchive: {archive}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
