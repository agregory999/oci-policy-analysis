"""Check this repository's OCI Python project contract without accessing OCI."""

import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
    required = (
        '.oci-project.yml',
        'AGENTS.md',
        'README.md',
        'pyproject.toml',
        'uv.lock',
        'Dockerfile',
        '.dockerignore',
        'run/.env.example',
        'run-build/.env.example',
        'run/common.sh',
        'run/build.sh',
        'run/clean.sh',
        'run/README.md',
        'run/local.sh',
        'run/build-push-image.sh',
        'run/deploy-container-instance.sh',
        'docs/architecture.md',
        'docs/requirements.md',
    )
    missing = [path for path in required if not (root / path).is_file()]
    if missing:
        print('Missing project contract files: ' + ', '.join(missing), file=sys.stderr)
        return 1
    for name in ('run/.env', 'run-build/.env'):
        if name not in (root / '.gitignore').read_text():
            print(f'{name} is not ignored', file=sys.stderr)
            return 1
    print('OCI Python project structure: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
