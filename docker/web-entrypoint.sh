#!/usr/bin/env bash
set -euo pipefail
# Published releases may not read WEB_HOST/WEB_PORT themselves; pass stable CLI flags.
exec oci-policy-analysis-web --host "${WEB_HOST:-0.0.0.0}" --port "${WEB_PORT:-8000}" "$@"
