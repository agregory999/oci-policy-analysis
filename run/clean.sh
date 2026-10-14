#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
# Deliberate reset of generated artifacts only; configuration and OCI keys survive.
[[ $# == 0 ]] || { echo "Usage: run/clean.sh" >&2; exit 2; }
rm -rf -- "$root_dir/.venv" "$root_dir/dist" "$root_dir/build" "$root_dir/wheels"
rm -f -- "$root_dir/frozen.txt" "$root_dir/deps.txt" "$root_dir/deps2.txt"
find "$root_dir/src" -type d -name __pycache__ -prune -exec rm -rf -- {} +
echo "Removed local environment and build artifacts. Run run/build.sh to rebuild."
