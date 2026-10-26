#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
require_values OPA_VERSION
[[ "$OPA_VERSION" =~ ^[0-9][a-zA-Z0-9.+!-]*$ ]] || { echo "OPA_VERSION must be one exact published version (no ranges, URLs or latest)." >&2; exit 2; }
# Explicit opt-in; the ordinary build command always defaults to checked-out source.
exec "$script_dir/build-push-image-common.sh" pypi "$@"
