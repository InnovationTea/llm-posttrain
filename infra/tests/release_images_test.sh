#!/usr/bin/env bash

set -euo pipefail

readonly REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/release-images-test.XXXXXX")"

cleanup() {
  rm -rf "${TEST_DIR}"
}

trap cleanup EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "expected file: $1"
}

assert_contains() {
  local file="$1"
  local text="$2"

  grep -F -- "${text}" "${file}" >/dev/null ||
    fail "expected ${file} to contain: ${text}"
}

fake_puller="${TEST_DIR}/fake-puller.sh"
cat >"${fake_puller}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

printf 'test' >"${DOCKER_PULL_OUTPUT}"
printf '%s\n' '{"imageReference":"registry.example/demo:v1","platform":"linux/amd64","manifestDigest":"sha256:abc"}' >"${DOCKER_PULL_METADATA_OUTPUT}"
EOF
chmod +x "${fake_puller}"

output_dir="${TEST_DIR}/output"
RELEASE_IMAGE_PART_SIZE_BYTES=2 \
RELEASE_IMAGE_PULL_SCRIPT="${fake_puller}" \
bash "${REPOSITORY_ROOT}/infra/images/build-release-image.sh" \
  demo registry.example/demo:v1 linux/amd64 "${output_dir}"

assert_file "${output_dir}/demo--linux-amd64.oci.tar.part-000"
assert_file "${output_dir}/demo--linux-amd64.oci.tar.part-001"
assert_file "${output_dir}/demo--linux-amd64.parts.sha256"
assert_file "${output_dir}/demo--linux-amd64.archive.sha256"
assert_file "${output_dir}/demo--linux-amd64.asset.json"
[[ ! -e "${output_dir}/demo--linux-amd64.oci.tar" ]] ||
  fail 'build script must remove the unsplit archive after checksumming it'

cp "${output_dir}/demo--linux-amd64.parts.sha256" "${output_dir}/SHA256SUMS.parts"
cp "${output_dir}/demo--linux-amd64.archive.sha256" "${output_dir}/SHA256SUMS.archives"

mkdir "${TEST_DIR}/bin"
cat >"${TEST_DIR}/bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >"${DOCKER_ARGS_PATH}"
EOF
chmod +x "${TEST_DIR}/bin/docker"

PATH="${TEST_DIR}/bin:${PATH}" \
DOCKER_ARGS_PATH="${TEST_DIR}/docker.args" \
  bash "${REPOSITORY_ROOT}/infra/images/load-release-image.sh" \
    demo linux/amd64 "${output_dir}"

assert_file "${output_dir}/demo--linux-amd64.oci.tar"
[[ "$(cat "${output_dir}/demo--linux-amd64.oci.tar")" == 'test' ]] ||
  fail 'loader did not reconstruct archive contents'
[[ "$(tr '\n' ' ' <"${TEST_DIR}/docker.args")" == "load -i ${output_dir}/demo--linux-amd64.oci.tar " ]] ||
  fail 'loader did not invoke docker load for reconstructed archive'

metadata_archive="${TEST_DIR}/metadata.oci.tar"
metadata_output="${TEST_DIR}/pull-metadata.json"
printf 'metadata' >"${metadata_archive}"
(
  source "${REPOSITORY_ROOT}/infra/docker_pull.sh"
  IMAGE_REFERENCE='registry.example/demo:v1'
  DOCKER_PULL_PLATFORM='linux/amd64'
  DOCKER_PULL_METADATA_OUTPUT="${metadata_output}"
  write_pull_metadata "${metadata_archive}" 'sha256:def'
)

[[ "$(jq -r '.imageReference' "${metadata_output}")" == 'registry.example/demo:v1' ]] ||
  fail 'pull metadata image reference is incorrect'
[[ "$(jq -r '.platform' "${metadata_output}")" == 'linux/amd64' ]] ||
  fail 'pull metadata platform is incorrect'
[[ "$(jq -r '.manifestDigest' "${metadata_output}")" == 'sha256:def' ]] ||
  fail 'pull metadata manifest digest is incorrect'
[[ "$(jq -r '.archiveSha256' "${metadata_output}")" == "$(sha256sum "${metadata_archive}" | awk '{print $1}')" ]] ||
  fail 'pull metadata archive checksum is incorrect'
[[ "$(jq -r '.archiveSize' "${metadata_output}")" == '8' ]] ||
  fail 'pull metadata archive size is incorrect'

workflow="${REPOSITORY_ROOT}/.github/workflows/release-images.yml"
assert_file "${workflow}"
assert_contains "${workflow}" 'workflow_dispatch:'
assert_contains "${workflow}" 'release_tag:'
assert_contains "${workflow}" 'required: true'
assert_contains "${workflow}" 'contents: write'
assert_contains "${workflow}" 'git tag -a'
assert_contains "${workflow}" 'gh release create'
assert_contains "${workflow}" '--draft --generate-notes'
assert_contains "${workflow}" 'compression-level: 0'
assert_contains "${workflow}" 'gh release edit'
assert_contains "${workflow}" '--draft=false'

readme="${REPOSITORY_ROOT}/README.md"
assert_contains "${readme}" 'images.json'
assert_contains "${readme}" 'workflow_dispatch'
assert_contains "${readme}" 'release_tag'
assert_contains "${readme}" 'SHA256SUMS.parts'
assert_contains "${readme}" 'SHA256SUMS.archives'
assert_contains "${readme}" 'load-image.sh'

printf 'PASS: release image archive build\n'
