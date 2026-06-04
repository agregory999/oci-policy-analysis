#!/usr/bin/env bash
set -euo pipefail

# Deploy (or redeploy) OCI Policy Analysis MCP as an OCI Container Instance.
#
# Required environment variables:
#   OCI_COMPARTMENT_OCID
#   OCI_SUBNET_OCID
#   OCI_IMAGE_URL
#
# Optional environment variables:
#   OCI_PROFILE                         (recommended)
#   OCI_AD                              (required if no existing instance with same display name)
#   OCI_CONTAINER_INSTANCE_NAME         (default: opa-mcp-policy-latest-a1)
#   OCI_CONTAINER_NAME                  (default: mcp)
#   OCI_CONTAINER_SHAPE                 (default: CI.Standard.A1.Flex)
#   OCI_CONTAINER_OCPUS                 (default: 1)
#   OCI_CONTAINER_MEMORY_GBS            (default: 8)
#   OCI_PRIVATE_IP                      (optional static private IP in selected subnet)
#   OCI_REDEPLOY                        (default: true)
#
#   MCP_AUTH_MODE                       (default: resource_principal)
#   MCP_TRANSPORT                       (default: streamable-http)
#   MCP_HOST                            (default: 0.0.0.0)
#   MCP_PORT                            (default: 8765)
#   MCP_LOG_LEVEL                       (default: INFO)
#   MCP_SAVE_CACHE_AFTER_LOAD           (default: false)
#   MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH (default: 1)

if ! command -v oci >/dev/null 2>&1; then
  echo "ERROR: OCI CLI is required but not installed." >&2
  exit 2
fi

REQUIRED_VARS=(
  "OCI_COMPARTMENT_OCID"
  "OCI_SUBNET_OCID"
  "OCI_IMAGE_URL"
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
  export OCI_COMPARTMENT_OCID=<compartment-ocid>
  export OCI_SUBNET_OCID=<subnet-ocid>
  export OCI_IMAGE_URL=ocir.us-ashburn-1.oci.oraclecloud.com/<namespace>/<repo>:latest
EOF
  exit 2
fi

OCI_PROFILE="${OCI_PROFILE:-}"
OCI_CONTAINER_INSTANCE_NAME="${OCI_CONTAINER_INSTANCE_NAME:-opa-mcp-policy-latest-a1}"
OCI_CONTAINER_NAME="${OCI_CONTAINER_NAME:-mcp}"
OCI_CONTAINER_SHAPE="${OCI_CONTAINER_SHAPE:-CI.Standard.A1.Flex}"
OCI_CONTAINER_OCPUS="${OCI_CONTAINER_OCPUS:-1}"
OCI_CONTAINER_MEMORY_GBS="${OCI_CONTAINER_MEMORY_GBS:-8}"
OCI_PRIVATE_IP="${OCI_PRIVATE_IP:-}"
OCI_REDEPLOY="${OCI_REDEPLOY:-true}"
OCI_AD="${OCI_AD:-}"

MCP_AUTH_MODE="${MCP_AUTH_MODE:-resource_principal}"
MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_PORT="${MCP_PORT:-8765}"
MCP_LOG_LEVEL="${MCP_LOG_LEVEL:-INFO}"
MCP_SAVE_CACHE_AFTER_LOAD="${MCP_SAVE_CACHE_AFTER_LOAD:-false}"
MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH="${MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH:-1}"

if [[ ! "${MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH}" =~ ^[0-9]+$ ]] || (( MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH < 1 || MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH > 6 )); then
  echo "ERROR: MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH must be an integer between 1 and 6." >&2
  exit 2
fi

oci_cli() {
  if [[ -n "${OCI_PROFILE}" ]]; then
    oci --profile "${OCI_PROFILE}" "$@"
  else
    oci "$@"
  fi
}

to_lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

echo "Using OCI profile: ${OCI_PROFILE:-<default>}"
echo "Preflight checks: compartment, subnet, and image reference..."

if ! oci_cli iam compartment get --compartment-id "${OCI_COMPARTMENT_OCID}" >/dev/null 2>&1; then
  echo "ERROR: Unable to access OCI_COMPARTMENT_OCID=${OCI_COMPARTMENT_OCID} with profile ${OCI_PROFILE:-<default>}." >&2
  exit 2
fi

if ! oci_cli network subnet get --subnet-id "${OCI_SUBNET_OCID}" >/dev/null 2>&1; then
  echo "ERROR: Unable to access OCI_SUBNET_OCID=${OCI_SUBNET_OCID} with profile ${OCI_PROFILE:-<default>}." >&2
  echo "Check that the subnet OCID is correct and in the same region as your OCI CLI/profile context." >&2
  exit 2
fi

if [[ "${OCI_IMAGE_URL}" != *".ocir.io/"* && "${OCI_IMAGE_URL}" != ocir.*.oci.oraclecloud.com/* ]]; then
  echo "ERROR: OCI_IMAGE_URL does not look like an OCIR image URL: ${OCI_IMAGE_URL}" >&2
  exit 2
fi

echo "Resolving existing container instance named '${OCI_CONTAINER_INSTANCE_NAME}'..."
existing_id="$(oci_cli container-instances container-instance list \
  --compartment-id "${OCI_COMPARTMENT_OCID}" \
  --all \
  --query "data.items[?\"display-name\"=='${OCI_CONTAINER_INSTANCE_NAME}' && \"lifecycle-state\"!='DELETED'] | [0].id" \
  --raw-output 2>/dev/null || true)"

if [[ "${existing_id}" == "null" ]]; then
  existing_id=""
fi

if [[ -n "${existing_id}" ]]; then
  echo "Found existing instance: ${existing_id}"
  if [[ -z "${OCI_AD}" ]]; then
    OCI_AD="$(oci_cli container-instances container-instance get \
      --container-instance-id "${existing_id}" \
      --query 'data."availability-domain"' \
      --raw-output)"
    echo "Using existing instance availability domain: ${OCI_AD}"
  fi
  if [[ "$(to_lower "${OCI_REDEPLOY}")" == "true" ]]; then
    echo "Deleting existing instance for redeploy..."
    oci_cli container-instances container-instance delete \
      --container-instance-id "${existing_id}" \
      --force \
      --wait-for-state SUCCEEDED \
      --max-wait-seconds 1800 >/dev/null
  else
    echo "ERROR: Existing instance found and OCI_REDEPLOY is not true. Set OCI_REDEPLOY=true to replace it." >&2
    exit 2
  fi
fi

if [[ -z "${OCI_AD}" ]]; then
  echo "ERROR: OCI_AD is required when creating a new instance and no existing instance was found." >&2
  exit 2
fi

containers_json="$(mktemp)"
vnics_json="$(mktemp)"
cleanup() {
  rm -f "${containers_json}" "${vnics_json}"
}
trap cleanup EXIT

cat > "${containers_json}" <<EOF
[
  {
    "displayName": "${OCI_CONTAINER_NAME}",
    "imageUrl": "${OCI_IMAGE_URL}",
    "environmentVariables": {
      "MCP_AUTH_MODE": "${MCP_AUTH_MODE}",
      "MCP_TRANSPORT": "${MCP_TRANSPORT}",
      "MCP_HOST": "${MCP_HOST}",
      "MCP_PORT": "${MCP_PORT}",
      "MCP_LOG_LEVEL": "${MCP_LOG_LEVEL}",
      "MCP_SAVE_CACHE_AFTER_LOAD": "${MCP_SAVE_CACHE_AFTER_LOAD}",
      "MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH": "${MCP_COMPARTMENT_DOMAIN_SEARCH_DEPTH}"
    }
  }
]
EOF

private_ip_fragment=""
if [[ -n "${OCI_PRIVATE_IP}" ]]; then
  private_ip_fragment="\"privateIp\": \"${OCI_PRIVATE_IP}\","
fi

cat > "${vnics_json}" <<EOF
[
  {
    "displayName": "mcp-vnic",
    "subnetId": "${OCI_SUBNET_OCID}",
    ${private_ip_fragment}
    "isPublicIpAssigned": false
  }
]
EOF

echo "Creating container instance '${OCI_CONTAINER_INSTANCE_NAME}' in AD '${OCI_AD}'..."
oci_cli container-instances container-instance create \
  --compartment-id "${OCI_COMPARTMENT_OCID}" \
  --availability-domain "${OCI_AD}" \
  --display-name "${OCI_CONTAINER_INSTANCE_NAME}" \
  --shape "${OCI_CONTAINER_SHAPE}" \
  --shape-config "{\"ocpus\":${OCI_CONTAINER_OCPUS},\"memoryInGBs\":${OCI_CONTAINER_MEMORY_GBS}}" \
  --container-restart-policy ALWAYS \
  --containers "file://${containers_json}" \
  --vnics "file://${vnics_json}" \
  --wait-for-state SUCCEEDED \
  --max-wait-seconds 1800 >/dev/null

new_instance_id="$(oci_cli container-instances container-instance list \
  --compartment-id "${OCI_COMPARTMENT_OCID}" \
  --all \
  --query "data.items[?\"display-name\"=='${OCI_CONTAINER_INSTANCE_NAME}' && \"lifecycle-state\"=='ACTIVE'] | [0].id" \
  --raw-output 2>/dev/null || true)"

new_container_id=""
if [[ -n "${new_instance_id}" && "${new_instance_id}" != "null" ]]; then
  new_container_id="$(oci_cli container-instances container-instance get \
    --container-instance-id "${new_instance_id}" \
    --query 'data.containers[0]."container-id"' \
    --raw-output 2>/dev/null || true)"
fi

echo "Deployment complete."
[[ -n "${new_instance_id}" ]] && echo "Container Instance OCID: ${new_instance_id}"
[[ -n "${new_container_id}" ]] && echo "Container OCID: ${new_container_id}"

if [[ -n "${new_container_id}" ]]; then
  private_ip="$(oci_cli container-instances container-instance get \
    --container-instance-id "${new_instance_id}" \
    --query 'data.vnics[0]."vnic-id"' \
    --raw-output 2>/dev/null || true)"
  if [[ -n "${private_ip}" && "${private_ip}" != "null" ]]; then
    resolved_ip="$(oci_cli network vnic get --vnic-id "${private_ip}" --query 'data."private-ip"' --raw-output 2>/dev/null || true)"
    [[ -n "${resolved_ip}" && "${resolved_ip}" != "null" ]] && echo "Private IP: ${resolved_ip}"
  fi
fi
