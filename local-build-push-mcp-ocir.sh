#!/usr/bin/env bash
set -euo pipefail

# Build and push MCP container image to OCIR.
#
# Required environment variables:
#   OCI_REGION             OCIR region key, for example iad, phx, uk-london-1.
#   OCI_NAMESPACE          Object Storage namespace used by OCIR.
#   OCIR_REPO              OCIR repository path, for example oci-policy-analysis/mcp.
#   OCI_COMPARTMENT_OCID   Compartment OCID that owns the container repository.
#   OCIR_USERNAME          OCI username for docker login (with OCIR_AUTH_TOKEN), or
#                          use an existing Docker login for the OCIR registry.
#   OCIR_AUTH_TOKEN        OCI auth token for docker login (with OCIR_USERNAME).
#
# Optional environment variables:
#   IMAGE_TAG              Image tag to build and push. Defaults to current git short SHA.
#   PUSH_LATEST            Also tag and push :latest. Defaults to true. Allowed: true, false.
#   DOCKERFILE_PATH        Dockerfile path. Defaults to Dockerfile.mcp.
#   OCI_PROFILE            OCI CLI profile. Defaults to the CLI default profile.

print_env_help() {
  cat >&2 <<'EOF'

Required environment variables:
  export OCI_REGION="iad"
  export OCI_NAMESPACE="<object-storage-namespace>"
  export OCIR_REPO="oci-policy-analysis/mcp"
  export OCI_COMPARTMENT_OCID="ocid1.compartment.oc1..<unique_id>"
  # Either authenticate explicitly:
  export OCIR_USERNAME="<oci-username>"
  export OCIR_AUTH_TOKEN="<oci-auth-token>"

  # Or omit both values and reuse an existing Docker login for OCI_REGION.ocir.io.

Optional environment variables:
  export IMAGE_TAG="$(git rev-parse --short HEAD)"
  export PUSH_LATEST="true"
  export DOCKERFILE_PATH="Dockerfile.mcp"
  export OCI_PROFILE="<oci-cli-profile>"

Copy the required block, replace placeholder values, then rerun:
  ./local-build-push-mcp-ocir.sh
EOF
}

REQUIRED_VARS=(
  "OCI_REGION"
  "OCI_NAMESPACE"
  "OCIR_REPO"
  "OCI_COMPARTMENT_OCID"
)

IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
PUSH_LATEST="${PUSH_LATEST:-true}"
PUSH_LATEST_NORMALIZED="$(printf '%s' "${PUSH_LATEST}" | tr '[:upper:]' '[:lower:]')"
DOCKERFILE_PATH="${DOCKERFILE_PATH:-Dockerfile.mcp}"
OCI_PROFILE="${OCI_PROFILE:-}"

MISSING_VARS=()
for var_name in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    MISSING_VARS+=("${var_name}")
  fi
done

if (( ${#MISSING_VARS[@]} > 0 )); then
  echo "ERROR: Missing required environment variables: ${MISSING_VARS[*]}" >&2
  print_env_help
  exit 2
fi

if [[ -n "${OCIR_USERNAME:-}" && -z "${OCIR_AUTH_TOKEN:-}" ]] || [[ -z "${OCIR_USERNAME:-}" && -n "${OCIR_AUTH_TOKEN:-}" ]]; then
  echo "ERROR: Set both OCIR_USERNAME and OCIR_AUTH_TOKEN, or omit both to reuse an existing Docker login." >&2
  exit 2
fi

INVALID_VARS=()
if [[ "${PUSH_LATEST_NORMALIZED}" != "true" && "${PUSH_LATEST_NORMALIZED}" != "false" ]]; then
  INVALID_VARS+=("PUSH_LATEST must be true or false; got '${PUSH_LATEST}'")
fi

if [[ -z "${IMAGE_TAG}" ]]; then
  INVALID_VARS+=("IMAGE_TAG must not be empty")
fi

if [[ -z "${DOCKERFILE_PATH}" ]]; then
  INVALID_VARS+=("DOCKERFILE_PATH must not be empty")
elif [[ ! -f "${DOCKERFILE_PATH}" ]]; then
  INVALID_VARS+=("DOCKERFILE_PATH does not exist: ${DOCKERFILE_PATH}")
fi

if (( ${#INVALID_VARS[@]} > 0 )); then
  echo "ERROR: Invalid environment variable values:" >&2
  printf '  - %s\n' "${INVALID_VARS[@]}" >&2
  print_env_help
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required but not installed." >&2
  exit 2
fi

if ! command -v oci >/dev/null 2>&1; then
  echo "ERROR: OCI CLI is required but not installed." >&2
  exit 2
fi

IMAGE_URI="${OCI_REGION}.ocir.io/${OCI_NAMESPACE}/${OCIR_REPO}:${IMAGE_TAG}"
LATEST_IMAGE_URI="${OCI_REGION}.ocir.io/${OCI_NAMESPACE}/${OCIR_REPO}:latest"

oci_cli() {
  if [[ -n "${OCI_PROFILE}" ]]; then
    oci --profile "${OCI_PROFILE}" "$@"
  else
    oci "$@"
  fi
}

echo "Using image URI: ${IMAGE_URI}"
echo "Checking OCIR repository '${OCIR_REPO}'..."

if ! oci_cli artifacts container repository list \
  --compartment-id "${OCI_COMPARTMENT_OCID}" \
  --all \
  --query "data.items[?\"display-name\"=='${OCIR_REPO}'] | length(@)" \
  --raw-output | grep -q '^1$'; then
  echo "Repository not found. Creating '${OCIR_REPO}'..."
  oci_cli artifacts container repository create \
    --compartment-id "${OCI_COMPARTMENT_OCID}" \
    --display-name "${OCIR_REPO}" \
    >/dev/null
fi

echo "Logging into OCIR registry ${OCI_REGION}.ocir.io..."
if [[ -n "${OCIR_USERNAME:-}" ]]; then
  echo "docker login ${OCI_REGION}.ocir.io --username ${OCI_NAMESPACE}/${OCIR_USERNAME} --password-stdin"
  echo "${OCIR_AUTH_TOKEN}" | docker login "${OCI_REGION}.ocir.io" \
    --username "${OCI_NAMESPACE}/${OCIR_USERNAME}" \
    --password-stdin
else
  echo "Reusing the existing Docker login for ${OCI_REGION}.ocir.io."
fi

echo "Building image with ${DOCKERFILE_PATH}..."
docker build -f "${DOCKERFILE_PATH}" -t "${IMAGE_URI}" .

if [[ "${PUSH_LATEST_NORMALIZED}" == "true" && "${IMAGE_TAG}" != "latest" ]]; then
  echo "Tagging image as latest..."
  docker tag "${IMAGE_URI}" "${LATEST_IMAGE_URI}"
fi

echo "Pushing image..."
docker push "${IMAGE_URI}"

if [[ "${PUSH_LATEST_NORMALIZED}" == "true" && "${IMAGE_TAG}" != "latest" ]]; then
  echo "Pushing latest tag..."
  docker push "${LATEST_IMAGE_URI}"
fi

echo "Done."
echo "Pushed image: ${IMAGE_URI}"
if [[ "${PUSH_LATEST_NORMALIZED}" == "true" ]]; then
  echo "Pushed image: ${LATEST_IMAGE_URI}"
  echo "Deploy with: export OCI_IMAGE_URL=${LATEST_IMAGE_URI}"
fi
