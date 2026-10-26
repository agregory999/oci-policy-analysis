#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
kind="${1:-${CONTAINER_MODE:-combined}}"
case "$kind" in combined) modes=(web mcp) ;; web|mcp) modes=("$kind") ;; *) echo "Usage: run/deploy-container-instance.sh [combined|web|mcp]" >&2; exit 2 ;; esac
tags=()
for mode in "${modes[@]}"; do
  case "$mode" in web) require_values IMAGE_TAG_WEB; tags+=("$IMAGE_TAG_WEB") ;; mcp) require_values IMAGE_TAG_MCP; tags+=("$IMAGE_TAG_MCP") ;; esac
done
for name in OCI_PROFILE OCI_REGION OCI_COMPARTMENT_ID OCI_SUBNET_ID OCI_NSG_ID OCI_AVAILABILITY_DOMAIN OCI_INSTANCE_NAME OCI_REGISTRY_HOST OCI_NAMESPACE OCI_REPOSITORY; do
  [[ -n "${!name:-}" ]] || { echo "Missing ${name} in ${env_file}" >&2; exit 2; }
done
for command_name in oci jq; do command -v "${command_name}" >/dev/null || { echo "${command_name} is required." >&2; exit 2; }; done
[[ "$kind" != combined || "${IMAGE_TAG_WEB:-}" != "${IMAGE_TAG_MCP:-}" ]] || { echo "Web and MCP tags must differ." >&2; exit 2; }
[[ "${WEB_RESOURCE_PRINCIPAL_ONLY:-true}" == true ]] || { echo "This deployment requires WEB_RESOURCE_PRINCIPAL_ONLY=true." >&2; exit 2; }
[[ "${OCI_REDEPLOY:-false}" == false || "${OCI_REDEPLOY:-false}" == true ]] || { echo "OCI_REDEPLOY must be true or false." >&2; exit 2; }
[[ "${OCI_DRY_RUN:-false}" == false || "${OCI_DRY_RUN:-false}" == true ]] || { echo "OCI_DRY_RUN must be true or false." >&2; exit 2; }
[[ "${OCI_OCPUS:-1}" =~ ^[0-9]+([.][0-9]+)?$ && "${OCI_MEMORY_GB:-8}" =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo "OCI_OCPUS and OCI_MEMORY_GB must be numeric." >&2; exit 2; }
profile_args=(--profile "${OCI_PROFILE}" --region "${OCI_REGION}")
web_image="${OCI_REGISTRY_HOST}/${OCI_NAMESPACE}/${OCI_REPOSITORY}:${IMAGE_TAG_WEB:-}"
mcp_image="${OCI_REGISTRY_HOST}/${OCI_NAMESPACE}/${OCI_REPOSITORY}:${IMAGE_TAG_MCP:-}"
command -v python3 >/dev/null || { echo "Python 3 is required." >&2; exit 2; }
umask 077
tmp_dir="$(mktemp -d)"
cleanup() { rm -rf -- "$tmp_dir"; }
trap cleanup EXIT
python3 "$script_dir/container-config.py" "$kind" >"$tmp_dir/containers.json"
# Validate availability domain, shape capacity, and network consistency before replacement.
oci iam availability-domain list "${profile_args[@]}" --all --output json >"$tmp_dir/ads.json"
jq -e --arg ad "$OCI_AVAILABILITY_DOMAIN" 'any(.data[]?; .name==$ad)' "$tmp_dir/ads.json" >/dev/null || { echo "Availability domain not found." >&2; exit 2; }
oci container-instances container-instance list-shapes "${profile_args[@]}" --compartment-id "$OCI_COMPARTMENT_ID" --availability-domain "$OCI_AVAILABILITY_DOMAIN" --all --output json >"$tmp_dir/shapes.json"
jq -e --arg shape "${OCI_SHAPE:-CI.Standard.E4.Flex}" 'any(.data.items[]?; .name==$shape)' "$tmp_dir/shapes.json" >/dev/null || { echo "Container Instance shape unavailable." >&2; exit 2; }
jq -e --arg shape "${OCI_SHAPE:-CI.Standard.E4.Flex}" --argjson cpu "${OCI_OCPUS:-1}" --argjson memory "${OCI_MEMORY_GB:-8}" '
 any(.data.items[]?; .name==$shape and $cpu>=.["ocpu-options"].min and $cpu<=.["ocpu-options"].max
 and $memory>=.["memory-options"]["min-in-gbs"] and $memory<=.["memory-options"]["max-in-gbs"]
 and $memory/$cpu>=.["memory-options"]["min-per-ocpu-in-gbs"]
 and $memory/$cpu<=.["memory-options"]["max-per-ocpu-in-gbs"])' "$tmp_dir/shapes.json" >/dev/null || { echo "CPU/memory is outside the available shape limits." >&2; exit 2; }
echo "Validating OCI target and images."
oci iam compartment get "${profile_args[@]}" --compartment-id "${OCI_COMPARTMENT_ID}" >/dev/null
oci network subnet get "${profile_args[@]}" --subnet-id "${OCI_SUBNET_ID}" --output json >"$tmp_dir/subnet.json"
oci network nsg get "${profile_args[@]}" --nsg-id "${OCI_NSG_ID}" --output json >"$tmp_dir/nsg.json"
jq -e --slurpfile nsg "$tmp_dir/nsg.json" '.data["vcn-id"]==$nsg[0].data["vcn-id"]' "$tmp_dir/subnet.json" >/dev/null || { echo "Subnet and NSG belong to different VCNs." >&2; exit 2; }
for tag in "${tags[@]}"; do
  oci artifacts container image lookup "${profile_args[@]}" --image-uri "${OCI_NAMESPACE}/${OCI_REPOSITORY}:${tag}" >/dev/null || { echo "OCIR image tag ${tag} is missing." >&2; exit 2; }
done
instances="$(oci container-instances container-instance list "${profile_args[@]}" --compartment-id "${OCI_COMPARTMENT_ID}" --all --output json)"
mapfile_compatible_ids=()
while IFS= read -r id; do [[ -n "${id}" ]] && mapfile_compatible_ids+=("${id}"); done < <(jq -r --arg name "${OCI_INSTANCE_NAME}" '.data.items[]? | select(."display-name"==$name and ."lifecycle-state"!="DELETED") | .id' <<<"${instances}")
(( ${#mapfile_compatible_ids[@]} <= 1 )) || { echo "Multiple active instances use ${OCI_INSTANCE_NAME}; resolve them first." >&2; exit 2; }
old_id="${mapfile_compatible_ids[0]:-}"
old_ip=""
if [[ -n "${old_id}" ]]; then
  old="$(oci container-instances container-instance get "${profile_args[@]}" --container-instance-id "${old_id}" --output json)"
  [[ "$(jq -r '.data."lifecycle-state"' <<<"${old}")" == ACTIVE ]] || { echo "Existing instance is not ACTIVE; inspect ${old_id}." >&2; exit 2; }
  matches=0
  while IFS= read -r cid; do
    oci container-instances container get "${profile_args[@]}" --container-id "$cid" --output json >"$tmp_dir/current.json"
    if jq -e --slurpfile desired "$tmp_dir/containers.json" '
      .data as $actual | any($desired[0][];
        .imageUrl==$actual["image-url"] and $actual["is-resource-principal-disabled"]==false
        and .environmentVariables==$actual["environment-variables"]
        and .healthChecks[0].port==$actual["health-checks"][0].port)
      ' "$tmp_dir/current.json" >/dev/null; then matches=$((matches+1)); fi
  done < <(jq -r '.data.containers[]?."container-id"' <<<"${old}")
  old_vnic="$(jq -r '.data.vnics[0]."vnic-id" // empty' <<<"${old}")"
  [[ -n "${old_vnic}" ]] || { echo "Existing instance has no VNIC; refusing replacement." >&2; exit 2; }
  old_vnic_data="$(oci network vnic get "${profile_args[@]}" --vnic-id "${old_vnic}" --output json)"
  [[ "$(jq -r '.data."subnet-id"' <<<"${old_vnic_data}")" == "${OCI_SUBNET_ID}" ]] || { echo "Existing instance uses another subnet; refusing replacement." >&2; exit 2; }
  jq -e --arg nsg "${OCI_NSG_ID}" '.data."nsg-ids" | index($nsg)' <<<"${old_vnic_data}" >/dev/null || { echo "Existing instance uses another NSG; refusing replacement." >&2; exit 2; }
  old_ip="$(jq -r '.data."private-ip"' <<<"${old_vnic_data}")"
  [[ -z "${OCI_PRIVATE_IP:-}" || "${OCI_PRIVATE_IP}" == "${old_ip}" ]] || { echo "Configured private IP differs from existing ${old_ip}; refusing replacement." >&2; exit 2; }
  if [[ "$matches" == "${#modes[@]}" && "$(jq '.data.containers | length' <<<"${old}")" == "${#modes[@]}" ]] &&
     jq -e --arg shape "${OCI_SHAPE:-CI.Standard.E4.Flex}" --arg ad "$OCI_AVAILABILITY_DOMAIN" --argjson cpu "${OCI_OCPUS:-1}" --argjson memory "${OCI_MEMORY_GB:-8}" '
       .data.shape==$shape and .data["availability-domain"]==$ad
       and .data["shape-config"].ocpus==$cpu and .data["shape-config"]["memory-in-gbs"]==$memory' <<<"$old" >/dev/null; then
    echo "$OCI_INSTANCE_NAME already runs requested images, runtime environment and capacity; no changes."
    exit 0
  fi
  [[ "${OCI_REDEPLOY:-false}" == true ]] || { echo "$OCI_INSTANCE_NAME differs. Set OCI_REDEPLOY=true for an explicit delete/create replacement." >&2; exit 2; }
fi
target_ip="${OCI_PRIVATE_IP:-${old_ip}}"
if [[ -n "${target_ip}" ]]; then
  jq -n --arg subnet "${OCI_SUBNET_ID}" --arg nsg "${OCI_NSG_ID}" --arg ip "${target_ip}" '[{subnetId:$subnet,nsgIds:[$nsg],isPublicIpAssigned:false,privateIp:$ip}]' >"${tmp_dir}/vnics.json"
else
  jq -n --arg subnet "${OCI_SUBNET_ID}" --arg nsg "${OCI_NSG_ID}" '[{subnetId:$subnet,nsgIds:[$nsg],isPublicIpAssigned:false}]' >"${tmp_dir}/vnics.json"
fi
if [[ "${OCI_DRY_RUN:-false}" == true ]]; then
  echo "Dry run: mode=$kind, instance=$OCI_INSTANCE_NAME, replace=${old_id:-none}, requested IP=${target_ip:-automatic}, domain depth=${OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH:-1}. Load Balancer remains operator-managed."
  exit 0
fi
if [[ -n "${old_id}" ]]; then
  echo "Deleting ${old_id}; service will be unavailable until the new instance and Load Balancer backends are healthy."
  oci container-instances container-instance delete "${profile_args[@]}" --container-instance-id "${old_id}" --force --wait-for-state SUCCEEDED --wait-interval-seconds 10 --max-wait-seconds 1200 >/dev/null
fi
echo "Creating ${OCI_INSTANCE_NAME} ($kind), domain discovery depth ${OPA_COMPARTMENT_DOMAIN_SEARCH_DEPTH:-1}."
oci container-instances container-instance create "${profile_args[@]}" --compartment-id "${OCI_COMPARTMENT_ID}" --availability-domain "${OCI_AVAILABILITY_DOMAIN}" --shape "${OCI_SHAPE:-CI.Standard.E4.Flex}" --shape-config "{\"ocpus\":${OCI_OCPUS:-1},\"memoryInGBs\":${OCI_MEMORY_GB:-8}}" --containers "file://${tmp_dir}/containers.json" --vnics "file://${tmp_dir}/vnics.json" --display-name "${OCI_INSTANCE_NAME}" --container-restart-policy ALWAYS --wait-for-state SUCCEEDED --wait-interval-seconds 10 --max-wait-seconds 1200 >/dev/null
new_instances="$(oci container-instances container-instance list "${profile_args[@]}" --compartment-id "${OCI_COMPARTMENT_ID}" --all --output json)"
new_id="$(jq -r --arg name "${OCI_INSTANCE_NAME}" '.data.items[]? | select(."display-name"==$name and ."lifecycle-state"!="DELETED") | .id' <<<"${new_instances}" | head -n 1)"
[[ -n "${new_id}" ]] || { echo "Create completed but instance lookup failed; inspect OCI work requests." >&2; exit 1; }
new="$(oci container-instances container-instance get "${profile_args[@]}" --container-instance-id "${new_id}" --output json)"
vnic="$(jq -r '.data.vnics[0]."vnic-id" // empty' <<<"${new}")"
assigned_ip="$(oci network vnic get "${profile_args[@]}" --vnic-id "${vnic}" --output json | jq -r '.data."private-ip"')"
printf '%s\n' "${assigned_ip}" >"${script_dir}/.container-private-ip"
printf '%s\n' "${new_id}" >"${script_dir}/.container-instance-id"
echo "Created ${new_id} at ${assigned_ip}. Check web http://${assigned_ip}:${WEB_PORT:-8000}/health and MCP http://${assigned_ip}:${MCP_PORT:-8765}/health, then verify both Load Balancer backends; this script does not change the Load Balancer."
