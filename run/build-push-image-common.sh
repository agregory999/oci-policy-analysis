#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
image_source="${1:?build source is required}"
shift
kind="${1:-}"
build_args=()
case "${image_source}" in
  local) dockerfile="$root_dir/Dockerfile"; context="$root_dir" ;;
  pypi)
    require_values OPA_VERSION
    [[ "$OPA_VERSION" =~ ^[0-9][a-zA-Z0-9.+!-]*$ ]] || { echo "OPA_VERSION must be an exact published version." >&2; exit 2; }
    dockerfile="$root_dir/Dockerfile.pypi"; context="$root_dir/docker"
    build_args=(--build-arg "OPA_VERSION=$OPA_VERSION") ;;
  *) echo "Invalid build source; use run/build-push-image.sh or run/build-push-pypi.sh." >&2; exit 2 ;;
esac
if [[ "$kind" == combined ]]; then
  require_values IMAGE_TAG_WEB IMAGE_TAG_MCP
  [[ "$IMAGE_TAG_WEB" != "$IMAGE_TAG_MCP" ]] || { echo "Web and MCP tags must differ." >&2; exit 2; }
  "$script_dir/build-push-image-common.sh" "$image_source" web
  exec "$script_dir/build-push-image-common.sh" "$image_source" mcp
fi
case "${kind}" in web) tag="${IMAGE_TAG_WEB:-}"; tag_name=IMAGE_TAG_WEB ;; mcp) tag="${IMAGE_TAG_MCP:-}"; tag_name=IMAGE_TAG_MCP ;; *) echo "Usage: run/build-push-image.sh web|mcp|combined" >&2; exit 2 ;; esac
for name in OCI_REGISTRY_HOST OCI_NAMESPACE OCI_REPOSITORY OCI_PROFILE OCI_REGION OCI_COMPARTMENT_ID; do
  [[ -n "${!name:-}" ]] || { echo "Missing ${name} in ${env_file}" >&2; exit 2; }
done
[[ -n "${tag}" ]] || { echo "Missing ${tag_name} in ${env_file}" >&2; exit 2; }
[[ "${tag}" != latest ]] || { echo "Use a unique image tag, not latest." >&2; exit 2; }
command -v docker >/dev/null || { echo "Docker is required." >&2; exit 2; }
command -v oci >/dev/null || { echo "OCI CLI is required." >&2; exit 2; }
command -v jq >/dev/null || { echo "jq is required." >&2; exit 2; }
docker info >/dev/null || { echo "Docker daemon or registry authentication is unavailable." >&2; exit 2; }
image="${OCI_REGISTRY_HOST}/${OCI_NAMESPACE}/${OCI_REPOSITORY}:${tag}"
profile_args=(--profile "${OCI_PROFILE}" --region "${OCI_REGION}")
oci iam compartment get "${profile_args[@]}" --compartment-id "${OCI_COMPARTMENT_ID}" >/dev/null
repositories="$(oci artifacts container repository list "${profile_args[@]}" --compartment-id "${OCI_COMPARTMENT_ID}" --all --output json)"
jq -e --arg name "${OCI_REPOSITORY}" 'any(.data.items[]?; ."display-name"==$name)' <<<"${repositories}" >/dev/null || { echo "OCIR repository ${OCI_REPOSITORY} is absent or inaccessible in ${OCI_COMPARTMENT_ID}." >&2; exit 2; }
if oci artifacts container image lookup "${profile_args[@]}" --image-uri "${OCI_NAMESPACE}/${OCI_REPOSITORY}:${tag}" >/dev/null 2>&1 && [[ "${ALLOW_TAG_REPUSH:-false}" != true ]]; then
  echo "${image} exists; choose a new tag or set ALLOW_TAG_REPUSH=true explicitly." >&2
  exit 2
fi
build_args+=(--build-arg "IMAGE_TAG=$tag" --build-arg "BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)")
docker buildx build --platform "${BUILD_PLATFORM:-linux/amd64}" --target "${kind}" --file "$dockerfile" ${build_args[@]+"${build_args[@]}"} --tag "${image}" --load "$context"
docker push "${image}"
echo "Published ${image}. Record the digest from docker push output."
