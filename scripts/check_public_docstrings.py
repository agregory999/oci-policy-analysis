#!/usr/bin/env python3
"""Check Google/Napoleon docstrings on maintained public Python symbols."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

EXCLUDED_PARTS = {'__pycache__', 'generated', 'condition_parser', 'policy_parser'}
EXCLUDED_FILES = {
    'OciIamPolicyConditionLexer.py',
    'OciIamPolicyConditionListener.py',
    'OciIamPolicyConditionParser.py',
    'OciIamPolicyConditionVisitor.py',
    'PolicyLexer.py',
    'PolicyListener.py',
    'PolicyParser.py',
    'PolicyVisitor.py',
}


def _is_public(name: str) -> bool:
    return not name.startswith('_')


def _iter_public_symbols(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and _is_public(node.name):
            yield node, node.name


def find_missing(root: Path) -> list[str]:
    missing: list[str] = []
    for path in sorted(root.rglob('*.py')):
        if set(path.parts) & EXCLUDED_PARTS or path.name in EXCLUDED_FILES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError as exc:
            missing.append(f'{path}: syntax error: {exc}')
            continue
        for node, name in _iter_public_symbols(tree):
            if not ast.get_docstring(node, clean=False):
                missing.append(f'{path}:{node.lineno}: {name}')
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('src/oci_policy_analysis'))
    args = parser.parse_args()
    missing = find_missing(args.root)
    if missing:
        print('Missing public Google/Napoleon docstrings:')
        print('\n'.join(missing))
        return 1
    print(f'Public docstring coverage passed for {args.root}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
