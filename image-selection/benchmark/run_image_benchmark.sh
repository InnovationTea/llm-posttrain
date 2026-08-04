#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)

IMAGE=${1:-}
SUITE=${2:-all}
DEVICE_IDS=${3:-}

RESULT_ROOT=${RESULT_ROOT:-/mnt/data/image-benchmark}
MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}
SFT_DATA_DIR=${SFT_DATA_DIR:-/mnt/data/gsm8k_sft}
GRPO_DATA_DIR=${GRPO_DATA_DIR:-/mnt/data/gsm8k}
BENCHMARK_STEPS=${BENCHMARK_STEPS:-20}
WARMUP_STEPS=${WARMUP_STEPS:-5}
KEEP_CONTAINER=${KEEP_CONTAINER:-0}

usage() {
  cat <<'EOF'
Usage:
  bash image-selection/benchmark/run_image_benchmark.sh IMAGE [SUITE] [DEVICE_IDS]

Arguments:
  IMAGE       Docker image reference, required.
  SUITE       sft, grpo, or all. Default: all.
  DEVICE_IDS  Optional comma-separated physical device IDs. Default: all.

Examples:
  bash image-selection/benchmark/run_image_benchmark.sh quay.io/ascend/verl:tag sft
  bash image-selection/benchmark/run_image_benchmark.sh quay.io/ascend/verl:tag all 0,1,2,3
EOF
}

if [[ -z "${IMAGE}" ]]; then
  usage >&2
  exit 2
fi
case "${SUITE}" in
  sft|grpo|all) ;;
  *)
    echo "Error: SUITE must be sft, grpo, or all; got: ${SUITE}" >&2
    exit 2
    ;;
esac
if [[ "${KEEP_CONTAINER}" != "0" && "${KEEP_CONTAINER}" != "1" ]]; then
  echo "Error: KEEP_CONTAINER must be 0 or 1." >&2
  exit 2
fi
if ! [[ "${BENCHMARK_STEPS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: BENCHMARK_STEPS must be a positive integer." >&2
  exit 2
fi
if ! [[ "${WARMUP_STEPS}" =~ ^[0-9]+$ ]] || ((WARMUP_STEPS >= BENCHMARK_STEPS)); then
  echo "Error: WARMUP_STEPS must be a non-negative integer smaller than BENCHMARK_STEPS." >&2
  exit 2
fi
if [[ "${RESULT_ROOT}" != /mnt/data/* ]]; then
  echo "Error: RESULT_ROOT must be under /mnt/data so host and container share it." >&2
  exit 2
fi
if [[ "${SUITE}" == "grpo" || "${SUITE}" == "all" ]]; then
  if [[ -n "${DEVICE_IDS}" ]]; then
    device_count=$(awk -F, '{print NF}' <<< "${DEVICE_IDS}")
    if [[ "${device_count}" -ne 16 ]]; then
      echo "Error: the current GRPO workload requires 16 logical NPU devices." >&2
      exit 2
    fi
  fi
fi

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
unique_suffix="${timestamp}-$$-${RANDOM}"
BENCHMARK_ID=${BENCHMARK_ID:-benchmark-${unique_suffix}}
CONTAINER_NAME=${CONTAINER_NAME:-verl-bench-${unique_suffix}}

if [[ ! "${BENCHMARK_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Error: BENCHMARK_ID contains unsupported characters: ${BENCHMARK_ID}" >&2
  exit 2
fi
if [[ ! "${CONTAINER_NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
  echo "Error: CONTAINER_NAME contains unsupported characters: ${CONTAINER_NAME}" >&2
  exit 2
fi

RUN_DIR="${RESULT_ROOT}/${BENCHMARK_ID}"
mkdir -p -- "${RESULT_ROOT}"
if ! mkdir -- "${RUN_DIR}" 2>/dev/null; then
  echo "Error: benchmark result directory already exists: ${RUN_DIR}" >&2
  exit 2
fi
mkdir -- "${RUN_DIR}/checks"

container_started=0
finalized=0
cleanup() {
  if [[ "${finalized}" -eq 0 ]]; then
    printf 'FAIL\n' > "${RUN_DIR}/status"
    printf '1\n' > "${RUN_DIR}/exit_code"
  fi
  if [[ "${container_started}" -eq 1 && "${KEEP_CONTAINER}" -eq 0 ]]; then
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

echo "Benchmark ID: ${BENCHMARK_ID}"
echo "Image:        ${IMAGE}"
echo "Suite:        ${SUITE}"
echo "Container:    ${CONTAINER_NAME}"
echo "Results:      ${RUN_DIR}"

WORK_DIR="${PROJECT_ROOT}" \
  bash "${PROJECT_ROOT}/infra/startContainer.sh" \
  "${CONTAINER_NAME}" "${DEVICE_IDS}" "${IMAGE}"
container_started=1

image_id=$(docker inspect --format '{{.Image}}' "${CONTAINER_NAME}")
image_repo_digests=$(docker image inspect --format '{{join .RepoDigests ","}}' "${image_id}" 2>/dev/null || true)

{
  echo "benchmark_id=${BENCHMARK_ID}"
  echo "started_at=${timestamp}"
  echo "image_ref=${IMAGE}"
  echo "image_id=${image_id}"
  echo "image_repo_digests=${image_repo_digests}"
  echo "container_name=${CONTAINER_NAME}"
  echo "suite=${SUITE}"
  echo "device_ids=${DEVICE_IDS:-all}"
  echo "model_path=${MODEL_PATH}"
  echo "sft_data_dir=${SFT_DATA_DIR}"
  echo "grpo_data_dir=${GRPO_DATA_DIR}"
  echo "benchmark_steps=${BENCHMARK_STEPS}"
  echo "warmup_steps=${WARMUP_STEPS}"
} > "${RUN_DIR}/run.env"

overall_status=0

echo "[1/3] Ascend environment check"
if docker exec "${CONTAINER_NAME}" \
  bash /workspace/infra/check_ascend_env.sh \
  2>&1 | tee "${RUN_DIR}/checks/ascend.log"; then
  printf 'PASS\n' > "${RUN_DIR}/checks/ascend.status"
else
  printf 'FAIL\n' > "${RUN_DIR}/checks/ascend.status"
  overall_status=1
fi

if [[ "${overall_status}" -eq 0 ]]; then
  echo "[2/3] Model and data preflight"
  preflight_args=(
    python3 /workspace/frameworks/verl/qwen36_gsm8k/sft/preflight.py
    --model-path "${MODEL_PATH}"
  )
  if [[ "${SUITE}" == "sft" || "${SUITE}" == "all" ]]; then
    preflight_args+=(--data-dir "${SFT_DATA_DIR}" --max-length 2048)
  fi
  if docker exec "${CONTAINER_NAME}" "${preflight_args[@]}" \
    2>&1 | tee "${RUN_DIR}/checks/preflight.log"; then
    printf 'PASS\n' > "${RUN_DIR}/checks/preflight.status"
  else
    printf 'FAIL\n' > "${RUN_DIR}/checks/preflight.status"
    overall_status=1
  fi
else
  printf 'SKIPPED\n' > "${RUN_DIR}/checks/preflight.status"
fi

if [[ "${overall_status}" -eq 0 ]]; then
  echo "[3/3] Training benchmark suite: ${SUITE}"
  if [[ "${SUITE}" == "sft" || "${SUITE}" == "all" ]]; then
    if docker exec \
      -e "BENCHMARK_ID=${BENCHMARK_ID}" \
      -e "IMAGE_REF=${IMAGE}" \
      -e "IMAGE_DIGEST=${image_id}" \
      -e "CONTAINER_NAME=${CONTAINER_NAME}" \
      -e "MODEL_PATH=${MODEL_PATH}" \
      -e "DATA_DIR=${SFT_DATA_DIR}" \
      -e "RESULT_ROOT=${RESULT_ROOT}" \
      -e "BENCHMARK_STEPS=${BENCHMARK_STEPS}" \
      -e "WARMUP_STEPS=${WARMUP_STEPS}" \
      "${CONTAINER_NAME}" \
      bash /workspace/image-selection/benchmark/run_sft_benchmark.sh; then
      :
    else
      overall_status=1
    fi
  fi

  if [[ "${SUITE}" == "grpo" || "${SUITE}" == "all" ]]; then
    if docker exec \
      -e "BENCHMARK_ID=${BENCHMARK_ID}" \
      -e "IMAGE_REF=${IMAGE}" \
      -e "IMAGE_DIGEST=${image_id}" \
      -e "CONTAINER_NAME=${CONTAINER_NAME}" \
      -e "MODEL_PATH=${MODEL_PATH}" \
      -e "DATA_DIR=${GRPO_DATA_DIR}" \
      -e "RESULT_ROOT=${RESULT_ROOT}" \
      -e "BENCHMARK_STEPS=${BENCHMARK_STEPS}" \
      -e "WARMUP_STEPS=${WARMUP_STEPS}" \
      "${CONTAINER_NAME}" \
      bash /workspace/image-selection/benchmark/run_grpo_benchmark.sh; then
      :
    else
      overall_status=1
    fi
  fi
fi

if [[ "${overall_status}" -eq 0 ]]; then
  printf 'PASS\n' > "${RUN_DIR}/status"
  printf '0\n' > "${RUN_DIR}/exit_code"
  finalized=1
  echo "Image benchmark PASS: ${RUN_DIR}"
else
  printf 'FAIL\n' > "${RUN_DIR}/status"
  printf '1\n' > "${RUN_DIR}/exit_code"
  finalized=1
  echo "Image benchmark FAIL: ${RUN_DIR}" >&2
  exit 1
fi
