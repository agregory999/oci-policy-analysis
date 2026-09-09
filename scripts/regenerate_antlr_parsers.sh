#!/usr/bin/env bash
# Regenerate the checked-in ANTLR Python parsers after changing a .g4 source.
# Requires Java; the pinned ANTLR 4.13.2 jar is stored with the grammars.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
resources="$root/src/oci_policy_analysis/application/core/resources/parsers"
parser_root="$root/src/oci_policy_analysis/application/core/parser"

generate() {
  local grammar="$1" output="$2"
  # Run from the grammar directory: ANTLR otherwise mirrors an absolute input
  # path beneath the output directory instead of writing into the parser package.
  (
    cd "$resources"
    java -jar antlr-4.13.2-complete.jar -Dlanguage=Python3 -visitor -listener -o "$output" "$grammar"
  )
  # Normalize generator whitespace and run the repository's pinned hooks. ANTLR's
  # Python template uses tabs in a few files, which fails the normal commit hook.
  perl -0777 -pi -e 's/^[ \t]+(?=\n)//mg; s/^\t/    /mg; s/[ \t]+(?=\n)//g; s/\n+\z/\n/' "$output"/*.py
  if ! uv run pre-commit run ruff --files "$output"/*.py; then
    uv run pre-commit run ruff --files "$output"/*.py
  fi
  if ! uv run pre-commit run ruff-format --files "$output"/*.py; then
    uv run pre-commit run ruff-format --files "$output"/*.py
  fi
}

generate Policy.g4 "$parser_root/policy_parser"
generate OciIamPolicyCondition.g4 "$parser_root/condition_parser"
