#!/usr/bin/env bash
# Pull a registry image into an OCI archive that Docker 20.10+ can load.
set -euo pipefail

readonly MANIFEST_ACCEPT='application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

format_size() {
  awk -v bytes="$1" 'BEGIN {
    split("B KiB MiB GiB TiB", units, " ")
    unit_index = 1
    while (bytes >= 1024 && unit_index < 5) {
      bytes /= 1024
      unit_index++
    }
    if (unit_index == 1) {
      printf "%.0f %s", bytes, units[unit_index]
    } else {
      printf "%.1f %s", bytes, units[unit_index]
    }
  }'
}

format_speed() {
  printf '%s/s' "$(format_size "$1")"
}

render_progress() {
  local digest="$1"
  local downloaded="$2"
  local total="$3"
  local elapsed_ms="$4"
  local percent=0
  local rate=0
  local complete=0
  local bar_width=24
  local filled
  local empty
  local short_digest="${digest#sha256:}"

  if (( total > 0 )); then
    percent=$(( downloaded * 100 / total ))
    (( percent > 100 )) && percent=100
  fi
  if (( elapsed_ms > 0 )); then
    rate=$(( downloaded * 1000 / elapsed_ms ))
  fi

  complete=$(( percent * bar_width / 100 ))
  filled="$(printf '%*s' "${complete}" '' | tr ' ' '=')"
  empty="$(printf '%*s' "$((bar_width - complete))" '' | tr ' ' ' ')"
  printf '%s: [%s%s] %3d%% %s / %s %s' \
    "${short_digest:0:12}" \
    "${filled}" \
    "${empty}" \
    "${percent}" \
    "$(format_size "${downloaded}")" \
    "$(format_size "${total}")" \
    "$(format_speed "${rate}")"
}

require_commands() {
  local command
  for command in curl jq sha256sum tar stat date uname; do
    command -v "${command}" >/dev/null 2>&1 || die "missing required command: ${command}"
  done
}

host_architecture() {
  case "$(uname -m)" in
    x86_64) printf 'amd64\n' ;;
    aarch64 | arm64) printf 'arm64\n' ;;
    *) die "unsupported host architecture: $(uname -m); set DOCKER_PULL_PLATFORM explicitly" ;;
  esac
}

parse_reference() {
  local reference="$1"
  local path
  local first_component
  local last_component

  IMAGE_REFERENCE="${reference}"
  IMAGE_TAG='latest'
  if [[ "${reference}" == *@* ]]; then
    path="${reference%@*}"
    IMAGE_TAG="${reference##*@}"
  else
    last_component="${reference##*/}"
    if [[ "${last_component}" == *:* ]]; then
      path="${reference%:*}"
      IMAGE_TAG="${last_component##*:}"
    else
      path="${reference}"
    fi
  fi

  first_component="${path%%/*}"
  if [[ "${path}" == */* ]] && [[ "${first_component}" == *.* || "${first_component}" == *:* || "${first_component}" == 'localhost' ]]; then
    REGISTRY="${first_component}"
    REPOSITORY="${path#*/}"
  else
    REGISTRY='registry-1.docker.io'
    REPOSITORY="${path}"
    if [[ "${REPOSITORY}" != */* ]]; then
      REPOSITORY="library/${REPOSITORY}"
    fi
  fi

  [[ -n "${REPOSITORY}" ]] || die 'image repository cannot be empty'
}

registry_auth_header() {
  local headers
  local challenge
  local realm
  local service
  local scope
  local token_response
  local token

  headers="$(curl --silent --show-error --location --dump-header - --output /dev/null "https://${REGISTRY}/v2/")" \
    || die "cannot contact registry: ${REGISTRY}"
  challenge="$(printf '%s\n' "${headers}" | tr -d '\r' | awk 'BEGIN { IGNORECASE = 1 } /^WWW-Authenticate:/ { sub(/^[^:]*:[[:space:]]*/, ""); print; exit }')"

  if [[ -z "${challenge}" ]]; then
    return
  fi
  [[ "${challenge}" == Bearer* ]] || die "unsupported registry authentication challenge: ${challenge}"

  realm="$(printf '%s' "${challenge}" | sed -n 's/.*realm="\([^"]*\)".*/\1/p')"
  service="$(printf '%s' "${challenge}" | sed -n 's/.*service="\([^"]*\)".*/\1/p')"
  scope="$(printf '%s' "${challenge}" | sed -n 's/.*scope="\([^"]*\)".*/\1/p')"
  [[ -n "${realm}" ]] || die "registry did not provide an authentication realm: ${REGISTRY}"
  [[ -n "${scope}" ]] || scope="repository:${REPOSITORY}:pull"

  token_response="$(curl --silent --show-error --fail --location --get "${realm}" \
    --data-urlencode "service=${service}" \
    --data-urlencode "scope=${scope}")" || die "cannot request pull token for ${REPOSITORY}"
  token="$(jq -r '.token // .access_token // empty' <<<"${token_response}")"
  [[ -n "${token}" ]] || die "registry token response did not contain a token"
  printf 'Authorization: Bearer %s\n' "${token}"
}

fetch_manifest() {
  local reference="$1"
  local destination="$2"

  curl --silent --show-error --fail --location \
    -H "Accept: ${MANIFEST_ACCEPT}" \
    -H "${AUTH_HEADER}" \
    --output "${destination}" \
    "https://${REGISTRY}/v2/${REPOSITORY}/manifests/${reference}" \
    || die "cannot fetch manifest: ${REGISTRY}/${REPOSITORY}:${reference}"
}

file_size() {
  stat -c '%s' "$1"
}

now_ms() {
  date +%s%3N
}

verify_digest() {
  local file="$1"
  local digest="$2"
  local expected="${digest#sha256:}"
  local actual

  actual="$(sha256sum "${file}" | awk '{print $1}')"
  [[ "${actual}" == "${expected}" ]] || die "checksum mismatch for ${file}"
}

download_blob() {
  local digest="$1"
  local expected_size="$2"
  local destination="$3"
  local show_progress="$4"
  local start_ms
  local elapsed_ms
  local downloaded
  local curl_pid

  : > "${destination}"
  start_ms="$(now_ms)"
  curl --silent --show-error --fail --location \
    -H "${AUTH_HEADER}" \
    --output "${destination}" \
    "https://${REGISTRY}/v2/${REPOSITORY}/blobs/${digest}" &
  curl_pid=$!

  while kill -0 "${curl_pid}" 2>/dev/null; do
    if [[ "${show_progress}" == 'true' ]]; then
      downloaded="$(file_size "${destination}")"
      elapsed_ms=$(( $(now_ms) - start_ms ))
      printf '\r%s' "$(render_progress "${digest}" "${downloaded}" "${expected_size}" "${elapsed_ms}")"
    fi
    sleep 0.2
  done
  if ! wait "${curl_pid}"; then
    die "cannot download blob: ${digest}"
  fi

  downloaded="$(file_size "${destination}")"
  [[ "${downloaded}" == "${expected_size}" ]] || die "unexpected size for ${digest}: got ${downloaded}, expected ${expected_size}"
  verify_digest "${destination}" "${digest}"
  if [[ "${show_progress}" == 'true' ]]; then
    elapsed_ms=$(( $(now_ms) - start_ms ))
    printf '\r%s\n' "$(render_progress "${digest}" "${downloaded}" "${expected_size}" "${elapsed_ms}")"
  fi
}

select_platform_manifest() {
  local manifest_file="$1"
  local platform="${DOCKER_PULL_PLATFORM:-linux/$(host_architecture)}"
  local digest

  digest="$(jq -r --arg platform "${platform}" '.manifests[] | select((.platform.os + "/" + .platform.architecture) == $platform) | .digest' "${manifest_file}" | head -n 1)"
  [[ -n "${digest}" ]] || die "no manifest for ${platform}; set DOCKER_PULL_PLATFORM to one of: $(jq -r '.manifests[] | .platform.os + "/" + .platform.architecture' "${manifest_file}" | paste -sd ',')"
  printf '%s\n' "${digest}"
}

write_oci_index() {
  local manifest_file="$1"
  local manifest_digest="$2"
  local manifest_size="$3"
  local destination="$4"
  local media_type

  media_type="$(jq -r '.mediaType // "application/vnd.oci.image.manifest.v1+json"' "${manifest_file}")"
  jq -n \
    --arg digest "sha256:${manifest_digest}" \
    --arg media_type "${media_type}" \
    --arg reference "${IMAGE_REFERENCE}" \
    --argjson size "${manifest_size}" \
    '{schemaVersion: 2, manifests: [{mediaType: $media_type, digest: $digest, size: $size, annotations: {"org.opencontainers.image.ref.name": $reference}}]}' \
    > "${destination}"
}

usage() {
  cat <<'EOF'
Usage: bash infra/docker_pull.sh <image-reference>

Examples:
  bash infra/docker_pull.sh quay.io/ascend/verl:verl-8.5.0-a3-ubuntu22.04-py3.11-v0.7.1
  DOCKER_PULL_OUTPUT=/mnt/model/verl.oci.tar bash infra/docker_pull.sh quay.io/ascend/verl:<tag>
  DOCKER_PULL_PLATFORM=linux/arm64 bash infra/docker_pull.sh quay.io/namespace/image:<tag>
EOF
}

main() {
  local work_dir
  local layout
  local manifest_file
  local manifest_reference
  local manifest_digest
  local manifest_size
  local config_digest
  local config_size
  local config_target
  local layer
  local layer_digest
  local layer_size
  local layer_target
  local output_name
  local output_path

  [[ "$#" -eq 1 ]] || { usage >&2; exit 1; }
  require_commands
  parse_reference "$1"
  AUTH_HEADER="$(registry_auth_header)"

  work_dir="$(mktemp -d "${TMPDIR:-/tmp}/docker-pull.XXXXXX")"
  trap 'rm -rf "${work_dir}"' EXIT
  layout="${work_dir}/oci-layout"
  mkdir -p "${layout}/blobs/sha256"
  printf '{"imageLayoutVersion":"1.0.0"}\n' > "${layout}/oci-layout"

  manifest_file="${work_dir}/manifest.json"
  manifest_reference="${IMAGE_TAG}"
  fetch_manifest "${manifest_reference}" "${manifest_file}"
  if jq -e 'has("manifests")' "${manifest_file}" >/dev/null; then
    manifest_reference="$(select_platform_manifest "${manifest_file}")"
    fetch_manifest "${manifest_reference}" "${manifest_file}"
  fi
  jq -e 'has("config") and has("layers")' "${manifest_file}" >/dev/null \
    || die 'registry returned an unsupported manifest'

  manifest_digest="$(sha256sum "${manifest_file}" | awk '{print $1}')"
  manifest_size="$(file_size "${manifest_file}")"
  cp "${manifest_file}" "${layout}/blobs/sha256/${manifest_digest}"

  read -r config_digest config_size < <(jq -r '.config.digest + " " + (.config.size | tostring)' "${manifest_file}")
  config_target="${layout}/blobs/sha256/${config_digest#sha256:}"
  download_blob "${config_digest}" "${config_size}" "${config_target}" false

  while IFS= read -r layer; do
    layer_digest="$(jq -r '.digest' <<<"${layer}")"
    layer_size="$(jq -r '.size' <<<"${layer}")"
    layer_target="${layout}/blobs/sha256/${layer_digest#sha256:}"
    download_blob "${layer_digest}" "${layer_size}" "${layer_target}" true
  done < <(jq -c '.layers[]' "${manifest_file}")

  write_oci_index "${manifest_file}" "${manifest_digest}" "${manifest_size}" "${layout}/index.json"
  output_name="${IMAGE_REFERENCE//\//_}"
  output_name="${output_name//:/_}"
  output_name="${output_name//@/_}.oci.tar"
  output_path="${DOCKER_PULL_OUTPUT:-${output_name}}"
  [[ "${output_path}" = /* ]] || output_path="${PWD}/${output_path}"
  tar -C "${layout}" -cf "${output_path}" .
  printf 'Saved OCI image archive: %s\n' "${output_path}"
  printf 'Load it with: docker load -i %s\n' "${output_path}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
