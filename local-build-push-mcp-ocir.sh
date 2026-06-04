#!/usr/bin/env bash
set -euo pipefail

# Build and push MCP container image to OCIR.
#
# Required environment variables:
#   OCI_REGION
#   OCI_NAMESPACE
#   OCIR_REPO
#   OCI_COMPARTMENT_OCID
#   OCIR_USERNAME
#   OCIR_AUTH_TOKEN
#
# Optional:
#   IMAGE_TAG (default: current git short SHA)
#   DOCKERFILE_PATH (default: Dockerfile.mcp)
#   OCI_PROFILE (default: CLI default profile)

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required but not installed." >&2
  exit 2
fi

if ! command -v oci >/dev/null 2>&1; then
  echo "ERROR: OCI CLI is required but not installed." >&2
  exit 2
fi

REQUIRED_VARS=(
  "OCI_REGION"
  "OCI_NAMESPACE"
  "OCIR_REPO"
  "OCI_COMPARTMENT_OCID"
  "OCIR_USERNAME"
  "OCIR_AUTH_TOKEN"
)

MISSING_VARS=()
for var_name in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    MISSING_VARS+=("${var_name}")
  fi
done

if (( ${#MISSING_VARS[@]} > 0 )); then
  echo "ERROR: Missing required environment variables: ${MISSING_VARS[*]}" >&2
  cat >&2 <<'EOF'
Set them before running, for example:
  export OCI_REGION=iad
  export OCI_NAMESPACE=<object-storage-namespace>
  export OCIR_REPO=<repo-path>
  export OCI_COMPARTMENT_OCID=<compartment-ocid>
  export OCIR_USERNAME=<oci-username>
  export OCIR_AUTH_TOKEN=<oci-auth-token>
EOF
  exit 2
fi

IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD)}"
DOCKERFILE_PATH="${DOCKERFILE_PATH:-Dockerfile.mcp}"
OCI_PROFILE="${OCI_PROFILE:-}"
IMAGE_URI="${OCI_REGION}.ocir.io/${OCI_NAMESPACE}/${OCIR_REPO}:${IMAGE_TAG}"

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
echo "${OCIR_AUTH_TOKEN}" | docker login "${OCI_REGION}.ocir.io" \
  --username "${OCI_NAMESPACE}/${OCIR_USERNAME}" \
  --password-stdin

echo "Building image with ${DOCKERFILE_PATH}..."
docker build -f "${DOCKERFILE_PATH}" -t "${IMAGE_URI}" .

echo "Pushing image..."
docker push "${IMAGE_URI}"

echo "Done."
echo "Pushed image: ${IMAGE_URI}"
