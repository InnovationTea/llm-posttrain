#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)

BENCHMARK_ID=${BENCHMARK_ID:-}
IMAGE_REF=${IMAGE_REF:-unknown}
IMAGE_DIGEST=${IMAGE_DIGEST:-unknown}
CONTAINER_NAME=${CONTAINER_NAME:-unknown}
MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}
DATA_DIR=${DATA_DIR:-/mnt/data/gsm8k}
RESULT_ROOT=${RESULT_ROOT:-/mnt/data/image-benchmark}
BENCHMARK_STEPS=${BENCHMARK_STEPS:-20}
WARMUP_STEPS=${WARMUP_STEPS:-5}

if [[ -z "${BENCHMARK_ID}" ]]; then
  echo "Error: BENCHMARK_ID is required; run this executor through run_image_benchmark.sh." >&2
  exit 2
fi
if [[ ! "${BENCHMARK_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Error: BENCHMARK_ID contains unsupported characters." >&2
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
if [[ ! -d "${MODEL_PATH}" ]]; then
  echo "Error: model directory does not exist: ${MODEL_PATH}" >&2
  exit 2
fi
if [[ ! -f "${DATA_DIR}/train.parquet" || ! -f "${DATA_DIR}/test.parquet" ]]; then
  echo "Error: expected train.parquet and test.parquet in ${DATA_DIR}" >&2
  exit 2
fi

RUN_DIR="${RESULT_ROOT}/${BENCHMARK_ID}/grpo"
if [[ -e "${RUN_DIR}" ]]; then
  echo "Error: result directory already exists: ${RUN_DIR}" >&2
  echo "Use a new host-level BENCHMARK_ID." >&2
  exit 2
fi
mkdir -p -- "${RUN_DIR}"

status=1
finish() {
  printf '%s\n' "${status}" > "${RUN_DIR}/exit_code"
  if [[ "${status}" -eq 0 ]]; then
    printf 'PASS\n' > "${RUN_DIR}/status"
  else
    printf 'FAIL\n' > "${RUN_DIR}/status"
  fi
}
trap finish EXIT

{
  echo "benchmark=grpo"
  echo "benchmark_id=${BENCHMARK_ID}"
  echo "image_ref=${IMAGE_REF}"
  echo "image_digest=${IMAGE_DIGEST}"
  echo "container_name=${CONTAINER_NAME}"
  echo "started_at=$(date --iso-8601=seconds)"
  echo "hostname=$(hostname)"
  echo "model_path=${MODEL_PATH}"
  echo "data_dir=${DATA_DIR}"
  echo "benchmark_steps=${BENCHMARK_STEPS}"
  echo "warmup_steps=${WARMUP_STEPS}"
  echo "npu_count=16"
  echo "tensor_parallel_size=8"
  echo "rollout_n=4"
} > "${RUN_DIR}/benchmark.env"

{
  python3 --version 2>&1 || true
  pip show torch torch-npu transformers verl vllm vllm-ascend 2>&1 || true
  if [[ -f /usr/local/Ascend/ascend-toolkit/latest/version.info ]]; then
    cat /usr/local/Ascend/ascend-toolkit/latest/version.info
  fi
  npu-smi info 2>&1 || true
} > "${RUN_DIR}/environment.txt"

echo "GRPO benchmark results: ${RUN_DIR}"
cd "${RUN_DIR}"

bash "${PROJECT_ROOT}/frameworks/verl/qwen36_gsm8k/rl/run_grpo.sh" \
  "data.train_files=${DATA_DIR}/train.parquet" \
  "data.val_files=${DATA_DIR}/test.parquet" \
  "actor_rollout_ref.model.path=${MODEL_PATH}" \
  "trainer.total_training_steps=${BENCHMARK_STEPS}" \
  trainer.save_freq=-1 \
  trainer.test_freq=-1 \
  "$@"

python3 "${SCRIPT_DIR}/parse_grpo_metrics.py" \
  --log-file "${RUN_DIR}/verl_grpo.log" \
  --output-file "${RUN_DIR}/summary.json" \
  --text-output "${RUN_DIR}/summary.txt" \
  --expected-steps "${BENCHMARK_STEPS}" \
  --warmup-steps "${WARMUP_STEPS}" \
  --prompt-batch-size 8 \
  --rollout-n 4 \
  --npu-count 16

status=0
echo "GRPO benchmark PASS: ${RUN_DIR}"
