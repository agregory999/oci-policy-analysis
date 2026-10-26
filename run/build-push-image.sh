#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# This command always builds the checked-out application source.
exec "$script_dir/build-push-image-common.sh" local "$@"
