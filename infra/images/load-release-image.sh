#!/usr/bin/env bash

set -euo pipefail

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: load-release-image.sh <image-id> <platform> [asset-directory]

Verifies split OCI archive parts, reconstructs the archive, verifies it, and
loads it into Docker.
EOF
}

validate_arguments() {
  [[ "$1" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || die "invalid image id: $1"
  [[ "$2" =~ ^linux/[a-z0-9][a-z0-9._-]*$ ]] || die "invalid platform: $2"
}

main() {
  local image_id platform asset_dir asset_name archive_name archive_path
  local parts_checksum archives_checksum checksum filename archive_line
  local expected_part part
  local -a part_names=()
  local -a part_checksums=()
  local -a sorted_parts=()
  local -a disk_parts=()

  [[ "$#" -ge 2 && "$#" -le 3 ]] || {
    usage >&2
    exit 1
  }

  image_id="$1"
  platform="$2"
  asset_dir="${3:-$PWD}"
  validate_arguments "${image_id}" "${platform}"
  [[ -d "${asset_dir}" ]] || die "asset directory does not exist: ${asset_dir}"
  asset_dir="$(cd "${asset_dir}" && pwd)"

  asset_name="${image_id}--${platform//\//-}"
  archive_name="${asset_name}.oci.tar"
  archive_path="${asset_dir}/${archive_name}"
  parts_checksum="${asset_dir}/SHA256SUMS.parts"
  archives_checksum="${asset_dir}/SHA256SUMS.archives"

  [[ -f "${parts_checksum}" ]] || die "missing part checksum file: ${parts_checksum}"
  [[ -f "${archives_checksum}" ]] || die "missing archive checksum file: ${archives_checksum}"

  while read -r checksum filename; do
    filename="${filename#\*}"
    [[ "${filename}" == "${archive_name}".part-[0-9][0-9][0-9] ]] || continue
    [[ -f "${asset_dir}/${filename}" ]] || die "missing archive part: ${filename}"
    part_names+=("${filename}")
    part_checksums+=("${checksum}  ${filename}")
  done <"${parts_checksum}"

  ((${#part_names[@]} > 0)) || die "no checksummed parts found for ${archive_name}"
  mapfile -t sorted_parts < <(printf '%s\n' "${part_names[@]}" | LC_ALL=C sort)

  for part in "${sorted_parts[@]}"; do
    disk_parts+=("${asset_dir}/${part}")
  done

  shopt -s nullglob
  local -a all_matching_parts=("${asset_dir}/${archive_name}.part-"*)
  shopt -u nullglob
  ((${#all_matching_parts[@]} == ${#disk_parts[@]})) ||
    die "some archive parts are absent from ${parts_checksum}"

  for ((expected_part = 0; expected_part < ${#sorted_parts[@]}; expected_part++)); do
    printf -v part '%s.part-%03d' "${archive_name}" "${expected_part}"
    [[ "${sorted_parts[expected_part]}" == "${part}" ]] ||
      die "archive parts are not contiguous from part-000"
  done

  (
    cd "${asset_dir}"
    printf '%s\n' "${part_checksums[@]}" | sha256sum --check --status -
  ) || die 'part checksum verification failed'

  for part in "${sorted_parts[@]}"; do
    cat "${asset_dir}/${part}"
  done >"${archive_path}"

  archive_line=''
  while read -r checksum filename; do
    filename="${filename#\*}"
    if [[ "${filename}" == "${archive_name}" ]]; then
      archive_line="${checksum}  ${filename}"
      break
    fi
  done <"${archives_checksum}"
  [[ -n "${archive_line}" ]] || die "no archive checksum found for ${archive_name}"

  (
    cd "${asset_dir}"
    printf '%s\n' "${archive_line}" | sha256sum --check --status -
  ) || die 'archive checksum verification failed'

  docker load -i "${archive_path}"
}

main "$@"
