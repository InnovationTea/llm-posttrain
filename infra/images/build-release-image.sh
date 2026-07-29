#!/usr/bin/env bash

set -euo pipefail

readonly DEFAULT_PART_SIZE_BYTES=$((1900 * 1024 * 1024))
readonly REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: build-release-image.sh <image-id> <image-reference> <platform> <output-directory>

Exports one platform-specific OCI archive, splits it into GitHub Release-safe
parts, and writes checksums plus image metadata alongside the parts.
EOF
}

require_commands() {
  local command

  for command in jq sha256sum split stat; do
    command -v "${command}" >/dev/null 2>&1 || die "missing required command: ${command}"
  done
}

file_size() {
  stat -c '%s' "$1" 2>/dev/null || stat -f '%z' "$1"
}

validate_arguments() {
  local image_id="$1"
  local platform="$2"
  local part_size="$3"

  [[ "${image_id}" =~ ^[a-z0-9][a-z0-9._-]*$ ]] ||
    die "invalid image id: ${image_id}"
  [[ "${platform}" =~ ^linux/[a-z0-9][a-z0-9._-]*$ ]] ||
    die "invalid platform: ${platform}"
  [[ "${part_size}" =~ ^[1-9][0-9]*$ ]] ||
    die "invalid part size: ${part_size}"
}

main() {
  local image_id reference platform output_dir part_size pull_script
  local asset_name archive_name archive_path pull_metadata metadata_path
  local source_reference source_platform manifest_digest archive_sha256 archive_size
  local part part_name
  local -a parts=()
  local -a part_names=()
  local parts_json

  [[ "$#" -eq 4 ]] || {
    usage >&2
    exit 1
  }

  image_id="$1"
  reference="$2"
  platform="$3"
  output_dir="$4"
  part_size="${RELEASE_IMAGE_PART_SIZE_BYTES:-${DEFAULT_PART_SIZE_BYTES}}"
  pull_script="${RELEASE_IMAGE_PULL_SCRIPT:-${REPOSITORY_ROOT}/infra/docker_pull.sh}"

  require_commands
  validate_arguments "${image_id}" "${platform}" "${part_size}"
  [[ -f "${pull_script}" ]] || die "pull script does not exist: ${pull_script}"

  mkdir -p "${output_dir}"
  output_dir="$(cd "${output_dir}" && pwd)"
  asset_name="${image_id}--${platform//\//-}"
  archive_name="${asset_name}.oci.tar"
  archive_path="${output_dir}/${archive_name}"
  pull_metadata="${output_dir}/${asset_name}.pull.json"
  metadata_path="${output_dir}/${asset_name}.asset.json"

  DOCKER_PULL_OUTPUT="${archive_path}" \
    DOCKER_PULL_PLATFORM="${platform}" \
    DOCKER_PULL_METADATA_OUTPUT="${pull_metadata}" \
    bash "${pull_script}" "${reference}"

  [[ -s "${archive_path}" ]] || die "pull script did not create archive: ${archive_path}"
  [[ -f "${pull_metadata}" ]] || die "pull script did not create metadata: ${pull_metadata}"

  source_reference="$(jq -er '.imageReference' "${pull_metadata}")" || die 'pull metadata has no imageReference'
  source_platform="$(jq -er '.platform' "${pull_metadata}")" || die 'pull metadata has no platform'
  manifest_digest="$(jq -er '.manifestDigest' "${pull_metadata}")" || die 'pull metadata has no manifestDigest'
  [[ "${source_reference}" == "${reference}" ]] || die 'pull metadata image reference does not match input'
  [[ "${source_platform}" == "${platform}" ]] || die 'pull metadata platform does not match input'

  (
    cd "${output_dir}"
    split --bytes="${part_size}" --numeric-suffixes=0 --suffix-length=3 \
      "${archive_name}" "${archive_name}.part-"
  )

  shopt -s nullglob
  parts=("${output_dir}/${archive_name}.part-"*)
  shopt -u nullglob
  ((${#parts[@]} > 0)) || die "archive was not split: ${archive_path}"

  for part in "${parts[@]}"; do
    part_name="$(basename "${part}")"
    part_names+=("${part_name}")
  done

  (
    cd "${output_dir}"
    sha256sum -- "${part_names[@]}" >"${asset_name}.parts.sha256"
    sha256sum -- "${archive_name}" >"${asset_name}.archive.sha256"
  )

  archive_sha256="$(awk '{print $1}' "${output_dir}/${asset_name}.archive.sha256")"
  archive_size="$(file_size "${archive_path}")"
  parts_json="$(printf '%s\n' "${part_names[@]}" | jq -R . | jq -sc .)"

  jq -n \
    --arg id "${image_id}" \
    --arg reference "${reference}" \
    --arg platform "${platform}" \
    --arg manifest_digest "${manifest_digest}" \
    --arg archive "${archive_name}" \
    --arg archive_sha256 "${archive_sha256}" \
    --argjson archive_size "${archive_size}" \
    --argjson parts "${parts_json}" \
    '{
      id: $id,
      reference: $reference,
      platform: $platform,
      manifestDigest: $manifest_digest,
      archive: $archive,
      archiveSha256: $archive_sha256,
      archiveSize: $archive_size,
      parts: $parts
    }' >"${metadata_path}"

  rm -f "${pull_metadata}"
  rm -f "${archive_path}"

  printf 'Built release image assets: %s\n' "${asset_name}"
}

main "$@"
