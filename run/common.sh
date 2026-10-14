#!/usr/bin/env bash
# Shared configuration loader; caller enables strict shell mode.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "${script_dir}/.." && pwd)"
env_file="${RUN_ENV_FILE:-${root_dir}/run-build/.env}"
# Export sourceable assignments to Python, while preserving one-run overrides.
load_run_env() {
  local name value
  local overrides=()
  while IFS= read -r name; do
    case "$name" in RUN_ENV_FILE|LOCAL_*|BUILD_*|PYTHON_BIN|OCI_*|IMAGE_TAG_*|ALLOW_TAG_REPUSH|MCP_*|WEB_*|OPA_*)
      value="${!name}"; overrides+=("$name=$value") ;;
    esac
  done < <(compgen -e)
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  elif [[ -n "${RUN_ENV_FILE:-}" ]]; then
    echo "Missing config: $env_file" >&2; exit 2
  fi
  for value in ${overrides[@]+"${overrides[@]}"}; do export "$value"; done
}
load_run_env
require_values() {
  local name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || { echo "Missing $name; configure $env_file (see run-build/.env.example)." >&2; exit 2; }
  done
}
cd "$root_dir"
