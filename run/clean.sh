#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
mode="all"
if [[ $# -gt 0 ]]; then
  [[ $# == 2 && "$1" == "--mode" ]] || { echo "Usage: run/clean.sh [--mode ui|legacy-ui]" >&2; exit 2; }
  mode="$2"
fi
case "$mode" in
  ui)
    rm -rf -- "$root_dir/dist/qt" "$root_dir/build/qt"
    echo "Removed modern UI executable build artifacts. The shared .venv remains."
    ;;
  legacy-ui)
    rm -rf -- "$root_dir/dist/tk" "$root_dir/build/tk"
    rm -f -- "$root_dir/run-build/oci-policy-analysis-tk.spec" "$root_dir/frozen.txt" "$root_dir/deps.txt" "$root_dir/deps2.txt"
    echo "Removed legacy UI executable build artifacts. The shared .venv remains."
    ;;
  all)
    # Deliberate full reset of generated artifacts; configuration and OCI keys survive.
    rm -rf -- "$root_dir/.venv" "$root_dir/dist" "$root_dir/build" "$root_dir/wheels"
    rm -f -- "$root_dir/frozen.txt" "$root_dir/deps.txt" "$root_dir/deps2.txt"
    find "$root_dir/src" -type d -name __pycache__ -prune -exec rm -rf -- {} +
    echo "Removed local environment and build artifacts. Run run/build.sh to rebuild."
    ;;
  *) echo "Invalid clean mode: $mode (expected ui, legacy-ui, or all)" >&2; exit 2 ;;
esac
