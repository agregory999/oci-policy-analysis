#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
mode="${LOCAL_BUILD_MODE:-all}"
if [[ "${1:-}" == --mode ]]; then mode="${2:?--mode requires a value}"; shift 2; fi
[[ $# == 0 ]] || { echo "Usage: run/build.sh [--mode desktop|web|cli|mcp|all]" >&2; exit 2; }
command -v uv >/dev/null || { echo "Install uv first." >&2; exit 2; }
extras=()
case "$mode" in
  all) extras=(--extra web --extra mcp) ;;
  web|mcp) extras=(--extra "$mode") ;;
  desktop|cli) ;;
  *) echo "Invalid build mode: $mode" >&2; exit 2 ;;
esac
uv sync ${extras[@]+"${extras[@]}"} ${PYTHON_BIN:+--python "$PYTHON_BIN"}
uv build
