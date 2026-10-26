#!/usr/bin/env bash
# Regenerate the checked-in ANTLR Python parsers after changing a .g4 source.
# Requires Java and the ignored ANTLR 4.13.2 jar alongside the grammars.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
resources="$root/src/oci_policy_analysis/application/core/resources/parsers"
parser_root="$root/src/oci_policy_analysis/application/core/parser"

command -v java >/dev/null || { echo "Java is required to regenerate parsers." >&2; exit 2; }
[[ -f "$resources/antlr-4.13.2-complete.jar" ]] || {
  echo "Place antlr-4.13.2-complete.jar in $resources before regenerating parsers." >&2
  exit 2
}

generate() {
  local grammar="$1" output="$2"
  # Run from the grammar directory: ANTLR otherwise mirrors an absolute input
  # path beneath the output directory instead of writing into the parser package.
  (
    cd "$resources"
    java -jar antlr-4.13.2-complete.jar -Dlanguage=Python3 -visitor -listener -o "$output" "$grammar"
  )
  # Normalize generated whitespace. Generated parsers are intentionally excluded
  # from Ruff/pre-commit; those hooks would skip these files.
  perl -0777 -pi -e 's/^[ \t]+(?=\n)//mg; s/^\t/    /mg; s/[ \t]+(?=\n)//g; s/\n+\z/\n/' "$output"/*.py
}

generate Policy.g4 "$parser_root/policy_parser"
generate OciIamPolicyCondition.g4 "$parser_root/condition_parser"
